"""Cross-check classes.berkeley.edu counts against Berkeleytime ``GetClass`` for N sections.

DESIGN_A2 section 9 and docs/PHASE0.md "Cross-check". Needs the network; never imported by tests.

    python probe/crosscheck_berkeleytime.py --term "Fall 2026" --n 20

Section refs come from ``ClassesSiteSource.list_sections``: the cached full listing at
``catalog/<term_id>/sections.json`` under ``--data-root`` when a classes_site run wrote one
in the last 24 h, else a fresh listing capped at ``--max-pages`` pages (alphabetical, so
early pages are AEROENG..). COMPSCI/DATA/STAT refs are preferred whenever they are present
in the pool. Each chosen section page is fetched live and matched to the same ``sectionId``
in Berkeleytime's GetClass (primarySection + sections).

Berkeleytime's counts are at most 15 minutes old, so the report separates
"agree" (identical) from "drift" (every difference <= DRIFT_TOLERANCE seats) and flags
"disagree" (some difference > DRIFT_TOLERANCE). Berkeleytime does not index every class
(e.g. group-study ``198`` sections come back with ``primarySection: null``), so a section
that cannot be compared is listed as "error" and the next candidate is drawn, up to
``2 * n`` attempts, so the report always has ``n`` comparable sections. Exit 1 only when a
section disagrees or fewer than ``n`` could be compared. Writes ``docs/crosscheck_<UTC date>.md``.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper import config  # noqa: E402
from scraper.sources.base import TermSpec  # noqa: E402

logger = logging.getLogger("probe.crosscheck")

REPO_ROOT = Path(__file__).resolve().parents[1]
PREFERRED_SUBJECTS: tuple[str, ...] = ("COMPSCI", "DATA", "STAT")
DRIFT_TOLERANCE = 10  # seats; larger differences are not explained by 15-minute staleness
COMPARE_FIELDS: tuple[tuple[str, str], ...] = (
    ("enrolled_count", "enrolledCount"),
    ("waitlist_count", "waitlistedCount"),
    ("enroll_capacity", "maxEnroll"),
    ("waitlist_capacity", "maxWaitlist"),
)

VERDICT_AGREE = "agree"
VERDICT_DRIFT = "drift"
VERDICT_DISAGREE = "disagree"
VERDICT_ERROR = "error"


@dataclass
class Comparison:
    label: str
    section_id: str
    site: dict[str, int | None] = field(default_factory=dict)
    bt: dict[str, int | None] = field(default_factory=dict)
    verdict: str = VERDICT_ERROR
    max_diff: int | None = None
    note: str = ""


# ------------------------------------------------------------------ refs


def load_refs(source: Any, term: TermSpec, max_pages: int) -> list[Any]:
    """Section refs for the term via the source (cached full listing, else ``max_pages`` live pages)."""
    facet_id = source.discover_term_facet_id(term.name)
    refs = source.list_sections(facet_id, max_pages, term_id=term.sis_term_id)
    logger.info("facet %s: %d refs available", facet_id, len(refs))
    return refs


def order_refs(refs: list[Any]) -> list[Any]:
    """Every ref, preferred subjects first, original order otherwise."""
    preferred = [r for r in refs if r.subject.upper() in PREFERRED_SUBJECTS]
    others = [r for r in refs if r.subject.upper() not in PREFERRED_SUBJECTS]
    return preferred + others


def choose_refs(refs: list[Any], n: int) -> list[Any]:
    """Up to ``n`` refs in ``order_refs`` order."""
    return order_refs(refs)[:n]


# --------------------------------------------------------------- compare


def site_counts(row: Mapping[str, Any]) -> dict[str, int | None]:
    return {ours: row.get(ours) for ours, _ in COMPARE_FIELDS}


def bt_counts(latest: Mapping[str, Any]) -> dict[str, int | None]:
    return {ours: latest.get(theirs) for ours, theirs in COMPARE_FIELDS}


def unwrap_class(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept a full GraphQL response, a ``{"class": ...}`` wrapper, or the class object itself."""
    if "data" in payload:
        return payload["data"]["class"]
    if "class" in payload:
        return payload["class"]
    return payload


def find_bt_section(cls: Mapping[str, Any], section_id: str) -> Mapping[str, Any] | None:
    """The primarySection or secondary section whose ``sectionId`` equals ``section_id``."""
    for s in [cls.get("primarySection")] + list(cls.get("sections") or []):
        if s and str(s.get("sectionId")) == str(section_id):
            return s
    return None


def classify(site: Mapping[str, int | None], bt: Mapping[str, int | None]) -> tuple[str, int | None]:
    """``(verdict, max_abs_diff)`` over the four count fields."""
    diffs = []
    for key, _ in COMPARE_FIELDS:
        a, b = site.get(key), bt.get(key)
        if a is None or b is None:
            return VERDICT_ERROR, None
        diffs.append(abs(int(a) - int(b)))
    worst = max(diffs)
    if worst == 0:
        return VERDICT_AGREE, worst
    if worst <= DRIFT_TOLERANCE:
        return VERDICT_DRIFT, worst
    return VERDICT_DISAGREE, worst


def crosscheck_one(
    client: Any,
    site_source: Any,
    bt_source: Any,
    class_cache: dict[tuple[str, str, str], Mapping[str, Any]],
    term: TermSpec,
    ref: Any,
) -> Comparison:
    """Fetch one section live from both sources and compare."""
    from scraper.http import HttpError
    from scraper.sources.base import ParseError
    from scraper.sources.berkeleytime import BerkeleytimeError
    from scraper.sources.sis_api import TransportError

    label = f"{ref.course_key} {ref.component} {ref.section_number}"
    comp = Comparison(label=label, section_id=str(ref.section_id))
    try:
        html = client.get(site_source.section_url(ref))
        row = site_source.parse_section_page(html, ref, datetime.now(timezone.utc), term)
        comp.site = site_counts(row)
    except (HttpError, ParseError, ValueError, KeyError) as exc:
        comp.note = f"site: {type(exc).__name__}: {exc}"
        return comp
    key = (ref.subject, ref.catalog_number, ref.class_number)
    try:
        if key not in class_cache:
            class_cache[key] = unwrap_class(bt_source.get_class(term, ref.subject, ref.catalog_number, ref.class_number))
        section = find_bt_section(class_cache[key], comp.section_id)
    except (BerkeleytimeError, TransportError, ParseError, ValueError, KeyError, TypeError) as exc:
        comp.note = f"berkeleytime: {type(exc).__name__}: {exc}"
        return comp
    if section is None:
        comp.note = "berkeleytime: sectionId not found in GetClass"
        return comp
    comp.bt = bt_counts((section.get("enrollment") or {}).get("latest") or {})
    comp.verdict, comp.max_diff = classify(comp.site, comp.bt)
    return comp


# ---------------------------------------------------------------- report


def fmt_counts(c: Mapping[str, int | None]) -> str:
    if not c:
        return "-"
    return "/".join("?" if c.get(k) is None else str(c[k]) for k, _ in COMPARE_FIELDS)


def summarize(comps: list[Comparison]) -> dict[str, int]:
    """Verdict counts plus ``comparable`` (everything except errors)."""
    counts = {VERDICT_AGREE: 0, VERDICT_DRIFT: 0, VERDICT_DISAGREE: 0, VERDICT_ERROR: 0}
    for c in comps:
        counts[c.verdict] += 1
    counts["comparable"] = counts[VERDICT_AGREE] + counts[VERDICT_DRIFT] + counts[VERDICT_DISAGREE]
    return counts


def render_markdown(term: TermSpec, when: datetime, comps: list[Comparison]) -> str:
    """Markdown report: table of both counts per section plus the agreement summary."""
    s = summarize(comps)
    n = s["comparable"]
    lines = [
        f"# Cross-check: classes.berkeley.edu vs Berkeleytime GetClass, {term.name}",
        "",
        f"Run at {when.strftime('%Y-%m-%d %H:%M:%S UTC')} by `probe/crosscheck_berkeleytime.py`. "
        f"Counts are enrolled/waitlisted/maxEnroll/maxWaitlist. Berkeleytime is at most 15 minutes old, "
        f"so differences of a few seats are drift, not error; differences over {DRIFT_TOLERANCE} seats are flagged. "
        f"A section Berkeleytime does not index (or that failed to fetch) is listed as `error`, excluded from the "
        f"comparison, and replaced by the next candidate.",
        "",
        f"- compared: **{n}** sections ({len(comps)} attempted)",
        f"- agree exactly: **{s[VERDICT_AGREE]}/{n}**",
        f"- within 15-minute drift (<= {DRIFT_TOLERANCE} seats): **{s[VERDICT_DRIFT]}/{n}**",
        f"- disagree (> {DRIFT_TOLERANCE} seats): **{s[VERDICT_DISAGREE]}/{n}**",
        f"- could not compare (excluded): **{s[VERDICT_ERROR]}**",
        "",
        "| # | section | id | site enr/wl/cap/wlcap | berkeleytime enr/wl/cap/wlcap | max diff | verdict | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, c in enumerate(comps, 1):
        diff = "-" if c.max_diff is None else str(c.max_diff)
        lines.append(f"| {i} | {c.label} | {c.section_id} | {fmt_counts(c.site)} | {fmt_counts(c.bt)} | {diff} | {c.verdict} | {c.note} |")
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ main


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compare live classes.berkeley.edu counts with Berkeleytime for N sections.")
    p.add_argument("--term", required=True, help='e.g. "Fall 2026"')
    p.add_argument("--n", type=int, default=20, help="comparable sections wanted; uncomparable ones are replaced by the next candidate (at most 2n attempts)")
    p.add_argument("--data-root", type=Path, default=Path(config.DEFAULTS["data_root"]), help="where catalog/<term_id>/sections.json may live")
    p.add_argument("--max-pages", type=int, default=6, help="listing pages to read when no catalog cache exists (18 refs per page)")
    p.add_argument("--min-interval-s", type=float, default=config.DEFAULTS["min_interval_s"])
    p.add_argument("--out", type=Path, default=None, help="report path; default docs/crosscheck_<UTC date>.md")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from scraper.http import HttpClient
    from scraper.sources.berkeleytime import BerkeleytimeSource
    from scraper.sources.classes_site import ClassesSiteSource

    term = TermSpec.from_name(args.term)
    when = datetime.now(timezone.utc)
    client = HttpClient(config.USER_AGENT, min_interval_s=args.min_interval_s, max_concurrency=1)
    site_source = ClassesSiteSource(client, args.data_root)
    pool = order_refs(load_refs(site_source, term, args.max_pages))
    if not pool:
        print("no section refs available; nothing to compare", file=sys.stderr)
        return 1
    bt_source = BerkeleytimeSource()
    class_cache: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    comps: list[Comparison] = []
    n_comparable = 0
    max_attempts = 2 * args.n
    for ref in pool:
        if n_comparable >= args.n or len(comps) >= max_attempts:
            break
        comp = crosscheck_one(client, site_source, bt_source, class_cache, term, ref)
        logger.info("%s id=%s site=%s bt=%s -> %s %s", comp.label, comp.section_id, fmt_counts(comp.site), fmt_counts(comp.bt), comp.verdict, comp.note)
        comps.append(comp)
        if comp.verdict != VERDICT_ERROR:
            n_comparable += 1
    if n_comparable < args.n:
        logger.warning(
            "only %d of %d requested sections could be compared (%d attempted from a pool of %d)",
            n_comparable, args.n, len(comps), len(pool),
        )

    report = render_markdown(term, when, comps)
    print(report)
    out = args.out or (REPO_ROOT / "docs" / f"crosscheck_{when.strftime('%Y-%m-%d')}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    s = summarize(comps)
    print(
        f"agree={s[VERDICT_AGREE]} drift={s[VERDICT_DRIFT]} disagree={s[VERDICT_DISAGREE]} "
        f"of {s['comparable']} compared (error={s[VERDICT_ERROR]}, {len(comps)} attempted); wrote {out}"
    )
    return 0 if s[VERDICT_DISAGREE] == 0 and s["comparable"] >= args.n else 1


if __name__ == "__main__":
    sys.exit(main())

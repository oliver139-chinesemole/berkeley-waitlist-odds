"""Rank courses by reconstructed waitlist joins and write a candidate priority list.

docs/dev/BACKFILL_BACKTEST.md B5. The hand-written ``config/priority_courses.txt``
matched only 99 of the 478 Fall 2026 sections that carried a waitlist on
2026-09-19. A finished cycle (the Fall 2026 backfill, and Spring 2026) says
where the joins actually were: rank sections by their reconstructed waitlist
joins, take the top N, and list their courses in that order, so a run whose
time budget runs out drops the least-joined courses first.

A second pass (``--min-course-joins``) admits every course whose joins over the
input cycles reach the floor, however small its sections: reading-and-composition
courses spread their queues over many 17-seat sections and no single section
reaches the per-section cutoff (review of the 2026-09-23 install).

Output is a candidate file (default ``config/priority_courses.candidate.txt``),
never the live list: installing it changes ``priority_sha`` and needs a row in
docs/DATA_LOG.md. The report printed alongside compares the current list and
the candidate on the same data (sections and joins covered) and, with
``--catalog``, on a live catalog: sections a run would fetch every 30 minutes.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scraper.sources.base import PrioritySpec, shard_of

logger = logging.getLogger(__name__)

DEFAULT_TOP_SECTIONS = 900
DEFAULT_OUT = Path("config/priority_courses.candidate.txt")
DEFAULT_CURRENT = Path("config/priority_courses.txt")


def section_activity(flows: pd.DataFrame, identity: pd.DataFrame, *, term_id: str | None = None) -> pd.DataFrame:
    """One row per section: reconstructed waitlist joins, admits, the longest
    queue seen and the share of intervals with a queue, joined to its course."""
    f = flows.copy()
    f["section_id"] = f["section_id"].astype(str)
    grp = f.groupby("section_id")
    act = pd.DataFrame(
        {
            "wl_joins": grp["wl_joins"].sum().astype(int),
            "admits": grp["admits"].sum().astype(int),
            "max_waitlist": grp["waitlist0"].max().astype(int),
            "share_intervals_with_queue": (grp["waitlist0"].apply(lambda s: float((s > 0).mean()))).round(4),
        }
    ).reset_index()
    ident = identity[["section_id", "course_key", "subject", "catalog_number"]].copy()
    ident["section_id"] = ident["section_id"].astype(str)
    out = act.merge(ident, on="section_id", how="left")
    out["term_id"] = term_id if term_id is not None else ""
    return out.sort_values(["wl_joins", "max_waitlist", "course_key"], ascending=[False, False, True]).reset_index(drop=True)


def rank_courses(activity: pd.DataFrame, *, top_sections: int = DEFAULT_TOP_SECTIONS, min_course_joins: int = 0) -> pd.DataFrame:
    """Courses of the ``top_sections`` most-joined sections (joins > 0), plus every
    course whose joins over all its sections reach ``min_course_joins`` (0 = off),
    ordered by the joins of all their sections: ``course_key, subject, joins,
    sections, top_sections`` (``top_sections`` 0 = admitted by course total)."""
    act = activity[activity["wl_joins"] > 0].sort_values(["wl_joins", "max_waitlist"], ascending=[False, False])
    top = act.head(int(top_sections))
    courses = set(top["course_key"].dropna().astype(str))
    if min_course_joins > 0:
        totals = activity.groupby(activity["course_key"].astype(str))["wl_joins"].sum()
        courses |= {str(k) for k, v in totals.items() if v >= min_course_joins and k and k != "nan"}
    rows = activity[activity["course_key"].astype(str).isin(courses)]
    out = (
        rows.groupby("course_key")
        .agg(subject=("subject", "first"), joins=("wl_joins", "sum"), sections=("section_id", "nunique"))
        .reset_index()
    )
    in_top = top.groupby("course_key")["section_id"].nunique().rename("top_sections")
    out = out.merge(in_top, left_on="course_key", right_index=True, how="left")
    out["top_sections"] = out["top_sections"].fillna(0).astype(int)
    out["joins"] = out["joins"].astype(int)
    return out.sort_values(["joins", "sections", "course_key"], ascending=[False, False, True]).reset_index(drop=True)


def render(courses: pd.DataFrame, *, source_note: str, top_sections: int, min_course_joins: int = 0) -> str:
    """The candidate file: the format rules, then one exact course per line, most-joined first."""
    pass_note = (
        f", plus every course with at least {min_course_joins} joins over all its sections (marked 'by course total')"
        if min_course_joins > 0
        else ""
    )
    lines = [
        "# Priority course list for classes.berkeley.edu runs (docs/DESIGN_A2.md section 6).",
        "#",
        "# Format: one pattern per line, either",
        "#   SUBJECT            every course in the subject          (e.g. COMPSCI)",
        "#   SUBJECT CATALOG    one course, or a catalog prefix with a trailing *  (e.g. MATH 1*)",
        "# Matching ignores spaces inside the subject and is case-insensitive; see PrioritySpec in",
        "# scraper/sources/base.py. Text after # is a comment; blank lines are ignored.",
        "#",
        "# ORDER MATTERS. Sections are fetched in the order of the first pattern they match, so",
        "# when a run's time budget runs out the courses at the bottom are the ones dropped.",
        "#",
        f"# Built by `python -m analysis.priority_from_flows` on {datetime.now(timezone.utc).date().isoformat()}: {source_note}.",
        f"# Courses of the {top_sections} sections with the most reconstructed waitlist joins{pass_note}, ordered by",
        "# the joins of all their sections (the number after each course), then by section count.",
        "# Section counts are unique section ids across the input cycles.",
        "# Any edit to this file changes priority_sha in the snapshot metadata; note it in docs/DATA_LOG.md.",
    ]
    width = max((len(str(k)) for k in courses["course_key"]), default=10)
    for row in courses.itertuples(index=False):
        tag = ", by course total" if int(row.top_sections) == 0 else ""
        lines.append(f"{str(row.course_key):<{width}}  # {int(row.joins)} joins, {int(row.sections)} sections{tag}")
    return "\n".join(lines) + "\n"


def coverage(activity: pd.DataFrame, spec: PrioritySpec) -> dict:
    """How much of the observed waitlisting a list catches: sections with any queue,
    sections with joins, and the share of all joins, that match a pattern."""
    keys = activity["course_key"].astype(str)
    matched = keys.map(lambda k: spec.matches(k) if k and k != "nan" else False).to_numpy(dtype=bool)
    queued = (activity["max_waitlist"] > 0).to_numpy()
    joined = (activity["wl_joins"] > 0).to_numpy()
    total_joins = int(activity["wl_joins"].sum())
    return {
        "patterns": len(spec.patterns),
        "sections": int(len(activity)),
        "sections_matched": int(matched.sum()),
        "sections_with_queue": int(queued.sum()),
        "sections_with_queue_matched": int((queued & matched).sum()),
        "sections_with_joins": int(joined.sum()),
        "sections_with_joins_matched": int((joined & matched).sum()),
        "share_joins_matched": round(float(activity.loc[matched, "wl_joins"].sum()) / total_joins, 4) if total_joins else 0.0,
    }


def catalog_report(spec: PrioritySpec, catalog: Path | str, n_shards: int = 12) -> dict:
    """What a run fetches with ``spec`` against a live catalog (``catalog/<term_id>/catalog.json``
    on the data branch): sections with ``last_status`` 200 that match a pattern, their distinct
    courses, and the per-run selection once one of ``n_shards`` shards of the remainder is added
    (shards by ``shard_of(url_path, n_shards)``, as ``ClassesSiteSource._select`` does)."""
    entries = json.loads(Path(catalog).read_text(encoding="utf-8"))["sections"]
    live = [e for e in entries if e.get("last_status") == 200]
    hit = [spec.rank(str(e.get("course_key") or "")) is not None for e in live]
    matched = [e for e, h in zip(live, hit) if h]
    shards = [0] * max(int(n_shards), 1)
    for e, h in zip(live, hit):
        if not h:
            shards[shard_of(str(e["url_path"]), len(shards))] += 1
    return {
        "live": len(live),
        "matched": len(matched),
        "courses": len({str(e.get("course_key")) for e in matched}),
        "selection_min": len(matched) + min(shards),
        "selection_max": len(matched) + max(shards),
    }


def build(
    flows_paths: list[Path], identity_paths: list[Path], *, top_sections: int, current: Path | None, out: Path, source_note: str,
    min_course_joins: int = 0, catalog: Path | None = None, n_shards: int = 12,
) -> dict:
    acts = []
    for fp, ip in zip(flows_paths, identity_paths):
        flows = pd.read_parquet(fp)
        identity = pd.read_parquet(ip)
        acts.append(section_activity(flows, identity, term_id=str(fp.parent.name)))
    activity = pd.concat(acts, ignore_index=True)
    courses = rank_courses(activity, top_sections=top_sections, min_course_joins=min_course_joins)
    text = render(courses, source_note=source_note, top_sections=top_sections, min_course_joins=min_course_joins)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    candidate = PrioritySpec.from_text(text)
    report: dict = {
        "out": str(out),
        "courses": int(len(courses)),
        "sections_in_top": int(courses["top_sections"].sum()),
        "courses_by_total": int((courses["top_sections"] == 0).sum()),
        "min_course_joins": int(min_course_joins),
        "candidate": coverage(activity, candidate),
    }
    if catalog is not None:
        report["candidate"]["live"] = catalog_report(candidate, catalog, n_shards)
    if current is not None and Path(current).exists():
        spec = PrioritySpec.from_file(current)
        report["current"] = coverage(activity, spec)
        if catalog is not None:
            report["current"]["live"] = catalog_report(spec, catalog, n_shards)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Candidate priority list from reconstructed waitlist joins.")
    p.add_argument("--flows", type=Path, nargs="+", required=True, help="flows.parquet of one or more backfilled terms")
    p.add_argument("--identity", type=Path, nargs="+", required=True, help="identity.parquet, one per --flows, same order")
    p.add_argument("--top-sections", type=int, default=DEFAULT_TOP_SECTIONS)
    p.add_argument("--min-course-joins", type=int, default=0, help="also admit every course with at least this many joins over all its sections (0 = off)")
    p.add_argument("--catalog", type=Path, default=None, help="a live catalog.json: report what a run would fetch with the candidate and the current list")
    p.add_argument("--n-shards", type=int, default=12, help="shards of the remainder for the --catalog selection numbers")
    p.add_argument("--current", type=Path, default=DEFAULT_CURRENT, help="the live list, for the comparison")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--note", default="Berkeleytime history (berkeleytime_history)", help="source note written into the file header")
    args = p.parse_args(argv)
    if len(args.flows) != len(args.identity):
        p.error("--flows and --identity must have the same number of paths")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    report = build(
        args.flows, args.identity, top_sections=args.top_sections, current=args.current, out=args.out, source_note=args.note,
        min_course_joins=args.min_course_joins, catalog=args.catalog, n_shards=args.n_shards,
    )
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

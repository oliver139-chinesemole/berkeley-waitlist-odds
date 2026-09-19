"""Probe: fetch six known sections from every available source; print raw payload and parsed row.

DESIGN_A2 section 9. Needs the network; never imported by tests.

    python probe/probe_sources.py --term "Fall 2026"
    python probe/probe_sources.py --term "Fall 2026" --source classes_site --source berkeleytime

Sources: classes_site (always), sis_api (only when SIS_CLASS_APP_ID/SIS_CLASS_APP_KEY are
set), berkeleytime (always). A source whose module is missing from the checkout is
reported and skipped.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper import config  # noqa: E402
from scraper.sources.base import TermSpec  # noqa: E402

logger = logging.getLogger("probe.sources")


@dataclass(frozen=True)
class Target:
    subject: str
    catalog_number: str
    component: str
    section_number: str
    note: str
    class_number: str = "001"

    @property
    def course_key(self) -> str:
        return f"{self.subject} {self.catalog_number}"

    @property
    def label(self) -> str:
        return f"{self.course_key} {self.component} {self.section_number}"


TARGETS: tuple[Target, ...] = (
    Target("COMPSCI", "61A", "LEC", "001", "impacted"),
    Target("DATA", "C100", "LEC", "001", "impacted"),
    Target("STAT", "134", "LEC", "001", "impacted"),
    Target("ECON", "1", "LEC", "001", "large lecture"),
    Target("AEROENG", "1", "SEM", "001", "small seminar"),
    Target("AEROENG", "10", "LEC", "001", "reserved seats"),
)

DRUPAL_SETTINGS_RE = re.compile(
    rb'<script[^>]*data-drupal-selector="drupal-settings-json"[^>]*>(.*?)</script>', re.S
)


def section_url_path(term: TermSpec, t: Target) -> str:
    """``/content/2026-fall-aeroeng-10-001-lec-001`` (docs/PHASE0.md, source 2)."""
    parts = (str(term.year), term.semester, t.subject, t.catalog_number, t.class_number, t.component, t.section_number)
    return "/content/" + "-".join(p.lower().replace(" ", "-") for p in parts)


def extract_drupal_settings(html: bytes) -> dict[str, Any]:
    """The ``drupal-settings-json`` blob of a section page as a dict."""
    m = DRUPAL_SETTINGS_RE.search(html)
    if not m:
        raise ValueError("no drupal-settings-json script in page")
    return json.loads(m.group(1).decode("utf-8"))


def dump(title: str, payload: Any) -> None:
    print(f"--- {title}")
    print(json.dumps(payload, indent=2, default=str))


def probe_classes_site(term: TermSpec, targets: tuple[Target, ...], min_interval_s: float, env: Mapping[str, str]) -> None:
    """Fetch each section page, print ``ucb.enrollment`` and the parsed SnapshotRow."""
    from scraper.http import HttpClient, HttpError
    from scraper.sources.base import ParseError
    from scraper.sources.classes_site import SectionRef, parse_section_page

    client = HttpClient(config.USER_AGENT, min_interval_s=min_interval_s, max_concurrency=1)
    for t in targets:
        url_path = section_url_path(term, t)
        url = config.CLASSES_BASE_URL + url_path
        print(f"\n=== classes_site: {t.label} ({t.note})  {url}")
        try:
            html = client.get(url)
            settings = extract_drupal_settings(html)
            enrollment = settings.get("ucb", {}).get("enrollment")
            dump("raw ucb.enrollment", enrollment)
            section_id = str(enrollment["available"]["id"])
            ref = SectionRef(
                section_id=section_id,
                url_path=url_path,
                course_key=t.course_key,
                subject=t.subject,
                catalog_number=t.catalog_number,
                class_number=t.class_number,
                section_number=t.section_number,
                component=t.component,
            )
            row = parse_section_page(html, ref, datetime.now(timezone.utc), term)
            dump("parsed row", dict(row))
        except (HttpError, ParseError, ValueError, KeyError, TypeError) as exc:
            print(f"!!! {type(exc).__name__}: {exc}")


def probe_sis_api(term: TermSpec, targets: tuple[Target, ...], min_interval_s: float, env: Mapping[str, str]) -> None:
    """Query ``/v1/classes/sections`` per course, print the matching classSection and parsed rows."""
    import requests

    from scraper.sources.sis_api import parse_sections

    creds = config.sis_credentials(env)
    if creds is None:
        print("sis_api: skipped (SIS_CLASS_APP_ID / SIS_CLASS_APP_KEY not set)")
        return
    app_id, app_key = creds
    headers = {"app_id": app_id, "app_key": app_key, "Accept": "application/json", "User-Agent": config.USER_AGENT}
    for t in targets:
        params = {
            "term-id": term.sis_term_id,
            "subject-area-code": t.subject,
            "catalog-number": t.catalog_number,
            "class-number": t.class_number,
            "include-secondary": "true",
            "page-size": "50",
        }
        print(f"\n=== sis_api: {t.label} ({t.note})  {config.SIS_SECTIONS_URL} {params}")
        try:
            resp = requests.get(config.SIS_SECTIONS_URL, headers=headers, params=params, timeout=40)
            print(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            payload = resp.json()
            sections = payload.get("apiResponse", {}).get("response", {}).get("classSections", []) or []
            match = [
                s for s in sections
                if (s.get("component") or {}).get("code") == t.component and str(s.get("number")) == t.section_number
            ]
            dump("raw classSection", match or {"note": f"no {t.component} {t.section_number} among {len(sections)} sections", "first": sections[:1]})
            rows = parse_sections(payload, datetime.now(timezone.utc), term)
            wanted = [dict(r) for r in rows if r["component"] == t.component and r["section_number"] == t.section_number]
            dump("parsed row", wanted)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            print(f"!!! {type(exc).__name__}: {exc}")


def unwrap_class(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept a full GraphQL response, a ``{"class": ...}`` wrapper, or the class object itself."""
    if "data" in payload:
        return payload["data"]["class"]
    if "class" in payload:
        return payload["class"]
    return payload


def find_bt_section(cls: Mapping[str, Any], component: str, number: str) -> Mapping[str, Any] | None:
    """The primarySection or secondary section with this component and number."""
    candidates = [cls.get("primarySection")] + list(cls.get("sections") or [])
    for s in candidates:
        if s and s.get("component") == component and str(s.get("number")) == number:
            return s
    return None


def probe_berkeleytime(term: TermSpec, targets: tuple[Target, ...], min_interval_s: float, env: Mapping[str, str]) -> None:
    """``GetClass`` per course; print the section's ``enrollment.latest`` and the counts we would keep.

    Berkeleytime's fetch path is GetCatalog (primary sections, synthetic ids), so the
    "parsed" output here is the count mapping, not a full SnapshotRow.
    """
    from scraper.sources.base import ParseError
    from scraper.sources.berkeleytime import BerkeleytimeError, BerkeleytimeSource
    from scraper.sources.sis_api import TransportError

    source = BerkeleytimeSource()
    for t in targets:
        print(f"\n=== berkeleytime: {t.label} ({t.note})  GetClass({term.year}, {term.semester}, {t.subject}, {t.catalog_number}, {t.class_number})")
        try:
            cls = unwrap_class(source.get_class(term, t.subject, t.catalog_number, t.class_number))
            section = find_bt_section(cls, t.component, t.section_number)
            if section is None:
                print(f"!!! no section {t.component} {t.section_number} in GetClass response")
                continue
            latest = (section.get("enrollment") or {}).get("latest") or {}
            dump("raw section", {"sectionId": section.get("sectionId"), "number": section.get("number"), "component": section.get("component"), "enrollment.latest": latest})
            dump("counts", {
                "section_id": str(section.get("sectionId")),
                "enrolled_count": latest.get("enrolledCount"),
                "enroll_capacity": latest.get("maxEnroll"),
                "waitlist_count": latest.get("waitlistedCount"),
                "waitlist_capacity": latest.get("maxWaitlist"),
                "status": latest.get("status"),
                "as_of": latest.get("endTime"),
            })
        except (BerkeleytimeError, TransportError, ParseError, ValueError, KeyError, TypeError) as exc:
            print(f"!!! {type(exc).__name__}: {exc}")


PROBES: dict[str, Callable[[TermSpec, tuple[Target, ...], float, Mapping[str, str]], None]] = {
    "classes_site": probe_classes_site,
    "sis_api": probe_sis_api,
    "berkeleytime": probe_berkeleytime,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch six known sections from each source and print raw + parsed data.")
    p.add_argument("--term", required=True, help='e.g. "Fall 2026"')
    p.add_argument("--source", action="append", choices=tuple(PROBES), help="repeatable; default: all")
    p.add_argument("--min-interval-s", type=float, default=config.DEFAULTS["min_interval_s"])
    return p


def main(argv: list[str] | None = None) -> int:
    import os

    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    term = TermSpec.from_name(args.term)
    print(f"term {term.name} sis_term_id={term.sis_term_id}  user-agent: {config.USER_AGENT}")
    for name in args.source or list(PROBES):
        print(f"\n##### source: {name}")
        try:
            PROBES[name](term, TARGETS, args.min_interval_s, os.environ)
        except ImportError as exc:
            print(f"{name}: module not available in this checkout ({exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

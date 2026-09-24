"""Tests for analysis.priority_from_flows: ranking, rendering, coverage, CLI."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from analysis.priority_from_flows import catalog_report, coverage, main, rank_courses, render, section_activity
from scraper.sources.base import PrioritySpec


def flows_and_identity() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    # section: (joins per interval, waitlist0 per interval)
    spec = {
        "1": ([5, 3, 0], [0, 5, 8]),  # COMPSCI 61A, busy
        "2": ([0, 0, 0], [0, 0, 0]),  # COMPSCI 61A, quiet section
        "3": ([2, 0], [0, 2]),  # MATH 1A
        "4": ([0, 0], [3, 3]),  # ART 1: a queue but no joins seen
        "5": ([9], [9]),  # STAT 20
    }
    for sid, (joins, w0) in spec.items():
        for j, w in zip(joins, w0):
            rows.append({"section_id": sid, "wl_joins": j, "admits": 0, "waitlist0": w})
    flows = pd.DataFrame(rows)
    identity = pd.DataFrame(
        [
            {"section_id": "1", "course_key": "COMPSCI 61A", "subject": "COMPSCI", "catalog_number": "61A"},
            {"section_id": "2", "course_key": "COMPSCI 61A", "subject": "COMPSCI", "catalog_number": "61A"},
            {"section_id": "3", "course_key": "MATH 1A", "subject": "MATH", "catalog_number": "1A"},
            {"section_id": "4", "course_key": "ART 1", "subject": "ART", "catalog_number": "1"},
            {"section_id": "5", "course_key": "STAT 20", "subject": "STAT", "catalog_number": "20"},
        ]
    )
    return flows, identity


def test_activity_ranking_and_rendering() -> None:
    flows, identity = flows_and_identity()
    act = section_activity(flows, identity, term_id="2268")
    assert list(act["section_id"]) == ["5", "1", "3", "2", "4"] or list(act["section_id"])[:3] == ["5", "1", "3"]
    assert act.set_index("section_id").at["1", "wl_joins"] == 8 and act.set_index("section_id").at["1", "max_waitlist"] == 8
    courses = rank_courses(act, top_sections=2)  # sections 5 and 1 -> STAT 20 and COMPSCI 61A
    assert list(courses["course_key"]) == ["STAT 20", "COMPSCI 61A"]
    assert courses.set_index("course_key").at["COMPSCI 61A", "sections"] == 2 and courses.set_index("course_key").at["COMPSCI 61A", "top_sections"] == 1
    text = render(courses, source_note="unit test", top_sections=2)
    spec = PrioritySpec.from_text(text)
    assert spec.patterns == ("STAT 20", "COMPSCI 61A") and "# 9 joins, 1 sections" in text and "ORDER MATTERS" in text
    assert spec.rank("compsci 61a") == 1 and spec.matches("MATH 1A") is False


def test_coverage_counts_sections_and_joins() -> None:
    flows, identity = flows_and_identity()
    act = section_activity(flows, identity)
    current = PrioritySpec.from_text("COMPSCI *\nMATH 1*\n")
    cov = coverage(act, current)
    assert cov["patterns"] == 2 and cov["sections"] == 5 and cov["sections_matched"] == 3
    assert cov["sections_with_queue"] == 4 and cov["sections_with_queue_matched"] == 2  # 1 and 3 (2 has no queue, 4 and 5 unmatched)
    assert cov["sections_with_joins"] == 3 and cov["sections_with_joins_matched"] == 2
    assert cov["share_joins_matched"] == round(10 / 19, 4)


def test_cli_writes_candidate_and_reports(tmp_path: Path) -> None:
    flows, identity = flows_and_identity()
    fdir = tmp_path / "2268"
    fdir.mkdir()
    flows.to_parquet(fdir / "flows.parquet", index=False)
    identity.to_parquet(fdir / "identity.parquet", index=False)
    current = tmp_path / "priority_courses.txt"
    current.write_text("COMPSCI *\n")
    out = tmp_path / "candidate.txt"
    assert main(["--flows", str(fdir / "flows.parquet"), "--identity", str(fdir / "identity.parquet"), "--top-sections", "3", "--current", str(current), "--out", str(out), "--note", "test"]) == 0
    text = out.read_text()
    assert PrioritySpec.from_text(text).patterns == ("STAT 20", "COMPSCI 61A", "MATH 1A")
    assert "Built by `python -m analysis.priority_from_flows`" in text and "test" in text


# -- course-total pass and the live-catalog report (review of the 2026-09-23 install) -----


def test_course_total_pass_adds_courses_with_many_small_sections() -> None:
    flows, identity = flows_and_identity()
    act = section_activity(flows, identity, term_id="2268")
    only_top = rank_courses(act, top_sections=1)  # section 5 -> STAT 20
    assert list(only_top["course_key"]) == ["STAT 20"]
    courses = rank_courses(act, top_sections=1, min_course_joins=8)  # COMPSCI 61A totals 8 over two sections
    assert list(courses["course_key"]) == ["STAT 20", "COMPSCI 61A"]
    by_key = courses.set_index("course_key")
    assert by_key.at["COMPSCI 61A", "top_sections"] == 0 and by_key.at["COMPSCI 61A", "joins"] == 8
    text = render(courses, source_note="unit test", top_sections=1, min_course_joins=8)
    lines = {l.split()[0] + " " + l.split()[1]: l for l in text.splitlines() if not l.startswith("#") and l.strip()}
    assert "by course total" in lines["COMPSCI 61A"] and "by course total" not in lines["STAT 20"]
    assert "at least 8 joins" in text and "unique section ids" in text


def test_catalog_report_counts_live_matches_and_the_selection(tmp_path: Path) -> None:
    import json

    entries = [
        {"url_path": "/content/a", "course_key": "COMPSCI 61A", "last_status": 200},
        {"url_path": "/content/b", "course_key": "COMPSCI 61A", "last_status": 200},
        {"url_path": "/content/c", "course_key": "STAT 20", "last_status": 200},
        {"url_path": "/content/d", "course_key": "MATH 1A", "last_status": 404},
        {"url_path": "/content/e", "course_key": "ART 1", "last_status": 200},
    ]
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"sections": entries}))
    report = catalog_report(PrioritySpec.from_text("STAT 20\nCOMPSCI 61A\n"), catalog, n_shards=2)
    assert report["live"] == 4 and report["matched"] == 3 and report["courses"] == 2
    # one remainder section (ART 1) lands in one of the two shards
    assert (report["selection_min"], report["selection_max"]) == (3, 4)


def test_cli_course_total_and_catalog_flags(tmp_path: Path, capsys) -> None:
    import json

    flows, identity = flows_and_identity()
    fdir = tmp_path / "2268"
    fdir.mkdir()
    flows.to_parquet(fdir / "flows.parquet", index=False)
    identity.to_parquet(fdir / "identity.parquet", index=False)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"sections": [
        {"url_path": "/content/a", "course_key": "COMPSCI 61A", "last_status": 200},
        {"url_path": "/content/c", "course_key": "STAT 20", "last_status": 200},
        {"url_path": "/content/e", "course_key": "ART 1", "last_status": 200},
    ]}))
    current = tmp_path / "priority_courses.txt"
    current.write_text("ART 1\n")
    out = tmp_path / "candidate.txt"
    assert main(["--flows", str(fdir / "flows.parquet"), "--identity", str(fdir / "identity.parquet"), "--top-sections", "1",
                 "--min-course-joins", "8", "--catalog", str(catalog), "--n-shards", "2", "--current", str(current), "--out", str(out), "--note", "test"]) == 0
    assert PrioritySpec.from_text(out.read_text()).patterns == ("STAT 20", "COMPSCI 61A")
    report = json.loads(capsys.readouterr().out)
    assert report["min_course_joins"] == 8
    assert report["candidate"]["live"] == {"live": 3, "matched": 2, "courses": 2, "selection_min": 2, "selection_max": 3}
    assert report["current"]["live"]["matched"] == 1

"""Tests for analysis.priority_from_flows: ranking, rendering, coverage, CLI."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from analysis.priority_from_flows import coverage, main, rank_courses, render, section_activity
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

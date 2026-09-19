"""Renders site/index.html without a browser and checks the states in docs/DESIGN_A6.md.

The page's own inline script runs under node against a stub document and a
file-backed ``fetch`` (tests/site/harness.js). Skipped when node is missing.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from analysis.calendar import TermCalendar
from analysis.export import export_site_tables
from analysis.run import run_analysis
from tests.test_run import sim_inputs
from tests.test_survival import synthetic_cohort

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "site" / "index.html"
HARNESS = ROOT / "tests" / "site" / "harness.js"


def find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    candidates = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
    return candidates[-1] if candidates else None


NODE = find_node()
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

# Matches tests/test_survival.T0 (joins from 2026-10-27) so the horizon is positive.
CAL = TermCalendar(
    term_id="9999",
    name="Simulated term",
    phase1_start=date(2026, 10, 26),
    phase1_end=date(2026, 11, 15),
    phase2_start=date(2026, 11, 23),
    phase2_end=date(2027, 1, 10),
    adjustment_start=date(2027, 1, 11),
    instruction_start=date(2027, 1, 19),
    last_auto_waitlist=date(2027, 2, 5),
    add_drop_deadline=date(2027, 2, 10),
)


def render(site_root: Path, *, search: str = "", course: str = "", position: str = "") -> dict:
    proc = subprocess.run(
        [str(NODE), str(HARNESS), str(INDEX), str(site_root), search, course, position],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def full_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("site_full")
    export_site_tables(synthetic_cohort(), CAL, root / "data")
    return root


@pytest.fixture(scope="module")
def narrow_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Only positions 1 to 5 ever joined, so every course has a single bucket."""
    root = tmp_path_factory.mktemp("site_narrow")
    cohort = synthetic_cohort()
    export_site_tables(cohort[cohort["position"] <= 5], CAL, root / "data")
    return root


def test_empty_state_without_data(tmp_path: Path) -> None:
    out = render(tmp_path)
    assert "No estimates yet" in out["status"] and "Oct 26, 2026" in out["status"]
    assert out["form_hidden"] and out["result_hidden"] and out["datalist_options"] == 0


def test_empty_state_shows_counts_from_meta(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "meta.json").write_text(json.dumps({"events": 3, "sections": 704, "cohort_rows": 809, "term_name": "Fall 2026"}))
    out = render(tmp_path)
    assert "No estimates yet" in out["status"] and "704 sections" in out["status"] and "809 hypothetical joiners" in out["status"] and "3 clearings" in out["status"]
    assert out["form_hidden"]


def test_meta_from_the_analysis_run_renders_as_numbers(tmp_path: Path) -> None:
    """analysis.run writes meta.json for the site; every count it prints must be a number, not an object."""
    panel, identity, cal = sim_inputs()
    few = panel[panel["section_id"].isin(sorted(panel["section_id"].unique())[:2])]
    site_root = tmp_path / "site"
    res = run_analysis(few, identity, cal, tmp_path / "out", site_dir=site_root / "data", join_every_min=1440)
    assert res.site_files is not None
    meta = json.loads(Path(res.site_files[1]).read_text())
    out = render(site_root)
    assert "[object Object]" not in out["status"] and "undefined" not in out["status"]
    assert f"{meta['cohort_rows']} hypothetical joiners" in out["status"] and f"{meta['sections']} sections" in out["status"]


def test_full_state_lists_courses(full_site: Path) -> None:
    courses = json.loads((full_site / "data" / "courses.json").read_text())
    meta = json.loads((full_site / "data" / "meta.json").read_text())
    assert meta["events"] >= 10
    out = render(full_site)
    assert not out["form_hidden"] and out["result_hidden"]
    assert out["datalist_options"] == len(courses)
    assert "Simulated term" in out["status"] and f"{len(courses)} courses" in out["status"] and f"{meta['events']} of whom cleared" in out["status"]
    assert out["stamp"].startswith("Data through") and "[object Object]" not in out["status"]


def test_lookup_renders_estimate_curve_and_sample_size(full_site: Path) -> None:
    courses = json.loads((full_site / "data" / "courses.json").read_text())
    cell = courses["COMPSCI 0"]["buckets"]["1-5"]
    assert cell["pooled"] is False
    out = render(full_site, course="compsci   0", position="3")
    r = out["result"]
    assert not out["result_hidden"]
    assert "COMPSCI 0" in r and "position 3" in r and "bucket 1-5" in r
    assert f"{round(cell['p_clear_by_instruction'] * 100)}%" in r and "by the first day of instruction" in r
    assert f"{cell['n']} hypothetical joiners" in r and f"{cell['events']} cleared" in r
    assert "<svg" in r and r.count("<circle") == len(cell["curve"]) and "instruction" in r
    assert 'class="tag pooled"' not in r


def test_pooled_estimate_is_labelled(full_site: Path) -> None:
    courses = json.loads((full_site / "data" / "courses.json").read_text())
    cell = courses["COMPSCI 0"]["buckets"]["6-15"]
    assert cell["pooled"] == "COMPSCI" and "n_course" in cell
    out = render(full_site, course="COMPSCI 0", position="10")
    r = out["result"]
    assert 'class="tag pooled"' in r and "COMPSCI department" in r
    assert f"({cell['n_course']} in this course)" in r


def test_unknown_course_message(full_site: Path) -> None:
    out = render(full_site, course="NOPE 1", position="4")
    assert "No data for" in out["result"] and "NOPE 1" in out["result"] and not out["result_hidden"]


def test_missing_bucket_names_the_buckets_with_data(narrow_site: Path) -> None:
    out = render(narrow_site, course="MATH 1", position="20")
    r = out["result"]
    assert "No estimate for positions 16-40" in r and "MATH 1" in r and "Positions with data: 1-5" in r


def test_query_string_runs_the_lookup_on_load(full_site: Path) -> None:
    out = render(full_site, search="?course=STAT%202&position=12")
    assert not out["result_hidden"] and "STAT 2" in out["result"] and "position 12" in out["result"]

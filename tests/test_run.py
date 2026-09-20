"""End-to-end test of analysis.run on simulated data, plus the site exporter's pooling rule."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from analysis.calendar import TermCalendar
from analysis.export import course_tables, export_site_tables
from analysis.run import run_analysis
from analysis.synthetic import SimConfig, simulate
from tests.test_survival import synthetic_cohort

SUBJECTS = ["COMPSCI", "MATH", "STAT", "ART", "HISTORY"]


# Longer queues and fewer drops than the simulator's defaults, so that some virtual
# waitlisters are still waiting 14 days after joining and the out-of-sample check
# has known negatives as well as known positives.
SIM = dict(days=21, join_rate_per_day=10.0, enr_drop_rate_per_day=1.0, wl_drop_rate_per_day=0.5, initial_fill=1.0)


def sim_inputs(seed: int = 1):
    """Simulated panel, identity and a calendar whose Phase 2 starts on day 5, so the
    out-of-sample check (fit before Phase 2, score 14-day outcomes after it) has
    rows with a known outcome."""
    panel, _, _ = simulate(SimConfig(seed=seed, **SIM))
    ids = sorted(panel["section_id"].unique())
    identity = pd.DataFrame(
        [
            {
                "section_id": s,
                "course_key": f"{SUBJECTS[i % 5]} {100 + i if i % 3 == 0 else i + 1}",
                "subject": SUBJECTS[i % 5],
                "catalog_number": str(100 + i if i % 3 == 0 else i + 1),
                "class_number": "001",
                "section_number": "001",
                "component": "LEC",
                "is_primary": True,
                "session_id": "1",
            }
            for i, s in enumerate(ids)
        ]
    )
    day0 = pd.Timestamp(panel["run_started_at"].min()).date()
    cal = TermCalendar(
        term_id="9999",
        name="Simulated term",
        phase1_start=day0,
        phase1_end=day0 + timedelta(days=4),
        phase2_start=day0 + timedelta(days=5),
        phase2_end=day0 + timedelta(days=15),
        adjustment_start=day0 + timedelta(days=16),
        instruction_start=day0 + timedelta(days=24),
        last_auto_waitlist=day0 + timedelta(days=34),
        add_drop_deadline=day0 + timedelta(days=38),
    )
    return panel, identity, cal


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory):
    panel, identity, cal = sim_inputs()
    out = tmp_path_factory.mktemp("analysis_out")
    return run_analysis(panel, identity, cal, out, site_dir=out / "site", join_every_min=240), out


def test_run_produces_everything(result) -> None:
    res, out = result
    assert res.notes == [] or all("PH assumption" in n for n in res.notes)
    assert set(res.km_tables) == {"position_bucket", "level", "dept_group", "phase"}
    assert res.cox_summary is not None and "log_position" in res.cox_summary.index
    assert res.cox_summary.at["log_position", "coef"] < 0
    assert list(res.sensitivity["scenario"]) == ["optimistic", "central", "pessimistic"]
    med = res.sensitivity.set_index("scenario")["median_days_pos10_lower_phase1"]
    assert med["optimistic"] <= med["central"] <= med["pessimistic"]
    oos = res.out_of_sample
    assert list(oos["metrics"]["predictor"]) == ["bucket", "dept", "course", "site", "cox"] and oos["brier_rows"] > 0
    assert 0.5 < oos["auc_cox"] <= 1.0 and 0.0 <= oos["brier_cox"] <= 1.0
    assert (term_dir / "backtest_14d.csv").exists() if (term_dir := out / "9999") else True
    names = {p.name for p in res.figures}
    assert {"km_position_bucket.png", "km_level.png", "km_dept_group.png", "km_phase.png", "hero.png", "calibration.png"} <= names
    assert all(p.exists() and p.stat().st_size > 1000 for p in res.figures)
    term_dir = out / "9999"
    for name in ("flows.parquet", "cohort_central.parquet", "cohort_optimistic.parquet", "cohort_pessimistic.parquet", "cox.csv", "cox_ph_test.csv", "sensitivity.csv", "calibration.csv", "report.md"):
        assert (term_dir / name).exists(), name
    report = (term_dir / "report.md").read_text()
    assert "## Kaplan-Meier by position_bucket" in report and "## Cox proportional hazards" in report and "## Headline" in report


def test_site_tables_are_valid_json_with_sample_sizes(result) -> None:
    res, out = result
    courses_path, meta_path = res.site_files
    courses = json.loads(courses_path.read_text())
    meta = json.loads(meta_path.read_text())
    # a simulated course whose sections never filled and never queued has no joinable moments, so 40 is an upper bound
    assert 36 <= len(courses) <= 40 and meta["courses"] == len(courses) and meta["term_id"] == "9999"
    for key, entry in courses.items():
        assert entry["subject"] == key.split()[0] and entry["level"] in ("lower", "upper", "grad")
        for bucket, cell in entry["buckets"].items():
            assert 0.0 <= cell["p_clear_by_instruction"] <= 1.0 and cell["n"] > 0 and 1 <= cell["sections"] <= cell["n"]
            assert cell["pooled"] in (False, "all") or isinstance(cell["pooled"], str)
            assert cell["horizon_days"] >= 0 and cell["curve"] and all(0.0 <= p <= 1.0 for _, p, _, _ in cell["curve"])
            ps = [p for _, p, _, _ in cell["curve"]]
            assert ps == sorted(ps)  # cumulative clearing never falls
            assert cell["curve"][-1][0] == pytest.approx(cell["reach_days"], abs=0.06) and cell["reach_days"] > 0
            for _, p, lo, hi in cell["curve"]:
                assert lo is None or (lo - 1e-9 <= p <= hi + 1e-9 and 0.0 <= lo <= hi <= 1.0)


def test_export_pooling_rule() -> None:
    cohort = synthetic_cohort(n_sections=8, joins_per_section=4)
    cal = TermCalendar("2272", "x", *([pd.Timestamp("2026-10-26").date()] * 8))
    tables = course_tables(cohort, cal, min_n=30, level="course")
    # each course has 4 joins x 6 positions = 24 rows spread over buckets: every cell is pooled
    for entry in tables.values():
        for cell in entry["buckets"].values():
            assert cell["pooled"] is not False and "n_course" in cell and "sections_course" in cell
    big = synthetic_cohort(n_sections=8, joins_per_section=40)
    tables = course_tables(big, cal, min_n=30, level="course")
    unpooled = [cell for e in tables.values() for cell in e["buckets"].values() if cell["pooled"] is False]
    assert unpooled and all(cell["n"] >= 30 for cell in unpooled)
    # the default level serves the department curve everywhere, with the course's own counts alongside
    dept = course_tables(big, cal, min_n=30)
    for key, entry in dept.items():
        for cell in entry["buckets"].values():
            assert cell["pooled"] in (entry["subject"], "OTHER", "all") and cell["n_course"] <= cell["n"] and cell["sections_course"] >= 1
    with pytest.raises(ValueError):
        course_tables(big, cal, level="school")


def test_export_empty(tmp_path: Path) -> None:
    cal = TermCalendar("2272", "x", *([pd.Timestamp("2026-10-26").date()] * 8))
    empty = synthetic_cohort(n_sections=1, joins_per_section=1).iloc[0:0]
    courses_path, meta_path = export_site_tables(empty, cal, tmp_path)
    meta = json.loads(meta_path.read_text())
    assert json.loads(courses_path.read_text()) == {} and meta["cohort_rows"] == 0
    assert meta["deadline"] == "2026-10-26" and meta["instruction_start"] == "2026-10-26" and meta["positions"] == [] and meta["estimate_level"] == "dept"


def test_run_too_small_writes_notes(tmp_path: Path) -> None:
    panel, identity, cal = sim_inputs()
    first_days = panel["run_started_at"] < panel["run_started_at"].min() + timedelta(days=3)
    few = panel[first_days & panel["section_id"].isin(sorted(panel["section_id"].unique())[:2])]
    res = run_analysis(few, identity, cal, tmp_path, join_every_min=1440)
    assert any("too small" in n for n in res.notes) and res.cox_summary is None and (res.out_dir / "report.md").exists()

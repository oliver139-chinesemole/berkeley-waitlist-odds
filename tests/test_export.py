"""The site's JSON (docs/DESIGN_A5.md section 4): index, per-subject curves, pools, insights, meta."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from analysis.calendar import FALL_2026, SPRING_2027, TermCalendar
from analysis.export import HORIZONS, course_tables, export_site_tables, index_rows, insights_tables, joins_by_course, main, pool_tables, read_curve, resolve_pool
from tests.test_survival import synthetic_cohort

CAL = TermCalendar("9999", "Simulated term", date(2026, 10, 26), date(2026, 11, 15), date(2026, 11, 23), date(2027, 1, 10), date(2027, 1, 11), date(2027, 1, 19), date(2027, 2, 5), date(2027, 2, 10))


@pytest.fixture(scope="module")
def cohort() -> pd.DataFrame:
    return synthetic_cohort()


@pytest.fixture(scope="module")
def pools(cohort: pd.DataFrame) -> dict:
    return pool_tables(cohort, min_n=30, n_boot=20)


def test_read_curve_is_a_step_function() -> None:
    curve = [[0.5, 0.1, 0.05, 0.2], [1, 0.3, 0.2, 0.4], [7, 0.6, 0.5, 0.7]]
    assert read_curve(curve, 0.2) == (0.0, None, None, 0.0)
    assert read_curve(curve, 0.5) == (0.1, 0.05, 0.2, 0.5)
    assert read_curve(curve, 3.0) == (0.3, 0.2, 0.4, 1.0)
    assert read_curve(curve, 100.0) == (0.6, 0.5, 0.7, 7.0)  # past the reach the last point stands


def test_pools_cover_all_dept_and_level(cohort: pd.DataFrame, pools: dict) -> None:
    assert set(pools["all"]) == {"1-5", "6-15", "16-40", "41+"}
    assert set(pools["dept"]) <= {"COMPSCI", "MATH", "STAT", "OTHER"} and set(pools["level"]) <= {"lower", "upper"}
    for group in (pools["all"], *pools["dept"].values(), *pools["level"].values()):
        for cell in group.values():
            assert cell["n"] >= 30 and cell["curve"] and cell["curve"][-1][0] == pytest.approx(cell["reach_days"], abs=0.06)
    assert resolve_pool(pools, "all", "1-5") is pools["all"]["1-5"] and resolve_pool(pools, "COMPSCI", "1-5") is pools["dept"]["COMPSCI"]["1-5"]
    assert resolve_pool(pools, "NOPE", "1-5") is None


def test_course_cells_are_curves_or_pointers(cohort: pd.DataFrame, pools: dict) -> None:
    courses = course_tables(cohort, CAL, min_n=30, n_boot=20, pools=pools)
    kinds = {"curve": 0, "pointer": 0}
    for key, entry in courses.items():
        assert entry["subject"] == key.split()[0] and entry["number"] == key.split()[1] and entry["dept_group"] in pools["dept"] | {"OTHER": None}
        for bucket, cell in entry["buckets"].items():
            if cell["pooled"] is False:
                kinds["curve"] += 1
                assert cell["n"] >= 30 and "curve" in cell
            else:
                kinds["pointer"] += 1
                assert set(cell) == {"pooled", "n_course", "sections_course"} and cell["n_course"] < 30
                assert resolve_pool(pools, cell["pooled"], bucket) is not None
    assert kinds["curve"] > 0 and kinds["pointer"] > 0


def test_index_rows_summarise_at_the_fixed_horizons(cohort: pd.DataFrame, pools: dict) -> None:
    courses = course_tables(cohort, CAL, min_n=30, n_boot=20, pools=pools)
    rows = index_rows(courses, pools, {"COMPSCI 0": 17})
    by_key = {r["key"]: r for r in rows}
    assert by_key["COMPSCI 0"]["joins"] == 17 and by_key["MATH 1"]["joins"] == 0
    for key, row in by_key.items():
        for bucket, s in row["buckets"].items():
            cell = courses[key]["buckets"][bucket]
            source = cell if cell["pooled"] is False else resolve_pool(pools, cell["pooled"], bucket)
            assert s["p"] == [read_curve(source["curve"], h)[0] for h in HORIZONS]
            assert s["reach"] == [source["curve"][-1][1], source["reach_days"]] and s["n"] == source["n"]
            assert s["pooled"] == cell["pooled"]
            if cell["pooled"] is not False:
                assert s["n_course"] == cell["n_course"]
            assert s["p"] == sorted(s["p"])


def test_joins_by_course_sums_flows_of_known_sections(cohort: pd.DataFrame) -> None:
    flows = pd.DataFrame({"section_id": ["0", "0", "1", "999"], "wl_joins": [3, 4, 5, 100]})
    joins = joins_by_course(cohort, flows)
    assert joins == {"COMPSCI 0": 7, "MATH 1": 5}
    assert joins_by_course(cohort, None) == {} and joins_by_course(cohort, flows.iloc[0:0]) == {}


def test_insights_tables(cohort: pd.DataFrame, pools: dict) -> None:
    flows = pd.DataFrame(
        {
            "section_id": ["0", "0", "1"],
            "t1": pd.to_datetime(["2026-10-27T10:00Z", "2026-10-28T10:00Z", "2026-10-28T12:00Z"]),
            "admits": [1, 2, 0],
            "wl_joins": [3, 0, 1],
            "wl_drops": [0, 1, 0],
            "censored": [False, True, False],
            "waitlist0": [5, 4, 2],
            "d_waitlist": [-1, 0, 1],
        }
    )
    ins = insights_tables(cohort, pools, min_n=30, n_boot=10, flows=flows)
    assert ins["horizons"] == [7.0, 14.0, 28.0] and ins["counts"]["rows"] == len(cohort)
    assert list(ins["all_by_bucket"]) == ["1-5", "6-15", "16-40", "41+"]
    assert set(ins["hero"]) and all(c["n"] >= 30 and c["curve"] for c in ins["hero"].values())
    assert set(ins["by_phase"]) == {"phase1", "phase2"} and all(len(s["p"]) == 3 for grid in ins["by_phase"].values() for s in grid.values())
    assert set(ins["by_level"]) <= {"lower", "upper"}
    assert ins["daily"] == [
        {"date": "2026-10-27", "admits": 1, "joins": 3, "drops": 0, "intervals": 1, "share_censored": 0.0},
        {"date": "2026-10-28", "admits": 2, "joins": 1, "drops": 1, "intervals": 2, "share_censored": 0.5},
    ]
    assert ins["exits"] == {"admitted": 3, "dropped": 1, "still_waiting": 4 + 3}


def test_export_writes_every_file_and_the_forecast_calendar(cohort: pd.DataFrame, tmp_path: Path) -> None:
    index_path, meta_path = export_site_tables(cohort, FALL_2026, tmp_path, n_boot=10, forecast_calendar=SPRING_2027, meta={"data_source": "berkeleytime_history"})
    meta = json.loads(meta_path.read_text())
    assert meta["term_id"] == "2268" and meta["term_name"] == "Fall 2026" and meta["forecast_term_id"] == "2272"
    assert meta["deadline"] == "2027-02-05" and meta["instruction_start"] == "2027-01-19" and meta["dates"]["phase1_start"] == "2026-10-26"
    assert meta["data_dates"]["instruction_start"] == "2026-08-26" and meta["data_dates"]["last_auto_waitlist"] == "2026-09-11"
    assert meta["data_source"] == "berkeleytime_history" and meta["terms"] == [{"term_id": "2268", "term_name": "Fall 2026", "data_source": "berkeleytime_history"}]
    assert meta["rank"] is None  # no flows given
    assert {p.name for p in tmp_path.iterdir()} == {"index.json", "meta.json", "pooled.json", "insights.json", "courses"}
    assert {p.name for p in (tmp_path / "courses").iterdir()} == {"COMPSCI.json", "MATH.json", "STAT.json", "ART.json"}
    assert meta["subject_files"]["ART"] == "courses/ART.json"
    index = json.loads(index_path.read_text())
    assert index["term_id"] == "2268" and len(index["courses"]) == meta["courses"] > 0
    for text in (index_path.read_text(), (tmp_path / "pooled.json").read_text()):
        assert "NaN" not in text and "Infinity" not in text


def test_export_removes_stale_files(cohort: pd.DataFrame, tmp_path: Path) -> None:
    (tmp_path / "courses").mkdir()
    (tmp_path / "courses" / "OLD.json").write_text("{}")
    (tmp_path / "courses.json").write_text("{}")
    export_site_tables(cohort, CAL, tmp_path, n_boot=5)
    assert not (tmp_path / "courses" / "OLD.json").exists() and not (tmp_path / "courses.json").exists()


def test_cli_rebuilds_site_data_from_a_saved_cohort(cohort: pd.DataFrame, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cohort_path = tmp_path / "cohort.parquet"
    cohort.to_parquet(cohort_path, index=False)
    old_meta = tmp_path / "old_meta.json"
    old_meta.write_text(json.dumps({"data_source": "berkeleytime_history", "backfill": {"sections": 296}, "flows": {"admits": 1}, "unrelated": 1}))
    out = tmp_path / "site_data"
    assert main(["--cohort", str(cohort_path), "--term-id", "2268", "--forecast-term", "2272", "--out", str(out), "--meta-from", str(old_meta), "--n-boot", "5", "--prereg-commit", "abc123", "--prereg-date", "2026-09-21"]) == 0
    printed = json.loads(capsys.readouterr().out)
    meta = json.loads((out / "meta.json").read_text())
    assert printed["courses"] == meta["courses"] and printed["data_source"] == "berkeleytime_history"
    assert meta["backfill"] == {"sections": 296} and meta["flows"] == {"admits": 1} and "unrelated" not in meta
    assert meta["prereg_commit"] == "abc123" and meta["prereg_date"] == "2026-09-21" and meta["forecast_term_name"] == "Spring 2027"

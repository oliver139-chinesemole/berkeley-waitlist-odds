"""The site's JSON (docs/DESIGN_A5.md section 4): index, per-subject curves, pools, insights, meta, titles."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import analysis.export as export
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


def test_course_cells_are_pointers_at_the_department_level(cohort: pd.DataFrame, pools: dict) -> None:
    courses = course_tables(cohort, CAL, min_n=30, n_boot=20, pools=pools, estimate_level="dept")
    assert courses
    for key, entry in courses.items():
        for bucket, cell in entry["buckets"].items():
            assert set(cell) == {"pooled", "n_course", "sections_course"} and cell["pooled"] in (entry["dept_group"], "all")
            assert resolve_pool(pools, cell["pooled"], bucket) is not None and cell["n_course"] >= 1
    with pytest.raises(ValueError):
        course_tables(cohort, CAL, min_n=30, n_boot=5, pools=pools, estimate_level="section")


def test_course_cells_are_curves_or_pointers_at_the_course_default(cohort: pd.DataFrame, pools: dict) -> None:
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


@pytest.mark.parametrize("level", ["dept", "course"])
def test_index_rows_summarise_at_the_fixed_horizons(cohort: pd.DataFrame, pools: dict, level: str) -> None:
    courses = course_tables(cohort, CAL, min_n=30, n_boot=20, pools=pools, estimate_level=level)
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
    assert meta["estimate_level"] == "course"
    entries = json.loads((tmp_path / "courses" / "COMPSCI.json").read_text())["courses"]
    assert any(cell["pooled"] is False for e in entries.values() for cell in e["buckets"].values())
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
    assert main(["--cohort", str(cohort_path), "--term-id", "2268", "--forecast-term", "2272", "--out", str(out), "--meta-from", str(old_meta), "--n-boot", "5", "--prereg-commit", "abc123", "--prereg-date", "2026-09-21", "--estimate-level", "dept"]) == 0
    printed = json.loads(capsys.readouterr().out)
    meta = json.loads((out / "meta.json").read_text())
    assert printed["courses"] == meta["courses"] and printed["data_source"] == "berkeleytime_history" and printed["estimate_level"] == "dept" and meta["estimate_level"] == "dept"
    assert all(cell["pooled"] is not False for e in json.loads((out / "courses" / "COMPSCI.json").read_text())["courses"].values() for cell in e["buckets"].values())
    assert meta["backfill"] == {"sections": 296} and meta["flows"] == {"admits": 1} and "unrelated" not in meta
    assert meta["prereg_commit"] == "abc123" and meta["prereg_date"] == "2026-09-21" and meta["forecast_term_name"] == "Spring 2027"


# --- titles.json: course titles and instructors from the classes_site catalog (Q4) ---

TITLE_CATALOG = {
    "term_id": "2268",
    "term_name": "Fall 2026",
    "sections": [
        # two sections, two spellings of the title (one each: the tie goes to the LEC's); instructors as lists
        {"course_key": "COMPSCI 0", "component": "DIS", "section_id": "101", "title": "The Structure and Interpretation of Computer Programs", "instructors": ["Pamela Fox", " Zoe Tan "]},
        {"course_key": "COMPSCI 0", "component": "LEC", "section_id": "100", "title": "Structure and Interpretation of Computer Programs", "instructors": ["Rebecca Sofia Lie", "Pamela Fox", ""]},
        # instructors as the scraper writes them: one comma-separated string
        {"course_key": "MATH 1", "component": "LEC", "section_id": "200", "title": "Calculus", "instructors": "Zed Zhang,  Amy Adams , Zed Zhang"},
        # absent from the index: never written
        {"course_key": "HISTORY 7", "component": "LEC", "section_id": "300", "title": "Introduction to the History of the United States", "instructors": "Brian DeLay"},
    ],
}


def _write_catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog" / "2268" / "catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(TITLE_CATALOG), encoding="utf-8")
    return path


def _without_generated_at(text: str) -> str:
    return re.sub(r'"generated_at": "[^"]*"', '"generated_at": ""', text)


def test_titles_table_title_rule_and_instructor_union() -> None:
    entries = [
        # the most common title wins, even against the lecture's
        {"course_key": "A 1", "component": "DIS", "title": "Common", "instructors": ""},
        {"course_key": "A 1", "component": "DIS", "title": "Common", "instructors": ""},
        {"course_key": "A 1", "component": "LEC", "title": "Rare", "instructors": "X Y"},
        # a tie with no lecture among the tied titles goes alphabetical; an empty title never counts
        {"course_key": "B 2", "component": "SEM", "title": "Zeta", "instructors": []},
        {"course_key": "B 2", "component": "DIS", "title": "Alpha", "instructors": []},
        {"course_key": "B 2", "component": "LAB", "title": "", "instructors": ""},
        {"course_key": "B 2", "component": "LAB", "title": "", "instructors": ""},
        # a tie: the title a LEC carries comes first, whatever the alphabet says
        {"course_key": "C 3", "component": "DIS", "title": "Aardvark", "instructors": ""},
        {"course_key": "C 3", "component": "LEC", "title": "Zebra", "instructors": ""},
        # no title, only instructors: kept, with an empty title
        {"course_key": "D 4", "component": "LEC", "title": "", "instructors": "Only Instructor"},
        # nothing at all: left out
        {"course_key": "E 5", "component": "LEC", "title": "", "instructors": ""},
        {"course_key": "E 5", "component": "LEC", "title": " ", "instructors": [" ", ""]},
        # not in the index: left out
        {"course_key": "Z 9", "component": "LEC", "title": "Elsewhere", "instructors": "Some One"},
    ]
    table = export.titles_table(["A 1", "B 2", "C 3", "D 4", "E 5", "F 6"], entries)
    assert table == {
        "A 1": {"title": "Common", "instructors": ["X Y"]},
        "B 2": {"title": "Alpha", "instructors": []},
        "C 3": {"title": "Zebra", "instructors": []},
        "D 4": {"title": "", "instructors": ["Only Instructor"]},
    }
    assert list(table) == sorted(table)


def test_export_writes_titles_from_the_catalog(cohort: pd.DataFrame, tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path)
    out = tmp_path / "site_data"
    index_path, meta_path = export_site_tables(cohort, CAL, out, n_boot=5, catalog=catalog)
    assert json.loads(meta_path.read_text())["titles_file"] == "titles.json"
    titles = json.loads((out / "titles.json").read_text())
    assert set(titles) == {"generated_at", "source", "catalog_term_id", "courses"}
    assert titles["source"] == "classes_site catalog" and titles["catalog_term_id"] == "2268"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", titles["generated_at"])
    index_keys = {r["key"] for r in json.loads(index_path.read_text())["courses"]}
    assert set(titles["courses"]) <= index_keys and "HISTORY 7" not in titles["courses"]
    assert titles["courses"] == {
        "COMPSCI 0": {"title": "Structure and Interpretation of Computer Programs", "instructors": ["Pamela Fox", "Rebecca Sofia Lie", "Zoe Tan"]},
        "MATH 1": {"title": "Calculus", "instructors": ["Amy Adams", "Zed Zhang"]},
    }
    first = (out / "titles.json").read_text()
    assert first.index('"COMPSCI 0"') < first.index('"MATH 1"')
    export_site_tables(cohort, CAL, out, n_boot=5, catalog=catalog)
    assert _without_generated_at((out / "titles.json").read_text()) == _without_generated_at(first)


def test_catalog_term_id_falls_back_to_the_catalog_path(tmp_path: Path) -> None:
    path = tmp_path / "catalog" / "2272" / "catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"sections": TITLE_CATALOG["sections"]}), encoding="utf-8")
    export.write_titles(tmp_path, ["MATH 1"], path)
    titles = json.loads((tmp_path / "titles.json").read_text())
    assert titles["catalog_term_id"] == "2272" and list(titles["courses"]) == ["MATH 1"]


def test_export_without_a_catalog_writes_no_titles(cohort: pd.DataFrame, tmp_path: Path) -> None:
    (tmp_path / "titles.json").write_text("{}")  # left over from an export that had a catalog
    _, meta_path = export_site_tables(cohort, CAL, tmp_path, n_boot=5)
    assert not (tmp_path / "titles.json").exists() and "titles_file" not in json.loads(meta_path.read_text())


def test_cli_catalog_and_titles_only(cohort: pd.DataFrame, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    catalog = _write_catalog(tmp_path)
    cohort_path = tmp_path / "cohort.parquet"
    cohort.to_parquet(cohort_path, index=False)
    full, bare = tmp_path / "full", tmp_path / "bare"
    assert main(["--cohort", str(cohort_path), "--term-id", "2268", "--out", str(full), "--n-boot", "5", "--catalog", str(catalog)]) == 0
    assert main(["--cohort", str(cohort_path), "--term-id", "2268", "--out", str(bare), "--n-boot", "5"]) == 0
    assert (full / "titles.json").exists() and json.loads((full / "meta.json").read_text())["titles_file"] == "titles.json"
    assert not (bare / "titles.json").exists() and "titles_file" not in json.loads((bare / "meta.json").read_text())
    capsys.readouterr()
    before = json.loads((bare / "meta.json").read_text())
    untouched = {p.name: p.read_bytes() for p in bare.iterdir() if p.is_file() and p.name != "meta.json"}
    # --titles-only: no cohort, no refit; titles.json from the index already there, meta.json patched
    assert main(["--titles-only", "--out", str(bare), "--catalog", str(catalog)]) == 0
    printed = json.loads(capsys.readouterr().out)
    n_index = len(json.loads((bare / "index.json").read_text())["courses"])
    assert printed["courses"] == 2 and printed["index_keys"] == n_index and printed["index_keys_without_title"] == n_index - 2
    assert json.loads((bare / "meta.json").read_text()) == {**before, "titles_file": "titles.json"}
    assert {p.name: p.read_bytes() for p in bare.iterdir() if p.is_file() and p.name not in ("meta.json", "titles.json")} == untouched
    assert _without_generated_at((bare / "titles.json").read_text()) == _without_generated_at((full / "titles.json").read_text())
    with pytest.raises(SystemExit):
        main(["--titles-only", "--out", str(bare)])  # needs --catalog
    with pytest.raises(SystemExit):
        main(["--out", str(bare), "--catalog", str(catalog)])  # a full export still needs --cohort and --term-id
    with pytest.raises(SystemExit):
        main(["--titles-only", "--out", str(bare), "--catalog", str(catalog), "--cohort", str(cohort_path)])  # refused, not ignored
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main(["--titles-only", "--out", str(tmp_path / "empty"), "--catalog", str(catalog)])  # a plain error, not a traceback
    assert "no index.json or meta.json there" in capsys.readouterr().err

def test_cli_carries_no_labels_from_another_terms_meta(cohort: pd.DataFrame, tmp_path: Path) -> None:
    """`make site-data` carries source labels from the meta.json already in site/data; when that
    file describes another term (Spring 2026 labels, a Fall 2026 cohort) nothing may be carried."""
    cohort_path = tmp_path / "cohort.parquet"
    cohort.to_parquet(cohort_path, index=False)
    old_meta = tmp_path / "old_meta.json"
    old_meta.write_text(json.dumps({
        "term_id": "2262", "data_source": "berkeleytime_history", "backfill": {"sections": 6131},
        "flows": {"wl_joins": 109421}, "cohort_rows_by_scenario": {"central": 531568}, "prereg_commit": "7f348ed", "prereg_date": "2026-09-21",
    }))
    out = tmp_path / "site"
    assert main(["--cohort", str(cohort_path), "--term-id", "2268", "--forecast-term", "2272", "--out", str(out), "--meta-from", str(old_meta), "--n-boot", "5"]) == 0
    meta = json.loads((out / "meta.json").read_text())
    assert meta["term_id"] == "2268"
    for key in ("backfill", "flows", "cohort_rows_by_scenario", "prereg_commit", "prereg_date"):
        assert key not in meta, key
    assert meta.get("data_source") != "berkeleytime_history"

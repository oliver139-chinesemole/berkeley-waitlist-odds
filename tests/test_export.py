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
from scraper.sources.classes_site import SectionRef
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


def _entry(course_key: str, component: str, class_number: str, title: str = "", instructors: object = "") -> dict:
    """A catalog entry as the scraper writes it (``SectionRef.to_dict``); ``instructors`` may be a list."""
    subject, number = course_key.split()
    ref = SectionRef(
        section_id="",
        url_path=f"/content/2027-spring-{subject}-{number}-{class_number}-{component}-{class_number}".lower(),
        course_key=course_key,
        subject=subject,
        catalog_number=number,
        class_number=class_number,
        section_number=class_number,
        component=component,
        title=title,
    )
    return {**ref.to_dict(), "instructors": instructors}


TITLE_CATALOG = {
    "term_id": "2268",
    "term_name": "Fall 2026",
    "sections": [
        # a lecture and its discussion: the course's title and instructors (a list here) are the lecture's; the
        # discussion is a secondary, so its spelling of the title and its GSI (Zoe Tan) never count
        _entry("COMPSCI 0", "DIS", "101", "The Structure and Interpretation of Computer Programs", ["Pamela Fox", " Zoe Tan "]),
        _entry("COMPSCI 0", "LEC", "001", "Structure and Interpretation of Computer Programs", ["Rebecca Sofia Lie", "Pamela Fox", ""]),
        # instructors as the scraper writes them: one comma-separated string
        _entry("MATH 1", "LEC", "001", "Calculus", "Zed Zhang,  Amy Adams , Zed Zhang"),
        # no cohort rows: a catalog stub (catalog_stubs), so in the index and titled too
        _entry("HISTORY 7", "LEC", "001", "Introduction to the History of the United States", "Brian DeLay"),
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
    # every entry here is primary-like (class number below 100); the next test covers secondaries
    entries = [
        # the most common title wins, even against the lecture's
        _entry("A 1", "DIS", "001", "Common"),
        _entry("A 1", "DIS", "002", "Common"),
        _entry("A 1", "LEC", "003", "Rare", "X Y"),
        # a tie with no lecture among the tied titles goes alphabetical; an empty title never counts
        _entry("B 2", "SEM", "001", "Zeta", []),
        _entry("B 2", "DIS", "002", "Alpha", []),
        _entry("B 2", "LAB", "003"),
        _entry("B 2", "LAB", "004"),
        # a tie: the title a LEC carries comes first, whatever the alphabet says
        _entry("C 3", "DIS", "001", "Aardvark"),
        _entry("C 3", "LEC", "002", "Zebra"),
        # no title, only instructors: kept, with an empty title
        _entry("D 4", "LEC", "001", "", "Only Instructor"),
        # nothing at all: left out
        _entry("E 5", "LEC", "001"),
        _entry("E 5", "LEC", "002", " ", [" ", ""]),
        # not in the index: left out
        _entry("Z 9", "LEC", "001", "Elsewhere", "Some One"),
    ]
    table = export.titles_table(["A 1", "B 2", "C 3", "D 4", "E 5", "F 6"], entries)
    assert table == {
        "A 1": {"title": "Common", "instructors": ["X Y"]},
        "B 2": {"title": "Alpha", "instructors": []},
        "C 3": {"title": "Zebra", "instructors": []},
        "D 4": {"title": "", "instructors": ["Only Instructor"]},
    }
    assert list(table) == sorted(table)


def test_titles_come_from_primary_like_entries_only() -> None:
    """A secondary's instructor field names its GSI or lab lead, not the course's instructor, so only the
    entries ``primary_like`` keeps (docs/DESIGN_A2.md section 19) give a course its title and instructors."""
    entries = [
        # a lecture and its discussions: the GSIs are not instructors, and the discussions' spelling does not outvote the lecture's
        _entry("P 1", "LEC", "001", "Right Title", "Prof A"),
        _entry("P 1", "DIS", "101", "Other Title", "GSI B"),
        _entry("P 1", "DIS", "102", "Other Title", "GSI C"),
        # a lab-only course: its labs are its primaries (the course's lowest class number), so their names stay
        _entry("L 2", "LAB", "101", "Lab Course", "Lab Lead"),
        _entry("L 2", "LAB", "102", "Lab Course", "Other Lead"),
    ]
    assert export.titles_table(["P 1", "L 2"], entries) == {
        "L 2": {"title": "Lab Course", "instructors": ["Lab Lead", "Other Lead"]},
        "P 1": {"title": "Right Title", "instructors": ["Prof A"]},
    }


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
    assert set(titles["courses"]) <= index_keys and "HISTORY 7" in index_keys
    assert titles["courses"] == {
        "COMPSCI 0": {"title": "Structure and Interpretation of Computer Programs", "instructors": ["Pamela Fox", "Rebecca Sofia Lie"]},
        "HISTORY 7": {"title": "Introduction to the History of the United States", "instructors": ["Brian DeLay"]},
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
    full_meta, bare_meta = json.loads((full / "meta.json").read_text()), json.loads((bare / "meta.json").read_text())
    assert (full / "titles.json").exists() and full_meta["titles_file"] == "titles.json"
    assert not (bare / "titles.json").exists() and "titles_file" not in bare_meta
    # --catalog adds a stub for each catalog course with no cohort rows (HISTORY 7); meta.courses keeps its meaning
    assert full_meta["courses"] == bare_meta["courses"] and full_meta["catalog_term_id"] == "2268"
    assert full_meta["catalog_courses"] == 3 and full_meta["catalog_only_courses"] == 1
    assert [r for r in json.loads((full / "index.json").read_text())["courses"] if r.get("catalog_only")] == [
        r for r in json.loads((full / "index.json").read_text())["courses"] if r["key"] == "HISTORY 7"
    ]
    assert not {"catalog_term_id", "catalog_courses", "catalog_only_courses"} & set(bare_meta)
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
    # the same titles for the courses both indexes have; the full export's stub (HISTORY 7) is titled too
    full_titles = json.loads((full / "titles.json").read_text())["courses"]
    assert json.loads((bare / "titles.json").read_text())["courses"] == {k: v for k, v in full_titles.items() if k != "HISTORY 7"} and "HISTORY 7" in full_titles
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


# --- catalog stubs: every course on the forecast term's schedule, with or without cohort rows (Task 19) ---


STUB_CATALOG = {
    "term_id": "2272",
    "sections": [
        # a course with cohort rows: neither duplicated nor overwritten
        _entry("COMPSCI 0", "LEC", "001", "Structure and Interpretation of Computer Programs", "Pamela Fox"),
        _entry("COMPSCI 0", "DIS", "101"),
        # no cohort rows, in subjects the cohort has: that subject's dept_group (ART's is OTHER in this cohort)
        _entry("COMPSCI 299", "LEC", "001", "Research"),
        _entry("COMPSCI 299", "DIS", "101"),  # two entries, one course
        _entry("STAT 150", "LEC", "001", "Stochastic Processes"),
        _entry("ART 100", "STD", "001", "Drawing"),
        # no cohort rows, in a subject the cohort lacks: OTHER
        _entry("HISTORY 7", "LEC", "001", "Introduction to the History of the United States", "Brian DeLay"),
        _entry("MATH C10", "LEC", "001"),
    ],
}
STUB_KEYS = {"COMPSCI 299", "STAT 150", "ART 100", "HISTORY 7", "MATH C10"}


def _write_stub_catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog" / "2272" / "catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(STUB_CATALOG), encoding="utf-8")
    return path


def test_catalog_stubs_point_at_the_department_then_all(cohort: pd.DataFrame, pools: dict) -> None:
    trimmed = {
        "all": {b: c for b, c in pools["all"].items() if b != "41+"},
        "dept": {**pools["dept"], "OTHER": {b: c for b, c in pools["dept"]["OTHER"].items() if b != "1-5"}},
        "level": pools["level"],
    }
    stubs = export.catalog_stubs(STUB_CATALOG["sections"], cohort, trimmed)
    assert set(stubs) == STUB_KEYS  # COMPSCI 0 has cohort rows
    hist = stubs["HISTORY 7"]
    assert {k: v for k, v in hist.items() if k != "buckets"} == {"subject": "HISTORY", "number": "7", "level": "lower", "dept_group": "OTHER", "catalog_only": True}
    # OTHER lacks 1-5 here, so that bucket points at all courses; 41+ is in the OTHER pool only
    assert hist["buckets"] == {
        "1-5": {"pooled": "all", "n_course": 0, "sections_course": 0},
        "6-15": {"pooled": "OTHER", "n_course": 0, "sections_course": 0},
        "16-40": {"pooled": "OTHER", "n_course": 0, "sections_course": 0},
        "41+": {"pooled": "OTHER", "n_course": 0, "sections_course": 0},
    }
    assert list(hist["buckets"]) == [b for b in export.BUCKET_ORDER if b in hist["buckets"]]
    # STAT has every bucket but 41+, which no pool covers once all-course 41+ is gone: skipped
    stat = {**trimmed, "dept": {**trimmed["dept"], "STAT": {b: c for b, c in pools["dept"]["STAT"].items() if b != "41+"}}}
    assert export.catalog_stubs(STUB_CATALOG["sections"], cohort, stat)["STAT 150"]["buckets"] == {
        b: {"pooled": "STAT", "n_course": 0, "sections_course": 0} for b in ("1-5", "6-15", "16-40")
    }
    assert stubs["ART 100"]["dept_group"] == "OTHER" and stubs["COMPSCI 299"]["dept_group"] == "COMPSCI" and stubs["STAT 150"]["dept_group"] == "STAT"
    assert [stubs[k]["level"] for k in ("MATH C10", "STAT 150", "COMPSCI 299")] == ["lower", "upper", "grad"]
    assert stubs["MATH C10"]["dept_group"] == "MATH" and stubs["MATH C10"]["number"] == "C10"


def test_export_adds_a_stub_for_every_catalog_course_without_cohort_rows(cohort: pd.DataFrame, tmp_path: Path) -> None:
    catalog = _write_stub_catalog(tmp_path)
    plain, full = tmp_path / "plain", tmp_path / "full"
    export_site_tables(cohort, CAL, plain, n_boot=5)
    index_path, meta_path = export_site_tables(cohort, CAL, full, n_boot=5, catalog=catalog)
    before = {r["key"]: r for r in json.loads((plain / "index.json").read_text())["courses"]}
    rows = {r["key"]: r for r in json.loads(index_path.read_text())["courses"]}
    assert set(rows) == set(before) | STUB_KEYS and len(rows) == len(before) + len(STUB_KEYS)
    # the cohort's courses, pools and insights are exactly what an export without a catalog writes
    assert {k: rows[k] for k in before} == before
    for name in ("pooled.json", "insights.json"):
        assert (full / name).read_text() == (plain / name).read_text()
    for path in (plain / "courses").iterdir():
        assert json.loads((full / "courses" / path.name).read_text())["courses"].items() >= json.loads(path.read_text())["courses"].items()
    pooled = json.loads((full / "pooled.json").read_text())
    for key in STUB_KEYS:
        row = rows[key]
        assert row["catalog_only"] is True and row["buckets"]
        for bucket, s in row["buckets"].items():
            assert s["pooled"] == row["dept_group"] and s["n_course"] == 0 and s["sections_course"] == 0
            assert s["median_days"] == pooled["dept"][row["dept_group"]][bucket]["median_days"]
    assert all("catalog_only" not in r for r in before.values())
    assert [r["key"] for r in json.loads(index_path.read_text())["courses"]] == sorted(rows)
    history = json.loads((full / "courses" / "HISTORY.json").read_text())
    assert history["courses"]["HISTORY 7"] == {
        "subject": "HISTORY", "number": "7", "level": "lower", "dept_group": "OTHER", "catalog_only": True,
        "buckets": {b: {"pooled": "OTHER", "n_course": 0, "sections_course": 0} for b in export.BUCKET_ORDER},
    }
    assert "catalog_only" not in json.loads((full / "courses" / "COMPSCI.json").read_text())["courses"]["COMPSCI 0"]
    meta, plain_meta = json.loads(meta_path.read_text()), json.loads((plain / "meta.json").read_text())
    assert meta["courses"] == plain_meta["courses"] == len(before)  # courses with cohort rows
    assert meta["catalog_term_id"] == "2272" and meta["catalog_courses"] == 6 and meta["catalog_only_courses"] == 5
    assert meta["subject_files"]["HISTORY"] == "courses/HISTORY.json"
    assert "HISTORY 7" in json.loads((full / "titles.json").read_text())["courses"]
    for key in ("catalog_term_id", "catalog_courses", "catalog_only_courses"):
        assert key not in plain_meta
    assert "HISTORY" not in plain_meta["subject_files"]


# --- Task 19 review: catalog term, malformed entries, one parse per export ---


def test_export_with_a_catalog_needs_its_term_id(cohort: pd.DataFrame, tmp_path: Path) -> None:
    path = tmp_path / "nodigits" / "catalog.json"  # no term_id in the file, its entries or its directory
    path.parent.mkdir()
    path.write_text(json.dumps({"sections": [{k: v for k, v in e.items() if k != "term_id"} for e in STUB_CATALOG["sections"]]}), encoding="utf-8")
    with pytest.raises(ValueError, match="term id"):
        export_site_tables(cohort, CAL, tmp_path / "out", n_boot=5, catalog=path)
    meta = json.loads(export_site_tables(cohort, CAL, tmp_path / "ok", n_boot=5, catalog=_write_stub_catalog(tmp_path))[1].read_text())
    assert meta["catalog_term_id"] == "2272" and isinstance(meta["catalog_term_id"], str)


def test_catalog_stubs_and_the_catalog_count_skip_the_same_malformed_entries(cohort: pd.DataFrame, pools: dict, tmp_path: Path) -> None:
    good = _entry("HISTORY 7", "LEC", "001")
    no_subject = {k: v for k, v in _entry("ETHSTD 21", "LEC", "001").items() if k != "subject"}
    no_number = {k: v for k, v in _entry("PHYSICS 7A", "LEC", "001").items() if k != "catalog_number"}
    stubs = export.catalog_stubs([no_subject, no_number, good], cohort, pools)  # no KeyError
    assert set(stubs) == {"HISTORY 7"}
    path = tmp_path / "catalog" / "2272" / "catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"term_id": "2272", "sections": [no_subject, no_number, good]}), encoding="utf-8")
    meta = json.loads(export_site_tables(cohort, CAL, tmp_path / "out", n_boot=5, catalog=path)[1].read_text())
    assert meta["catalog_courses"] == 1 and meta["catalog_only_courses"] == 1


def test_an_export_parses_the_catalog_once(cohort: pd.DataFrame, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    real = export.load_catalog
    monkeypatch.setattr(export, "load_catalog", lambda p: calls.append(p) or real(p))
    export_site_tables(cohort, CAL, tmp_path / "out", n_boot=5, catalog=_write_stub_catalog(tmp_path))
    assert len(calls) == 1 and (tmp_path / "out" / "titles.json").exists()


# --- default-off options (Task 21): with the defaults every file is what the exporter wrote before them ---

GOLDEN_FLOWS = pd.DataFrame(
    {
        "section_id": ["0", "0", "1", "2"],
        "t1": pd.to_datetime(["2026-01-27T10:00Z", "2026-02-06T23:00Z", "2026-02-07T12:00Z", "2026-05-01T12:00Z"]),
        "admits": [1, 2, 0, 1],
        "wl_joins": [3, 0, 1, 0],
        "wl_drops": [0, 1, 4, 2],
        "censored": [False, True, False, False],
        "waitlist0": [5, 4, 6, 2],
        "d_waitlist": [-1, 0, -4, -2],
    }
)


def _export_digest(out: Path) -> dict[str, str]:
    """sha256 of every file an export wrote, ``generated_at`` blanked."""
    import hashlib

    return {str(p.relative_to(out)): hashlib.sha256(_without_generated_at(p.read_text(encoding="utf-8")).encode()).hexdigest() for p in sorted(out.rglob("*.json"))}

GOLDEN_DIGEST = {  # analysis.export at e3265ed (before the Task 21 options), synthetic cohort, n_boot=10
    "courses/ART.json": "00af1e831ab16c2b41cb41c3ddb19979ba3e5747ccaafc927d92a4b5d60366d2",
    "courses/COMPSCI.json": "6b2b234ea0a0bbfe8165fd36192e04f5cc158feb3458c65c2aed0dbc2a00e071",
    "courses/HISTORY.json": "b0c1000e8cce32990af52beae842619ba0173398b8c4db65b2d867bbd74bfe3e",
    "courses/MATH.json": "13e90c5626fdefcf3f671ff153d19bab2b196f1aba4c6c6cda3ea2cd46e093b5",
    "courses/STAT.json": "b5ef8df61f1165b0471925a4e0f2fe10517016dc247dc2bdc626182d02fc4c85",
    "index.json": "cd49034455f732eb30e2caee22a4583d2eeeadffdd739e192cde838aeaeb60c0",
    "insights.json": "bb9cf1b76bc24ae48e2cdea7d46aebe81a8b579e3bbddeb8ac47e5bdad9838b6",
    "meta.json": "acde6db0c1cc2e00a86bcec003c50e9be86505fb822ee619c367f3bfa0b7a54f",
    "pooled.json": "09a512843be0fbf000671236e71d2392f19d4655ba69d52dd66d461554ef257e",
    "titles.json": "f0c0fd3ffbdf6f650a2f7a83ba8db39b6b9654a64246a2bbadff433779437d53",
}


def _golden_export(out: Path, catalog: Path, **options: object) -> dict[str, str]:
    from analysis.calendar import SPRING_2026

    export_site_tables(synthetic_cohort(), SPRING_2026, out, n_boot=10, forecast_calendar=SPRING_2027, flows=GOLDEN_FLOWS, catalog=catalog, **options)
    return _export_digest(out)


def test_default_options_write_the_same_bytes_as_before_them(tmp_path: Path) -> None:
    catalog = _write_stub_catalog(tmp_path)
    assert _golden_export(tmp_path / "default", catalog) == GOLDEN_DIGEST
    assert _golden_export(tmp_path / "off", catalog, reach_min_at_risk=0, interval_min_sections=0, exits_at_last_auto=False) == GOLDEN_DIGEST


def _toy_rows(durations: list[float], events: list[int], sections: list[str] | None = None) -> pd.DataFrame:
    return pd.DataFrame({"duration_days": durations, "event": events, "section_id": sections or [str(i % 4) for i in range(len(durations))]})


def test_reach_min_at_risk_cuts_the_curve_where_fewer_than_n_are_left() -> None:
    # 37 joiners followed 1..37 days, none cleared; the last 3 (followed past day 37) all clear on day 40:
    # Kaplan-Meier jumps to 1.0 on three people
    durations = [float(d) for d in range(1, 38)] + [40.0, 40.0, 40.0]
    events = [0] * 37 + [1, 1, 1]
    rows = _toy_rows(durations, events)
    full = export._cell(rows, n_boot=5)
    assert full["reach_days"] == 40.0 and full["curve"][-1][1] == 1.0
    cut = export._cell(rows, n_boot=5, reach_min_at_risk=20)
    # 20 joiners have duration >= 21 (days 21..37 and the three 40s): day 21 is the last with 20 at risk
    assert cut["reach_days"] == 21.0 and cut["curve"][-1][0] == 21.0 and cut["curve"][-1][1] == 0.0
    # the cut curve is the full curve's prefix (the estimate at t does not depend on later rows)
    assert cut["curve"] == [pt for pt in full["curve"] if pt[0] <= 21.0]
    # the median is a statistic of the full data, not a curve point: kept though it lies past the cut
    assert full["median_days"] == 40.0 and cut["median_days"] == 40.0 > cut["reach_days"]
    assert cut["n"] == full["n"] and cut["events"] == full["events"] and cut["sections"] == full["sections"]
    s = export._summary(cut)
    assert s["reach"] == [0.0, 21.0]
    with pytest.raises(ValueError, match="fewer"):  # a cell under N rows never gets a curve (export_site_tables raises min_n to N)
        export._cell(_toy_rows([2.0, 3.0, 5.0], [1, 0, 1]), n_boot=0, reach_min_at_risk=20)
    # N at or below 1 is the uncut curve
    assert export._cell(rows, n_boot=5, reach_min_at_risk=1) == full


def test_reach_min_at_risk_reaches_pools_courses_insights_and_the_clis(cohort: pd.DataFrame, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    plain, cut = tmp_path / "plain", tmp_path / "cut"
    export_site_tables(cohort, CAL, plain, n_boot=5)
    export_site_tables(cohort, CAL, cut, n_boot=5, reach_min_at_risk=30)
    p_pool, c_pool = (json.loads((d / "pooled.json").read_text()) for d in (plain, cut))
    for b, cell in p_pool["all"].items():
        d = sorted(cohort.loc[cohort["position_bucket"] == b, "duration_days"], reverse=True)
        assert c_pool["all"][b]["reach_days"] == round(d[29], 1) <= cell["reach_days"]
    assert json.loads((cut / "meta.json").read_text())["reach_min_at_risk"] == 30 and "reach_min_at_risk" not in json.loads((plain / "meta.json").read_text())
    own = {(k, b): c for k, e in json.loads((cut / "courses" / "COMPSCI.json").read_text())["courses"].items() for b, c in e["buckets"].items() if c["pooled"] is False}
    assert own
    for (k, b), c in own.items():
        d = sorted(cohort.loc[(cohort["course_key"] == k) & (cohort["position_bucket"] == b), "duration_days"], reverse=True)
        assert c["reach_days"] == round(d[29], 1) and c["curve"][-1][0] == round(d[29], 2)
    ins = json.loads((cut / "insights.json").read_text())
    assert all(c["reach_days"] <= p_pool["all"][b]["reach_days"] for b, c in ins["all_by_bucket"].items())
    cohort_path = tmp_path / "cohort.parquet"
    cohort.to_parquet(cohort_path, index=False)
    assert main(["--cohort", str(cohort_path), "--term-id", "2268", "--out", str(tmp_path / "cli"), "--n-boot", "5", "--reach-min-at-risk", "30"]) == 0
    capsys.readouterr()
    assert json.loads((tmp_path / "cli" / "meta.json").read_text())["reach_min_at_risk"] == 30
    assert json.loads((tmp_path / "cli" / "pooled.json").read_text())["all"] == c_pool["all"]


def test_reach_min_at_risk_above_min_n_sends_smaller_cells_to_their_pool(cohort: pd.DataFrame, tmp_path: Path) -> None:
    # ART 11 at 1-5: 36 rows plus 4 followed only 0.2 days = 40 rows, a course curve at min_n 30
    extra = cohort[(cohort["course_key"] == "ART 11") & (cohort["position_bucket"] == "1-5")].head(4).assign(duration_days=0.2, duration_min=0.2 * 1440, event=0)
    rows = pd.concat([cohort, extra], ignore_index=True)
    assert len(rows[(rows["course_key"] == "ART 11") & (rows["position_bucket"] == "1-5")]) == 40
    plain, cut = tmp_path / "plain", tmp_path / "cut"
    export_site_tables(rows, CAL, plain, n_boot=5)
    export_site_tables(rows, CAL, cut, n_boot=5, reach_min_at_risk=60)
    before = json.loads((plain / "courses" / "ART.json").read_text())["courses"]["ART 11"]["buckets"]["1-5"]
    after = json.loads((cut / "courses" / "ART.json").read_text())["courses"]["ART 11"]["buckets"]["1-5"]
    assert before["pooled"] is False and before["n"] == 40
    # at N=60 the 40-row cell falls back to its pool like any cell under min_n, not a one-point curve at 0.2 days
    assert after["pooled"] not in (False, None) and after["n_course"] == 40 and "curve" not in after
    pools = json.loads((cut / "pooled.json").read_text())
    pool = pools["all"]["1-5"] if after["pooled"] == "all" else pools["dept"][after["pooled"]]["1-5"]
    assert pool["n"] >= 60 and pool["reach_days"] > 0.2
    meta = json.loads((cut / "meta.json").read_text())
    assert meta["min_n"] == 60 and meta["reach_min_at_risk"] == 60 and json.loads((plain / "meta.json").read_text())["min_n"] == 30


def test_interval_min_sections_drops_the_band_of_a_cell_with_too_few_sections(cohort: pd.DataFrame, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    durations = [float(d % 9 + 1) for d in range(60)]
    events = [d % 3 != 0 for d in range(60)]
    two = _toy_rows(durations, [int(e) for e in events], [str(i % 2) for i in range(60)])
    three = _toy_rows(durations, [int(e) for e in events], [str(i % 3) for i in range(60)])
    assert any(pt[2] is not None for pt in export._cell(two, n_boot=20)["curve"])  # the bootstrap runs on 2 sections
    cut = export._cell(two, n_boot=20, interval_min_sections=3)
    assert all(pt[2] is None and pt[3] is None for pt in cut["curve"]) and cut["sections"] == 2
    assert [pt[:2] for pt in cut["curve"]] == [pt[:2] for pt in export._cell(two, n_boot=20)["curve"]]
    s = export._summary(cut)
    assert s["lo"] == [None, None, None] and s["hi"] == [None, None, None]
    assert export._cell(three, n_boot=20, interval_min_sections=3) == export._cell(three, n_boot=20)
    plain, banded = tmp_path / "plain", tmp_path / "banded"
    export_site_tables(cohort, CAL, plain, n_boot=5)
    export_site_tables(cohort, CAL, banded, n_boot=5, interval_min_sections=16)
    pools = json.loads((banded / "pooled.json").read_text())
    for kind in ("dept", "level"):
        for cells in pools[kind].values():
            for c in cells.values():
                assert all(pt[2] is None for pt in c["curve"]) == (c["sections"] < 16)
    assert json.loads((banded / "meta.json").read_text())["interval_min_sections"] == 16 and "interval_min_sections" not in json.loads((plain / "meta.json").read_text())
    idx = {r["key"]: r for r in json.loads((banded / "index.json").read_text())["courses"]}
    for r in idx.values():
        for s in r["buckets"].values():
            if s["pooled"] is False:
                assert (s["lo"][0] is None) == (s["sections"] < 16)
    cohort_path = tmp_path / "cohort.parquet"
    cohort.to_parquet(cohort_path, index=False)
    assert main(["--cohort", str(cohort_path), "--term-id", "2268", "--out", str(tmp_path / "cli"), "--n-boot", "5", "--interval-min-sections", "16"]) == 0
    capsys.readouterr()
    assert json.loads((tmp_path / "cli" / "meta.json").read_text())["interval_min_sections"] == 16


def test_exits_at_last_auto_measures_still_waiting_at_the_last_automatic_run(cohort: pd.DataFrame, pools: dict, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from analysis.calendar import SPRING_2026

    flows = GOLDEN_FLOWS.assign(t0=pd.to_datetime(["2026-01-27T09:30Z", "2026-02-06T22:30Z", "2026-02-06T23:30Z", "2026-05-01T11:30Z"]))
    # section 3: the last automatic run itself, Fri Feb 6, 2026 at 6:40 PM Pacific = 02:40Z on Feb 7
    last_run = pd.DataFrame({"section_id": ["3"], "t0": pd.to_datetime(["2026-02-07T02:10Z"]), "t1": pd.to_datetime(["2026-02-07T02:40Z"]), "admits": [2], "wl_joins": [0], "wl_drops": [0], "censored": [False], "waitlist0": [3], "d_waitlist": [-2]})
    flows = pd.concat([flows, last_run], ignore_index=True)
    # the last observation (the default): section 0 ends at 4, section 1 at 2, section 2 at 0, section 3 at 1
    assert insights_tables(cohort, pools, min_n=30, n_boot=5, flows=flows)["exits"] == {"admitted": 6, "dropped": 7, "still_waiting": 7}
    ins = insights_tables(cohort, pools, min_n=30, n_boot=5, flows=flows, calendar=SPRING_2026, exits_at_last_auto=True)
    # cut at the end of Feb 6, 2026 in Pacific time (08:00Z on Feb 7), after the 6:40 PM run: its admits count (a
    # UTC-midnight cut would have put them in the purge); section 0's list after its Feb 6 interval (4), section 1's
    # at the start of the interval that straddles the cut (6), section 3's after the run (1), section 2 not yet seen
    assert ins["exits"] == {
        "admitted": 5,
        "dropped": 1,
        "still_waiting": 4 + 6 + 1,
        "as_of": "2026-02-07T08:00:00+00:00",
        "after_last_auto": {"admitted": 1, "dropped": 6},
    }
    assert export.last_auto_cutoff(SPRING_2027).isoformat() == "2027-02-06T08:00:00+00:00"  # Feb 5, 2027 run, PST
    assert export.last_auto_cutoff(FALL_2026).isoformat() == "2026-09-12T07:00:00+00:00"  # Sep 11, 2026, PDT
    with pytest.raises(ValueError, match="calendar"):
        insights_tables(cohort, pools, min_n=30, n_boot=5, flows=flows, exits_at_last_auto=True)
    with pytest.raises(ValueError, match="t0"):
        insights_tables(cohort, pools, min_n=30, n_boot=5, flows=GOLDEN_FLOWS, calendar=SPRING_2026, exits_at_last_auto=True)
    with pytest.raises(ValueError, match="flows"):
        export_site_tables(cohort, SPRING_2026, tmp_path / "noflows", n_boot=5, exits_at_last_auto=True)
    export_site_tables(cohort, SPRING_2026, tmp_path / "on", n_boot=5, flows=flows, exits_at_last_auto=True)
    assert json.loads((tmp_path / "on" / "insights.json").read_text())["exits"]["still_waiting"] == 11
    assert json.loads((tmp_path / "on" / "meta.json").read_text())["exits_at_last_auto"] is True
    cohort_path, flows_path = tmp_path / "cohort.parquet", tmp_path / "flows.parquet"
    cohort.to_parquet(cohort_path, index=False)
    flows.to_parquet(flows_path, index=False)
    assert main(["--cohort", str(cohort_path), "--term-id", "2262", "--flows", str(flows_path), "--out", str(tmp_path / "cli"), "--n-boot", "5", "--exits-at-last-auto"]) == 0
    capsys.readouterr()
    assert json.loads((tmp_path / "cli" / "insights.json").read_text())["exits"]["as_of"] == "2026-02-07T08:00:00+00:00"
    with pytest.raises(SystemExit):
        main(["--cohort", str(cohort_path), "--term-id", "2262", "--out", str(tmp_path / "cli2"), "--n-boot", "5", "--exits-at-last-auto"])
    assert "--flows" in capsys.readouterr().err and not (tmp_path / "cli2").exists()


@pytest.mark.parametrize("flag", ["--reach-min-at-risk", "--interval-min-sections"])
def test_cli_refuses_a_negative_option(flag: str, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit):
        main(["--cohort", str(tmp_path / "c.parquet"), "--term-id", "2262", "--out", str(tmp_path / "out"), flag, "-1"])
    error = capsys.readouterr().err.strip().splitlines()[-1]  # the usage lines name every flag; the error line is the message
    assert flag in error and ">= 0" in error and not (tmp_path / "out").exists()


@pytest.mark.parametrize("extra", [["--reach-min-at-risk", "20"], ["--interval-min-sections", "3"], ["--exits-at-last-auto"]])
def test_titles_only_refuses_the_export_options(extra: list[str], tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    catalog = _write_catalog(tmp_path)
    with pytest.raises(SystemExit):
        main(["--titles-only", "--catalog", str(catalog), "--out", str(tmp_path), *extra])
    error = capsys.readouterr().err.strip().splitlines()[-1]
    assert "--titles-only" in error and extra[0] in error

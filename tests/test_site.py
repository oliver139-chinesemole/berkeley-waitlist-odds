"""Renders the pages under site/ without a browser and checks the states in docs/DESIGN_A6.md.

Each page's own inline script runs under node against a stub document and a
file-backed ``fetch`` (tests/site/harness.js), after the shared assets/site.js.
Skipped when node is missing. "Today" is pinned through the pages' own
``?today=YYYY-MM-DD`` query parameter.
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
from analysis.export import export_site_tables, read_curve
from analysis.run import run_analysis
from tests.test_run import sim_inputs
from tests.test_survival import synthetic_cohort

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
HARNESS = ROOT / "tests" / "site" / "harness.js"
PAGES = ("index.html", "courses.html", "course.html", "insights.html", "accuracy.html", "methodology.html", "about.html", "404.html")


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
TODAY = "2027-01-10"  # 9 days before instruction, 27 days before the end of the last waitlist run's day


def render(site_root: Path, *, page: str = "index.html", search: str = "", course: str = "", position: str = "", today: str | None = TODAY, expression: str = "", env: dict | None = None) -> dict:
    if today:
        search = (search + "&" if search else "?") + f"today={today}"
        if not search.startswith("?"):
            search = "?" + search
    proc = subprocess.run(
        [str(NODE), str(HARNESS), str(SITE / page), str(site_root), search, course, position, expression],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**os.environ, **(env or {})},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def pct(p: float) -> str:
    return f"{round(p * 100)}%"


def load(site_root: Path, name: str) -> dict:
    return json.loads((site_root / "data" / name).read_text())


def cell_of(site_root: Path, key: str, bucket: str) -> dict:
    subject = key.split()[0]
    entry = load(site_root, f"courses/{subject}.json")["courses"][key]
    cell = entry["buckets"][bucket]
    if cell["pooled"] is False:
        return cell
    pooled = load(site_root, "pooled.json")
    return pooled["all"][bucket] if cell["pooled"] == "all" else pooled["dept"][cell["pooled"]][bucket]


@pytest.fixture(scope="module")
def full_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The default export: department-level estimates, course cells as pointers with the course's own counts."""
    root = tmp_path_factory.mktemp("site_full")
    export_site_tables(synthetic_cohort(), CAL, root / "data", n_boot=50)
    return root


@pytest.fixture(scope="module")
def course_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """estimate_level="course": a course with 30 or more cases gets its own curve (kept for later terms)."""
    root = tmp_path_factory.mktemp("site_course")
    export_site_tables(synthetic_cohort(), CAL, root / "data", n_boot=50, estimate_level="course")
    return root


@pytest.fixture(scope="module")
def backfill_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("site_backfill")
    export_site_tables(synthetic_cohort(), CAL, root / "data", n_boot=20, meta={"data_source": "berkeleytime_history"})
    return root


@pytest.fixture(scope="module")
def narrow_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Only positions 1 to 5 ever joined, so every course has a single bucket."""
    root = tmp_path_factory.mktemp("site_narrow")
    cohort = synthetic_cohort()
    export_site_tables(cohort[cohort["position"] <= 5], CAL, root / "data", n_boot=20, estimate_level="course")
    return root


# ------------------------------------------------------------------ states


def test_every_page_loads_the_shared_assets() -> None:
    for page in PAGES:
        html = (SITE / page).read_text()
        assert '<link rel="stylesheet" href="assets/site.css">' in html, page
        assert 'href="#main"' in html and 'id="main"' in html, page
        assert '<nav aria-label="Site">' in html, page
        if page not in ("404.html",):
            assert '<script src="assets/site.js"></script>' in html, page


def test_empty_state_without_data(tmp_path: Path) -> None:
    out = render(tmp_path)
    assert "No estimates yet" in out["status"] and "Oct 26, 2026" in out["status"]
    assert out["form_hidden"] and out["result_hidden"]


def test_empty_state_shows_counts_from_meta(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "meta.json").write_text(json.dumps({"events": 3, "sections": 704, "cohort_rows": 809, "term_name": "Fall 2026"}))
    out = render(tmp_path)
    assert "No estimates yet" in out["status"] and "704 sections" in out["status"] and "809 hypothetical joiners" in out["status"] and "3 clearings" in out["status"]
    assert out["form_hidden"]


def test_fetch_failure_is_not_the_empty_state(full_site: Path) -> None:
    out = render(full_site, env={"HARNESS_FAIL_FETCH": "1"})
    assert "Could not load the estimates" in out["status"] and "No estimates yet" not in out["status"]
    assert "Reload" in out["status"] and out["form_hidden"]


def test_meta_from_the_analysis_run_renders_as_numbers(tmp_path: Path) -> None:
    """analysis.run writes meta.json for the site; every count it prints must be a number, not an object."""
    panel, identity, cal = sim_inputs()
    few = panel[panel["section_id"].isin(sorted(panel["section_id"].unique())[:2])]
    site_root = tmp_path / "site"
    res = run_analysis(few, identity, cal, tmp_path / "out", site_dir=site_root / "data", join_every_min=1440)
    assert res.site_files is not None
    meta = json.loads(Path(res.site_files[1]).read_text())
    out = render(site_root, today=None)
    assert "[object Object]" not in out["status"] and "undefined" not in out["status"]
    assert f"{meta['cohort_rows']} hypothetical joiners" in out["status"] and f"{meta['sections']} sections" in out["status"]


def test_full_state_shows_source_dates_and_examples(full_site: Path) -> None:
    meta = load(full_site, "meta.json")
    index = load(full_site, "index.json")
    assert meta["events"] >= 10 and meta["deadline"] == "2027-02-05"
    out = render(full_site)
    assert not out["form_hidden"] and out["result_hidden"]
    assert "Simulated term" in out["status"] and f"{len(index['courses'])} courses" in out["status"] and f"{meta['events']:,} of whom cleared" in out["status"]
    assert "Berkeleytime" not in out["status"] and "[object Object]" not in out["status"]
    assert out["stamp"].startswith("Data through") and "Horizons computed for 2027-01-10" in out["stamp"] and "27 days away" in out["stamp"]
    dates = out["elements"]["dates"]["html"]
    assert "Simulated term" in dates and "Jan 19, 2027" in dates and "First day of class" in dates and "in 9 days" in dates and "Feb 5, 2027" in dates
    chips = out["elements"]["examples"]["html"]
    assert chips.count('class="chip"') == 3 and "at 10" in chips
    teaser = out["elements"]["teaser"]["html"]
    assert "positions 6 to 15 got in within 14 days" in teaser and "insights.html" in teaser


def test_backfill_source_is_labelled(backfill_site: Path) -> None:
    out = render(backfill_site)
    assert "from Berkeleytime's public 15-minute enrollment history" in out["status"] and "Simulated term" in out["status"]
    assert "Live Spring 2027 collection" in out["status"] and not out["form_hidden"]
    out = render(backfill_site, course="COMPSCI 0", position="3")
    assert "from Berkeleytime's public history" in out["result"]


# ------------------------------------------------------------------ lookup


def test_lookup_reads_the_curve_at_the_askers_own_horizons(course_site: Path) -> None:
    cell = cell_of(course_site, "COMPSCI 0", "1-5")
    assert cell["sections"] >= 1 and cell["reach_days"] > 0
    out = render(course_site, course="compsci   0", position="3")
    r = out["result"]
    assert not out["result_hidden"]
    assert "COMPSCI 0" in r and "position 3 (positions 1 to 5)" in r
    # headline: P(cleared within the 27 days left before the end of the last waitlist run's day)
    at_deadline = read_curve(cell["curve"], 27.0)
    assert f'<div class="big">{pct(at_deadline[0])}' in r and "within 27 days of joining" in r and "last automatic waitlist run" in r and "Feb 5, 2027" in r
    k = round(at_deadline[0] * 20)
    assert f'aria-label="{k} of 20 dots filled: {pct(at_deadline[0])}"' in r and r.count('<i class="on"></i>') == k
    if at_deadline[1] is not None:
        assert f"95% interval {pct(at_deadline[1])} to {pct(at_deadline[2])}" in r
    assert 'class="verdict"' in r and "Verdicts: Likely at 75% or more" in r
    # second line: by the first day of instruction, 9 days from "today"
    at_instruction = read_curve(cell["curve"], 9.0)
    assert f"<strong>{pct(at_instruction[0])}</strong> by the first day of instruction" in r and "9 days from now" in r
    # by-when table: 7 and 14 days from today with their dates, then the two calendar dates
    at7 = read_curve(cell["curve"], 7.0)
    assert "7 days from now" in r and "Jan 17" in r and f"<strong>{pct(at7[0])}</strong>" in r and "Last waitlist run" in r and "First day of class" in r
    assert f"{cell['sections']} section" in r and f"{cell['n']} hypothetical joiners, {cell['events']} cleared" in r
    assert "<svg" in r and 'class="mark"' in r and "last waitlist run" in r and 'role="img"' in r and "Show as table" in r
    assert r.count('class="curve') == 1 and ' H ' in r  # one step-drawn curve
    assert ('class="band"' in r) == (cell["sections"] >= 2 and cell["curve"][0][2] is not None)
    assert '(positions 1 to 5)<span class="tag pooled"' not in r  # the asker's own cell is not pooled
    assert "Estimates are by course and position when a course has at least 30 cases" in r
    assert "Other positions" in r and 'class="you"' in r and "positions 6 to 15" in r
    assert "Copy link" in r and "Copy as text" in r and "as of Jan 10" in r
    if cell["reach_days"] < 27:
        assert "treat this as a floor" in r
    else:
        assert "treat this as a floor" not in r
    assert "course=COMPSCI%200&position=3" in out["location"] and out["title"].startswith("COMPSCI 0 at position 3")


def test_lookup_after_the_last_waitlist_run_is_a_look_back(course_site: Path) -> None:
    cell = cell_of(course_site, "COMPSCI 0", "1-5")
    out = render(course_site, course="COMPSCI 0", position="3", today="2027-03-01")
    r = out["result"]
    last = cell["curve"][-1]
    assert f'<div class="big">{pct(last[1])}' in r and "no longer processed automatically" in r and "look back, not a forecast" in r
    assert "by the first day of instruction" not in r and "days away" not in out["stamp"]


def test_pooled_estimate_is_labelled(course_site: Path) -> None:
    subject_file = load(course_site, "courses/COMPSCI.json")
    cell = subject_file["courses"]["COMPSCI 0"]["buckets"]["6-15"]
    assert cell["pooled"] == "COMPSCI" and "n_course" in cell and "curve" not in cell
    out = render(course_site, course="COMPSCI 0", position="10")
    r = out["result"]
    assert 'class="tag pooled"' in r and "COMPSCI department" in r
    assert f"this course alone: {cell['n_course']} joiners in {cell['sections_course']} section" in r
    assert "Pooled over the whole COMPSCI department" in r


def test_department_level_is_the_default_estimate(full_site: Path) -> None:
    """Every course cell points at its department's curve; the course's own cases are counts, and nothing is called pooled."""
    meta = load(full_site, "meta.json")
    assert meta["estimate_level"] == "dept"
    pooled = load(full_site, "pooled.json")
    dept = pooled["dept"]["COMPSCI"]["1-5"]
    own = load(full_site, "courses/COMPSCI.json")["courses"]["COMPSCI 0"]["buckets"]["1-5"]
    assert own["pooled"] == "COMPSCI" and own["n_course"] >= 30 and "curve" not in own
    out = render(full_site, course="cs 0", position="3")
    r = out["result"]
    assert f'<div class="big">{pct(read_curve(dept["curve"], 27.0)[0])}' in r
    assert "position 3 (positions 1 to 5)</p>" in r and 'class="tag pooled"' not in r
    assert "Department estimate: the whole COMPSCI department at these positions." in r
    assert f"{dept['sections']} sections, {dept['n']} hypothetical joiners, {dept['events']} cleared (this course alone: {own['n_course']} joiners in {own['sections_course']} section" in r
    assert "Estimates are by department and position, not by course" in r and "course-level curves did not beat the position-only baseline" in r
    # the course page says the same, with the course's own cases in their own column
    out = render(full_site, page="course.html", search="?c=cs0&position=3")
    html = out["elements"]["course"]["html"]
    assert "Department estimate: the whole COMPSCI department" in html and 'class="tag pooled"' not in html
    assert '<th scope="col" class="num">This course</th>' in html and f'<td class="num">{own["n_course"]}<span class="sub muted">' in html
    assert "of its own cases, COMPSCI estimate" in html
    # the Courses table keeps every course (department estimates are not "pooled"), cases are the course's own
    out = render(full_site, page="courses.html", search="?bucket=1-5")
    index = load(full_site, "index.json")
    rows = [c for c in index["courses"] if "1-5" in c["buckets"] and c["buckets"]["1-5"]["pooled"] != "all"]
    table = out["elements"]["table"]["html"]
    assert table.count('<tr class="course">') == len(rows) and "COMPSCI estimate" in table and 'class="tag pooled"' not in table
    assert "Hide estimates pooled over all courses" == out["elements"]["hidepooled-label"]["text"]
    assert "department estimates, cases are the course's own" in out["elements"]["count"]["text"]
    # no most-and-least list on Insights: every course in a department shares its curve
    out = render(full_site, page="insights.html")
    assert "Where a mid-list spot moved most" not in out["elements"]["content"]["html"]


def test_unknown_course_falls_back_to_the_department_then_level_then_all(full_site: Path) -> None:
    pooled = load(full_site, "pooled.json")
    # known subject, unknown number: the department's curve for the bucket
    out = render(full_site, course="COMPSCI 999", position="4")
    r = out["result"]
    assert "No data for" in r and "COMPSCI 999" in r and not out["result_hidden"]
    assert "Showing the estimate for the whole COMPSCI department at positions 1 to 5 instead" in r
    dept = pooled["dept"]["COMPSCI"]["1-5"]
    assert f'<div class="big">{pct(read_curve(dept["curve"], 27.0)[0])}' in r
    # unknown subject, upper-division number: the level pool, else all courses
    out = render(full_site, course="NOPE 101", position="4")
    r = out["result"]
    assert "No data for" in r and "NOPE 101" in r
    if "upper" in pooled["level"] and "1-5" in pooled["level"]["upper"]:
        assert "all upper-division courses at positions 1 to 5" in r
    else:
        assert "all courses at positions 1 to 5" in r


def test_missing_bucket_names_the_buckets_with_data(narrow_site: Path) -> None:
    out = render(narrow_site, course="MATH 1", position="20")
    r = out["result"]
    assert "No estimate for positions 16-40" in r and "MATH 1" in r and "Positions with data: 1-5" in r


def test_query_string_runs_the_lookup_on_load(full_site: Path) -> None:
    out = render(full_site, search="?course=STAT%202&position=12")
    assert not out["result_hidden"] and "STAT 2" in out["result"] and "position 12" in out["result"]


def test_search_is_forgiving(full_site: Path) -> None:
    index_rows = load(full_site, "index.json")["courses"]
    keys = {r["key"] for r in index_rows}
    assert "COMPSCI 0" in keys and "MATH 1" in keys
    cases = {
        "compsci0": "COMPSCI 0", "CS 0": "COMPSCI 0", "cs0": "COMPSCI 0", "Comp Sci 0": "COMPSCI 0", "math 1": "MATH 1", "STATS 2": "STAT 2", "stat 2": "STAT 2",
    }
    for text, key in cases.items():
        out = render(full_site, expression=f"(BWO.findCourse(BWO.loaded.index, {json.dumps(text)}) || {{}}).key")
        assert out["eval"] == key, text
    out = render(full_site, expression="BWO.findCourse(BWO.loaded.index, 'NOPE 1')")
    assert out["eval"] is None
    out = render(full_site, expression="BWO.searchCourses(BWO.loaded.index, 'cs', 5).map((r) => r.key)")
    assert out["eval"] and all(k.startswith("COMPSCI") for k in out["eval"])
    out = render(full_site, expression="BWO.searchCourses(BWO.loaded.index, 'math 1', 5).map((r) => r.key)")
    assert out["eval"][0] == "MATH 1" and all(k.startswith("MATH 1") for k in out["eval"])


def test_cross_listed_number_resolves_with_or_without_the_c(full_site: Path) -> None:
    out = render(full_site, expression="(function(){ const i = {courses: [{key: 'DATA C8', subject: 'DATA', number: 'C8', joins: 5, buckets: {}}, {key: 'DATA 100', subject: 'DATA', number: '100', joins: 1, buckets: {}}]}; return ['data 8', 'DATA C8', 'datac8', 'ds 8', 'ds c8'].map((t) => (BWO.findCourse(i, t) || {}).key); })()")
    assert out["eval"] == ["DATA C8"] * 5


def test_verdict_thresholds() -> None:
    out = render(Path("/nonexistent"), expression="[BWO.verdict({p: .8, lo: .7, hi: .9}, false).label, BWO.verdict({p: .5, lo: .4, hi: .6}, false).label, BWO.verdict({p: .2, lo: .1, hi: .3}, false).label, BWO.verdict({p: .8, lo: .5, hi: .9}, false).label, BWO.verdict({p: .8, lo: .7, hi: .9}, 'all').label, BWO.verdict({p: .8, lo: null, hi: null}, false).label]")
    assert out["eval"] == ["Likely", "Could go either way", "Unlikely", "Too little data to call", "Too little data to call", "Too little data to call"]


# ------------------------------------------------------------- other pages


def test_courses_page_filters_sorts_and_keeps_state_in_the_url(course_site: Path) -> None:
    index = load(course_site, "index.json")
    out = render(course_site, page="courses.html", search="?bucket=1-5")
    assert "Simulated term" in out["status"] and not out["elements"]["controls"]["hidden"]
    table = out["elements"]["table"]["html"]
    own = [r for r in index["courses"] if r["buckets"].get("1-5", {}).get("pooled") is False]
    assert own and table.count('<tr class="course">') == len(own) and f"{len(own)} courses at positions 1 to 5" in out["elements"]["count"]["text"]
    assert 'aria-sort="descending"' in table and 'data-sort="p"' in table
    # the default view hides pooled rows; when that hides everything the page says so
    out = render(course_site, page="courses.html")
    mid_own = [r for r in index["courses"] if r["buckets"].get("6-15", {}).get("pooled") is False]
    assert (out["elements"]["table"]["html"].count('<tr class="course">') == len(mid_own)) and (mid_own or "No courses match" in out["elements"]["table"]["html"])
    # show pooled rows, filter by subject, sort by cases ascending
    out = render(course_site, page="courses.html", search="?pooled=1&q=cs&sort=n&dir=asc&bucket=1-5")
    table = out["elements"]["table"]["html"]
    rows = [r for r in index["courses"] if r["subject"] == "COMPSCI" and "1-5" in r["buckets"]]
    assert table.count('<tr class="course">') == len(rows) and all(r["key"] in table for r in rows)
    assert 'aria-sort="ascending"' in table and "course.html?c=COMPSCI%200" in table
    assert out["elements"]["bucket"]["value"] == "1-5" and out["elements"]["q"]["value"] == "cs" and out["elements"]["hidepooled"]["value"] == ""
    # an empty filter says so
    out = render(course_site, page="courses.html", search="?q=zzz")
    assert "No courses match" in out["elements"]["table"]["html"]


def test_course_page_shows_every_bucket_and_the_same_headline(course_site: Path) -> None:
    cell = cell_of(course_site, "COMPSCI 0", "1-5")
    out = render(course_site, page="course.html", search="?c=cs0&position=3")
    html = out["elements"]["course"]["html"]
    assert out["title"].startswith("COMPSCI 0") and "<h1>COMPSCI 0" in html
    at_deadline = read_curve(cell["curve"], 27.0)
    assert f'<div class="big">{pct(at_deadline[0])}' in html and "position 3 (positions 1 to 5)" in html and "within 27 days of joining" in html
    assert html.count('class="curve') == len([b for b in ("1-5", "6-15", "16-40", "41+") if b in load(course_site, "courses/COMPSCI.json")["courses"]["COMPSCI 0"]["buckets"]])
    assert 'class="curve s1 you"' in html and "Show as table" in html and 'class="legend"' in html
    assert "Every position" in html and '<th scope="row">positions 1 to 5 <span class="tag">you</span>' in html and "Other COMPSCI courses" in html
    assert "index.html?course=COMPSCI%200&position=3" in html
    assert out["elements"].get("live", {"html": ""})["html"] == ""  # no live file: the block stays hidden, no error


def test_course_page_without_a_course(full_site: Path) -> None:
    out = render(full_site, page="course.html", search="?c=NOPE%201")
    assert "No data for" in out["status"] and "NOPE 1" in out["status"] and "index.html?course=NOPE%201" in out["status"]
    out = render(full_site, page="course.html")
    assert "No data for" in out["status"]


def test_insights_page_renders_findings_grid_and_departments(full_site: Path) -> None:
    ins = load(full_site, "insights.json")
    out = render(full_site, page="insights.html")
    html = out["elements"]["content"]["html"]
    b1 = read_curve(ins["all_by_bucket"]["1-5"]["curve"], 14.0)[0]
    assert "Position matters most in the first two weeks" in html and pct(b1) in html
    assert f"{ins['counts']['courses']} courses" in html and "hypothetical joiners" in html
    assert html.count("<figure") >= 2 and 'id="hero-chart"' in html and "Show as table" in html
    assert "Longest follow-up" in html and "positions 41 and up" in html
    assert 'class="dotplot"' in html and "Show as table" in html
    assert ("When waitlists move" in html) == bool(ins.get("daily"))
    assert "Where a mid-list spot moved most" not in html  # department level: every course in a department shares its curve


def test_accuracy_page_without_and_with_a_backtest(full_site: Path, tmp_path: Path) -> None:
    out = render(full_site, page="accuracy.html")
    assert "has not been published yet" in out["status"] and "Pre-registered" in out["elements"]["prereg"]["html"]
    from tests.test_export_backtest import make_reports
    from analysis.export_backtest import export_backtest

    export_backtest(make_reports(tmp_path), full_site / "data" / "backtest.json", term_id="9999", term_name="Simulated term")
    try:
        out = render(full_site, page="accuracy.html")
        html = out["elements"]["content"]["html"]
        assert "1 backtest run" in out["status"]
        assert "Later joiners scored with a model fit on earlier ones, within 14 days" in html
        assert "When the estimate said about <strong>70%</strong>, <strong>61%</strong> got in within 14 days" in html
        assert "Fixed-lead-time number (site v1) (what the pages use)" in html and "+0.029" in html and "(-0.034 to +0.082)" in html and "2,938" in html
        assert "<svg" in html and "Which joiners could be scored" in html and "87,324 training joiners" in html
    finally:
        (full_site / "data" / "backtest.json").unlink()


def test_about_and_methods_pages_show_the_data_status(full_site: Path) -> None:
    out = render(full_site, page="about.html")
    assert "Simulated term" in out["elements"]["data-status"]["html"] and "this project's own snapshots" in out["elements"]["data-status"]["html"]
    out = render(full_site, page="methodology.html")
    assert "Showing: <strong>Simulated term</strong>" in out["elements"]["data-status"]["html"]

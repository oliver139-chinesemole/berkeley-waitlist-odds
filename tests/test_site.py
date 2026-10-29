"""Renders the pages under site/ without a browser and checks the states in docs/DESIGN_A6.md.

Each page's own inline script runs under node against a stub document and a
file-backed ``fetch`` (tests/site/harness.js), after the shared assets/site.js.
Skipped when node is missing. "Today" is pinned through the pages' own
``?today=YYYY-MM-DD`` query parameter; the tests about the reader's own clock
pin the instant (``HARNESS_NOW``) and the time zone (``TZ``) instead.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import pytest

from analysis.calendar import TermCalendar
from analysis.export import export_site_tables, read_curve
from analysis.run import run_analysis
from tests.test_run import sim_inputs
from tests.test_survival import synthetic_cohort

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
HARNESS = ROOT / "tests" / "site" / "harness.js"
PAGES = ("index.html", "courses.html", "course.html", "dept.html", "insights.html", "accuracy.html", "methodology.html", "about.html", "404.html")


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
    """The default export: a course with 30 or more cases gets its own curve, smaller cells point at the department's."""
    root = tmp_path_factory.mktemp("site_full")
    export_site_tables(synthetic_cohort(), CAL, root / "data", n_boot=50)
    return root


course_site = full_site  # the lookup tests read the course's own curve; at the default that is what they get


@pytest.fixture(scope="module")
def dept_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """estimate_level="dept": every course cell points at its department's curve; the course's own cases are counts."""
    root = tmp_path_factory.mktemp("site_dept")
    export_site_tables(synthetic_cohort(), CAL, root / "data", n_boot=50, estimate_level="dept")
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
    export_site_tables(cohort[cohort["position"] <= 5], CAL, root / "data", n_boot=20)
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
    assert "No estimates yet" in out["status"] and "The curves appear once this project's own Spring 2027 snapshots have seen enough waitlists clear." in out["status"]
    assert "Oct 26" not in out["status"] and "mid-November" not in out["status"]  # true before and after Phase 1 opens
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


def jsround(x: float) -> int:
    """Math.round as the page rounds: a half goes up (Python's round() sends it to even)."""
    return int(x + 0.5)


def freq(p: float) -> str:
    """BWO.frequency: the share as a natural frequency out of 20."""
    k = jsround(p * 20)
    return "Almost no one" if k == 0 else "Almost everyone" if k == 20 else f"About {k} in 20"


def test_lookup_reads_the_curve_at_the_askers_own_horizons(course_site: Path) -> None:
    cell = cell_of(course_site, "COMPSCI 0", "1-5")
    assert cell["sections"] == 1 and 0 < cell["reach_days"] < 7  # one section, followed for less than a week
    out = render(course_site, course="compsci   0", position="3")
    r = out["result"]
    assert not out["result_hidden"]
    assert "COMPSCI 0" in r and "position 3 (positions 1 to 5)" in r
    # headline: P(cleared within the 27 days left before the end of the last waitlist run's day), which no one in
    # this curve was followed for, so it is read at the reach, said as "within <reach> days", and "at least" for the 27
    at_deadline = read_curve(cell["curve"], 27.0)
    reach = jsround(at_deadline[3])
    assert f"<p>{freq(at_deadline[0])} got in within {reach} days of joining</p>" in r and "got in by" not in r
    assert (f"<p><strong>{pct(at_deadline[0])}</strong> of comparable students had cleared within {reach} days of joining, the longest the data follow anyone; "
            f"the time left before the last automatic waitlist run (Feb 5, 2027) is 27 days, so at least {pct(at_deadline[0])} had cleared within that time.</p>") in r
    assert "treat this as a floor" not in r
    k = jsround(at_deadline[0] * 20)
    assert f'<span class="dots dim" role="img" aria-label="{k} of 20 dots filled: {pct(at_deadline[0])}">' in r and r.count('<i class="on"></i>') == k
    # one section, no interval: the verdict leads, the share follows the by-when table, and nothing is big
    assert r.index('<p class="lead"><span class="verdict">Too little data to call</span> <span class="muted small">(one section only, no interval)</span></p>') < r.index('class="bywhen"') < r.index("got in within")
    assert '<div class="big">' not in r and "Verdicts: Likely at 75% or more" in r
    # second line: by the first day of instruction, 9 days from "today", also past the reach
    at_instruction = read_curve(cell["curve"], 9.0)
    assert f"<p>At least <strong>{pct(at_instruction[0])}</strong> by the first day of instruction (Jan 19, 2027, 9 days from now).</p>" in r
    # by-when table: 7 and 14 days from today with their dates, then the two calendar dates, every one past the reach
    at7 = read_curve(cell["curve"], 7.0)
    assert '<th class="num">Share in by then</th>' in r and "Share who got in" not in r and 'aria-label="Share in by then"' in r
    assert f'<td>7 days from now <span class="muted">(Jan 17)</span></td><td class="num"><span class="muted small">at least</span> <strong>{pct(at7[0])}</strong></td>' in r
    assert '<td>Last waitlist run <span class="muted">(Feb 5)</span></td>' in r and '<td>First day of class <span class="muted">(Jan 19)</span></td>' in r
    assert ">floor<" not in r
    assert f"{cell['sections']} section" in r and f"{cell['n']} hypothetical joiners, {cell['events']} cleared" in r
    assert "<svg" in r and 'class="mark"' in r and "last waitlist run" in r and 'role="img"' in r and "Show as table" in r
    assert r.count('class="curve') == 1 and ' H ' in r  # one step-drawn curve
    assert ('class="band"' in r) == (cell["sections"] >= 2 and cell["curve"][0][2] is not None)
    assert '(positions 1 to 5)<span class="tag pooled"' not in r  # the asker's own cell is not pooled
    assert "Estimates are by course and position when a course has at least 30 cases" in r
    assert "Other positions" in r and 'class="you"' in r and "positions 6 to 15" in r
    assert "Copy link" in r and "Copy as text" in r and "as of Jan 10" in r
    assert "course=COMPSCI%200&position=3" in out["location"] and out["title"].startswith("COMPSCI 0 at position 3")


def test_lookup_after_the_last_waitlist_run_is_a_look_back(course_site: Path) -> None:
    cell = cell_of(course_site, "COMPSCI 0", "1-5")
    out = render(course_site, course="COMPSCI 0", position="3", today="2027-03-01")
    r = out["result"]
    last = cell["curve"][-1]
    assert f"<p><strong>{pct(last[1])}</strong></p>" in r and "no longer processed automatically" in r and "look back, not a forecast" in r
    assert r.index('class="verdict"') < r.index("no longer processed automatically") < r.index("got in within")  # one section: the verdict leads here too
    assert "by the first day of instruction" not in r and "days away" not in out["stamp"]
    # item 22: no "7 days from now" row under the sentence saying waitlists are no longer processed; nothing is left to put in the table
    assert "days from now" not in r and 'class="bywhen"' not in r
    out = render(Path("/nonexistent"), today="2027-03-01", expression=f"BWO.byWhenHtml({{curve: {json.dumps(HEADLINE_CELLS['within reach'])}}}, {json.dumps(HEADLINE_META)}, BWO.today())")
    assert out["eval"] == ""


# The headline block (BWO.headlineHtml, the lookup's and the course page's) pinned on hand-made curves on Jan 10,
# 27 days to the end of the last run's day and 9 to instruction: a curve that reaches the 27 days, one that stops
# at 20 (audit item 1: the share is read at the reach and said as "within 20 days", with "at least" for the 27),
# and one section with no interval (item 3: the verdict leads, the share comes after the by-when table, dimmed).
# A verdict's cut-off range is printed in the verdict note only (item 17: "Could go either way (40% to 74%)" sat next to
# "95% interval 64% to 82%"); "Too little data to call" keeps its reason, which is not a range.
HEADLINE_META = {"deadline": "2027-02-05", "instruction_start": "2027-01-19", "forecast_term_name": "Spring 2027"}
HEADLINE_CELLS = {
    "within reach": [[0.5, 0.1, 0.05, 0.15], [7, 0.5, 0.45, 0.55], [28, 0.8, 0.74, 0.86]],
    "past the reach": [[0.5, 0.1, 0.05, 0.15], [7, 0.5, 0.45, 0.55], [20, 0.8, 0.74, 0.86]],
    "one section": [[0.5, 0.2, None, None], [6.65, 0.84, None, None]],
    "all in by the reach": [[0.5, 0.3, 0.2, 0.4], [8, 1.0, 0.97, 1.0]],  # "at least 100%" says nothing: no "at least"
}
LOOK_BACK = "<p>The last automatic waitlist run for Spring 2027 was on Feb 5, 2027; waitlists are no longer processed automatically, so this is a look back, not a forecast.</p>"
THIN_LEAD = '<p class="lead"><span class="verdict">Too little data to call</span> <span class="muted small">(one section only, no interval)</span></p>'
HEADLINES = {  # (html, after): the caller prints `after` under its table
    ("2027-01-10", "within reach"): (
        '<p class="lead">About 10 in 20 got in within 27 days of joining</p>[dots 10 of 20 dots filled: 50%]<div class="big">50% <small>(95% interval 45% to 55%)</small></div>'
        "<p>of comparable students had cleared within 27 days of joining, the time left before the last automatic waitlist run (Feb 5, 2027).</p>"
        '<p><span class="verdict">Could go either way</span></p>'
        "<p><strong>50%</strong> by the first day of instruction (Jan 19, 2027, 9 days from now).</p>", ""),
    ("2027-01-10", "past the reach"): (
        '<p class="lead">About 16 in 20 got in within 20 days of joining</p>[dots 16 of 20 dots filled: 80%]<div class="big">80% <small>(95% interval 74% to 86%)</small></div>'
        "<p>of comparable students had cleared within 20 days of joining, the longest the data follow anyone; "
        "the time left before the last automatic waitlist run (Feb 5, 2027) is 27 days, so at least 80% had cleared within that time.</p>"
        '<p><span class="verdict">Likely</span></p>'
        "<p><strong>50%</strong> by the first day of instruction (Jan 19, 2027, 9 days from now).</p>", ""),
    ("2027-01-10", "one section"): (
        THIN_LEAD,
        "<p>About 17 in 20 got in within 7 days of joining</p>[dim dots 17 of 20 dots filled: 84%]"
        "<p><strong>84%</strong> of comparable students had cleared within 7 days of joining, the longest the data follow anyone; "
        "the time left before the last automatic waitlist run (Feb 5, 2027) is 27 days, so at least 84% had cleared within that time.</p>"
        "<p>At least <strong>84%</strong> by the first day of instruction (Jan 19, 2027, 9 days from now).</p>"),
    ("2027-01-10", "all in by the reach"): (
        '<p class="lead">Almost everyone got in within 8 days of joining</p>[dots 20 of 20 dots filled: 100%]<div class="big">100% <small>(95% interval 97% to 100%)</small></div>'
        "<p>of comparable students had cleared within 8 days of joining, the longest the data follow anyone; "
        "the time left before the last automatic waitlist run (Feb 5, 2027) is 27 days.</p>"
        '<p><span class="verdict">Likely</span></p>'
        "<p><strong>100%</strong> by the first day of instruction (Jan 19, 2027, 9 days from now).</p>", ""),
    ("2027-03-01", "within reach"): (
        '<p class="lead">About 16 in 20 got in within 28 days of joining</p>[dots 16 of 20 dots filled: 80%]<div class="big">80% <small>(95% interval 74% to 86%)</small></div>'
        + LOOK_BACK + '<p><span class="verdict">Likely</span></p>', ""),
    ("2027-03-01", "one section"): (
        THIN_LEAD + LOOK_BACK,
        "<p>About 17 in 20 got in within 7 days of joining</p>[dim dots 17 of 20 dots filled: 84%]<p><strong>84%</strong></p>"),
}


def squeeze(html: str) -> str:
    """Markup without its template indentation (whitespace around a line break, never a space the page means) and the 20-dot line as one token."""
    html = re.sub(r"\s*\n\s*", "", html)
    return re.sub(r'<span class="dots( dim)?" role="img" aria-label="([^"]*)">(?:<i class="(?:on)?"></i>)*</span>', lambda m: f"[{'dim ' if m.group(1) else ''}dots {m.group(2)}]", html)


@pytest.mark.parametrize(("today", "cell"), sorted(HEADLINES))
def test_the_headline_block_is_pinned(today: str, cell: str) -> None:
    expression = (f"(function(){{ const h = BWO.headlineHtml({{curve: {json.dumps(HEADLINE_CELLS[cell])}}}, false, 'course', {json.dumps(HEADLINE_META)}, BWO.today());"
                  " return [h.html, h.after || '', h.marks]; })()")
    out = render(Path("/nonexistent"), today=today, expression=expression)
    assert "eval_error" not in out, out.get("eval_error")
    html, after, marks = out["eval"]
    assert (squeeze(html), squeeze(after)) == HEADLINES[(today, cell)]
    assert marks == ([{"day": 27, "label": "last waitlist run"}, {"day": 9, "label": "instruction"}] if today == "2027-01-10" else [])


def test_the_by_when_table_says_at_least_past_the_reach() -> None:
    """Past the curve's reach a row is the value at the reach: "at least", except at 100%, where it would say nothing."""
    expression = ("[" + ", ".join(f"BWO.byWhenHtml({{curve: {json.dumps(HEADLINE_CELLS[c])}}}, {json.dumps(HEADLINE_META)}, BWO.today())" for c in ("past the reach", "all in by the reach")) + "]")
    out = render(Path("/nonexistent"), expression=expression)
    assert "eval_error" not in out, out.get("eval_error")
    capped, full = out["eval"]
    assert capped.startswith('<table class="bywhen" aria-label="Share in by then"><thead><tr><th>By when</th><th class="num">Share in by then</th><th class="num">95% interval</th></tr></thead>')
    assert '<tr><td>14 days from now <span class="muted">(Jan 24)</span></td><td class="num"><strong>50%</strong></td><td class="num muted small">45% to 55%</td></tr>' in capped
    assert '<tr><td>Last waitlist run <span class="muted">(Feb 5)</span></td><td class="num"><span class="muted small">at least</span> <strong>80%</strong></td><td class="num muted small">74% to 86%</td></tr>' in capped
    assert '<tr><td>Last waitlist run <span class="muted">(Feb 5)</span></td><td class="num"><strong>100%</strong></td><td class="num muted small">97% to 100%</td></tr>' in full
    assert "at least" not in full and "floor" not in capped + full


# Item 18 and Task 15's review: a share read past the curve's reach is "at least" that much on every table,
# as on the lookup and in the Methods page's sentence, and nothing where it prints as 100% ("100% floor" said nothing).
AT_LEAST = '<span class="muted small" title="The data follow joiners for fewer days than this horizon">at least</span> '


def capped_rows(index: dict, bucket: str, h: float) -> tuple[list[dict], list[dict]]:
    """The index rows whose cell at `bucket` stops short of `h` days: those under 100%, and those that print as 100%."""
    rows = [r for r in index["courses"] if r["buckets"].get(bucket) and r["buckets"][bucket]["reach"][1] < h]
    i = index["horizons"].index(h)
    return [r for r in rows if jspct(r["buckets"][bucket]["p"][i]) != "100%"], [r for r in rows if jspct(r["buckets"][bucket]["p"][i]) == "100%"]


def row_with(html: str, key: str) -> str:
    """The one table row of the Courses or department table that links `key`."""
    found = [tr for tr in html.split('<tr class="course">')[1:] if f">{key}</a>" in tr]
    assert len(found) == 1, (key, len(found))
    return found[0]


def test_past_the_reach_every_table_says_at_least(course_site: Path) -> None:
    index = load(course_site, "index.json")
    partial, full = capped_rows(index, "1-5", 14.0)
    assert partial and full  # the synthetic export has both at positions 1 to 5 within 14 days
    pages = {}
    # Courses: the share column, "at least" before the number, nothing at 100%
    out = render(course_site, page="courses.html", search="?bucket=1-5&pooled=1&all=1")
    pages["courses"] = table = out["elements"]["table"]["html"]
    for r in partial:
        assert f'<td class="num" data-label="Share who got in">{AT_LEAST}<strong>{jspct(r["buckets"]["1-5"]["p"][1])}</strong>' in row_with(table, r["key"]), r["key"]
    for r in full:
        tr = row_with(table, r["key"])
        assert '<td class="num" data-label="Share who got in"><strong>100%</strong><span class="sub">' in tr and "at least" not in tr, r["key"]
    # the course page's table of every bucket
    cell = next(r for r in index["courses"] if r["key"] == "COMPSCI 0")["buckets"]["1-5"]
    assert cell["reach"][1] < 7
    out = render(course_site, page="course.html", search="?c=cs0&position=3")
    pages["course"] = html = out["elements"]["course"]["html"]
    summary = html.split('aria-label="Share who got in by position and horizon"')[1].split("</table>")[0]
    for p in cell["p"]:
        assert f'<td class="num">{AT_LEAST if jspct(p) != "100%" else ""}{jspct(p)}</td>' in summary, p
    # the department page: the pool's three horizons and every course's 14 days
    pool = load(course_site, "pooled.json")["dept"]["COMPSCI"]["6-15"]
    assert pool["reach_days"] < 28
    out = render(course_site, page="dept.html", search="?subject=COMPSCI")
    pages["dept"] = out["elements"]["pool"]["html"] + out["elements"]["table"]["html"]
    p28 = read_curve(pool["curve"], 28.0)[0]
    assert f'<tr><td>28 days</td><td class="num">{AT_LEAST if jspct(p28) != "100%" else ""}<strong>{jspct(p28)}</strong></td>' in pages["dept"]
    out = render(course_site, page="dept.html", search="?subject=ART&bucket=1-5")
    dept_table = out["elements"]["table"]["html"]
    pages["dept_art"] = dept_table
    for r in partial + full:
        if r["subject"] == "ART":
            p = jspct(r["buckets"]["1-5"]["p"][1])
            assert f'<td class="num">{AT_LEAST if p != "100%" else ""}<strong>{p}</strong>' in row_with(dept_table, r["key"]), r["key"]
    # Insights: the bucket grid
    ins = load(course_site, "insights.json")["all_by_bucket"]
    out = render(course_site, page="insights.html")
    pages["insights"] = grid = out["elements"]["content"]["html"]
    for b, c in ins.items():
        if c["reach_days"] < 28:
            p = read_curve(c["curve"], 28.0)[0]
            assert f'<td class="num">{AT_LEAST if jspct(p) != "100%" else ""}<strong>{jspct(p)}</strong>' in grid, b
    # the chart's hatched region past the reach says the same in its title (the lookup's one curve stops at 7 days)
    pages["lookup"] = render(course_site, course="COMPSCI 0", position="3")["result"]
    assert "<title>Beyond 7 days, the longest the data follow anyone, the share is at least the value at 7 days</title>" in pages["lookup"]
    for name, text in pages.items():
        assert not re.search(r"\bfloor\b", text, re.I), name


def test_the_verdict_cut_offs_are_in_the_note_only(course_site: Path) -> None:
    """Item 17: the verdict chip carries no range of its own beside the share's interval; the note under it has the cut-offs."""
    r = render(course_site, course="COMPSCI 0", position="10")["result"]
    assert '<p><span class="verdict">' in r and not re.search(r'class="verdict">[^<]*</span> <span class="muted small">\(\d', r)
    for cut in ("(75% or more)", "(40% to 74%)", "(below 40%)"):
        assert cut not in r
    assert "Verdicts: Likely at 75% or more, Could go either way from 40% to 74%, Unlikely below 40%" in r
    markup = (SITE / "methodology.html").read_text()
    assert "are fixed cut-offs, not a model, and every page that shows a verdict prints them in a note." in markup and "printed next to every verdict" not in markup


def chart_svg(series: list[dict], **opts: object) -> str:
    out = render(Path("/nonexistent"), expression=f"BWO.curveChart({json.dumps({'series': series, 'id': 't', **opts})})")
    assert "eval_error" not in out, out.get("eval_error")
    return out["eval"]


def end_labels(svg: str) -> list[str]:
    """The direct labels at the curves' ends, top to bottom."""
    found = re.findall(r'<text class="lbl(?: ink)?" x="560" y="([\d.]+)">([^<]+)</text>', svg)
    return [label for _, label in sorted(found, key=lambda m: float(m[0]))]


def test_end_labels_keep_bucket_order_where_they_print_the_same() -> None:
    """Item 19: four curves ending at 99.8%, 99.6%, 99.5% and 99% read "16-40 100%, 1-5 100%, 6-15 100%, 41+ 99%";
    labels that print the same are in bucket order, and labels that differ stay in the order of their curves' ends."""
    def series(ends: dict[str, float]) -> list[dict]:
        return [{"label": b, "short": b, "curve": [[0.5, 0.1, None, None], [20, p, None, None]], "cls": f"s{i + 1}"} for i, (b, p) in enumerate(ends.items())]
    tied = chart_svg(series({"1-5": 0.996, "6-15": 0.995, "16-40": 0.998, "41+": 0.99}))
    assert end_labels(tied) == ["1-5 100%", "6-15 100%", "16-40 100%", "41+ 99%"]
    apart = chart_svg(series({"1-5": 0.83, "6-15": 0.92, "16-40": 0.88}))
    assert end_labels(apart) == ["6-15 92%", "16-40 88%", "1-5 83%"]  # each label beside its own curve's end


def test_the_phone_nav_wraps_rather_than_scrolls() -> None:
    """Item 15: below 30 rem the nav's links wrap instead of scrolling out of sight; tests/site/smoke.mjs checks every link is whole at 390 px."""
    css = (SITE / "assets" / "site.css").read_text()
    m = re.search(r"@media \(max-width: 30rem\) \{\s*\.site-head nav \{([^}]*)\}\s*\.site-head nav a \{([^}]*)\}", css)
    assert m, "no phone rule for the nav"
    assert "flex-wrap: wrap" in m.group(1) and "overflow-x: visible" in m.group(1)
    assert "min-height" not in m.group(2) and "min-height: 44px" in css  # the base rule's 44 px target stands


def test_every_other_x_tick_is_marked_for_phones() -> None:
    """Item 16: below 30 rem (480 px) every other x tick, its day and its date, is hidden, so the axis keeps half its labels."""
    svg = chart_svg([{"label": "a", "curve": [[0.5, 0.1, 0.05, 0.15], [80, 0.7, 0.6, 0.8]]}], marks=[{"day": 102, "label": "last waitlist run"}], t=None)
    days_ = re.findall(r'<text class="lbl( odd)?" x="[\d.]+" y="[\d.]+" text-anchor="middle">(\d+)d</text>', svg)
    assert [d for _, d in days_] == ["0", "14", "28", "42", "56", "70", "84", "98"]
    assert [d for odd, d in days_ if odd] == ["14", "42", "70", "98"]
    out = render(Path("/nonexistent"), expression=("(function(){ const svg = BWO.curveChart({series: [{label: 'a', curve: [[0.5, 0.1, 0.05, 0.15], [80, 0.7, 0.6, 0.8]]}],"
                                                   " marks: [{day: 102, label: 'x'}], t: BWO.today(), id: 'u'}); return svg; })()"))
    dates = re.findall(r'<text class="lbl date( odd)?" x="[\d.]+" y="[\d.]+" text-anchor="middle">([^<]+)</text>', out["eval"])
    assert len(dates) == 8 and [d for odd, d in dates if odd] == ["Jan 24", "Feb 21", "Mar 21", "Apr 18"]
    css = (SITE / "assets" / "site.css").read_text()
    rule = re.search(r"@media \(max-width: 30rem\) \{([^}]*\.chart \.lbl\.odd[^}]*)\}", css)
    assert rule and "display: none" in rule.group(1), "no phone rule hiding every other x tick"


def test_a_verdict_with_the_data_behind_it_leads_with_the_share(course_site: Path) -> None:
    """The department's pool at positions 6 to 15 has an interval: the share leads, big, and the verdict follows it."""
    own = load(course_site, "courses/COMPSCI.json")["courses"]["COMPSCI 0"]["buckets"]["6-15"]
    pool = load(course_site, "pooled.json")["dept"][own["pooled"]]["6-15"]
    p, lo, hi, day = read_curve(pool["curve"], 27.0)
    assert lo is not None and hi - lo <= 0.30 and day < 27  # a verdict, read at the reach
    r = render(course_site, course="COMPSCI 0", position="10")["result"]
    assert r.index(f'<p class="lead">{freq(p)} got in within {jsround(day)} days of joining</p>') < r.index(f'<div class="big">{jspct(p)}') < r.index('<p><span class="verdict">') < r.index('class="bywhen"')
    assert "dots dim" not in r


COPY_TEXT = ("(async () => { let got = null; navigator = { clipboard: { writeText: (t) => { got = t; return Promise.resolve(); } } };"
             " BWO.$('copy-text').listeners.click[0](); return got; })()")


def test_copy_as_text_says_what_the_headline_says(course_site: Path) -> None:
    """Item 1 in the shareable text: "within N days of joining", the days left, "at least" past the reach, the verdict when there is too little data."""
    tail = "Simulated term, this project's own snapshots. https://example.test/index.html?course="
    own = load(course_site, "courses/COMPSCI.json")["courses"]["COMPSCI 0"]["buckets"]["6-15"]
    pool = load(course_site, "pooled.json")["dept"][own["pooled"]]["6-15"]
    p, lo, hi, day = read_curve(pool["curve"], 27.0)
    out = render(course_site, course="COMPSCI 0", position="10", expression=COPY_TEXT)
    assert out["eval"] == (f"COMPSCI 0, position 10: {freq(p).lower()} comparable students got in within {jsround(day)} days of joining ({jspct(p)}, 95% interval {jspct(lo)} to {jspct(hi)}), "
                           f"the longest the data follow anyone; at least that share within the 27 days left before the last automatic waitlist run (Feb 5, 2027). {tail}COMPSCI%200&position=10")
    cell = cell_of(course_site, "COMPSCI 0", "1-5")
    p, _, _, day = read_curve(cell["curve"], 27.0)
    out = render(course_site, course="COMPSCI 0", position="3", expression=COPY_TEXT)
    assert out["eval"] == (f"COMPSCI 0, position 3: too little data to call (one section only, no interval); {freq(p).lower()} comparable students got in within {jsround(day)} days of joining ({jspct(p)}), "
                           f"the longest the data follow anyone; at least that share within the 27 days left before the last automatic waitlist run (Feb 5, 2027). {tail}COMPSCI%200&position=3")
    # three days before the end of the last run's day the curve reaches the horizon: the time left is the horizon
    p, _, _, _ = read_curve(cell["curve"], 3.0)
    out = render(course_site, course="COMPSCI 0", position="3", today="2027-02-03", expression=COPY_TEXT)
    assert out["eval"] == (f"COMPSCI 0, position 3: too little data to call (one section only, no interval); {freq(p).lower()} comparable students got in within 3 days of joining ({jspct(p)}), "
                           f"the time left before the last automatic waitlist run (Feb 5, 2027). {tail}COMPSCI%200&position=3")
    # "almost everyone" takes "among", not "almost everyone comparable students"; at 100% there is no "at least",
    # and the clause after the semicolon is still a sentence (Task 15's review): the run is 27 days away
    cell = cell_of(course_site, "MATH 25", "1-5")
    p, _, _, day = read_curve(cell["curve"], 27.0)
    assert jspct(p) == "100%"
    out = render(course_site, course="MATH 25", position="3", expression=COPY_TEXT)
    assert out["eval"] == (f"MATH 25, position 3: too little data to call (one section only, no interval); almost everyone among comparable students got in within {jsround(day)} days of joining (100%), "
                           f"the longest the data follow anyone; the last automatic waitlist run (Feb 5, 2027) is 27 days away. {tail}MATH%2025&position=3")


# Audit item 4: the pages ran on UTC, so from about 17:00 Pacific every date was tomorrow's. "Today" is the
# reader's own calendar date; at 18:20 PDT on Oct 27 (01:20Z Oct 28) a Pacific reader sees Oct 27 and a UTC
# reader Oct 28, each with whole days from it. Nov 1 is a DST change, so "7 days from now" crosses it.
PACIFIC_EVENING = "2026-10-28T01:20:00Z"
READER_DATES = {
    "America/Los_Angeles": {"day": "Oct 27", "phase2": 27, "adjust": 76, "instruction": 84, "deadline": 102, "week": "Nov 3", "fortnight": "Nov 10"},
    "UTC": {"day": "Oct 28", "phase2": 26, "adjust": 75, "instruction": 83, "deadline": 101, "week": "Nov 4", "fortnight": "Nov 11"},
}


@pytest.mark.parametrize("tz", sorted(READER_DATES))
def test_today_is_the_readers_own_calendar_date(course_site: Path, tz: str) -> None:
    want = READER_DATES[tz]
    expression = "[BWO.today().getHours(), BWO.today().getDate(), BWO.horizons(BWO.loaded.meta, BWO.today()), BWO.fmtShort(BWO.addDays(BWO.today(), 7))]"
    out = render(course_site, course="COMPSCI 0", position="3", today=None, expression=expression, env={"TZ": tz, "HARNESS_NOW": PACIFIC_EVENING})
    r = out["result"]
    assert f'<p class="muted small">Berkeley Waitlist Odds · as of {want["day"]}</p>' in r
    dates = out["elements"]["dates"]["html"]
    assert f'<strong>Nov 23, 2026</strong> Phase 2 opens <span class="muted">(in {want["phase2"]} days)</span>' in dates
    assert f'<strong>Jan 11, 2027</strong> Adjustment period <span class="muted">(in {want["adjust"]} days)</span>' in dates
    assert f'<strong>Jan 19, 2027</strong> First day of class <span class="muted">(in {want["instruction"]} days)</span>' in dates
    assert f'<td>7 days from now <span class="muted">({want["week"]})</span></td>' in r and f'<td>14 days from now <span class="muted">({want["fortnight"]})</span></td>' in r
    assert '<td>First day of class <span class="muted">(Jan 19)</span></td>' in r and '<td>Last waitlist run <span class="muted">(Feb 5)</span></td>' in r
    assert f"by the first day of instruction (Jan 19, 2027, {want['instruction']} days from now)" in r
    assert f"the time left before the last automatic waitlist run (Feb 5, 2027) is {want['deadline']} days" in r
    assert re.search(r'class="lbl date"[^>]*>([^<]*)<', r).group(1) == want["day"]  # the chart's x-axis starts today
    assert out["stamp"].endswith(f"Last automatic waitlist run Feb 5, 2027 ({want['deadline']} days away).")
    assert out["eval"] == [0, int(want["day"].split()[1]), {"deadline": want["deadline"], "instruction": want["instruction"]}, want["week"]]


@pytest.mark.parametrize("tz", ["America/Los_Angeles", "UTC", "Pacific/Kiritimati", "Pacific/Pago_Pago"])
def test_a_pinned_today_is_that_date_in_every_time_zone(course_site: Path, tz: str) -> None:
    """?today= is a date, not an instant: the same page in UTC+14 and UTC-11."""
    out = render(course_site, course="COMPSCI 0", position="3", env={"TZ": tz})
    assert "as of Jan 10</p>" in out["result"] and '<td>7 days from now <span class="muted">(Jan 17)</span></td>' in out["result"]
    assert "(in 9 days)" in out["elements"]["dates"]["html"] and out["stamp"].endswith("(27 days away).")


def test_insights_daily_dates_are_the_data_dates() -> None:
    """The admits-per-day axis labels are calendar dates from the data (the committed export has flows), printed as written in any time zone."""
    daily = load(SITE, "insights.json")["daily"]
    html = render(SITE, page="insights.html", env={"TZ": "America/Los_Angeles"})["elements"]["content"]["html"]
    first = date.fromisoformat(daily[0]["date"])
    assert f'text-anchor="start">{first.strftime("%b")} {first.day}</text>' in html


def test_pooled_estimate_is_labelled(course_site: Path) -> None:
    subject_file = load(course_site, "courses/COMPSCI.json")
    cell = subject_file["courses"]["COMPSCI 0"]["buckets"]["6-15"]
    assert cell["pooled"] == "COMPSCI" and "n_course" in cell and "curve" not in cell
    out = render(course_site, course="COMPSCI 0", position="10")
    r = out["result"]
    assert 'class="tag pooled"' in r and "COMPSCI department" in r
    assert f"this course alone: {cell['n_course']} joiners in {cell['sections_course']} section" in r
    assert f"This curve: the COMPSCI department, positions 6 to 15 (COMPSCI 0 had {cell['n_course']} cases, fewer than 30)" in r


def test_department_level_estimates(dept_site: Path) -> None:
    """At estimate_level dept every course cell points at its department's curve; the course's own cases are counts, and nothing is called pooled."""
    full_site = dept_site
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
    assert "This curve: the COMPSCI department, positions 1 to 5 (estimates are by department; COMPSCI 0 had" in r
    assert f"{dept['sections']} sections, {dept['n']} hypothetical joiners, {dept['events']} cleared (this course alone: {own['n_course']} joiners in {own['sections_course']} section" in r
    assert "Estimates are by department and position, not by course" in r and "course-level curves did not beat the position-only baseline" in r
    # the course page says the same, with the course's own cases in their own column
    out = render(full_site, page="course.html", search="?c=cs0&position=3")
    html = out["elements"]["course"]["html"]
    assert "This curve: the COMPSCI department, positions 1 to 5 (estimates are by department;" in html and 'class="tag pooled"' not in html
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


NO_DATA = "Check the spelling, or the course had too few waitlisted students to estimate."
BROWSE = '<p>Or browse <a href="courses.html?today=2027-01-10">every course</a>.</p>'


@pytest.mark.parametrize(("query", "shown", "near"), [("NOPE 999", "NOPE 999", None), ("COMPSCI 999", "COMPSCI 999", "COMPSCI"), ("NOPE 101", "NOPE 101", None), ("data structures", "DATA STRUCTURES", None)])
def test_a_course_not_in_the_index_gets_no_estimate(full_site: Path, query: str, shown: str, near: str | None) -> None:
    """Audit item 3: as on the course page, a code that is not a course in the index gets no pooled estimate, only suggestions.

    Item 13: "Did you mean" offers only what is close to the query (here COMPSCI's own courses for
    COMPSCI 999); for a subject nothing resembles it is left out, rather than offering the
    most-joined courses, which are the Try chips above the form."""
    out = render(full_site, course=query, position="10")
    r = out["result"]
    assert not out["result_hidden"]
    if near:
        assert r.startswith(f'<p class="error">No data for <strong>{shown}</strong>. {NO_DATA} Did you mean <a href="?course=')
        assert r.endswith("?</p>" + BROWSE)
        keys = [unquote(k) for k in re.findall(r'<a href="\?course=([^&"]+)&position=10', r)]
        assert len(keys) == 3 and all(k.startswith(near + " ") for k in keys), keys
    else:
        assert r == f'<p class="error">No data for <strong>{shown}</strong>. {NO_DATA}</p>{BROWSE}'
    for estimate in ('class="verdict"', "got in", 'class="big"', "Showing the estimate", "<svg", "This curve:", 'class="bywhen"', "dots"):
        assert estimate not in r, estimate
    assert out["title"] == f"No data for {shown} · Berkeley Waitlist Odds"
    assert out["location"] == f"?course={shown.replace(' ', '%20')}&position=10&today=2027-01-10"


def gap_copy(site_root: Path, tmp_path: Path, *, drop: tuple[str, ...] = ()) -> Path:
    """A copy of the export where COMPSCI 0 had no cases at positions 41 and up, and ``drop`` pools ("dept", "level") are missing there too."""
    root = tmp_path / ("gap_" + "_".join(drop))
    shutil.copytree(site_root, root)
    subject = root / "data" / "courses" / "COMPSCI.json"
    f = json.loads(subject.read_text())
    del f["courses"]["COMPSCI 0"]["buckets"]["41+"]
    subject.write_text(json.dumps(f))
    path = root / "data" / "pooled.json"
    pooled = json.loads(path.read_text())
    if "dept" in drop:
        del pooled["dept"]["COMPSCI"]["41+"]
    if "level" in drop:
        del pooled["level"]["lower"]["41+"]
    path.write_text(json.dumps(pooled))
    return root


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


def test_search_and_related_before_and_after_the_index_loads() -> None:
    """searchCourses has matchCourse's guard (nothing loaded yet: no suggestions, no error); relatedCourses ranks the matcher's way."""
    out = render(Path("/nonexistent"), expression="[null, undefined, {}].map((i) => { try { return BWO.searchCourses(i, 'cs61a', 8); } catch (e) { return String(e); } })")
    assert out["eval"] == [[], [], []]
    rows = (
        "{key: 'MATH 9', subject: 'MATH', joins: 5, buckets: {'6-15': {pooled: false}}},"
        "{key: 'MATH 2', subject: 'MATH', joins: 5, buckets: {'6-15': {pooled: false}}},"
        "{key: 'MATH 3', subject: 'MATH', joins: 7, buckets: {'6-15': {pooled: 'MATH'}}},"
        "{key: 'MATH 4', subject: 'MATH', buckets: {'6-15': {pooled: false}}},"
        "{key: 'MATH 5', subject: 'MATH', joins: 9, buckets: {'6-15': {pooled: 'all'}}},"
        "{key: 'MATH 1', subject: 'MATH', joins: 1, buckets: {'6-15': {pooled: false}}}"
    )
    out = render(Path("/nonexistent"), expression=f"(function(){{ const i = {{courses: [{rows}]}}; return BWO.relatedCourses(i, i.courses[5], '6-15', 5).map((r) => r.key); }})()")
    assert out["eval"] == ["MATH 3", "MATH 2", "MATH 9", "MATH 4"]  # joins descending, then key; a missing count is 0


def test_cross_listed_number_resolves_with_or_without_the_c(full_site: Path) -> None:
    out = render(full_site, expression="(function(){ const i = {courses: [{key: 'DATA C8', subject: 'DATA', number: 'C8', joins: 5, buckets: {}}, {key: 'DATA 100', subject: 'DATA', number: '100', joins: 1, buckets: {}}]}; return ['data 8', 'DATA C8', 'datac8', 'ds 8', 'ds c8'].map((t) => (BWO.findCourse(i, t) || {}).key); })()")
    assert out["eval"] == ["DATA C8"] * 5


# ------------------------------------------------------- course search (Q1, Q2, Q3, Q8)

QUERIES = ROOT / "tests" / "fixtures" / "course_queries.csv"
RUNNER = ROOT / "tests" / "site" / "queries.mjs"
# Every row of the table in docs/dev/NEXT_2026-09-24.md section 4 (A2) has to be in the fixture, with
# one substitution: MCELLBI 32 has no course in the Spring 2026 index (PR #11), so the table's
# "molecular and cell biology 32" is asked as "molecular and cell biology 104", a course in both terms.
REQUIRED_QUERIES = (
    "computer science 61a", "Computer Science 61A", "mechanical engineering 40", "molecular and cell biology 104",
    "cs 61 a", "cs61 a", "berkeley cs61a", "cs61a discussion", "cs61a spring 2027", "uc berkeley data 8", "61a",
    "compsi 61a", "phsyics 7a", "econimics 1", "staistics 20", "cs 61x", "physics 999", "asdf", "", "data 8", "data c8", "stat c8",
)


def fixture_rows() -> list[dict[str, str]]:
    import csv

    with QUERIES.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_course_query_fixture_covers_the_table_and_the_misses() -> None:
    """The fixture is the requirement written down: about 150 rows, every row of the plan's table, 20 or more misses."""
    rows = fixture_rows()
    assert 140 <= len(rows) <= 190, len(rows)
    assert '"' not in QUERIES.read_text(), "the fixture is plain CSV; a quoted field would need a real parser in both runners"
    queries = [r["query"] for r in rows]
    assert len(queries) == len(set(queries)), sorted(q for q in queries if queries.count(q) > 1)
    for query in REQUIRED_QUERIES:
        assert query in queries, query
    misses = [r for r in rows if r["expected_layer"] == "miss"]
    assert len(misses) >= 20, len(misses)
    assert all(r["expected_key"] == "" for r in misses)
    assert all(r["expected_key"] for r in rows if r["expected_layer"] != "miss")
    layers = {r["expected_layer"] for r in rows}
    out = render(SITE, expression="BWO.LAYERS")  # the fixture's vocabulary is the matcher's, not a copy of it
    assert out["eval"] and layers == set(out["eval"]), (sorted(layers), out["eval"])


def test_course_query_fixture_passes_in_the_node_runner_and_here() -> None:
    """One fixture, both runners: tests/site/queries.mjs drives the matcher through the harness and this reads its rows."""
    proc = subprocess.run([str(NODE), str(RUNNER)], capture_output=True, text=True, timeout=120, check=False)
    assert proc.stdout, proc.stderr
    report = json.loads(proc.stdout)
    assert report["failures"] == [], "\n".join(report["failures"])
    assert proc.returncode == 0, proc.stderr
    rows = fixture_rows()
    assert len(report["rows"]) == len(rows)
    for row, got in zip(rows, report["rows"], strict=True):
        want = None if row["expected_layer"] == "miss" else row["expected_key"]
        if want == "*":  # the key is whatever the joins ranking puts first; this row is about the layer
            assert got["key"], f"{row['query']!r}: wanted a course, got nothing"
        else:
            assert got["key"] == want, f"{row['query']!r}: wanted {want!r}, got {got['key']!r}"
        assert got["layer"] == row["expected_layer"], f"{row['query']!r}: wanted layer {row['expected_layer']}, got {got['layer']}"
        if row["expected_layer"] == "miss":
            assert len(got["nearest"]) <= 3, f"{row['query']!r}: {got['nearest']}"


# Item 13: what each of the fixture's misses offers, by subject (the keys are the joins ranking's, which a
# refresh may reorder). The subject understood, a prefix the combobox would complete, or a subject within the
# fuzzy rule's distance; nothing at all when none of those finds a course, never the most-joined three.
MISS_OFFERS = {
    "cs 61x": "COMPSCI", "compsci 9999": "COMPSCI", "computer science 9999": "COMPSCI", "physics 999": "PHYSICS",
    "math 9999": "MATH", "mathematics 9999": "MATH", "stat 61a": "STAT", "data 61a": "DATA", "econ 999": "ECON",
    "chem 1z": "CHEM", "data": "DATA",  # a subject alone: its courses (docs/DESIGN_A6.md, the title layer)
    "compsi 999": "COMPSCI",  # a typo in the subject, a number that is no course: the fuzzy rule's subject
    "comp 61": "COMPSCI",  # a prefix: what the combobox suggested while it was typed
    "asdf": None, "": None, "zzz 1": None, "qqqq 12": None, "!!!": None, "123456": None, "nope 1": None, "xyz 100": None,
    "berkeley 12345": None, "uc berkeley": None, "lecture": None, "spring 2027": None, "0000": None, "cs 61a1": None,
    "business administration 135": None, "quantum basketweaving": None, "data structures 2": None, "and": None,
}


def test_a_miss_offers_only_what_is_close(full_site: Path) -> None:
    """No match: up to three courses close to the query, or none; where the subject is unambiguous the offers come from it."""
    queries = list(MISS_OFFERS)
    out = render(SITE, expression=f"{json.dumps(queries)}.map((t) => {{ const m = BWO.matchCourse(BWO.loaded.index, t); return [m.layer, m.nearest.map((r) => r.key)]; }})")
    assert "eval_error" not in out, out.get("eval_error")
    for query, (layer, keys) in zip(queries, out["eval"], strict=True):
        subject = MISS_OFFERS[query]
        assert layer == "miss", query
        if subject is None:
            assert keys == [], (query, keys)
        else:
            assert 1 <= len(keys) <= 3 and all(k.startswith(subject + " ") for k in keys), (query, keys)
    out = render(SITE, expression="BWO.matchCourse(BWO.loaded.index, 'comp 61').nearest.map((r) => r.key)")
    assert all(k.startswith("COMPSCI 61") for k in out["eval"]), out["eval"]
    # a hit offers nothing: nearest is only for the no-match message
    out = render(SITE, expression="BWO.matchCourse(BWO.loaded.index, 'cs61a').nearest.length")
    assert out["eval"] == 0
    # the page prints them under its own no-match message, and prints none when there are none
    out = render(full_site, course="compsi 101", position="4")
    assert "Did you mean <a" in out["result"] and "COMPSCI" in out["result"]
    out = render(full_site, course="NOPE 101", position="4")
    assert "Did you mean" not in out["result"]


def test_a_bare_number_ranks_by_joins(full_site: Path) -> None:
    """Q2: "7a" is a ranked list, most-joined first, and the lookup uses the first item.

    Pinned to a hand-made index rather than the committed export: the ranking is
    data, and a refresh may reorder two close courses without anything being wrong.
    """
    out = render(full_site, expression="(function(){ const i = {courses: ["
        "{key: 'HISTORY 7A', subject: 'HISTORY', number: '7A', joins: 348, buckets: {}},"
        "{key: 'PHYSICS 7A', subject: 'PHYSICS', number: '7A', joins: 288, buckets: {}},"
        "{key: 'DATA C8', subject: 'DATA', number: 'C8', joins: 5, buckets: {}},"
        "{key: 'ART 8', subject: 'ART', number: '8', joins: 1, buckets: {}}]};"
        " const m = BWO.matchCourse(i, '7a');"
        " return [m.key, m.layer, m.ranked.map((r) => r.key), BWO.matchCourse(i, '8').key]; })()")
    key, layer, ranked, eight = out["eval"]
    assert key == "HISTORY 7A" and layer == "bare"
    assert ranked == ["HISTORY 7A", "PHYSICS 7A"]
    assert eight == "DATA C8"  # a bare number tries the cross-listed C form too


def test_the_matcher_survives_a_half_loaded_index(full_site: Path) -> None:
    """findCourse returns null rather than throwing before index.json has arrived."""
    out = render(full_site, expression="[BWO.findCourse({}, 'cs61a'), BWO.findCourse({}, 'asdf'), BWO.findCourse(null, 'cs61a'), BWO.matchCourse({}, 'cs61a').layer, BWO.matchCourse({}, 'cs61a').nearest.length]")
    assert "eval_error" not in out, out.get("eval_error")
    assert out["eval"] == [None, None, None, "miss", 0]


def test_a_fuzzy_match_says_what_it_showed(full_site: Path) -> None:
    """Q5: 'Showing COMPSCI 61A for compsi 61a' whenever a typo in the subject was forgiven, and never otherwise."""
    out = render(SITE, expression="[BWO.showingHtml(BWO.matchCourse(BWO.loaded.index, 'compsi 61a')), BWO.showingHtml(BWO.matchCourse(BWO.loaded.index, 'cs 61a'))]")
    fuzzy, plain = out["eval"]
    assert "Showing <strong>COMPSCI 61A</strong> for <em>compsi 61a</em>" in fuzzy
    assert plain == ""
    # the lookup puts the line under the page's status line, which it leaves alone
    out = render(full_site, course="compsi 0", position="3")
    assert "Showing <strong>COMPSCI 0</strong> for <em>compsi 0</em>" in out["elements"]["showing"]["html"] and "Showing" not in out["status"]
    out = render(full_site, course="cs 0", position="3")
    assert out["elements"]["showing"]["html"] == "" and "Showing" not in out["status"]


TITLES = ROOT / "tests" / "fixtures" / "titles_sample.json"
WITH_TITLES = {"HARNESS_TITLES_FILE": str(TITLES)}


def title_fetches(out: dict) -> int:
    return sum(1 for url in out["fetches"] if url == "data/titles.json")


def test_titles_load_only_for_a_title_query_and_only_once() -> None:
    """Q4: a code query, a digit, a bare subject, stop words alone and the combobox never fetch titles.json; the first title query fetches it once."""
    out = render(SITE, env=WITH_TITLES, expression="""(async () => {
        const i = BWO.loaded.index, n = () => __fetches.filter((u) => u === 'data/titles.json').length, seen = [];
        for (const q of ['cs61a', 'compsi 61a', 'data structures 2', 'data', 'computer science', 'lecture', 'cs 61x', 'and', 'the', 'of the', 'the data']) { await BWO.matchCourseAsync(i, q); }
        seen.push(n());
        BWO.searchCourses(i, 'data structures', 8); BWO.searchCourses(i, 'hilfinger', 8); BWO.matchCourse(i, 'data structures');
        seen.push(n());
        const m = await BWO.matchCourseAsync(i, 'data structures');
        seen.push(m.key, m.layer, n());
        await BWO.matchCourseAsync(i, 'hilfinger'); await BWO.matchCourseAsync(i, 'quantum basketweaving');
        seen.push(n());
        return seen; })()""")
    assert "eval_error" not in out, out.get("eval_error")
    assert out["eval"] == [0, 0, "COMPSCI 61B", "title", 1, 1]
    # the page's own load fetches nothing of it either, and neither does a code lookup
    out = render(SITE, env=WITH_TITLES, course="cs61a", position="10")
    assert "COMPSCI 61A" in out["result"] and title_fetches(out) == 0


def test_title_hits_are_whole_tokens_ranked_by_joins() -> None:
    """Every query word a whole word of the title, or of one instructor's name including the surname; ties by joins."""
    rows = ", ".join(
        f"{{key: '{k}', subject: '{k.split()[0]}', number: '{k.split()[1]}', joins: {j}, buckets: {{}}}}"
        for k, j in (("COMPSCI 61A", 5), ("DATA C8", 9), ("STAT 20", 1), ("ECON 1", 7), ("ASTRON 11", 3), ("COMPSCI 61B", 2))
    )
    queries = ["denero", "john denero", "introduction", "Data Structures", "berkeley data structures", "structure", "john", "intro", "yokota hilfinger", "business communication"]
    out = render(SITE, env=WITH_TITLES, expression=f"""(async () => {{ const i = {{courses: [{rows}]}}; const out = [];
        for (const q of {json.dumps(queries)}) {{ const m = await BWO.matchCourseAsync(i, q); out.push([m.layer, m.ranked.map((r) => r.key)]); }}
        return out; }})()""")
    assert "eval_error" not in out, out.get("eval_error")
    got = dict(zip(queries, out["eval"], strict=True))
    assert got["denero"] == ["title", ["DATA C8", "COMPSCI 61A"]]  # one instructor, two courses: most-joined first
    assert got["john denero"] == got["denero"]
    assert got["introduction"] == ["title", ["ECON 1", "ASTRON 11", "STAT 20"]]
    assert got["Data Structures"] == ["title", ["COMPSCI 61B"]] and got["berkeley data structures"] == ["title", ["COMPSCI 61B"]]
    assert got["structure"] == ["title", ["COMPSCI 61A"]]  # "Structures" is another word: whole tokens only
    for query in ("john", "intro", "yokota hilfinger", "business communication"):  # a first name, a prefix, two people, a course not in this index
        assert got[query] == ["miss", []], query


def test_a_title_query_works_end_to_end_and_says_what_it_showed() -> None:
    """The lookup form and the course page's ?c= take the async path; both print the Showing line for a title hit."""
    out = render(SITE, env=WITH_TITLES, course="data structures", position="10")
    assert "Showing <strong>COMPSCI 61B</strong> for <em>data structures</em>." in out["elements"]["showing"]["html"]
    assert "COMPSCI 61B · position 10" in out["result"] and title_fetches(out) == 1
    out = render(SITE, page="course.html", search="?c=hilfinger", env=WITH_TITLES)
    assert "Showing <strong>COMPSCI 61B</strong> for <em>hilfinger</em>." in out["status"] and out["title"].startswith("COMPSCI 61B")


def test_the_title_layer_is_skipped_silently_without_titles(tmp_path: Path) -> None:
    """No titles_file in meta, a missing file or a broken one: a title query is an ordinary miss, fetched at most once."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    expression = "(async () => { const i = BWO.loaded.index; const a = await BWO.matchCourseAsync(i, 'data structures'); const b = await BWO.matchCourseAsync(i, 'hilfinger'); return [a.layer, b.layer, a.nearest.map((r) => r.key)]; })()"
    for env, fetched in (({}, 0), ({"HARNESS_TITLES_FILE": str(tmp_path / "absent.json")}, 1), ({"HARNESS_TITLES_FILE": str(broken)}, 1)):
        out = render(SITE, env=env, expression=expression)
        assert "eval_error" not in out, (env, out.get("eval_error"))
        assert out["eval"] == ["miss", "miss", []], env  # nothing in it names a subject: no "Did you mean" (item 13)
        assert title_fetches(out) == fetched, (env, out["fetches"])


def test_every_subject_has_a_display_name() -> None:
    """Q1: config/subject_names.json names every subject in index.json.

    The file covers the Fall 2026 and the Spring 2026 index (the site switches
    terms by swapping site/data), so this holds on either. The Academic Guide's
    index does not list three of the subjects (DISSTD, MBN, QTP). DISSTD is in
    the index the site ships, so its name is typed into the generator's MANUAL
    map (audit item 21: the department list showed "DISSTD" among full names);
    MBN and QTP, which only the Fall 2026 index has, are written blank and
    listed under "_todo". Every subject of the shipped index is named, and the
    40 most-joined are named in both terms.
    """
    names = json.loads((ROOT / "config" / "subject_names.json").read_text())
    index = json.loads((SITE / "data" / "index.json").read_text())
    assert names["_source"].startswith("https://") and "classes.berkeley.edu" not in names["_source"]
    assert names["_fetched"]
    joins: dict[str, int] = {}
    for row in index["courses"]:
        joins[row["subject"]] = joins.get(row["subject"], 0) + (row["joins"] or 0)
    assert set(joins) <= set(names["names"]), sorted(set(joins) - set(names["names"]))
    blank = sorted(code for code, name in names["names"].items() if not name)
    assert blank == sorted(names["_todo"]), (blank, names["_todo"])
    top40 = sorted(joins, key=lambda s: (-joins[s], s))[:40]
    assert [s for s in top40 if not names["names"][s]] == []
    assert sorted(s for s in joins if not names["names"][s]) == []  # item 21: none of the shipped index's subjects is a bare code
    assert names["names"]["DISSTD"] == "Disability Studies" and "DISSTD" not in names["_todo"]
    # the hand-written nicknames are a separate file, so regenerating never clobbers them
    nicknames = json.loads((ROOT / "config" / "course_nicknames.json").read_text())["nicknames"]
    assert nicknames["E7"] == "ENGIN 7" and nicknames["DATA 8"] == "DATA C8" and nicknames["HAAS"] == "UGBA"


def test_site_js_carries_the_generated_names() -> None:
    """The site ships only site/, so the two config files travel in site.js; the generator keeps them in step."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "subject_names.py"), "--check"],
        capture_output=True, text=True, timeout=60, check=False, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    names = json.loads((ROOT / "config" / "subject_names.json").read_text())
    out = render(SITE, expression="[BWO.SUBJECT_NAMES['COMPSCI'], BWO.SUBJECT_NAMES['MCELLBI'], Object.keys(BWO.SUBJECT_NAMES).length, Object.keys(BWO.COURSE_NICKNAMES).length]")
    compsci, mcellbi, named, nicknames = out["eval"]
    assert compsci == names["names"]["COMPSCI"] and mcellbi == names["names"]["MCELLBI"]
    assert named == len([n for n in names["names"].values() if n]) and nicknames == 5
    # the Guide's "X, Y" names are stored in reading order, and their Guide spelling travels too
    assert names["names"]["HISTART"] == "History of Art" and names["aliases"]["HISTART"] == "Art, History of"
    assert names["names"]["THEATER"] == "Theater, Dance, and Performance Studies" and "THEATER" not in names["aliases"]
    aliases = render(SITE, expression="BWO.SUBJECT_NAME_ALIASES")["eval"]
    assert aliases == names["aliases"]


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
    assert f"<p><strong>{pct(at_deadline[0])}</strong> of comparable students" in html and "position 3 (positions 1 to 5)" in html and "is 27 days, so at least" in html
    # one section: the verdict leads, then the cases, then the share
    assert html.index('<p class="lead"><span class="verdict">Too little data to call</span>') < html.index("<dt>Cases</dt>") < html.index("got in within") < html.index('class="muted small ladder"')
    assert html.count('class="curve') == len([b for b in ("1-5", "6-15", "16-40", "41+") if b in load(course_site, "courses/COMPSCI.json")["courses"]["COMPSCI 0"]["buckets"]])
    assert 'class="curve s1 you"' in html and "Show as table" in html and 'class="legend"' in html
    assert "Every position" in html and '<th scope="row">positions 1 to 5 <span class="tag">you</span>' in html and "Other COMPSCI courses" in html
    assert "index.html?course=COMPSCI%200&position=3" in html
    assert out["elements"].get("live", {"html": ""})["html"] == ""  # no live file: the block stays hidden, no error


RELATED_HEAD = "<h2>Other COMPSCI courses at positions 6 to 15</h2>"


def test_course_page_says_what_its_related_list_is(course_site: Path, tmp_path: Path) -> None:
    """Item 20: the related list is the most-joined of the subject's other courses with their own or the
    department's curve at the bucket (one on the all-course pool would print that pool's number), and the
    page says how many there are, so five of fourteen does not read as the whole subject."""
    index = load(course_site, "index.json")
    others = [r for r in index["courses"] if r["subject"] == "COMPSCI" and r["key"] != "COMPSCI 0" and r["buckets"].get("6-15", {}).get("pooled", "all") != "all"]
    assert len(others) > 5
    html = render(course_site, page="course.html", search="?c=cs0&position=10")["elements"]["course"]["html"]
    assert (f"{RELATED_HEAD}<p class=\"muted small\">The 5 most-joined of the {len(others)} other COMPSCI courses with their own or the department's curve "
            "at these positions.</p>") in html
    assert html.split(RELATED_HEAD)[1].split("</ul>")[0].count("<li>") == 5
    # every one shown: the sentence says so
    root = tmp_path / "site"
    shutil.copytree(course_site, root)
    keep = {"COMPSCI 0", others[0]["key"], others[1]["key"]}
    trimmed = {**index, "courses": [r for r in index["courses"] if r["subject"] != "COMPSCI" or r["key"] in keep]}
    (root / "data" / "index.json").write_text(json.dumps(trimmed))
    html = render(root, page="course.html", search="?c=cs0&position=10")["elements"]["course"]["html"]
    assert f"{RELATED_HEAD}<p class=\"muted small\">Every other COMPSCI course with its own or the department's curve at these positions, most-joined first.</p>" in html
    assert html.split(RELATED_HEAD)[1].split("</ul>")[0].count("<li>") == 2


def test_course_page_says_which_course_a_forgiven_query_showed() -> None:
    """Q5 on the course page: a fuzzy, name or nickname match prints the lookup's "Showing X for query" line; an exact key does not."""
    for query, key in (("compsi%2061a", "COMPSCI 61A"), ("computer%20science%2061a", "COMPSCI 61A"), ("e7", "ENGIN 7")):
        out = render(SITE, page="course.html", search=f"?c={query}")
        assert f'Showing <strong>{key}</strong> for <em>{unquote(query)}</em>.' in out["status"], (query, out["status"])
        assert out["title"].startswith(key)
    for query in ("COMPSCI%2061A", "cs61a"):  # exact, and an alias: nothing was forgiven
        out = render(SITE, page="course.html", search=f"?c={query}")
        assert "Showing" not in out["status"] and out["title"].startswith("COMPSCI 61A"), (query, out["status"])


def test_course_page_without_a_course(full_site: Path) -> None:
    out = render(full_site, page="course.html", search="?c=NOPE%201")
    # the sentence is true of what the lookup shows (item 13): close matches when there are any, none otherwise
    assert out["status"] == (f'<p class="error">No data for <strong>NOPE 1</strong>. {NO_DATA}</p>'
                             '<p><a href="index.html?course=NOPE%201&position=10&today=2027-01-10">Try the lookup</a>, which suggests courses close to what you typed when there are any, '
                             'or browse <a href="courses.html?today=2027-01-10">every course</a>.</p>')
    assert "falls back to the department" not in out["status"]  # the lookup gives a code it cannot find no estimate either
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
    assert ("Where a mid-list spot moved most" in html) == (len([r for r in load(full_site, "index.json")["courses"] if r["buckets"].get("6-15", {}).get("pooled") is False and r["buckets"]["6-15"]["sections"] >= 3]) >= 6)


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


# The pre-registration (the Accuracy box, the About data status) in both regimes.
# Today meta.json carries the Spring 2026 Berkeleytime cohort with prereg_commit
# 7f348ed and prereg_date 2026-09-21. A deliberate own-data publish (PR #46) drops
# those fields, since they describe another cohort: the pages then state the
# pre-registration from BWO.PREREG and say the curves shown are not part of it.
# A Berkeleytime meta without the fields (`make site-data SITE_TERM=2268` carries
# nothing across terms) gets the record but no such clause: Fall 2026's cohort is
# frozen for the test too (a7240f4).
REGIMES = {
    "today": {"term_id": "2262", "term_name": "Spring 2026", "data_source": "berkeleytime_history", "prereg_commit": "7f348ed", "prereg_date": "2026-09-21"},
    "own_data": {"term_id": "2272", "term_name": "Spring 2027", "data_source": "own_snapshots"},
    "berkeleytime_without_fields": {"term_id": "2268", "term_name": "Fall 2026", "data_source": "berkeleytime_history"},
}
# The same two metas next to a backtest of this project's own snapshots: the Accuracy status
# line labels the runs Berkeleytime's when either file is (BWO.isBerkeleytime(bt) || ...(meta)).
OWN_BACKTEST = {"today_own_backtest": "today", "own_data_own_backtest": "own_data"}
REGIMES.update({name: REGIMES[base] for name, base in OWN_BACKTEST.items()})


def regime_site(site_root: Path, tmp_path: Path, regime: str) -> Path:
    """The export's meta.json with the regime's term, source and pre-registration fields, next to a Fall 2026 backtest with a cross-term run
    (from Berkeleytime's history, or from this project's own snapshots for an OWN_BACKTEST regime)."""
    from tests.test_export_backtest import make_reports
    from analysis.export_backtest import export_backtest

    root = tmp_path / regime
    (root / "data").mkdir(parents=True)
    meta = {k: v for k, v in load(site_root, "meta.json").items() if k not in ("prereg_commit", "prereg_date")}
    meta.update(REGIMES[regime], forecast_term_id="2272", forecast_term_name="Spring 2027")
    (root / "data" / "meta.json").write_text(json.dumps(meta))
    reports = make_reports(tmp_path)
    shutil.copytree(reports / "temporal_days14", reports / "cross_term_days14")  # the real file has cross-term runs too
    export_backtest(reports, root / "data" / "backtest.json", term_id="2268", term_name="Fall 2026", meta={"data_source": "own_snapshots" if regime in OWN_BACKTEST else "berkeleytime_history"})
    return root


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_the_preregistration_is_true_in_both_regimes(full_site: Path, tmp_path: Path, regime: str) -> None:
    root = regime_site(full_site, tmp_path, regime)
    acc = render(root, page="accuracy.html")
    box = acc["elements"]["prereg"]["html"]
    about = render(root, page="about.html")["elements"]["data-status"]["html"]
    for html in (box, about):
        assert "Spring 2026 cohort" in html and "<code>7f348ed</code> on 2026-09-21" in html, html
        assert "will be frozen" not in html and "Spring 2027 cohort" not in html
    page = " ".join(el["html"] for el in acc["elements"].values())
    if regime == "today":
        assert ("The Spring 2026 cohort behind the curves this site shows was frozen at commit <code>7f348ed</code> on 2026-09-21; the curves are read from it unchanged. "
                "After Spring 2027's add/drop deadline (Feb 10, 2027) they will be scored, unchanged,") in box
        assert "The Spring 2026 cohort behind the curves was frozen at commit <code>7f348ed</code> on 2026-09-21 for the Spring 2027 test." in about
        assert 'The runs headed "Fit on Spring 2026, scored on Fall 2026" score the curves the pages show' in acc["status"]
    elif regime == "own_data":
        assert ("The Spring 2026 cohort from Berkeleytime's public history was frozen for this test at commit <code>7f348ed</code> on 2026-09-21; "
                "the curves this site shows now (Spring 2027, this project's own snapshots) are not part of the test. "
                "After Spring 2027's add/drop deadline (Feb 10, 2027) the frozen curves will be scored, unchanged,") in box
        assert "The Spring 2026 cohort from Berkeleytime's public history was frozen at commit <code>7f348ed</code> on 2026-09-21 for the Spring 2027 test; the curves this site shows now are not part of it." in about
        assert "<strong>Spring 2027</strong>, this project's own snapshots" in about
        assert "Fit on Spring 2027" not in page and "score the curves the pages show" not in page  # no such run exists
        assert "<p>The pages show Spring 2027 curves from this project's own snapshots; these runs test the same method on Fall 2026, not those curves.</p>" in acc["status"]
        assert "Fall 2026</strong>, from Berkeleytime's public history: 2 backtest runs" in acc["status"]  # the backtest keeps its own label
        assert "Fit on Spring 2026, scored on Fall 2026, within 14 days" in page  # the run itself is still shown, under its own heading
    elif regime == "berkeleytime_without_fields":
        assert ("The Spring 2026 cohort from Berkeleytime's public history was frozen for this test at commit <code>7f348ed</code> on 2026-09-21. "
                "After Spring 2027's add/drop deadline (Feb 10, 2027) the frozen curves will be scored, unchanged,") in box
        assert "The Spring 2026 cohort from Berkeleytime's public history was frozen at commit <code>7f348ed</code> on 2026-09-21 for the Spring 2027 test." in about
        for html in (box, about):
            assert "not part of" not in html  # Fall 2026 is frozen for the test as well
        assert "The pages show" not in acc["status"]  # the backtest is of the same term


def test_the_preregistration_record_matches_the_committed_meta() -> None:
    """BWO.PREREG says what site/data/meta.json says while that file carries the fields, so the two cannot drift apart."""
    meta = load(SITE, "meta.json")
    record = render(SITE, page="about.html", expression="BWO.PREREG")["eval"]
    assert sorted(record) == ["commit", "date", "scored_after", "term_name"]
    if meta.get("prereg_commit"):  # gone after an own-data publish, which is when the record is used
        assert (record["term_name"], record["commit"], record["date"]) == (meta["term_name"], str(meta["prereg_commit"])[:10], meta["prereg_date"])
    if meta.get("forecast_term_id") == "2272":
        assert record["scored_after"] == meta["add_drop_deadline"]  # Spring 2027's add/drop deadline


def test_the_preregistration_without_meta(tmp_path: Path) -> None:
    """No meta.json at all (the empty state): the box still names the frozen cohort, and no term it does not have."""
    (tmp_path / "data").mkdir()
    box = render(tmp_path, page="accuracy.html")["elements"]["prereg"]["html"]
    assert "The Spring 2026 cohort from Berkeleytime's public history was frozen for this test at commit <code>7f348ed</code> on 2026-09-21. After" in box, box
    assert "undefined" not in box and "this site shows now" not in box


# Every string a page prints after asking which source the curves come from
# (BWO.isBerkeleytime), byte for byte in each regime, with the counts and dates fixed at
# today's site/data/meta.json and backtest.json and the clock in UTC. The OWN_BACKTEST regimes guard both
# operands of the Accuracy label: Berkeleytime meta with an own backtest keeps it, own and own drops it.
TODAY_COUNTS = {"courses": 2114, "sections": 2902, "cohort_rows": 531568, "events": 299826, "generated_at": "2026-09-24T08:03:05+00:00", "join_window": ["2025-10-27T00:01:10+00:00", "2026-05-15T13:23:04+00:00"]}
SOURCE_STRINGS: dict[str, dict[str, str]] = {
    "today": {
        "stamp": "Data through May 15, 2026, 1:23 PM; curves frozen Sep 21, 2026 (7f348ed). Horizons computed for 2027-01-10. Last automatic waitlist run Feb 5, 2027 (27 days away).",
        "source sentence": "<p><strong>Spring 2026</strong>, from Berkeleytime's public 15-minute enrollment history: 2,114 courses with estimates from 2,902 sections and 531,568 hypothetical joiners, 299,826 of whom cleared. Live Spring 2027 collection by this project begins with Phase 1 on Oct 26, 2026; the estimates switch to its own snapshots once Spring waitlists start clearing.</p>",
        "source label": "Spring 2026, from Berkeleytime's public history",
        "about": "<strong>Spring 2026</strong>, Berkeleytime's public history: 2,114 courses, 2,902 sections, 531,568 hypothetical joiners of whom 299,826 cleared. Data through May 15, 2026, 1:23 PM; files generated Sep 24, 2026, 8:03 AM. The Spring 2026 cohort behind the curves was frozen at commit <code>7f348ed</code> on 2026-09-21 for the Spring 2027 test.",
        "methods": "Showing: <strong>Spring 2026</strong>, from Berkeleytime's public history; 2,114 courses, 2,902 sections, 531,568 hypothetical joiners, 299,826 of whom got in. These joiners are overlapping copies, not separate students, placed at many positions of the same queues at every sampled moment, so the number of sections, not of joiners, is the better guide to how much data there is. Horizons on the pages count down to Spring 2027's dates.",
        "accuracy": "<p><strong>Fall 2026</strong>, from Berkeleytime's public history: 2 backtest runs, generated Sep 21, 2026, 2:22 AM.</p><p>The pages show Spring 2026 curves; these tests were run on Fall 2026. The runs headed \"Fit on Spring 2026, scored on Fall 2026\" score the curves the pages show; the others test the same method within Fall 2026.</p>",
        "prereg": "<h2>Pre-registered: the Spring 2027 test</h2><div class=\"prereg\"><p>The Spring 2026 cohort behind the curves this site shows was frozen at commit <code>7f348ed</code> on 2026-09-21; the curves are read from it unchanged. After Spring 2027's add/drop deadline (Feb 10, 2027) they will be scored, unchanged, against every Spring 2027 joiner this project's own snapshots recorded: Brier score, AUC and gain over the position-only baseline at 14 days, 28 days, the first day of instruction and the last automatic waitlist run, with the same observability rule and section bootstrap as above. The result goes on this page whatever it says.</p></div>",
    },
    "own_data": {
        "stamp": "Data through May 15, 2026, 1:23 PM; page generated Sep 24, 2026, 8:03 AM. Horizons computed for 2027-01-10. Last automatic waitlist run Feb 5, 2027 (27 days away).",
        "source sentence": "<p><strong>Spring 2027</strong>: 2,114 courses with estimates from 2,902 sections and 531,568 hypothetical joiners, 299,826 of whom cleared.</p>",
        "source label": "Spring 2027, this project's own snapshots",
        "about": "<strong>Spring 2027</strong>, this project's own snapshots: 2,114 courses, 2,902 sections, 531,568 hypothetical joiners of whom 299,826 cleared. Data through May 15, 2026, 1:23 PM; files generated Sep 24, 2026, 8:03 AM. The Spring 2026 cohort from Berkeleytime's public history was frozen at commit <code>7f348ed</code> on 2026-09-21 for the Spring 2027 test; the curves this site shows now are not part of it.",
        "methods": "Showing: <strong>Spring 2027</strong>, this project's own snapshots; 2,114 courses, 2,902 sections, 531,568 hypothetical joiners, 299,826 of whom got in. These joiners are overlapping copies, not separate students, placed at many positions of the same queues at every sampled moment, so the number of sections, not of joiners, is the better guide to how much data there is. Horizons on the pages count down to Spring 2027's dates.",
        "accuracy": "<p><strong>Fall 2026</strong>, from Berkeleytime's public history: 2 backtest runs, generated Sep 21, 2026, 2:22 AM.</p><p>The pages show Spring 2027 curves from this project's own snapshots; these runs test the same method on Fall 2026, not those curves.</p>",
        "prereg": "<h2>Pre-registered: the Spring 2027 test</h2><div class=\"prereg\"><p>The Spring 2026 cohort from Berkeleytime's public history was frozen for this test at commit <code>7f348ed</code> on 2026-09-21; the curves this site shows now (Spring 2027, this project's own snapshots) are not part of the test. After Spring 2027's add/drop deadline (Feb 10, 2027) the frozen curves will be scored, unchanged, against every Spring 2027 joiner this project's own snapshots recorded: Brier score, AUC and gain over the position-only baseline at 14 days, 28 days, the first day of instruction and the last automatic waitlist run, with the same observability rule and section bootstrap as above. The result goes on this page whatever it says.</p></div>",
    },
    "berkeleytime_without_fields": {
        "stamp": "Data through May 15, 2026, 1:23 PM; page generated Sep 24, 2026, 8:03 AM. Horizons computed for 2027-01-10. Last automatic waitlist run Feb 5, 2027 (27 days away).",
        "source sentence": "<p><strong>Fall 2026</strong>, from Berkeleytime's public 15-minute enrollment history: 2,114 courses with estimates from 2,902 sections and 531,568 hypothetical joiners, 299,826 of whom cleared. Live Spring 2027 collection by this project begins with Phase 1 on Oct 26, 2026; the estimates switch to its own snapshots once Spring waitlists start clearing.</p>",
        "source label": "Fall 2026, from Berkeleytime's public history",
        "about": "<strong>Fall 2026</strong>, Berkeleytime's public history: 2,114 courses, 2,902 sections, 531,568 hypothetical joiners of whom 299,826 cleared. Data through May 15, 2026, 1:23 PM; files generated Sep 24, 2026, 8:03 AM. The Spring 2026 cohort from Berkeleytime's public history was frozen at commit <code>7f348ed</code> on 2026-09-21 for the Spring 2027 test.",
        "methods": "Showing: <strong>Fall 2026</strong>, from Berkeleytime's public history; 2,114 courses, 2,902 sections, 531,568 hypothetical joiners, 299,826 of whom got in. These joiners are overlapping copies, not separate students, placed at many positions of the same queues at every sampled moment, so the number of sections, not of joiners, is the better guide to how much data there is. Horizons on the pages count down to Spring 2027's dates.",
        "accuracy": "<p><strong>Fall 2026</strong>, from Berkeleytime's public history: 2 backtest runs, generated Sep 21, 2026, 2:22 AM.</p>",
        "prereg": "<h2>Pre-registered: the Spring 2027 test</h2><div class=\"prereg\"><p>The Spring 2026 cohort from Berkeleytime's public history was frozen for this test at commit <code>7f348ed</code> on 2026-09-21. After Spring 2027's add/drop deadline (Feb 10, 2027) the frozen curves will be scored, unchanged, against every Spring 2027 joiner this project's own snapshots recorded: Brier score, AUC and gain over the position-only baseline at 14 days, 28 days, the first day of instruction and the last automatic waitlist run, with the same observability rule and section bootstrap as above. The result goes on this page whatever it says.</p></div>",
    },
    "today_own_backtest": {
        "stamp": "Data through May 15, 2026, 1:23 PM; curves frozen Sep 21, 2026 (7f348ed). Horizons computed for 2027-01-10. Last automatic waitlist run Feb 5, 2027 (27 days away).",
        "source sentence": "<p><strong>Spring 2026</strong>, from Berkeleytime's public 15-minute enrollment history: 2,114 courses with estimates from 2,902 sections and 531,568 hypothetical joiners, 299,826 of whom cleared. Live Spring 2027 collection by this project begins with Phase 1 on Oct 26, 2026; the estimates switch to its own snapshots once Spring waitlists start clearing.</p>",
        "source label": "Spring 2026, from Berkeleytime's public history",
        "about": "<strong>Spring 2026</strong>, Berkeleytime's public history: 2,114 courses, 2,902 sections, 531,568 hypothetical joiners of whom 299,826 cleared. Data through May 15, 2026, 1:23 PM; files generated Sep 24, 2026, 8:03 AM. The Spring 2026 cohort behind the curves was frozen at commit <code>7f348ed</code> on 2026-09-21 for the Spring 2027 test.",
        "methods": "Showing: <strong>Spring 2026</strong>, from Berkeleytime's public history; 2,114 courses, 2,902 sections, 531,568 hypothetical joiners, 299,826 of whom got in. These joiners are overlapping copies, not separate students, placed at many positions of the same queues at every sampled moment, so the number of sections, not of joiners, is the better guide to how much data there is. Horizons on the pages count down to Spring 2027's dates.",
        "accuracy": "<p><strong>Fall 2026</strong>, from Berkeleytime's public history: 2 backtest runs, generated Sep 21, 2026, 2:22 AM.</p><p>The pages show Spring 2026 curves; these tests were run on Fall 2026. The runs headed \"Fit on Spring 2026, scored on Fall 2026\" score the curves the pages show; the others test the same method within Fall 2026.</p>",
        "prereg": "<h2>Pre-registered: the Spring 2027 test</h2><div class=\"prereg\"><p>The Spring 2026 cohort behind the curves this site shows was frozen at commit <code>7f348ed</code> on 2026-09-21; the curves are read from it unchanged. After Spring 2027's add/drop deadline (Feb 10, 2027) they will be scored, unchanged, against every Spring 2027 joiner this project's own snapshots recorded: Brier score, AUC and gain over the position-only baseline at 14 days, 28 days, the first day of instruction and the last automatic waitlist run, with the same observability rule and section bootstrap as above. The result goes on this page whatever it says.</p></div>",
    },
    "own_data_own_backtest": {
        "stamp": "Data through May 15, 2026, 1:23 PM; page generated Sep 24, 2026, 8:03 AM. Horizons computed for 2027-01-10. Last automatic waitlist run Feb 5, 2027 (27 days away).",
        "source sentence": "<p><strong>Spring 2027</strong>: 2,114 courses with estimates from 2,902 sections and 531,568 hypothetical joiners, 299,826 of whom cleared.</p>",
        "source label": "Spring 2027, this project's own snapshots",
        "about": "<strong>Spring 2027</strong>, this project's own snapshots: 2,114 courses, 2,902 sections, 531,568 hypothetical joiners of whom 299,826 cleared. Data through May 15, 2026, 1:23 PM; files generated Sep 24, 2026, 8:03 AM. The Spring 2026 cohort from Berkeleytime's public history was frozen at commit <code>7f348ed</code> on 2026-09-21 for the Spring 2027 test; the curves this site shows now are not part of it.",
        "methods": "Showing: <strong>Spring 2027</strong>, this project's own snapshots; 2,114 courses, 2,902 sections, 531,568 hypothetical joiners, 299,826 of whom got in. These joiners are overlapping copies, not separate students, placed at many positions of the same queues at every sampled moment, so the number of sections, not of joiners, is the better guide to how much data there is. Horizons on the pages count down to Spring 2027's dates.",
        "accuracy": "<p><strong>Fall 2026</strong>: 2 backtest runs, generated Sep 21, 2026, 2:22 AM.</p><p>The pages show Spring 2027 curves from this project's own snapshots; these runs test the same method on Fall 2026, not those curves.</p>",
        "prereg": "<h2>Pre-registered: the Spring 2027 test</h2><div class=\"prereg\"><p>The Spring 2026 cohort from Berkeleytime's public history was frozen for this test at commit <code>7f348ed</code> on 2026-09-21; the curves this site shows now (Spring 2027, this project's own snapshots) are not part of the test. After Spring 2027's add/drop deadline (Feb 10, 2027) the frozen curves will be scored, unchanged, against every Spring 2027 joiner this project's own snapshots recorded: Brier score, AUC and gain over the position-only baseline at 14 days, 28 days, the first day of instruction and the last automatic waitlist run, with the same observability rule and section bootstrap as above. The result goes on this page whatever it says.</p></div>",
    },
}


def source_strings(site_root: Path, tmp_path: Path, regime: str) -> dict[str, str]:
    root = regime_site(site_root, tmp_path, regime)
    shutil.copytree(site_root / "data", root / "data", dirs_exist_ok=True, ignore=shutil.ignore_patterns("meta.json", "backtest.json"))  # the lookup needs index.json to print its status line
    for name, changes in (("meta.json", TODAY_COUNTS), ("backtest.json", {"generated_at": "2026-09-21T02:22:27+00:00"})):
        path = root / "data" / name
        path.write_text(json.dumps({**json.loads(path.read_text()), **changes}))
    utc = {"TZ": "UTC"}
    lookup = render(root, expression="BWO.sourceLabel(BWO.loaded.meta)", env=utc)
    accuracy = render(root, page="accuracy.html", env=utc)
    return {
        "stamp": lookup["stamp"],  # BWO.stamp on every page: the frozen curves while meta carries prereg_*, else the generation time (audit item 14)
        "source sentence": lookup["status"],  # BWO.sourceHtml: Lookup, Courses, Course, Department, Insights
        "source label": lookup["eval"],  # BWO.sourceLabel: the lookup's small print, Course, Department, Insights, Accuracy
        "about": render(root, page="about.html", env=utc)["elements"]["data-status"]["html"],
        "methods": render(root, page="methodology.html", env=utc)["elements"]["data-status"]["html"],
        "accuracy": accuracy["status"],
        "prereg": accuracy["elements"]["prereg"]["html"],
    }


@pytest.mark.parametrize("regime", sorted(REGIMES))
def test_the_source_strings_are_pinned(full_site: Path, tmp_path: Path, regime: str) -> None:
    assert source_strings(full_site, tmp_path, regime) == SOURCE_STRINGS[regime]


# ------------------------------------------------ live data status (B2)
# BWO.liveStatus appends one sentence read from the data branch's status.json
# (served by the harness from HARNESS_STATUS_FILE; unset, the URL 404s).
STATUS_FIXTURE = ROOT / "tests" / "fixtures" / "status_sample.json"
STATUS_PAGES = {  # page -> (query, id of the element that carries the status line)
    "index.html": ("", "status"),
    "courses.html": ("", "status"),
    "course.html": ("?c=cs0&position=3", "status"),
    "insights.html": ("", "status"),
    "accuracy.html": ("", "status"),
    "about.html": ("", "data-status"),
    "methodology.html": ("", "data-status"),
}


def status_file(tmp_path: Path, minutes_ago: float, **changes: object) -> Path:
    """The fixture with last_run_at moved to ``minutes_ago`` before now (the page measures against the real clock)."""
    from datetime import datetime, timedelta, timezone

    status = json.loads(STATUS_FIXTURE.read_text())
    status["last_run_at"] = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    status.update(changes)
    path = tmp_path / f"status_{minutes_ago}.json"
    path.write_text(json.dumps(status))
    return path


def status_line(site_root: Path, page: str, status: Path | None) -> str:
    query, el = STATUS_PAGES[page]
    out = render(site_root, page=page, search=query, env={"HARNESS_STATUS_FILE": str(status)} if status else None)
    return out["elements"][el]["html"]


def test_status_fixture_has_the_fields_the_scraper_writes() -> None:
    assert sorted(json.loads(STATUS_FIXTURE.read_text())) == [
        "complete", "kind", "last_run_at", "missing_share", "n_missing", "n_observed", "n_written",
        "scope", "shard", "snapshot", "source", "sweep_seconds", "term_id", "version",
    ]


@pytest.mark.parametrize("page", sorted(STATUS_PAGES))
def test_live_status_sentence_follows_the_status_line(full_site: Path, tmp_path: Path, page: str) -> None:
    import re

    fixture = json.loads(STATUS_FIXTURE.read_text())
    before = status_line(full_site, page, None)
    after = status_line(full_site, page, status_file(tmp_path, 12))
    assert after.startswith(before) and after != before
    added = after[len(before):]
    sentence = f"This project's last Fall 2026 snapshot ran about 12 min ago: {fixture['n_observed']:,} sections read, {fixture['n_missing']:,} not reached."
    assert sentence == "This project's last Fall 2026 snapshot ran about 12 min ago: 1,425 sections read, 1 not reached."
    escaped = sentence.replace("'", "&#39;")  # the page escapes the sentence like every other text it prints
    assert re.search(r"This project&#39;s last Fall 2026 snapshot ran about \d+ min ago: ", added) and escaped in added
    # A <p> status line gets an inline span; a status region gets its own paragraph.
    assert added == (f' <span class="live-status">{escaped}</span>' if STATUS_PAGES[page][1] == "data-status" else f'<p class="muted small live-status">{escaped}</p>')


def test_live_status_older_than_90_minutes_is_in_hours(full_site: Path, tmp_path: Path) -> None:
    html = status_line(full_site, "index.html", status_file(tmp_path, 185, n_observed=1, n_missing=0))
    assert "This project&#39;s last Fall 2026 snapshot ran about 3 hours ago: 1 section read, 0 not reached." in html
    html = status_line(full_site, "about.html", status_file(tmp_path, 89))
    assert "This project&#39;s last Fall 2026 snapshot ran about 89 min ago: 1,425 sections read, 1 not reached." in html


@pytest.mark.parametrize(
    ("status", "now", "expected"),
    [
        ({"last_run_at": "2026-09-25T18:00:00+00:00", "n_observed": 12345, "n_missing": 2}, "2026-09-25T18:00:20Z", "This project's last snapshot ran about 1 min ago: 12,345 sections read, 2 not reached."),
        ({"last_run_at": "2026-09-25T18:00:00+00:00", "n_observed": 1, "n_missing": 1}, "2026-09-25T19:30:00Z", "This project's last snapshot ran about 90 min ago: 1 section read, 1 not reached."),
        ({"last_run_at": "2026-09-25T18:00:00+00:00", "n_observed": 0, "n_missing": 0}, "2026-09-25T19:31:00Z", "This project's last snapshot ran about 2 hours ago: 0 sections read, 0 not reached."),
        ({"last_run_at": "2026-09-25T18:00:00+00:00", "n_observed": 5, "n_missing": 0}, "2026-09-25T17:58:00Z", "This project's last snapshot ran about 1 min ago: 5 sections read, 0 not reached."),
        ({"last_run_at": "2026-09-25T18:00:00+00:00", "n_observed": 5, "n_missing": 0, "term_id": "2272"}, "2026-09-25T18:05:00Z", "This project's last Spring 2027 snapshot ran about 5 min ago: 5 sections read, 0 not reached."),
        ({"last_run_at": "2026-09-25T18:00:00+00:00", "n_observed": 5, "n_missing": 0, "term_id": "2265"}, "2026-09-25T18:05:00Z", "This project's last Summer 2026 snapshot ran about 5 min ago: 5 sections read, 0 not reached."),
        ({"last_run_at": "2026-09-25T18:00:00+00:00", "n_observed": 5, "n_missing": 0, "term_id": "9999"}, "2026-09-25T18:05:00Z", "This project's last snapshot ran about 5 min ago: 5 sections read, 0 not reached."),
        ({"n_observed": 5, "n_missing": 0}, "2026-09-25T18:00:00Z", None),
        ({"last_run_at": "not a date", "n_observed": 5, "n_missing": 0}, "2026-09-25T18:00:00Z", None),
        ({"last_run_at": "2026-09-25T18:00:00+00:00", "n_missing": 0}, "2026-09-25T18:10:00Z", None),
        (None, "2026-09-25T18:00:00Z", None),
    ],
)
def test_live_status_text(full_site: Path, status: dict | None, now: str, expected: str | None) -> None:
    out = render(full_site, page="about.html", today=None, expression=f"BWO.liveStatusText({json.dumps(status)}, Date.parse({json.dumps(now)}))")
    assert "eval_error" not in out, out.get("eval_error")
    assert out.get("eval") == expected


# Audit item 7: until the scraper switches, status.json is for an earlier term than the one the pages count down
# to, so the sentence says the forecast term's collection has not started and names the run's term in a clause.
# Berkeley term ids sort in time order (2268 Fall 2026 < 2272 Spring 2027); an id that is not one, or a run of a
# later term, gets the plain sentence, since no order can be read from it.
SPRING_2027 = {"forecast_term_id": "2272", "forecast_term_name": "Spring 2027"}
BEFORE_THE_SWITCH = [
    ("2268", SPRING_2027, "This project has not started collecting Spring 2027 yet; its last snapshot, of Fall 2026, ran about 5 min ago: 5 sections read, 0 not reached."),
    ("2268", {"forecast_term_id": "2272"}, "This project has not started collecting Spring 2027 yet; its last snapshot, of Fall 2026, ran about 5 min ago: 5 sections read, 0 not reached."),
    ("2265", SPRING_2027, "This project has not started collecting Spring 2027 yet; its last snapshot, of Summer 2026, ran about 5 min ago: 5 sections read, 0 not reached."),
    ("2272", SPRING_2027, "This project's last Spring 2027 snapshot ran about 5 min ago: 5 sections read, 0 not reached."),
    ("2278", SPRING_2027, "This project's last Fall 2027 snapshot ran about 5 min ago: 5 sections read, 0 not reached."),
    ("2268", {"forecast_term_id": "9999", "forecast_term_name": "Simulated term"}, "This project's last Fall 2026 snapshot ran about 5 min ago: 5 sections read, 0 not reached."),
    ("9999", SPRING_2027, "This project's last snapshot ran about 5 min ago: 5 sections read, 0 not reached."),
    ("2268", None, "This project's last Fall 2026 snapshot ran about 5 min ago: 5 sections read, 0 not reached."),
]


@pytest.mark.parametrize(("term_id", "meta", "expected"), BEFORE_THE_SWITCH)
def test_live_status_text_before_the_switch(full_site: Path, term_id: str, meta: dict | None, expected: str) -> None:
    status = {"last_run_at": "2026-10-28T00:43:00+00:00", "n_observed": 5, "n_missing": 0, "term_id": term_id}
    out = render(full_site, page="about.html", today=None, expression=f"BWO.liveStatusText({json.dumps(status)}, Date.parse('2026-10-28T00:48:00Z'), {json.dumps(meta)})")
    assert "eval_error" not in out, out.get("eval_error")
    assert out["eval"] == expected


@pytest.mark.parametrize("page", sorted(STATUS_PAGES))
def test_live_status_failure_leaves_the_page_as_it_was(full_site: Path, tmp_path: Path, page: str) -> None:
    before = status_line(full_site, page, None)
    assert "last snapshot" not in before and "live-status" not in before
    if page == "index.html":  # byte for byte what the page printed before the live line existed
        out = render(full_site, expression="BWO.sourceHtml(BWO.loaded.meta)")
        assert out["status"] == before == out["eval"]
    truncated = tmp_path / "truncated.json"
    truncated.write_text(STATUS_FIXTURE.read_text()[:60])
    assert status_line(full_site, page, truncated) == before  # render() asserts the harness exited 0: nothing threw
    no_time = tmp_path / "no_time.json"
    no_time.write_text(json.dumps({k: v for k, v in json.loads(STATUS_FIXTURE.read_text()).items() if k != "last_run_at"}))
    assert status_line(full_site, page, no_time) == before
    # The fetch itself rejects (a dropped connection), with a good file behind it: still the line as it was.
    query, el = STATUS_PAGES[page]
    out = render(full_site, page=page, search=query, env={"HARNESS_STATUS_FILE": str(status_file(tmp_path, 12)), "HARNESS_STATUS_REJECT": "1"})
    assert out["elements"][el]["html"] == before


# SESSION_11 item 21d: the joiner counts are copies, not a sample of students, and a seat that opens
# when the student would be alone on the waitlist is a direct enrollment in the counts
# (docs/dev/STATUS.md item 10), so the walk never clears that joiner.
JOINERS_ARE_COPIES = "These joiners are overlapping copies, not separate students, placed at many positions of the same queues at every sampled moment, so the number of sections, not of joiners, is the better guide to how much data there is."
CANNOT_SEE = ("<strong>What this number cannot see:</strong> seats reserved for a category you are not in, time conflicts and unit caps that block an enrollment, "
              "discussion or lab sections with no room, and a seat that opens when you would be the only student left on the waitlist, which the enrollment counts show staying open or going to another student.")
ALONE_ON_THE_WAITLIST = ("<li>When you would be the only student left on a waitlist, a seat that opens is not counted as yours: "
                         "the counts show an empty waitlist and the seat staying open or going to another student, so the estimate can run low for short waitlists.</li>")


def test_the_copy_says_what_the_joiner_counts_and_an_empty_queue_cannot_show(full_site: Path) -> None:
    status = render(full_site, page="methodology.html")["elements"]["data-status"]["html"]
    assert f" of whom got in. {JOINERS_ARE_COPIES} Horizons on the pages" in status  # next to the counts it qualifies
    assert CANNOT_SEE in render(full_site, course="COMPSCI 0", position="3")["result"]
    cannot = (SITE / "methodology.html").read_text().split('<h2 id="cannot">')[1].split("</ul>")[0]
    assert ALONE_ON_THE_WAITLIST in cannot


def test_the_static_copy_the_audit_flagged() -> None:
    """Audit items 6, 9 and 12, and the Methods page's account of the headline after item 1."""
    about = (SITE / "about.html").read_text()
    assert "If you were on a waitlist and want to tell the project what happened, an outcome form may be linked from the lookup page later." in about
    assert "once Spring 2027 enrollment opens" not in about  # item 9: enrollment opened and there is no form
    methods = (SITE / "methodology.html").read_text()
    order = re.search(r"const ORDER = \[([^\]]*)\];", (SITE / "accuracy.html").read_text()).group(1)
    scored = re.findall(r'"(\w+)"', order)
    assert scored == ["bucket", "dept", "course", "site", "cox"]
    assert ("The reports compare five predictors: the position bucket alone, the department-and-bucket curve, the course-and-bucket curve the pages use, "
            "the literal number the first version of the lookup showed, and the Cox model;") in methods  # item 12: the five the Accuracy page scores
    odds = re.sub(r"<[^>]+>", "", methods.split('<h2 id="odds">')[1].split("<h2")[0])
    assert not re.search(r"\.\s+[a-z]", odds), re.findall(r".{30}\.\s+[a-z].{20}", odds)  # item 12: no sentence starts in lower case
    assert ("the page counts the days from today through the day of the last automatic waitlist run of the term and reads the curve for your course and position there") in methods
    assert ("When the time you have left is longer than the data followed anyone, the headline gives the share within the longest follow-up instead, "
            "says how long that was, and says the share by the last run was at least that.") in methods
    for page in [*SITE.glob("*.html"), SITE / "assets" / "site.js"]:  # item 6: the collection strings #42 reworded stay gone
        text = page.read_text()
        for stale in ("starts Oct 26, 2026", "none exist before Oct 26", "starts when Phase 1 opens"):
            assert stale not in text, (page.name, stale)


def test_about_and_methods_pages_show_the_data_status(full_site: Path) -> None:
    out = render(full_site, page="about.html")
    assert "Simulated term" in out["elements"]["data-status"]["html"] and "this project's own snapshots" in out["elements"]["data-status"]["html"]
    out = render(full_site, page="methodology.html")
    assert "Showing: <strong>Simulated term</strong>" in out["elements"]["data-status"]["html"]


# ------------------------------------------------------------- department page


def dept_copy(site_root: Path, tmp_path: Path) -> Path:
    """A copy of the export with distinct joins on the COMPSCI rows (the synthetic cohort has none),
    so the order the page prints is pinned, plus one QTP course: a subject with no display name (config/subject_names.json lists it under _todo)."""
    root = tmp_path / "site"
    shutil.copytree(site_root, root)
    path = root / "data" / "index.json"
    index = json.loads(path.read_text())
    compsci = sorted((r for r in index["courses"] if r["subject"] == "COMPSCI"), key=lambda r: r["key"])
    for i, r in enumerate(compsci):
        r["joins"] = (i * 7) % len(compsci) + 1  # 7 is coprime with 15: distinct, and not the key order
    art = next(r for r in index["courses"] if r["key"] == "ART 11")
    assert json.loads((ROOT / "config" / "subject_names.json").read_text())["names"]["QTP"] == ""  # still unnamed; pick another _todo code if it gets one
    index["courses"].append({**art, "key": "QTP 10", "subject": "QTP", "number": "10", "joins": 3})
    path.write_text(json.dumps(index))
    return root


def jspct(p: float) -> str:
    """pct() as the page rounds it: JavaScript's Math.round sends a half up, Python's round() to even (0.945 is 95% there, 94% here)."""
    return f"{int(p * 100 + 0.5)}%"


def dept_rows(html: str) -> list[str]:
    return html.split('<tr class="course">')[1:]


def controls_hidden(out: dict) -> bool:
    """The bucket form starts hidden in the markup (checked below); a page that never shows it never touches it."""
    return out["elements"].get("controls", {"hidden": True})["hidden"]


def test_department_page_shows_the_pool_curve_and_every_course(course_site: Path, tmp_path: Path) -> None:
    site = dept_copy(course_site, tmp_path)
    index = load(site, "index.json")
    pool = load(site, "pooled.json")["dept"]["COMPSCI"]["6-15"]
    out = render(site, page="dept.html", search="?subject=COMPSCI", expression="BWO.subjectName('COMPSCI')")
    name = out["eval"]
    assert name in ("COMPSCI", "Computer Science")  # the code on this branch; the generated name once PR #17 is merged
    els = out["elements"]
    assert els["dept-name"]["text"] == name and out["title"].startswith(f"{name} courses")
    rows = sorted((r for r in index["courses"] if r["subject"] == "COMPSCI"), key=lambda r: -r["joins"])
    assert len(rows) == 15
    summary = els["summary"]["html"]
    assert "15 courses with estimates in Simulated term, this project's own snapshots" in summary
    # the department's pool at the default bucket, positions 6 to 15, read at the three horizons
    assert els["bucket"]["value"] == "6-15" and not els["controls"]["hidden"]
    curve = els["pool"]["html"]
    assert curve.count('class="curve') == 1 and 'class="curve s2"' in curve and 'class="band"' in curve and 'role="img"' in curve and "Show as table" in curve
    assert "All COMPSCI courses together, positions 6 to 15" in curve
    for h in (7.0, 14.0, 28.0):
        p, lo, hi, _ = read_curve(pool["curve"], h)
        assert f"<strong>{jspct(p)}</strong>" in curve and f"{jspct(lo)} to {jspct(hi)}" in curve
    assert f"{pool['sections']} sections, {pool['n']} hypothetical joiners, {pool['events']} cleared" in curve
    # no "you" and no "now" on this page: no gold marks, no thick curve
    assert 'class="mark"' not in curve and " you" not in curve and 'class="tag">you' not in curve
    # every COMPSCI course, most-joined first, with its own share within 14 days at the bucket and a link
    table = els["table"]["html"]
    trs = dept_rows(table)
    assert len(trs) == 15
    for tr, r in zip(trs, rows):
        s = r["buckets"]["6-15"]
        assert f'course.html?c={r["key"].replace(" ", "%20")}&position=6&today=2027-01-10"' in tr
        assert f">{r['key']}</a>" in tr and f"<strong>{jspct(s['p'][1])}</strong>" in tr and f"{jspct(s['lo'][1])} to {jspct(s['hi'][1])}" in tr
        assert f"{r['level']} division" in tr and f"{s['n_course']} cases in {s['sections_course']} section" in tr
    assert 'aria-label="COMPSCI courses at positions 6 to 15"' in table and "Share who got in within 14 days" in table
    # another bucket: the course's own curves where it has 30 cases, and the pool follows
    out = render(site, page="dept.html", search="?subject=COMPSCI&bucket=1-5")
    trs = dept_rows(out["elements"]["table"]["html"])
    assert len(trs) == 15
    for tr, r in zip(trs, rows):
        s = r["buckets"]["1-5"]
        assert f"<strong>{jspct(s['p'][1])}</strong>" in tr and f"{s['n']} cases in {s['sections']} section" in tr and "pooled" not in tr
    assert "positions 1 to 5" in out["elements"]["pool"]["html"] and out["elements"]["bucket"]["value"] == "1-5"


def test_department_page_without_a_display_name_and_grouped_subjects(course_site: Path, tmp_path: Path) -> None:
    site = dept_copy(course_site, tmp_path)
    out = render(site, page="dept.html", search="?subject=QTP")
    els = out["elements"]
    assert els["dept-name"]["text"] == "QTP" and out["title"].startswith("QTP courses")
    assert "1 course with estimates" in els["summary"]["html"] and len(dept_rows(els["table"]["html"])) == 1
    # a small subject is pooled with the other small ones: the curve says so
    assert "QTP is grouped with the smaller departments" in els["summary"]["html"]
    assert "The smaller departments together, positions 6 to 15" in els["pool"]["html"]
    out = render(site, page="dept.html", search="?subject=art", expression="BWO.subjectName('ART')")
    assert out["elements"]["dept-name"]["text"] == out["eval"] and out["eval"] in ("ART", "Art Practice")
    assert len(dept_rows(out["elements"]["table"]["html"])) == 15 and "Every ART course" in out["elements"]["table"]["html"]
    # "cs" resolves through the aliases
    out = render(site, page="dept.html", search="?subject=cs", expression="BWO.subjectName('COMPSCI')")
    assert out["elements"]["dept-name"]["text"] == out["eval"] and "Every COMPSCI course" in out["elements"]["table"]["html"]
    # a display name from the generated map (PR #17) is used; a missing or empty one falls back to the code
    out = render(site, page="dept.html", search="?subject=cs", expression="(BWO.SUBJECT_NAMES = {COMPSCI: 'Computer Science', QTP: ''}, [BWO.subjectName('COMPSCI'), BWO.subjectName('QTP'), BWO.subjectName('NOPE')])")
    assert out["eval"] == ["Computer Science", "QTP", "NOPE"]


def test_the_department_list_shows_every_subject_by_name() -> None:
    """Item 21: dept.html with no subject lists every department of the shipped index; none is shown as its bare code."""
    out = render(SITE, page="dept.html")
    links = re.findall(r'<a href="dept\.html\?subject=([^&"]+)[^"]*">([^<]+)</a>', out["elements"]["summary"]["html"])
    subjects = {r["subject"] for r in load(SITE, "index.json")["courses"]}
    assert {code for code, _ in links} == subjects
    assert [code for code, text in links if text == code] == []
    assert ("DISSTD", "Disability Studies") in links


def test_unknown_department_names_the_nearest(course_site: Path) -> None:
    out = render(course_site, page="dept.html", search="?subject=NOPE")
    els = out["elements"]
    assert "No such department" in els["summary"]["html"] and "NOPE" in els["summary"]["html"]
    assert els["summary"]["html"].count("dept.html?subject=") == 0 and "Nearest" not in els["summary"]["html"]  # review 3.4: nothing is close
    assert els["pool"]["html"] == "" and els["table"]["html"] == "" and controls_hidden(out)
    assert out["title"].startswith("No such department")
    assert "Simulated term" in out["status"]
    out = render(course_site, page="dept.html", search="?subject=COMP")
    assert "No such department" in out["elements"]["summary"]["html"] and "dept.html?subject=COMPSCI" in out["elements"]["summary"]["html"]
    # no subject at all: every department, as links
    out = render(course_site, page="dept.html")
    summary = out["elements"]["summary"]["html"]
    assert "No such department" not in summary and all(f"dept.html?subject={s}" in summary for s in ("ART", "COMPSCI", "MATH", "STAT"))


# Fifteen real subject codes with distinct joins, one course each: the "Nearest:" links
# of an unknown subject depend only on the subjects and, for a prefix match, their joins.
NEAR_SUBJECTS = ("AEROENG", "AGRS", "ARESEC", "ARMENI", "ASTRON", "CHEM", "COMPSCI", "ECON", "GEOG", "HISTORY", "MATH", "PHYSICS", "POLSCI", "PSYCH", "STAT")


def test_nearest_subjects_for_misspelt_subjects_are_pinned() -> None:
    """The subjects the department page offers for a misspelt one, pinned.

    Review of 2026-10-29, 3.4: only close subjects. Shorthand and prefix matches (by code or name) come
    first, then the matcher's Damerau distance, at most 2; a spelling further than that from every code
    (the long ones here) gets none, where it used to get the three nearest however far they were.
    """
    index = {"courses": [{"key": f"{s} 1", "subject": s, "number": "1", "joins": (i * 7) % len(NEAR_SUBJECTS) + 1, "buckets": {}} for i, s in enumerate(NEAR_SUBJECTS)]}
    asked = {
        "AERONEG": ["AEROENG"],  # two letters swapped: one edit
        "aeroeg": ["AEROENG"],  # a letter dropped
        "compscience": [],  # longer than any code by more than 2, and no subject's name starts with it
        "poli science": [],
        "comp": ["COMPSCI"],  # a prefix
        "phsyics": ["PHYSICS"],
        "cs": ["COMPSCI"],  # the shorthand
        "chme": ["CHEM"],
        "nope": [],
    }
    out = render(Path("/nonexistent"), expression=f"(function(){{ const i = {json.dumps(index)}; return {json.dumps(list(asked))}.map((t) => BWO.nearestSubjects(i, t, 3)); }})()")
    assert "eval_error" not in out, out.get("eval_error")
    assert dict(zip(asked, out["eval"])) == asked


def test_department_page_shell_and_states(course_site: Path, tmp_path: Path) -> None:
    html = (SITE / "dept.html").read_text()
    assert '<meta property="og:title"' in html and '<meta property="og:description"' in html
    assert '<nav aria-label="Site">' in html and "aria-current" not in html and "<footer" in html and 'id="stamp"' in html
    assert '<form id="controls" class="controls" style="max-width:20rem" hidden>' in html
    assert html.index('<script src="assets/site.js"></script>') < html.index("BWO.subjectName")
    out = render(course_site, page="dept.html", search="?subject=COMPSCI")
    meta = load(course_site, "meta.json")
    assert out["status"].startswith("<p><strong>Simulated term</strong>") and f"{meta['courses']} courses with estimates from" in out["status"]
    assert out["stamp"].startswith("Data through")
    assert out["location"] == "https://example.test/dept.html?subject=COMPSCI&today=2027-01-10"  # nothing in the URL is rewritten
    out = render(tmp_path, page="dept.html", search="?subject=COMPSCI")
    assert "No estimates yet" in out["status"] and controls_hidden(out)
    out = render(course_site, page="dept.html", search="?subject=COMPSCI", env={"HARNESS_FAIL_FETCH": "1"})
    assert "Could not load the estimates" in out["status"] and controls_hidden(out)


def test_course_page_links_its_department(course_site: Path) -> None:
    out = render(course_site, page="course.html", search="?c=cs0&position=10")
    html = out["elements"]["course"]["html"]
    assert 'href="dept.html?subject=COMPSCI&bucket=6-15&today=2027-01-10">All COMPSCI courses</a>' in html


def test_course_page_links_its_department_without_related_courses(course_site: Path, tmp_path: Path) -> None:
    """QTP 10 is the only QTP course: no related-courses block, but the department link still shows."""
    site = dept_copy(course_site, tmp_path)
    art = load(site, "courses/ART.json")
    (site / "data" / "courses" / "QTP.json").write_text(json.dumps({**art, "courses": {"QTP 10": art["courses"]["ART 11"]}}))
    meta = load(site, "meta.json")
    meta["subject_files"]["QTP"] = "courses/QTP.json"
    (site / "data" / "meta.json").write_text(json.dumps(meta))
    out = render(site, page="course.html", search="?c=QTP%2010&position=10")
    html = out["elements"]["course"]["html"]
    assert "Other QTP courses" not in html
    assert 'href="dept.html?subject=QTP&bucket=6-15&today=2027-01-10">All QTP courses</a>' in html

# ------------------------------------------------------ the fallback ladder (S5)

SECTION_RUNG = "Section curves need this project's own Spring 2027 snapshots and are not published yet."  # no date: true before and after Phase 1 opens


@pytest.fixture(scope="module")
def solo_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """ART 11 is the whole ART department: 36 cases at positions 1 to 5 (its own curve, and a department pool),
    12 at positions 6 to 15 (too few for the course and for the department, so the cell points at all courses)."""
    root = tmp_path_factory.mktemp("site_solo")
    cohort = synthetic_cohort()
    cohort.loc[cohort["course_key"] == "ART 11", "dept_group"] = "ART"
    export_site_tables(cohort, CAL, root / "data", n_boot=20)
    return root


def ladder(html: str) -> str:
    """The ladder paragraph: the rung for the curve shown, then the section rung, last."""
    found = re.findall(r'<p class="muted small ladder">(.*?)</p>', html, flags=re.S)
    assert len(found) == 1, html
    text = " ".join(found[0].split())
    assert text.endswith(SECTION_RUNG), text
    assert text.count(SECTION_RUNG) == 1
    return text


def test_ladder_names_the_course_when_it_has_its_own_curve(course_site: Path) -> None:
    cell = cell_of(course_site, "COMPSCI 0", "1-5")
    assert cell["pooled"] is False
    rung = f"This curve: COMPSCI 0, positions 1 to 5, n&nbsp;=&nbsp;{cell['n']:,}."
    assert ladder(render(course_site, course="COMPSCI 0", position="3")["result"]) == f"{rung} {SECTION_RUNG}"
    html = render(course_site, page="course.html", search="?c=COMPSCI%200&position=3")["elements"]["course"]["html"]
    assert ladder(html) == f"{rung} {SECTION_RUNG}"
    assert html.index('<p class="muted small ladder">') < html.index("<h2>Every position</h2>")  # in the headline card, not under the chart


def test_ladder_names_the_department_and_why_when_the_course_is_pooled(course_site: Path) -> None:
    own = load(course_site, "courses/COMPSCI.json")["courses"]["COMPSCI 0"]["buckets"]["6-15"]
    pool = load(course_site, "pooled.json")["dept"]["COMPSCI"]["6-15"]
    assert own["pooled"] == "COMPSCI" and own["n_course"] < 30
    rung = f"This curve: the COMPSCI department, positions 6 to 15 (COMPSCI 0 had {own['n_course']} cases, fewer than 30), n&nbsp;=&nbsp;{pool['n']:,}."
    assert ladder(render(course_site, course="COMPSCI 0", position="10")["result"]) == f"{rung} {SECTION_RUNG}"
    html = render(course_site, page="course.html", search="?c=COMPSCI%200&position=10")["elements"]["course"]["html"]
    assert ladder(html) == f"{rung} {SECTION_RUNG}"
    # subjects too small for a department of their own are grouped as OTHER, printed as the other departments
    art = load(course_site, "courses/ART.json")["courses"]["ART 11"]["buckets"]["6-15"]
    assert art["pooled"] == "OTHER"
    other = load(course_site, "pooled.json")["dept"]["OTHER"]["6-15"]
    r = render(course_site, course="ART 11", position="10")["result"]
    assert ladder(r) == f"This curve: the other departments, positions 6 to 15 (ART 11 had {art['n_course']} cases, fewer than 30), n&nbsp;=&nbsp;{other['n']:,}. {SECTION_RUNG}"


def test_ladder_names_all_courses_and_why_when_the_department_is_too_small(solo_site: Path) -> None:
    own = load(solo_site, "courses/ART.json")["courses"]["ART 11"]["buckets"]
    pooled = load(solo_site, "pooled.json")
    assert own["1-5"]["pooled"] is False and own["6-15"]["pooled"] == "all" and "6-15" not in pooled["dept"]["ART"]
    rung = f"This curve: all courses, positions 6 to 15 (ART 11 had {own['6-15']['n_course']} cases, fewer than 30; the ART department also had fewer than 30), n&nbsp;=&nbsp;{pooled['all']['6-15']['n']:,}."
    assert ladder(render(solo_site, course="ART 11", position="10")["result"]) == f"{rung} {SECTION_RUNG}"
    html = render(solo_site, page="course.html", search="?c=ART%2011&position=10")["elements"]["course"]["html"]
    assert ladder(html) == f"{rung} {SECTION_RUNG}"


def test_ladder_on_the_missing_bucket_fallbacks(full_site: Path, tmp_path: Path) -> None:
    """A real course with no cases at the asker's bucket: its department's pool, then its level's, then all courses', each labelled."""
    pooled = load(full_site, "pooled.json")
    missing = "No estimate for positions 41+ in <strong>COMPSCI 0</strong>; the waitlist there was never that long. Positions with data: 1-5, 6-15, 16-40."
    for drop, rung, n, what in (
        ((), "the COMPSCI department", pooled["dept"]["COMPSCI"]["41+"]["n"], "the whole COMPSCI department"),
        (("dept",), "all lower-division courses", pooled["level"]["lower"]["41+"]["n"], "all lower-division courses"),
        (("dept", "level"), "all courses", pooled["all"]["41+"]["n"], "all courses"),
    ):
        r = render(gap_copy(full_site, tmp_path, drop=drop), course="COMPSCI 0", position="45")["result"]
        assert f'<p class="error">{missing}</p><p>Showing the estimate for {what} at positions 41 and up instead.</p>' in r, drop
        assert ladder(r) == f"This curve: {rung}, positions 41 and up (COMPSCI 0 had no cases), n&nbsp;=&nbsp;{n:,}. {SECTION_RUNG}", drop


def test_ladder_at_department_level_estimates(dept_site: Path) -> None:
    own = load(dept_site, "courses/COMPSCI.json")["courses"]["COMPSCI 0"]["buckets"]["1-5"]
    pool = load(dept_site, "pooled.json")["dept"]["COMPSCI"]["1-5"]
    rung = f"This curve: the COMPSCI department, positions 1 to 5 (estimates are by department; COMPSCI 0 had {own['n_course']} cases), n&nbsp;=&nbsp;{pool['n']:,}."
    assert ladder(render(dept_site, course="COMPSCI 0", position="3")["result"]) == f"{rung} {SECTION_RUNG}"
    html = render(dept_site, page="course.html", search="?c=COMPSCI%200&position=3")["elements"]["course"]["html"]
    assert ladder(html) == f"{rung} {SECTION_RUNG}"


def test_ladder_reads_min_n_from_meta(course_site: Path) -> None:
    """The threshold in the why is meta.min_n, not a constant."""
    out = render(course_site, expression="(function(){ const m = Object.assign({}, BWO.loaded.meta, {min_n: 40}); return BWO.ladderHtml({cell: {n: 500}, pooled: 'COMPSCI', source: 'dept', own: {n_course: 1, sections_course: 1}}, {key: 'COMPSCI 0', dept_group: 'COMPSCI'}, '6-15', m); })()")
    assert "(COMPSCI 0 had 1 case, fewer than 40), n&nbsp;=&nbsp;500." in out["eval"]
    out = render(course_site, expression="BWO.pooledSentence({cell: {n: 1234}, pooled: false, source: 'course', own: null}, {key: 'COMPSCI 0'}, '41+', BWO.loaded.meta)")
    assert out["eval"] == "This curve: COMPSCI 0, positions 41 and up, n&nbsp;=&nbsp;1,234."


# ------------------------------------------------ the Oct 29 review (docs/dev/SITE_REVIEW_2026-10-29.md)


def with_meta(site_root: Path, tmp_path: Path, name: str, **changes: object) -> Path:
    """A copy of the export with ``changes`` merged into meta.json (a value of None removes the key)."""
    root = tmp_path / name
    shutil.copytree(site_root, root)
    meta = load(root, "meta.json")
    for k, v in changes.items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    (root / "data" / "meta.json").write_text(json.dumps(meta))
    return root


def test_a_key_off_the_forecast_schedule_says_so(full_site: Path, tmp_path: Path) -> None:
    """Section 0: with the forecast term's catalog in the export, a key not in the index is not on that schedule;
    without one (the served export today) the message is the one the site has always printed."""
    site = with_meta(full_site, tmp_path, "catalog", catalog_term_id="2272", catalog_courses=10, catalog_only_courses=0)
    term = load(site, "meta.json")["forecast_term_name"]
    out = render(site, course="NOPE 999", position="10")
    assert out["result"] == f'<p class="error"><strong>NOPE 999</strong> isn\'t on the {term} schedule.</p>{BROWSE}'
    out = render(site, course="COMPSCI 999", position="10")
    assert out["result"].startswith(f'<p class="error"><strong>COMPSCI 999</strong> isn\'t on the {term} schedule. Did you mean <a href="?course=COMPSCI')
    assert out["result"].endswith(BROWSE) and NO_DATA not in out["result"]
    status = render(site, page="course.html", search="?c=NOPE%20999")["status"]
    assert status.startswith(f'<p class="error"><strong>NOPE 999</strong> isn\'t on the {term} schedule.</p><p><a href="index.html?course=NOPE%20999&position=10')
    assert "every course</a>" in status
    # no catalog: today's sentence on both pages
    assert NO_DATA in render(full_site, course="NOPE 999", position="10")["result"]
    assert NO_DATA in render(full_site, page="course.html", search="?c=NOPE%20999")["status"]


def test_a_catalog_only_row_keeps_the_stub_rendering(full_site: Path, tmp_path: Path) -> None:
    """A stub row (catalog_only, pointer cells with n_course 0) is a course: it gets the department's curve, labelled, not the off-schedule message."""
    site = with_meta(full_site, tmp_path, "stub", catalog_term_id="2272", catalog_courses=11, catalog_only_courses=1)
    pointer = {"pooled": "COMPSCI", "n_course": 0, "sections_course": 0}
    index = load(site, "index.json")
    index["courses"].append({"key": "COMPSCI 999", "subject": "COMPSCI", "number": "999", "level": "upper", "dept_group": "COMPSCI", "joins": 0, "catalog_only": True, "buckets": {"6-15": dict(pointer)}})
    (site / "data" / "index.json").write_text(json.dumps(index))
    subject = load(site, "courses/COMPSCI.json")
    subject["courses"]["COMPSCI 999"] = {"catalog_only": True, "buckets": {"6-15": dict(pointer)}}
    (site / "data" / "courses" / "COMPSCI.json").write_text(json.dumps(subject))
    r = render(site, course="COMPSCI 999", position="10")["result"]
    assert "isn't on the" not in r and "No data for" not in r
    assert "This curve: the COMPSCI department, positions 6 to 15 (COMPSCI 999 had 0 cases, fewer than 30)" in r


def test_the_courses_default_sort_puts_thin_and_capped_rows_last(course_site: Path, tmp_path: Path) -> None:
    """Section 2.1: by default a one-section row or one read past its curve's reach sorts after every other row,
    then by the interval's lower bound where there is one, else the share; an explicit column sort is unchanged."""
    rows = "[{key: 'A 1', p: 1.0, lo: null, sections: 1, floor: false}, {key: 'B 1', p: 0.7, lo: 0.6, sections: 2, floor: false}, {key: 'C 1', p: 0.9, lo: 0.5, sections: 3, floor: false}, {key: 'D 1', p: 0.99, lo: 0.95, sections: 4, floor: true}, {key: 'E 1', p: 0.65, lo: null, sections: 2, floor: false}]"
    out = render(course_site, page="courses.html", expression=f"{rows}.sort(BWO.courseDefaultOrder).map((x) => x.key)")
    assert out["eval"] == ["E 1", "B 1", "C 1", "A 1", "D 1"]
    # on the page: the default order follows the rule, and sorting by share is the plain share order
    site = tmp_path / "sort"
    shutil.copytree(course_site, site)
    index = load(site, "index.json")
    template = next(r for r in index["courses"] if "1-5" in r["buckets"] and r["buckets"]["1-5"]["pooled"] is False)
    cell = template["buckets"]["1-5"]
    one = {**template, "key": "ZZZ 1", "subject": "ZZZ", "number": "1", "buckets": {"1-5": {**cell, "p": [1.0, 1.0, 1.0], "lo": [None] * 3, "hi": [None] * 3, "sections": 1, "reach": [1.0, 99.0]}}}
    two = {**template, "key": "ZZZ 2", "subject": "ZZZ", "number": "2", "buckets": {"1-5": {**cell, "p": [0.7, 0.7, 0.7], "lo": [0.6] * 3, "hi": [0.8] * 3, "sections": 2, "reach": [0.7, 99.0]}}}
    index["courses"] = [one, two]
    (site / "data" / "index.json").write_text(json.dumps(index))
    order = lambda html: re.findall(r">(ZZZ \d)</a>", html)  # noqa: E731
    assert order(render(site, page="courses.html", search="?bucket=1-5")["elements"]["table"]["html"]) == ["ZZZ 2", "ZZZ 1"]
    assert order(render(site, page="courses.html", search="?bucket=1-5&sort=p&dir=asc")["elements"]["table"]["html"]) == ["ZZZ 2", "ZZZ 1"]
    assert order(render(site, page="courses.html", search="?bucket=1-5&sort=sections")["elements"]["table"]["html"]) == ["ZZZ 2", "ZZZ 1"]
    assert order(render(site, page="courses.html", search="?bucket=1-5&sort=sections&dir=asc")["elements"]["table"]["html"]) == ["ZZZ 1", "ZZZ 2"]


@pytest.mark.parametrize(("raw", "shown"), [("1000", 500), ("0", 1), ("-5", 1), ("abc", 10), ("12", 12), ("500", 500), ("", 10)])
def test_a_position_from_the_url_is_clamped_like_the_form(full_site: Path, raw: str, shown: int) -> None:
    """Section 2.7: one rule on both pages (BWO.clampPosition, 1 to 500, 10 when it is no number), written back into the input."""
    out = render(full_site, expression=f"BWO.clampPosition({json.dumps(raw)}, 10)")
    assert out["eval"] == shown
    out = render(full_site, search=f"?course=STAT%202&position={raw}")
    assert f"STAT 2 · position {shown} (" in out["result"]
    assert out["elements"]["position"]["value"] == str(shown)
    html = render(full_site, page="course.html", search=f"?c=STAT%202&position={raw}")["elements"]["course"]["html"]
    assert f"STAT 2 · position {shown} (" in html and f'<input id="position" type="number" inputmode="numeric" min="1" max="500" step="1" value="{shown}">' in html


def test_the_course_page_reads_course_as_well_as_c(full_site: Path) -> None:
    """Section 2.8: the lookup's parameter name works on the course page; ?c= wins when both are there."""
    html = render(full_site, page="course.html", search="?course=STAT%202&position=3")["elements"]["course"]["html"]
    assert "<h1>STAT 2 " in html and "STAT 2 · position 3 (" in html
    html = render(full_site, page="course.html", search="?c=MATH%201&course=STAT%202")["elements"]["course"]["html"]
    assert "<h1>MATH 1 " in html
    html = render(SITE, page="course.html", search="?course=ECON%20100A")["elements"]["course"]["html"]  # the review's URL, on the served data
    assert "<h1>ECON 100A " in html


def media_block(css: str, query: str) -> str:
    """The body of the first ``@media <query> { ... }`` block, nested braces and all."""
    start = css.index("@media " + query + " {") + len("@media " + query + " {")
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        i += 1
    return css[start:i - 1]


def test_the_phone_course_table_labels_its_numbers(course_site: Path) -> None:
    """Section 3.1: in the stacked layout (40 rem and down) each number says what it is; above it the header does."""
    table = render(course_site, page="courses.html", search="?bucket=1-5")["elements"]["table"]["html"]
    rows = re.findall(r'<tr class="course">(.*?)</tr>', table, flags=re.S)
    assert rows
    for tr in rows:
        labels = re.findall(r'<td class="num[^"]*" data-label="([^"]+)">', tr)
        assert labels == ["Share who got in", "Median days", "Cases", "Sections"], tr
    css = (SITE / "assets" / "site.css").read_text()
    stacked = media_block(css, "(max-width: 40rem)")
    assert re.search(r'table\.twoline td\[data-label\]::before \{[^}]*content: attr\(data-label\)', stacked)
    outside = css.replace("@media (max-width: 40rem) {" + stacked + "}", "")
    assert "data-label" not in outside  # nothing changes above the stacked width


def test_the_dot_row_never_wraps() -> None:
    """Section 3.5: the 20 dots stay on one line, smaller on a narrow phone."""
    css = (SITE / "assets" / "site.css").read_text()
    base = re.search(r"\n\.dots \{([^}]*)\}", css).group(1)
    assert "flex-wrap: nowrap" in base and "flex-wrap: wrap" not in base
    narrow = media_block(css, "(max-width: 28rem)")
    dot = re.search(r"\.dots i \{([^}]*)\}", narrow).group(1)
    width = float(re.search(r"width: ([\d.]+)rem", dot).group(1))
    gap = float(re.search(r"\.dots \{[^}]*gap: ([\d.]+)rem", narrow).group(1))
    # 20 dots and 19 gaps fit a 360 px phone's card: 360 px less the page's and the card's padding and border (66 px), at 16 px a rem
    assert (20 * width + 19 * gap) * 16 <= 360 - 66
    # and the full-size row fits wherever the narrow rule stops applying (28 rem, 448 px)
    full_w = float(re.search(r"\n\.dots i \{[^}]*width: ([\d.]+)rem", css).group(1))
    full_gap = float(re.search(r"gap: ([\d.]+)rem", base).group(1))
    assert (20 * full_w + 19 * full_gap) * 16 <= 448 - 66


def test_did_you_mean_ranks_the_subjects_own_courses_by_number() -> None:
    """Section 3.3, on the served index: ECON 121 (no such course) offers the ECON numbers nearest 121, not ECON 1;
    a subject that matches nothing offers nothing (the Try chips are not suggestions)."""
    out = render(SITE, expression="['ECON 121', 'econ 121', 'xyz', 'xyz 12'].map((t) => BWO.matchCourse(BWO.loaded.index, t).nearest.map((r) => r.key))")
    econ, lower, xyz, xyz12 = out["eval"]
    assert econ == lower and econ[0] == "ECON 119" and len(econ) == 3, econ
    assert all(k.startswith("ECON ") and abs(int(re.sub(r"\D", "", k)) - 121) <= 10 for k in econ) and "ECON 1" not in econ, econ
    assert xyz == [] and xyz12 == []
    page = render(SITE, course="ECON 121", position="10")["result"]
    assert "Did you mean" in page and ">ECON 119</a>" in page and ">ECON 1</a>" not in page


def test_did_you_mean_orders_numbers_then_suffixes() -> None:
    """The numeric part first, then the letter suffix nearest the one typed, then joins."""
    rows = ", ".join(f"{{key: 'MATH {n}', subject: 'MATH', number: '{n}', joins: {j}, buckets: {{}}}}" for n, j in (("1", 900), ("53", 50), ("54", 800), ("55", 10), ("56", 5), ("H54", 1), ("110", 400)))
    out = render(Path("/nonexistent"), expression=f"(function(){{ const i = {{courses: [{rows}]}}; return ['math 54a', 'math 57', 'math 100'].map((t) => BWO.matchCourse(i, t).nearest.map((r) => r.key)); }})()")
    assert out["eval"] == [["MATH 54", "MATH H54", "MATH 53"], ["MATH 56", "MATH 55", "MATH 54"], ["MATH 110", "MATH 56", "MATH 55"]]


def test_dept_page_offers_only_close_subjects() -> None:
    """Section 3.4: an unknown subject lists only subjects within edit distance 2, or whose code or name starts with
    what was typed; otherwise no "Nearest", only the browse sentence."""
    out = render(SITE, page="dept.html", search="?subject=NOPE")
    summary = out["elements"]["summary"]["html"]
    assert "Nearest" not in summary and "dept.html?subject=" not in summary
    assert summary.endswith('<p>Or browse <a href="courses.html?today=2027-01-10">every course</a>.</p>')
    out = render(SITE, page="dept.html", search="?subject=ECNO")
    assert "Nearest: " in out["elements"]["summary"]["html"] and "dept.html?subject=ECON" in out["elements"]["summary"]["html"]
    out = render(SITE, page="dept.html", search="?subject=Econom")
    assert "dept.html?subject=ECON" in out["elements"]["summary"]["html"]  # the start of the subject's name


def test_combobox_rows_say_what_the_joins_count() -> None:
    """Section 3.7, on the served index (the synthetic export has no joins): "· 538 joins" names what it counts
    and the term it is from; the number stays."""
    out = render(SITE, expression="(function(){ const list = document.getElementById('course-list'); BWO.combobox(document.getElementById('course'), list, BWO.loaded.index).suggest('cs 61a'); return list.innerHTML; })()")
    row = next(r for r in load(SITE, "index.json")["courses"] if r["key"] == "COMPSCI 61A")
    term = load(SITE, "meta.json")["term_name"]
    assert row["joins"] and f"<span>COMPSCI 61A</span><span class=\"sub\">lower division · {row['joins']:,} waitlist joins, {term}</span>" in out["eval"]
    assert " joins</span>" not in out["eval"]


def test_graduate_courses_say_graduate_division() -> None:
    """Section 3.8: "grad division" is "graduate division" (on the department page, and wherever a level is printed)."""
    out = render(SITE, page="dept.html", search="?subject=ECON", expression="['lower', 'upper', 'grad', null].map(BWO.levelText)")
    assert out["eval"] == ["lower division", "upper division", "graduate division", ""]
    table = out["elements"]["table"]["html"]
    assert "graduate division" in table and "grad division" not in table
    for page in ("dept.html", "courses.html", "course.html"):
        assert 'r.level + " division"' not in (SITE / page).read_text() and 'row.level + " division"' not in (SITE / page).read_text()
    assert '"DISSTD": "Disability Studies"' in (SITE / "assets" / "site.js").read_text()  # DISSTD already has its name on this branch


def test_the_404_page_has_a_description() -> None:
    """Section 3.10: every page has a meta description, the 404 page included."""
    for page in PAGES:
        assert re.search(r'<meta name="description" content="[^"]{20,}">', (SITE / page).read_text()), page

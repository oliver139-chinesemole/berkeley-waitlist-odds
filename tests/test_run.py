"""End-to-end test of analysis.run on simulated data, plus the site exporter's pooling rule."""
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import analysis.run as run
from analysis.calendar import TermCalendar, last_auto_cut
from analysis.export import course_tables, export_site_tables
from analysis.run import run_analysis, spans_phase1_end
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
    index_path, meta_path = res.site_files
    data_dir = index_path.parent
    index = json.loads(index_path.read_text())
    meta = json.loads(meta_path.read_text())
    pooled = json.loads((data_dir / "pooled.json").read_text())
    insights = json.loads((data_dir / "insights.json").read_text())
    rows = {r["key"]: r for r in index["courses"]}
    # a simulated course whose sections never filled and never queued has no joinable moments, so 40 is an upper bound
    assert 36 <= len(rows) <= 40 and meta["courses"] == len(rows) and meta["term_id"] == "9999"
    assert meta["forecast_term_id"] == "9999" and meta["dates"]["last_auto_waitlist"] == meta["deadline"] and meta["horizons"] == [7.0, 14.0, 28.0]
    assert meta["rank"] == "wl_joins" and any(r["joins"] > 0 for r in rows.values())
    assert set(meta["subject_files"]) == {r["subject"] for r in rows.values()}
    for subject, rel in meta["subject_files"].items():
        entries = json.loads((data_dir / rel).read_text())["courses"]
        assert entries and all(key.split()[0] == subject for key in entries)
        for key, entry in entries.items():
            assert entry["level"] in ("lower", "upper", "grad") and rows[key]["level"] == entry["level"]
            for bucket, cell in entry["buckets"].items():
                if cell["pooled"] is False:
                    assert cell["n"] >= 30 and 1 <= cell["sections"] <= cell["n"] and cell["events"] <= cell["n"]
                    ps = [p for _, p, _, _ in cell["curve"]]
                    assert ps == sorted(ps) and all(0.0 <= p <= 1.0 for p in ps)  # cumulative clearing never falls
                    assert cell["curve"][-1][0] == pytest.approx(cell["reach_days"], abs=0.06) and cell["reach_days"] > 0
                    for _, p, lo, hi in cell["curve"]:
                        assert lo is None or (lo - 1e-9 <= p <= hi + 1e-9 and 0.0 <= lo <= hi <= 1.0)
                else:
                    pool = pooled["all"][bucket] if cell["pooled"] == "all" else pooled["dept"][cell["pooled"]][bucket]
                    assert pool["n"] >= 30 and "curve" not in cell and 1 <= cell["sections_course"] <= cell["n_course"]
                    assert meta["estimate_level"] == "dept" or cell["n_course"] < 30
                summary = rows[key]["buckets"][bucket]
                assert summary["pooled"] == cell["pooled"] and len(summary["p"]) == 3 and all(0.0 <= p <= 1.0 for p in summary["p"])
    assert set(insights["all_by_bucket"]) <= {"1-5", "6-15", "16-40", "41+"} and insights["counts"]["courses"] == len(rows)
    assert insights["daily"] and insights["exits"]["admitted"] >= 0 and set(insights["by_phase"]) <= {"phase1", "phase2", "before", "between", "adjustment", "instruction", "after"}


def test_export_pooling_rule() -> None:
    cohort = synthetic_cohort(n_sections=8, joins_per_section=4)
    cal = TermCalendar("2272", "x", *([pd.Timestamp("2026-10-26").date()] * 8))
    tables = course_tables(cohort, cal, min_n=30)
    # each course has 4 joins x 6 positions = 24 rows spread over buckets: every cell is pooled
    for entry in tables.values():
        for cell in entry["buckets"].values():
            assert cell["pooled"] is not False and "n_course" in cell and "sections_course" in cell
    big = synthetic_cohort(n_sections=8, joins_per_section=40)
    assert all(cell["pooled"] is not False for e in course_tables(big, cal, min_n=30, estimate_level="dept").values() for cell in e["buckets"].values())  # department level: every cell a pointer
    tables = course_tables(big, cal, min_n=30)  # course by default
    unpooled = [cell for e in tables.values() for cell in e["buckets"].values() if cell["pooled"] is False]
    assert unpooled and all(cell["n"] >= 30 for cell in unpooled)


def test_export_empty(tmp_path: Path) -> None:
    cal = TermCalendar("2272", "x", *([pd.Timestamp("2026-10-26").date()] * 8))
    empty = synthetic_cohort(n_sections=1, joins_per_section=1).iloc[0:0]
    index_path, meta_path = export_site_tables(empty, cal, tmp_path)
    meta = json.loads(meta_path.read_text())
    assert json.loads(index_path.read_text())["courses"] == [] and meta["cohort_rows"] == 0 and meta["subject_files"] == {}
    assert json.loads((tmp_path / "pooled.json").read_text())["all"] == {} and json.loads((tmp_path / "insights.json").read_text())["counts"]["rows"] == 0
    assert meta["deadline"] == "2026-10-26" and meta["instruction_start"] == "2026-10-26" and meta["positions"] == []


def test_run_too_small_writes_notes(tmp_path: Path) -> None:
    panel, identity, cal = sim_inputs()
    first_days = panel["run_started_at"] < panel["run_started_at"].min() + timedelta(days=3)
    few = panel[first_days & panel["section_id"].isin(sorted(panel["section_id"].unique())[:2])]
    res = run_analysis(few, identity, cal, tmp_path, join_every_min=1440)
    assert any("too small" in n for n in res.notes) and res.cox_summary is None and (res.out_dir / "report.md").exists()


def _two_course_catalog(tmp_path: Path, keys: list[str]) -> Path:
    """A catalog.json with, per course, a lecture (its instructor) and a discussion (its GSI)."""
    sections = []
    for key in keys:
        subject, number = key.split()
        for component, cls, name in (("LEC", "001", f"Prof {subject}"), ("DIS", "101", f"GSI {subject}")):
            sections.append({"section_id": "", "url_path": f"/content/x-{subject}-{number}-{cls}".lower(), "course_key": key, "subject": subject, "catalog_number": number, "class_number": cls, "section_number": cls, "component": component, "title": f"Title of {key}", "instructors": name})
    path = tmp_path / "catalog" / "2272" / "catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"term_id": "2272", "sections": sections}), encoding="utf-8")
    return path


def test_run_writes_titles_from_the_catalog(tmp_path: Path) -> None:
    """run_analysis(catalog=) hands the catalog to the site export: titles.json for the index's courses, lecture names only."""
    panel, identity, cal = sim_inputs()
    few = panel[panel["section_id"].isin(sorted(panel["section_id"].unique())[:2])]
    keys = sorted(identity.loc[identity["section_id"].isin(few["section_id"]), "course_key"].unique())
    catalog = _two_course_catalog(tmp_path, keys)
    res = run_analysis(few, identity, cal, tmp_path / "out", site_dir=tmp_path / "site", join_every_min=1440, catalog=catalog)
    index_path, meta_path = res.site_files
    assert json.loads(meta_path.read_text())["titles_file"] == "titles.json"
    titles = json.loads((tmp_path / "site" / "titles.json").read_text())
    index_keys = [r["key"] for r in json.loads(index_path.read_text())["courses"]]
    assert titles["catalog_term_id"] == "2272" and index_keys and set(index_keys) <= set(keys)
    assert titles["courses"] == {k: {"title": f"Title of {k}", "instructors": [f"Prof {k.split()[0]}"]} for k in index_keys}
    # without a catalog there is no titles file and no meta key, as in export_site_tables
    res = run_analysis(few, identity, cal, tmp_path / "out", site_dir=tmp_path / "site", join_every_min=1440)
    assert not (tmp_path / "site" / "titles.json").exists() and "titles_file" not in json.loads(res.site_files[1].read_text())


def test_cli_passes_the_catalog_to_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """`python -m analysis.run --catalog <catalog.json>` reaches run_analysis(catalog=); a missing file is refused before any work."""
    seen: list[dict] = []

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        seen.append(kwargs)
        return SimpleNamespace(out_dir=tmp_path, flows_summary={}, cohort_rows={}, notes=[], figures=[])

    monkeypatch.setattr(run, "run_analysis", fake_run)
    monkeypatch.setattr(run, "load_panel", lambda root, term: pd.DataFrame())
    monkeypatch.setattr(run, "section_identity", lambda root, term: pd.DataFrame())
    catalog = _two_course_catalog(tmp_path, ["MATH 1"])
    base = ["--data-root", str(tmp_path), "--term-id", "2272", "--data-log", str(tmp_path / "no_log.md"), "--out", str(tmp_path / "out")]
    assert run.main([*base, "--catalog", str(catalog)]) == 0
    assert run.main(base) == 0
    assert [kw["catalog"] for kw in seen] == [catalog, None]
    capsys.readouterr()
    with pytest.raises(SystemExit):
        run.main([*base, "--catalog", str(tmp_path / "absent.json")])
    assert "no such file" in capsys.readouterr().err and len(seen) == 2


def _regime_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "analysis.run" and r.levelno == logging.WARNING and "regime boundary" in r.getMessage()]


def test_spans_phase1_end() -> None:
    """Observations on both sides of 00:00 UTC after ``phase1_end`` (the calendar's UTC-date convention) span it."""
    _, _, cal = sim_inputs()
    d = cal.phase1_end + timedelta(days=1)
    boundary = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    def fl(h0: float, h1: float) -> pd.DataFrame:
        return pd.DataFrame({"t0": [boundary + timedelta(hours=h0)], "t1": [boundary + timedelta(hours=h1)]})

    assert spans_phase1_end(fl(-1, 1), cal)
    assert spans_phase1_end(fl(-1, 0), cal)  # the last observation falls on the first day after Phase 1
    assert not spans_phase1_end(fl(-2, -1), cal)  # all of it in Phase 1
    assert not spans_phase1_end(fl(0, 1), cal)  # all of it after (the Fall 2026 own data)
    assert not spans_phase1_end(fl(0, 1).iloc[0:0], cal)


def test_cox_fit_across_phase1_end_logs_one_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """The Cox model is calibrated within a regime and wrong across the Phase 1 to Phase 2 shift:
    a fit on observations that span the end of Phase 1 says so once, as a WARNING; no model change."""
    panel, identity, cal = sim_inputs()
    few = panel[panel["section_id"].isin(sorted(panel["section_id"].unique())[:2])]
    with caplog.at_level(logging.WARNING, logger="analysis.run"):
        res = run_analysis(few, identity, cal, tmp_path / "spans", join_every_min=1440)
    assert res.cox_summary is not None  # the fit ran
    hits = _regime_warnings(caplog)
    assert len(hits) == 1
    assert cal.phase1_end.isoformat() in hits[0].getMessage() and "report-only" in hits[0].getMessage()
    # the same panel under a calendar whose Phase 1 ended before the data began: no boundary inside, no warning
    caplog.clear()
    day0 = pd.Timestamp(panel["run_started_at"].min()).date()
    after = dataclasses.replace(cal, phase1_start=day0 - timedelta(days=10), phase1_end=day0 - timedelta(days=1))
    with caplog.at_level(logging.WARNING, logger="analysis.run"):
        res = run_analysis(few, identity, after, tmp_path / "after", join_every_min=1440)
    assert res.cox_summary is not None and _regime_warnings(caplog) == []


def test_cut_at_last_auto_is_off_by_default_and_cuts_when_asked(tmp_path: Path) -> None:
    """``cut_at_last_auto`` (CLI ``--cut-at-last-auto``) is off by default. On a simulated panel whose
    last automatic run falls inside the data, turning it on places no joiner after the cut and ends
    every row by it; meta.json records the cut. With the run after the data ends the cohort files
    are byte-identical to a run without the option."""
    panel, identity, cal = sim_inputs()
    few = panel[panel["section_id"].isin(sorted(panel["section_id"].unique())[:4])]
    day0 = pd.Timestamp(panel["run_started_at"].min()).date()
    inside = dataclasses.replace(cal, last_auto_waitlist=day0 + timedelta(days=10))
    off = run_analysis(few, identity, inside, tmp_path / "off", site_dir=tmp_path / "off_site", join_every_min=240)
    on = run_analysis(few, identity, inside, tmp_path / "on", site_dir=tmp_path / "on_site", join_every_min=240, cut_at_last_auto="pacific")
    cut = last_auto_cut(inside, "pacific")
    c_off = pd.read_parquet(off.out_dir / "cohort_central.parquet")
    c_on = pd.read_parquet(on.out_dir / "cohort_central.parquet")
    assert (pd.to_datetime(c_off["join_time"], utc=True) >= cut).any() and len(c_on) < len(c_off)  # the panel spans the cut
    join = pd.to_datetime(c_on["join_time"], utc=True)
    assert (join < cut).all() and (join + pd.to_timedelta(c_on["duration_days"], unit="D") <= cut + timedelta(seconds=1)).all()
    assert json.loads(off.site_files[1].read_text()).get("cohort_cut") is None
    assert json.loads(on.site_files[1].read_text())["cohort_cut"] == {"at": cut.isoformat(), "instant": "pacific", "rule": "last_auto_waitlist"}
    assert any("cut at" in n for n in on.notes) and not any("cut at" in n for n in off.notes)
    assert on.cohort_rows["central"] == len(c_on)
    # the simulated term's own last run (day 34) is after the data (21 days): the option changes nothing
    a = run_analysis(few, identity, cal, tmp_path / "a", join_every_min=240)
    b = run_analysis(few, identity, cal, tmp_path / "b", join_every_min=240, cut_at_last_auto="pacific")
    for s in ("optimistic", "central", "pessimistic"):
        assert (a.out_dir / f"cohort_{s}.parquet").read_bytes() == (b.out_dir / f"cohort_{s}.parquet").read_bytes()
    for bad in ("utc", "eastern"):
        with pytest.raises(ValueError):
            run_analysis(few, identity, cal, tmp_path / "bad", cut_at_last_auto=bad)


def test_cli_cut_flag_defaults_off_and_takes_an_instant(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--cut-at-last-auto`` means the Pacific instant, the only one offered; absent, off."""
    import analysis.run as run_mod

    seen: list = []
    monkeypatch.setattr(run_mod, "load_panel", lambda root, term: pd.DataFrame())
    monkeypatch.setattr(run_mod, "section_identity", lambda root, term: pd.DataFrame())

    class _Result:
        out_dir, flows_summary, cohort_rows, notes, figures = tmp_path, {}, {}, [], []

    monkeypatch.setattr(run_mod, "run_analysis", lambda *a, **k: seen.append(k.get("cut_at_last_auto")) or _Result())
    base = ["--data-root", str(tmp_path), "--term-id", "2272", "--no-site", "--data-log", str(tmp_path / "none.md")]
    for extra in ([], ["--cut-at-last-auto"]):
        assert run_mod.main(base + extra) == 0
    assert seen == [None, "pacific"]
    with pytest.raises(SystemExit):
        run_mod.main(base + ["--cut-at-last-auto", "utc"])

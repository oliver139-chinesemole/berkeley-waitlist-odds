"""Conservation and determinism checks on the simulator in analysis.synthetic."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.synthetic import (
    BASE_TIME,
    PANEL_COLUMNS,
    STUDENT_COLUMNS,
    TRUE_FLOW_COLUMNS,
    TRUE_FLOWS_COLUMNS,
    SimConfig,
    simulate,
)

SMALL = SimConfig(seed=7, n_sections=8, days=3)
N_RUNS = int(SMALL.days * 1440 / SMALL.step_min) + 1


def _minutes(series: pd.Series) -> np.ndarray:
    """Minutes since BASE_TIME; NaT becomes NaN."""
    return ((series - BASE_TIME).dt.total_seconds() / 60.0).to_numpy(dtype="float64")


def _queued_matrix(times: np.ndarray, students: pd.DataFrame) -> np.ndarray:
    """(len(times), len(students)) boolean: student queued at each time (join <= t < clear/drop)."""
    join = _minutes(students["join_time"])[None, :]
    clear = _minutes(students["clear_time"])[None, :]
    drop = _minutes(students["drop_time"])[None, :]
    t = times[:, None]
    return (join <= t) & ~(clear <= t) & ~(drop <= t)


@pytest.fixture(scope="module")
def sim() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return simulate(SMALL)


def test_panel_shape_and_dtypes(sim) -> None:
    panel, _, _ = sim
    assert list(panel.columns) == list(PANEL_COLUMNS)
    for col in ("enrolled_count", "enroll_capacity", "waitlist_count", "waitlist_capacity", "reserved_count", "open_reserved"):
        assert str(panel[col].dtype) == "Int32", col
    for col in ("section_id", "status", "section_status", "source", "scope", "kind", "term_id"):
        assert str(panel[col].dtype) == "string", col
    assert str(panel["observed"].dtype) == "boolean"
    assert str(panel["run_started_at"].dt.tz) == "UTC"
    assert len(panel) == SMALL.n_sections * N_RUNS
    assert panel.groupby("section_id").size().eq(N_RUNS).all()
    runs = panel["run_started_at"].drop_duplicates().sort_values()
    assert runs.iloc[0] == BASE_TIME and (runs.diff().dropna() == pd.Timedelta(int(SMALL.step_min), unit="m")).all()
    # rebuild_panel order: run_started_at then section_id; run 0 is a baseline observed for every section
    assert panel.equals(panel.sort_values(["run_started_at", "section_id"], kind="stable").reset_index(drop=True))
    first = panel[panel["run_started_at"] == BASE_TIME]
    assert first["observed"].all() and (first["kind"] == "baseline").all()
    assert (panel.loc[panel["run_started_at"] != BASE_TIME, "kind"] == "delta").all()
    assert panel["reserved_count"].isna().all() and panel["open_reserved"].isna().all()


def test_counts_stay_within_capacity(sim) -> None:
    panel, _, _ = sim
    assert (panel["enrolled_count"] <= panel["enroll_capacity"]).all()
    assert (panel["waitlist_count"] <= panel["waitlist_capacity"]).all()
    assert (panel["enrolled_count"] >= 0).all() and (panel["waitlist_count"] >= 0).all()
    assert panel.groupby("section_id")["enroll_capacity"].nunique().eq(1).all()
    # a section with open seats never carries a waitlist: the queue is drained by the pending processing run
    # (except while that run is still pending), so status is consistent with the counts
    open_seats = panel["enrolled_count"] < panel["enroll_capacity"]
    assert (panel.loc[open_seats, "status"] == "O").all()
    assert (panel.loc[~open_seats, "status"].isin(["W", "C"])).all()


def test_waitlist_count_equals_queued_students_at_every_sample(sim) -> None:
    panel, _, students = sim
    for section_id, rows in panel.groupby("section_id"):
        rows = rows.sort_values("run_started_at")
        group = students[students["section_id"] == section_id]
        queued = _queued_matrix(_minutes(rows["run_started_at"]), group).sum(axis=1)
        observed = rows["observed"].to_numpy(dtype=bool)
        wl = rows["waitlist_count"].to_numpy(dtype="int64")
        assert np.array_equal(wl[observed], queued[observed]), section_id
        # unobserved rows carry the previous row's counts forward, as rebuild_panel does
        enr = rows["enrolled_count"].to_numpy(dtype="int64")
        idx = np.flatnonzero(~observed)
        assert np.array_equal(wl[idx], wl[idx - 1]) and np.array_equal(enr[idx], enr[idx - 1]), section_id


def test_true_flows_keys_and_conservation(sim) -> None:
    panel, truth, _ = sim
    assert list(truth.columns) == list(TRUE_FLOWS_COLUMNS)
    for col in (*TRUE_FLOW_COLUMNS, "n_events"):
        assert str(truth[col].dtype) == "Int64", col
    assert (truth[list(TRUE_FLOW_COLUMNS)].sum(axis=1) == truth["n_events"]).all()
    observed = panel[panel["observed"].astype(bool)].sort_values(["section_id", "run_started_at"])
    nxt = observed.groupby("section_id")[["run_started_at", "enrolled_count", "waitlist_count"]].shift(-1)
    pairs = observed[nxt["run_started_at"].notna()]
    nxt = nxt[nxt["run_started_at"].notna()]
    expected = pd.DataFrame({"section_id": pairs["section_id"].to_numpy(), "t0": pairs["run_started_at"].to_numpy(), "t1": nxt["run_started_at"].to_numpy()})
    expected["t0"] = pd.to_datetime(expected["t0"], utc=True)
    expected["t1"] = pd.to_datetime(expected["t1"], utc=True)
    expected["section_id"] = expected["section_id"].astype("string")
    expected["dE"] = (nxt["enrolled_count"].astype("int64") - pairs["enrolled_count"].astype("int64")).to_numpy()
    expected["dW"] = (nxt["waitlist_count"].astype("int64") - pairs["waitlist_count"].astype("int64")).to_numpy()
    merged = truth.merge(expected, on=["section_id", "t0", "t1"], how="outer", indicator=True)
    assert (merged["_merge"] == "both").all() and len(merged) == len(truth)
    assert (merged["dE"] == merged["admits"] + merged["enr_joins"] - merged["enr_drops"]).all()
    assert (merged["dW"] == merged["wl_joins"] - merged["admits"] - merged["wl_drops"]).all()
    assert truth.equals(truth.sort_values(["section_id", "t0"], kind="stable").reset_index(drop=True))


def test_students_consistent_with_true_flows(sim) -> None:
    panel, truth, students = sim
    assert list(students.columns) == list(STUDENT_COLUMNS)
    assert students["student_id"].is_unique and students["student_id"].is_monotonic_increasing
    join, clear, drop = (_minutes(students[c]) for c in ("join_time", "clear_time", "drop_time"))
    assert not np.any(~np.isnan(clear) & ~np.isnan(drop))  # a student clears or drops, never both
    assert np.all(np.isnan(clear) | (clear > join)) and np.all(np.isnan(drop) | (drop > join))
    assert (students["position_at_join"] >= 1).all()
    last_observed = panel[panel["observed"].astype(bool)].groupby("section_id")["run_started_at"].max()
    totals = truth.groupby("section_id")[list(TRUE_FLOW_COLUMNS)].sum()
    for section_id, group in students.groupby("section_id"):
        end = float((last_observed[section_id] - BASE_TIME).total_seconds() / 60.0)
        j, c, d = (_minutes(group[col]) for col in ("join_time", "clear_time", "drop_time"))
        assert int(totals.at[section_id, "admits"]) == int(np.sum(c <= end)), section_id
        assert int(totals.at[section_id, "wl_drops"]) == int(np.sum(d <= end)), section_id
        assert int(totals.at[section_id, "wl_joins"]) == int(np.sum((j > 0) & (j <= end))), section_id
        # FIFO: cleared students clear in join order
        cleared = c[~np.isnan(c)]
        assert np.all(np.diff(cleared) >= 0), section_id
        # position_at_join counts the students queued ahead plus the student
        ids = group["student_id"].to_numpy()
        queued = _queued_matrix(j, group)  # (student, other)
        ahead = (queued & (ids[None, :] < ids[:, None])).sum(axis=1)
        assert np.array_equal(ahead + 1, group["position_at_join"].to_numpy(dtype="int64")), section_id
    assert int(truth["admits"].sum()) == int(np.sum(~np.isnan(clear) & (clear <= np.vectorize(lambda s: float((last_observed[s] - BASE_TIME).total_seconds() / 60.0))(students["section_id"].astype(str).to_numpy()))))


def test_deterministic_for_a_seed() -> None:
    cfg = SimConfig(seed=3, n_sections=3, days=1)
    a = simulate(cfg)
    b = simulate(cfg)
    for x, y in zip(a, b):
        pd.testing.assert_frame_equal(x, y)
    c = simulate(SimConfig(seed=4, n_sections=3, days=1))
    assert not a[0].equals(c[0])


def test_full_observation_and_gaps() -> None:
    cfg = SimConfig(seed=5, n_sections=4, days=2, observe_prob=1.0)
    panel, truth, _ = simulate(cfg)
    n_steps = int(cfg.days * 1440 / cfg.step_min)
    assert panel["observed"].all() and len(truth) == cfg.n_sections * n_steps
    assert (truth["t1"] - truth["t0"] == pd.Timedelta(int(cfg.step_min), unit="m")).all()
    panel, truth, _ = simulate(SimConfig(seed=5, n_sections=4, days=2, observe_prob=0.5))
    share = float(panel.loc[panel["run_started_at"] != BASE_TIME, "observed"].mean())
    assert 0.4 < share < 0.6
    assert (truth["t1"] - truth["t0"] > pd.Timedelta(int(cfg.step_min), unit="m")).any()


def test_bad_config() -> None:
    with pytest.raises(ValueError):
        simulate(SimConfig(seed=1, n_sections=0))

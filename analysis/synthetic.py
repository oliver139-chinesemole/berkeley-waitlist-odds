"""Individual-student waitlist simulator for validating the flow reconstruction.

See docs/DESIGN_A4.md section 4. ``simulate`` runs a continuous-time
simulation of individual students on FIFO waitlists, samples the counts every
``step_min`` minutes into a panel with the exact ``scraper.rebuild.rebuild_panel``
shape (plus ``term_id``), and returns the true per-interval flows and the
per-student history so ``analysis.flows`` and ``analysis.positions`` can be
checked against a known answer.

Rules, per section, with every rate in events per day per section:

* waitlist joins arrive as a Poisson process. A join that finds an open seat
  and an empty queue enrols directly (a direct enrolment, ``enr_joins``);
  otherwise it appends to the queue (``wl_joins``). A join that finds the
  queue at waitlist capacity is turned away and leaves no trace.
* enrolled drops arrive as a Poisson process; each opens a seat
  (``enr_drops``).
* waitlist drops arrive as a Poisson process; each removes a uniformly random
  queue member (``wl_drops``) and does nothing on an empty queue.
* while a seat is open and the queue is non-empty, one processing run is
  pending: it fires after a delay drawn uniformly from ``admit_delay_min``
  and admits the head of the queue into every open seat (batch processing,
  ``admits``). A new run is scheduled the next time a seat opens with a
  non-empty queue.

Sampling: the state at ``t_s = s * step_min`` includes every event with time
``<= t_s``; the true flows of an interval ``(t0, t1]`` between two observed
runs are the events with ``t0 < time <= t1``. Each section is unobserved at a
run with probability ``1 - observe_prob``; an unobserved row carries the
previous row's counts forward with ``observed == False`` exactly as
``rebuild_panel`` does. Run 0 is always observed (a baseline).

All randomness comes from one ``numpy.random.Generator`` seeded with
``cfg.seed``, so the result is a deterministic function of the config.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

BASE_TIME = pd.Timestamp("2026-11-01T00:00:00Z")
TERM_ID = "2268"
SOURCE = "classes_site"
FIRST_SECTION_ID = 90001

PANEL_COLUMNS = (
    "section_id",
    "run_started_at",
    "enrolled_count",
    "enroll_capacity",
    "waitlist_count",
    "waitlist_capacity",
    "reserved_count",
    "open_reserved",
    "status",
    "section_status",
    "observed",
    "source",
    "scope",
    "kind",
    "term_id",
)
TRUE_FLOW_COLUMNS = ("admits", "wl_joins", "wl_drops", "enr_joins", "enr_drops")
TRUE_FLOWS_COLUMNS = ("section_id", "t0", "t1", *TRUE_FLOW_COLUMNS, "n_events")
STUDENT_COLUMNS = ("student_id", "section_id", "join_time", "position_at_join", "clear_time", "drop_time")

# event kinds
_JOIN, _ENR_DROP, _WL_DROP, _ADMIT = 0, 1, 2, 3
# columns of the per-step flow array
_F_ADMITS, _F_WL_JOINS, _F_WL_DROPS, _F_ENR_JOINS, _F_ENR_DROPS, _F_EVENTS = range(6)


@dataclass
class SimConfig:
    seed: int
    n_sections: int = 40
    days: float = 14
    step_min: float = 30
    capacity: tuple[int, int] = (20, 300)
    initial_fill: float = 0.9
    join_rate_per_day: float = 6.0
    enr_drop_rate_per_day: float = 2.0
    wl_drop_rate_per_day: float = 1.5
    admit_delay_min: tuple[float, float] = (0, 240)  # seat opens -> head of queue admitted after this delay (batch processing)
    observe_prob: float = 0.97  # each run observes a section with this probability (gaps)


class _Students:
    """Column lists for every student who ever joined a waitlist (times in minutes)."""

    def __init__(self) -> None:
        self.section_id: list[str] = []
        self.join_time: list[float] = []
        self.position: list[int] = []
        self.clear_time: list[float] = []
        self.drop_time: list[float] = []

    def add(self, section_id: str, t: float, position: int) -> int:
        self.section_id.append(section_id)
        self.join_time.append(t)
        self.position.append(position)
        self.clear_time.append(math.nan)
        self.drop_time.append(math.nan)
        return len(self.join_time) - 1

    def frame(self) -> pd.DataFrame:
        n = len(self.join_time)
        return pd.DataFrame(
            {
                "student_id": np.arange(n, dtype="int64"),
                "section_id": pd.array(self.section_id, dtype="string"),
                "join_time": _stamps(np.asarray(self.join_time, dtype="float64")),
                "position_at_join": pd.array(self.position, dtype="Int64"),
                "clear_time": _stamps(np.asarray(self.clear_time, dtype="float64")),
                "drop_time": _stamps(np.asarray(self.drop_time, dtype="float64")),
            },
            columns=list(STUDENT_COLUMNS),
        )


def _stamps(minutes: np.ndarray) -> pd.Series:
    """Minutes since BASE_TIME (NaN -> NaT) as tz-aware UTC timestamps."""
    return pd.Series(BASE_TIME + pd.to_timedelta(minutes, unit="m"))


def _poisson_times(rng: np.random.Generator, rate_per_day: float, horizon_min: float) -> np.ndarray:
    n = int(rng.poisson(rate_per_day * horizon_min / 1440.0)) if rate_per_day > 0 else 0
    return np.sort(rng.uniform(0.0, horizon_min, n))


def _simulate_section(
    rng: np.random.Generator,
    cfg: SimConfig,
    section_id: str,
    students: _Students,
    sample_times: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    """One section. Returns (enrolled per sample, waitlist per sample,
    per-step flow counts of shape (n_runs, 6), capacity, waitlist capacity)."""
    n_runs = len(sample_times)
    step = float(cfg.step_min)
    horizon = float(sample_times[-1])
    cap = int(rng.integers(cfg.capacity[0], cfg.capacity[1] + 1))
    wl_cap = max(10, cap // 5)
    fill = float(rng.uniform(cfg.initial_fill - 0.1, cfg.initial_fill + 0.1))
    enrolled = int(min(cap, max(0, round(cap * fill))))
    queue: list[int] = []
    if enrolled >= cap:  # a full section may start with a short waitlist
        for _ in range(int(rng.integers(0, 4))):
            queue.append(students.add(section_id, 0.0, len(queue) + 1))

    heap: list[tuple[float, int, int]] = []
    seq = 0
    for kind, rate in ((_JOIN, cfg.join_rate_per_day), (_ENR_DROP, cfg.enr_drop_rate_per_day), (_WL_DROP, cfg.wl_drop_rate_per_day)):
        for t in _poisson_times(rng, rate, horizon):
            heap.append((float(t), seq, kind))
            seq += 1
    heapq.heapify(heap)

    enrolled_s = np.zeros(n_runs, dtype="int64")
    waitlist_s = np.zeros(n_runs, dtype="int64")
    flows = np.zeros((n_runs, 6), dtype="int64")
    next_sample = 0
    pending = False
    lo, hi = cfg.admit_delay_min

    def schedule(now: float) -> None:
        nonlocal pending, seq
        if enrolled < cap and queue and not pending:
            pending = True
            heapq.heappush(heap, (now + float(rng.uniform(lo, hi)), seq, _ADMIT))
            seq += 1

    while heap:
        t, _, kind = heapq.heappop(heap)
        if t > horizon:
            break
        while next_sample < n_runs and sample_times[next_sample] < t:
            enrolled_s[next_sample] = enrolled
            waitlist_s[next_sample] = len(queue)
            next_sample += 1
        s = min(n_runs - 1, int(math.ceil(t / step)))  # the sample that first includes this event
        if kind == _JOIN:
            if enrolled < cap and not queue:
                enrolled += 1
                flows[s, _F_ENR_JOINS] += 1
                flows[s, _F_EVENTS] += 1
            elif len(queue) < wl_cap:
                queue.append(students.add(section_id, t, len(queue) + 1))
                flows[s, _F_WL_JOINS] += 1
                flows[s, _F_EVENTS] += 1
                schedule(t)
        elif kind == _ENR_DROP:
            if enrolled > 0:
                enrolled -= 1
                flows[s, _F_ENR_DROPS] += 1
                flows[s, _F_EVENTS] += 1
                schedule(t)
        elif kind == _WL_DROP:
            if queue:
                sid = queue.pop(int(rng.integers(len(queue))))
                students.drop_time[sid] = t
                flows[s, _F_WL_DROPS] += 1
                flows[s, _F_EVENTS] += 1
        else:  # _ADMIT: a processing run fills every open seat from the head of the queue
            pending = False
            n_admit = min(cap - enrolled, len(queue))
            for _ in range(n_admit):
                sid = queue.pop(0)
                students.clear_time[sid] = t
                enrolled += 1
                flows[s, _F_ADMITS] += 1
                flows[s, _F_EVENTS] += 1
    while next_sample < n_runs:
        enrolled_s[next_sample] = enrolled
        waitlist_s[next_sample] = len(queue)
        next_sample += 1
    return enrolled_s, waitlist_s, flows, cap, wl_cap


def simulate(cfg: SimConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the simulation. Returns ``(panel, true_flows, students)``.

    ``panel``: one row per section per run in the ``rebuild_panel`` shape plus
    ``term_id``, pandas nullable dtypes, sorted by ``run_started_at`` then
    ``section_id``.

    ``true_flows``: one row per section per pair of consecutive observed runs
    (keys ``section_id, t0, t1`` as in ``analysis.flows.interval_flows``) with
    the true ``admits, wl_joins, wl_drops, enr_joins, enr_drops`` in
    ``(t0, t1]`` and ``n_events``, their sum.

    ``students``: one row per student who ever joined a waitlist:
    ``student_id`` (assigned in join order, so a smaller id is ahead in the
    queue), ``section_id``, ``join_time``, ``position_at_join`` (1-based,
    counting the student), ``clear_time`` (NaT if never admitted) and
    ``drop_time`` (NaT if never dropped).
    """
    if cfg.step_min <= 0 or cfg.days <= 0 or cfg.n_sections <= 0:
        raise ValueError("step_min, days and n_sections must be positive")
    rng = np.random.default_rng(cfg.seed)
    step = float(cfg.step_min)
    n_steps = int(math.floor(cfg.days * 1440.0 / step + 1e-9))
    n_runs = n_steps + 1
    sample_times = np.arange(n_runs, dtype="float64") * step
    run_times = _stamps(sample_times).to_numpy()
    students = _Students()

    panel_pieces: list[pd.DataFrame] = []
    truth_pieces: list[pd.DataFrame] = []
    for i in range(cfg.n_sections):
        section_id = str(FIRST_SECTION_ID + i)
        enrolled_s, waitlist_s, flows, cap, wl_cap = _simulate_section(rng, cfg, section_id, students, sample_times)
        observed = rng.random(n_runs) < cfg.observe_prob
        observed[0] = True
        # unobserved rows carry the last observed counts forward, as rebuild_panel does
        enrolled_p = enrolled_s.copy()
        waitlist_p = waitlist_s.copy()
        for s in range(1, n_runs):
            if not observed[s]:
                enrolled_p[s] = enrolled_p[s - 1]
                waitlist_p[s] = waitlist_p[s - 1]
        status = np.where(enrolled_p < cap, "O", np.where(waitlist_p < wl_cap, "W", "C"))
        panel_pieces.append(
            pd.DataFrame(
                {
                    "section_id": section_id,
                    "run_started_at": run_times,
                    "enrolled_count": enrolled_p,
                    "enroll_capacity": cap,
                    "waitlist_count": waitlist_p,
                    "waitlist_capacity": wl_cap,
                    "reserved_count": pd.array([pd.NA] * n_runs, dtype="Int32"),
                    "open_reserved": pd.array([pd.NA] * n_runs, dtype="Int32"),
                    "status": status,
                    "section_status": "A",
                    "observed": observed,
                    "source": SOURCE,
                    "scope": "full",
                    "kind": np.where(np.arange(n_runs) == 0, "baseline", "delta"),
                    "term_id": TERM_ID,
                }
            )
        )
        obs_idx = np.flatnonzero(observed)
        cum = np.cumsum(flows, axis=0)
        d = cum[obs_idx[1:]] - cum[obs_idx[:-1]]
        truth_pieces.append(
            pd.DataFrame(
                {
                    "section_id": section_id,
                    "t0": run_times[obs_idx[:-1]],
                    "t1": run_times[obs_idx[1:]],
                    "admits": d[:, _F_ADMITS],
                    "wl_joins": d[:, _F_WL_JOINS],
                    "wl_drops": d[:, _F_WL_DROPS],
                    "enr_joins": d[:, _F_ENR_JOINS],
                    "enr_drops": d[:, _F_ENR_DROPS],
                    "n_events": d[:, _F_EVENTS],
                }
            )
        )

    panel = pd.concat(panel_pieces, ignore_index=True)
    for col in ("enrolled_count", "enroll_capacity", "waitlist_count", "waitlist_capacity", "reserved_count", "open_reserved"):
        panel[col] = panel[col].astype("Int32")
    for col in ("section_id", "status", "section_status", "source", "scope", "kind", "term_id"):
        panel[col] = panel[col].astype("string")
    panel["observed"] = panel["observed"].astype("boolean")
    panel["run_started_at"] = pd.to_datetime(panel["run_started_at"], utc=True)
    panel = panel.sort_values(["run_started_at", "section_id"], kind="stable").reset_index(drop=True)[list(PANEL_COLUMNS)]

    true_flows = pd.concat(truth_pieces, ignore_index=True)
    true_flows["section_id"] = true_flows["section_id"].astype("string")
    for col in ("t0", "t1"):
        true_flows[col] = pd.to_datetime(true_flows[col], utc=True)
    for col in (*TRUE_FLOW_COLUMNS, "n_events"):
        true_flows[col] = true_flows[col].astype("Int64")
    true_flows = true_flows.sort_values(["section_id", "t0"], kind="stable").reset_index(drop=True)[list(TRUE_FLOWS_COLUMNS)]

    return panel, true_flows, students.frame()


__all__ = ["BASE_TIME", "PANEL_COLUMNS", "STUDENT_COLUMNS", "TRUE_FLOWS_COLUMNS", "TRUE_FLOW_COLUMNS", "SimConfig", "simulate"]

# A4 design contract — flow reconstruction

Binding interfaces for step A4 (docs/FINISH_PLAN_WAITLIST.md A4; docs/SPEC.md section 5). Input is the rebuilt panel from `scraper.rebuild.rebuild_panel` (docs/DESIGN_A2.md section 3). Output is a per-section, per-interval table of reconstructed flows plus a FIFO position model for step A5. Everything is pure pandas; nothing here touches the network or the data branch except through `analysis/panel.py`.

Python package `analysis/` (already an empty directory). Tests in `tests/test_panel.py`, `tests/test_flows.py`, `tests/test_positions.py`, `tests/test_flows_synthetic.py`. `docs/ASSUMPTIONS.md` states every assumption below in plain English and is the artefact behind the word "documented" on the resume.

## 1. Panel loading (`analysis/panel.py`)

```python
@dataclass(frozen=True)
class Outage:
    start: datetime; end: datetime | None; kind: str; term_id: str | None; scope: str; note: str

def parse_data_log(path: Path = Path("docs/DATA_LOG.md")) -> list[Outage]
    # rows of the Entries table whose kind is outage, source_switch, schema or term_switch; a bare date is midnight UTC; end None = open

def load_panel(data_root: Path, term_id: str, *, start: date | None = None, end: date | None = None) -> pd.DataFrame
    # rebuild_panel(...) joined with identity columns (course_key, subject, catalog_number, class_number, section_number, component,
    # is_primary, session_id) taken from the latest snapshot row of each section_id across the data root; sorted by section_id, run_started_at

def section_identity(data_root: Path, term_id: str) -> pd.DataFrame
    # one row per section_id with the identity columns above and first_seen / last_seen run times
```

`load_panel` keeps the panel's dtypes (pandas nullable) and adds the identity columns as `string`. Sections whose identity cannot be found (impossible in practice) get `<NA>` identity.

`Outage.overlaps(t0, t1, term_id)`: an `outage` row with no end is open-ended (every interval after its start is censored); a `source_switch`, `schema` or `term_switch` row with no end is a point event and censors only the interval that contains its start; any row with an end is the span `[start, end)`. Rows carrying a term id apply only to that term. A `correction` row whose note says `starts <stamp>` closes the open row with that start, using the note's `end_utc is <stamp>` when present, else the correction's own start.

## 2. Interval flows (`analysis/flows.py`)

Unit: one row per section per pair of consecutive **observed** runs (`observed == True` at both ends; unobserved runs in between are skipped, which lengthens the interval). Rows are ordered by `section_id`, `t0`.

```python
FLOW_COLUMNS = ("admits", "wl_joins", "wl_drops", "enr_joins", "enr_drops")

def interval_flows(panel: pd.DataFrame, *, outages: list[Outage] = (), max_interval_min: float | None = None) -> pd.DataFrame
```

Output columns:

| column | type | meaning |
| --- | --- | --- |
| `section_id` | string | |
| `t0`, `t1` | datetime UTC | run_started_at of the two observed runs |
| `interval_min` | float | minutes between them |
| `d_enrolled`, `d_waitlist`, `d_capacity`, `d_wl_capacity` | Int64 | count differences t1 minus t0 |
| `enrolled0`, `capacity0`, `waitlist0`, `reserved0`, `open_reserved0` | Int64 | state at t0 (reserved fields nullable) |
| `full0` | boolean | `enrolled0 >= capacity0 - open_reserved0` when open_reserved0 is known, else `enrolled0 >= capacity0` |
| `admits` | Int64 | waitlist admits into enrolment |
| `wl_joins` | Int64 | joins to the waitlist |
| `wl_drops` | Int64 | voluntary or administrative drops from the waitlist |
| `enr_joins` | Int64 | direct enrolments (seat taken without passing through the waitlist) |
| `enr_drops` | Int64 | drops from enrolment |
| `expansion` | boolean | `d_capacity > 0` |
| `ambiguous` | boolean | more than one story fits (rules below) |
| `censored` | boolean | interval overlaps an outage or exceeds `max_interval_min`; flows are still computed but must be ignored by A5 |
| `rule` | string | the classification rule that fired (for audit) |

Classification, with `dE = d_enrolled`, `dW = d_waitlist` (net changes over the interval; flows are lower bounds, see ASSUMPTIONS 1):

1. `dE > 0 and dW < 0` (`rule="admit"`): `admits = min(dE, -dW)`. Leftover `dE - admits > 0` → `enr_joins`; leftover `-dW - admits > 0` → `wl_drops`. `ambiguous = dE != -dW`.
2. `dE > 0 and dW == 0` (`rule="enr_join"`): `enr_joins = dE`. `ambiguous = waitlist0 > 0` (an admit paired with a same-size join is invisible).
3. `dE > 0 and dW > 0` (`rule="join_and_enr_join"`): `wl_joins = dW`, `enr_joins = dE`, `ambiguous = waitlist0 > 0 or full0` (admits could hide inside).
4. `dE == 0 and dW > 0` (`rule="join"`): `wl_joins = dW`, `ambiguous = False`.
5. `dE == 0 and dW < 0` (`rule="wl_drop"`): `wl_drops = -dW`, `ambiguous = full0 and open_reserved0 in (0, NA)`? No: `ambiguous = False` (a drop is the only story when enrolment did not move) except when `d_capacity < 0` (capacity cut can purge a waitlist administratively; still `wl_drops`, note in `rule="wl_drop_capcut"`).
6. `dE < 0 and dW == 0` (`rule="enr_drop"`): `enr_drops = -dE`, `ambiguous = waitlist0 > 0 and full0` (a seat opened but nobody was admitted within the interval: batch processing, ASSUMPTIONS 5).
7. `dE < 0 and dW < 0` (`rule="enr_drop_wl_drop"`): `enr_drops = -dE`, `wl_drops = -dW`, `ambiguous = True` (admits plus larger drops also fit).
8. `dE < 0 and dW > 0` (`rule="enr_drop_join"`): `enr_drops = -dE`, `wl_joins = dW`, `ambiguous = False`.
9. `dE == 0 and dW == 0` (`rule="none"`): all zero, `ambiguous = False`.

Tombstone rows (`section_status == "GONE"`) end a section's series: no interval is built across or after them. Rows with any null count at either end produce no interval.

## 3. FIFO position model (`analysis/positions.py`)

```python
SCENARIOS = ("optimistic", "central", "pessimistic")

def cumulative_flows(flows: pd.DataFrame) -> pd.DataFrame
    # per section: rows of flows with cum_admits, cum_wl_drops (censored intervals contribute 0 and set a `broken` flag from then on? No:
    # censored intervals contribute their flows but the row keeps censored=True so callers can stop at the first censored interval)

def time_to_clear(section_flows: pd.DataFrame, join_time: datetime, position: int, scenario: str) -> tuple[float | None, bool]
    # (minutes from join_time until the virtual waitlister clears, or None) and whether the outcome is censored
    # walk intervals with t0 >= join_time in order; effective position after each interval:
    #   optimistic:  k -= admits + wl_drops                  (every drop was ahead of the joiner)
    #   pessimistic: k -= admits                            (every drop was behind)
    #   central:     k -= admits + wl_drops * (k / waitlist0) when waitlist0 > 0 else admits   (drops uniform over the list)
    # clears at the first interval end where k <= 0 (time = t1 - join_time); stops with censored=True at the first censored interval,
    # at a tombstone, or at the end of data

def virtual_waitlisters(flows: pd.DataFrame, *, positions: Sequence[int] = (1, 3, 5, 10, 20, 40), scenario: str = "central") -> pd.DataFrame
    # one row per (section_id, join_time = each observed t0 with waitlist0 >= position, position): duration_min, event (1 cleared, 0 censored)
```

## 4. Synthetic validation (`analysis/synthetic.py`, `tests/test_flows_synthetic.py`)

```python
@dataclass
class SimConfig:
    seed: int; n_sections: int = 40; days: float = 14; step_min: float = 30
    capacity: tuple[int, int] = (20, 300); initial_fill: float = 0.9
    join_rate_per_day: float = 6.0; enr_drop_rate_per_day: float = 2.0; wl_drop_rate_per_day: float = 1.5
    admit_delay_min: tuple[float, float] = (0, 240)   # seat opens -> head of queue admitted after this delay (batch processing)
    observe_prob: float = 0.97                          # each run observes a section with this probability (gaps)

def simulate(cfg: SimConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
    # returns (panel, true_flows, students): panel in the rebuild_panel shape (one row per section per run, observed flag),
    # true_flows with the same keys as interval_flows plus true admits/wl_joins/wl_drops/enr_joins/enr_drops per (section, run interval),
    # students with join_time, position_at_join, clear_time (None if never), drop_time
```

Simulation rules: individual students; enrolled drops open a seat; when a seat is open and the waitlist is non-empty, the head of the queue is admitted after a random delay (batch processing); waitlist drops remove a uniformly random queue member; joins append. Counts are sampled every `step_min`; the panel marks a section unobserved with probability `1 - observe_prob` per run.

`tests/test_flows_synthetic.py` must assert, for `SimConfig(seed=1)`: totals of each flow type recovered within the bounds written in `docs/ASSUMPTIONS.md` section 7 (admits within 5%, joins within 5%, drops within 15%; exact when at most one event occurred in the interval); `time_to_clear` under the **central** scenario against the students' true clear times: median absolute error under 2 steps and no systematic bias beyond 1 step; optimistic and pessimistic bracket the truth for at least 90% of students who cleared. The test prints the recovery table so the numbers can be copied into ASSUMPTIONS.md section 7 and CLAIMS.md.

## 5. Assumptions document (`docs/ASSUMPTIONS.md`)

Sections, in this order: (1) net flows within an interval are lower bounds; (2) FIFO ordering; (3) unobserved drop positions and the three scenarios; (4) reserved seats break pure FIFO; (5) batch waitlist processing; (6) gaps from DATA_LOG are censoring, not zero flow; (7) validation results from the synthetic test with the exact numbers and the config that produced them; (8) what individual-level data would change. Plain prose, no marketing tone, no dashes.

## 6. Commands

`make flows TERM=2268` (Makefile target added now; `make analysis` arrives in A5) runs `python -m analysis.flows --data-root ./data-branch --term-id 2268 --out analysis/out/flows_2268.parquet` and prints a summary: sections, intervals, share ambiguous, share censored, totals per flow type. CLAIMS.md row 2's check becomes `test -f docs/ASSUMPTIONS.md && python -m pytest tests/test_flows_synthetic.py -q`.

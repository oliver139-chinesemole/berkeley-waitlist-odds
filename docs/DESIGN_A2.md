# A2 build contract — scraper and storage

This is the binding interface spec for step A2. Modules are built in parallel against it; do not change a signature here without updating this file. Facts about the sources are in `docs/PHASE0.md`; fixtures in `data/fixtures/`.

Python 3.12. Dependencies are pinned in `requirements.txt` (`pyarrow`, `pandas`, `tenacity`, `certifi`; `requests` is NOT used for classes.berkeley.edu because its TLS stack is blocked; it is fine for Berkeleytime and the SIS gateway). Tests use `pytest` and never touch the network.

## 1. Snapshot row schema (`scraper/schema.py`)

`SNAPSHOT_SCHEMA: pyarrow.Schema`, field order fixed:

| field | type | notes |
| --- | --- | --- |
| `fetched_at` | `timestamp[us, tz=UTC]` | actual fetch time of that row, never the scheduled time |
| `term_id` | `string` | SIS term id, e.g. `"2268"` (Fall 2026), `"2272"` (Spring 2027, to confirm) |
| `section_id` | `string` | SIS class section id = "Class #", e.g. `"30174"` |
| `course_key` | `string` | `"<SUBJECT> <CATALOG>"`, e.g. `"COMPSCI 61A"` |
| `subject` | `string` | `"COMPSCI"` (spaces removed, Berkeleytime convention) |
| `catalog_number` | `string` | `"61A"` |
| `class_number` | `string` | `"001"` |
| `section_number` | `string` | `"001"` |
| `component` | `string` | `"LEC"`, `"DIS"`, `"LAB"`, ... |
| `is_primary` | `bool` nullable | null when the source cannot tell |
| `session_id` | `string` | `"1"` for regular session |
| `enrolled_count` | `int32` | `enrollmentStatus.enrolledCount` |
| `enroll_capacity` | `int32` | `enrollmentStatus.maxEnroll` |
| `waitlist_count` | `int32` | `enrollmentStatus.waitlistedCount` |
| `waitlist_capacity` | `int32` | `enrollmentStatus.maxWaitlist` |
| `reserved_count` | `int32` nullable | `enrollmentStatus.reservedCount` |
| `open_reserved` | `int32` nullable | `enrollmentStatus.openReserved` |
| `status` | `string` | `enrollmentStatus.status.code`: `O` open, `C` closed, `W` waitlist ... |
| `section_status` | `string` nullable | section `status.code` (`A` active, `X` cancelled); tombstone rows use `"GONE"` |
| `source` | `string` | `"sis_api"`, `"classes_site"`, `"berkeleytime"` |

Functions:

```python
SNAPSHOT_SCHEMA: pa.Schema
COUNT_FIELDS = ("enrolled_count","enroll_capacity","waitlist_count","waitlist_capacity","reserved_count","open_reserved","status","section_status")
class SnapshotRow(TypedDict): ...            # one key per field above
def rows_to_table(rows: list[SnapshotRow]) -> pa.Table   # casts to SNAPSHOT_SCHEMA, raises SchemaError on any violation
def validate_table(table: pa.Table) -> None              # raises SchemaError if schema differs or section_id duplicates exist
class SchemaError(ValueError): ...
```

## 2. Storage layout (`scraper/storage.py`)

Root is the checkout of the `data` branch (`data_root`). Files are never rewritten.

```
snapshots/date=YYYY-MM-DD/HHMM-baseline.parquet   # every observed section, all rows
snapshots/date=YYYY-MM-DD/HHMM-delta.parquet      # only rows whose COUNT_FIELDS changed vs the previous observation of that section, plus tombstones
catalog/<term_id>/sections.json                   # section list for the term (classes_site only), refreshed at most daily
status.json                                       # last run summary (small, rewritten each run)
```

`HHMM` is `fetched_at` of the run start in UTC. Date partition is the UTC date.

Every parquet file carries key-value metadata (all values are strings, JSON-encoded where structured):

| key | meaning |
| --- | --- |
| `run_started_at` | ISO-8601 UTC |
| `term_id` | |
| `source` | |
| `kind` | `baseline` or `delta` |
| `scope` | `full` (whole term universe observed) or `priority` (priority list ∪ shard observed) |
| `shard` | `"k/n"` when scope is `priority` and rotating shards are on, else `""` |
| `priority_sha` | sha256 of the priority list file content when scope is `priority`, else `""` |
| `missing_ids` | JSON list of section ids that were in scope but failed to fetch (HTTP error, parse error) |
| `n_observed` | integer, sections successfully fetched in this run |
| `n_written` | rows in the file |

Functions:

```python
@dataclass
class RunMeta:  # mirrors the metadata table above
    run_started_at: datetime; term_id: str; source: str; kind: str; scope: str
    shard: str = ""; priority_sha: str = ""; missing_ids: list[str] = field(default_factory=list); n_observed: int = 0

def snapshot_path(data_root: Path, run_started_at: datetime, kind: str) -> Path
def write_snapshot(data_root: Path, table: pa.Table, meta: RunMeta) -> Path      # validates, refuses to overwrite, writes atomically (tmp + rename)
def list_snapshots(data_root: Path, date: date | None = None) -> list[Path]      # sorted by time
def read_snapshot(path: Path) -> tuple[pa.Table, RunMeta]
def latest_state(data_root: Path, term_id: str, as_of_date: date) -> pd.DataFrame | None
    # section_id-indexed frame of the most recent observed COUNT_FIELDS for that UTC date (baseline + deltas applied in order); None if no baseline that day
def compute_delta(previous: pd.DataFrame | None, observed: pa.Table, universe_ids: set[str] | None) -> pa.Table
    # rows in `observed` whose COUNT_FIELDS differ from `previous` (or are new); when `universe_ids` is given (scope=full) also emit a tombstone row
    # (section_status="GONE", counts copied from previous) for ids in previous that are neither in observed nor in universe_ids.
```

Rules: the first run of a UTC day writes a `baseline` regardless of scope (rows = everything observed). Later runs write `delta`. A run that observes zero sections writes nothing and exits non-zero (see fetch.py).

## 3. Rebuild (`scraper/rebuild.py`)

```python
def rebuild_panel(data_root: Path, term_id: str, start: date | None = None, end: date | None = None) -> pd.DataFrame
```

Output: one row per (section_id, run_started_at) for every run in range, columns = COUNT_FIELDS + `observed: bool` + `source` + `scope`. Semantics:

- For each run, the observed set is: scope `full` → every section id present in the baseline of that day ∪ ids in this file, minus `missing_ids`; scope `priority` → the priority list at `priority_sha` (`config/priority_courses.txt` history is not needed; the set is reconstructed from the section list in `catalog/<term>/sections.json` matched against the list) ∪ shard members, minus `missing_ids`. To keep this simple the delta file also stores `observed_ids` as a compact JSON list in metadata **only when scope is priority** (≤ 1,500 ids ≈ 10 KB); rebuild uses it directly.
- Observed and unchanged → previous values carried forward, `observed=True`.
- Not observed → previous values carried forward, `observed=False`. (A4 treats runs of `observed=False` as censoring, not as zero flow.)
- Tombstone (`section_status="GONE"`) → carried forward with `observed=True` until the section reappears.

Round-trip requirement (test): a day of synthetic runs written as baseline + deltas rebuilds to exactly the same panel as writing every run as a full table.

## 4. HTTP client (`scraper/http.py`)

```python
class HttpError(Exception): status: int; url: str
class HttpClient:
    def __init__(self, user_agent: str, min_interval_s: float = 1.0, max_concurrency: int = 2, timeout_s: float = 40, retries: int = 3, backoff_base_s: float = 1.0, ca_file: str | None = None)
    def get(self, url: str, headers: dict | None = None) -> bytes        # urllib.request + ssl context from certifi; handles gzip; retries on 429/5xx/URLError with exponential backoff + jitter; raises HttpError after retries; 404 raises immediately (no retry)
    def get_many(self, urls: list[str], on_result: Callable[[str, bytes | HttpError], None], time_budget_s: float | None = None) -> None
        # thread pool of max_concurrency, global rate limiter so that requests start no faster than 1/min_interval_s; stops scheduling new URLs when time budget is exhausted
```

User-Agent everywhere: `berkeley-waitlist-odds/<version> (+https://github.com/<owner>/berkeley-waitlist-odds; mailto:oliver139@berkeley.edu)`.

## 5. Sources (`scraper/sources/`)

```python
@dataclass(frozen=True)
class TermSpec:
    name: str          # "Spring 2027"
    year: int          # 2027
    semester: str      # "Spring" | "Fall" | "Summer"
    sis_term_id: str   # "2272"
    @property
    def berkeleytime_semester(self) -> str  # same as semester
    @staticmethod
    def from_name(name: str) -> "TermSpec"   # derives sis_term_id: "2" + YY + {Spring:2, Summer:5, Fall:8}

@dataclass
class FetchResult:
    rows: list[SnapshotRow]
    missing_ids: list[str]
    universe_ids: set[str] | None     # all section ids the source considers in scope (None if unknown)
    scope: str                        # "full" | "priority"
    observed_ids: list[str]           # ids successfully fetched (== {r["section_id"] for r in rows})

class Source(Protocol):
    name: str
    def fetch(self, term: TermSpec, *, priority: PrioritySpec | None, time_budget_s: float | None) -> FetchResult
```

### 5a. `classes_site.py` (`name = "classes_site"`)

- `discover_term_facet_id(client, term_name) -> str`: parse the listing page's term facet links (`href` contains `term%3A<id>`, link text starts with the term name, e.g. `Spring 2027 (6131)`). Raise `TermNotPublished` if absent.
- `list_sections(client, facet_id, max_pages=None) -> list[SectionRef]` where `SectionRef(section_id, url_path, course_key, subject, catalog_number, class_number, section_number, component)` parsed from each `views-row` (`#30174`, `st--section-name`, the two `st--section-count`, `st--section-code`, and the `/content/...` href). Pager: `?page=N`, 18 rows per page, stop when a page yields no rows. Persist to `catalog/<term_id>/sections.json` with a `listed_at` timestamp; reuse if younger than 24 h.
- `parse_section_page(html: bytes, ref: SectionRef, fetched_at: datetime, term: TermSpec) -> SnapshotRow`: read `<script data-drupal-selector="drupal-settings-json">`, take `ucb.enrollment.available.id` (must equal `ref.section_id`) and `ucb.enrollment.available.enrollmentStatus`; `section_status` from `ucb.enrollment.history` if present else null; `is_primary` null. Raise `ParseError` when the blob or keys are absent.
- `fetch(...)`: scope = `priority` when `priority` is given, else `full`. Selection = priority matches ∪ shard `k` of the non-priority remainder (`k = run_index % n_shards`, membership by `int(hashlib.sha1(section_id)) % n_shards`). Fetch via `client.get_many` within the time budget; every failure or budget cutoff goes to `missing_ids`.

### 5b. `sis_api.py` (`name = "sis_api"`)

- Base `https://gateway.api.berkeley.edu/sis/v1/classes/sections`, headers `app_id`, `app_key` from env `SIS_CLASS_APP_ID` / `SIS_CLASS_APP_KEY`. Query `term-id`, `page-number` (1-based), `page-size=50`. Iterate pages until a page returns 404 or an empty `apiResponse.response.classSections`. Up to 8 pages in flight. Retry each page 3× on 5xx.
- `parse_sections(payload: dict, fetched_at, term) -> list[SnapshotRow]` using the field paths in `docs/PHASE0.md`; skip sections with `status.code == "X"` unless `include_cancelled`. `is_primary = association.primary`.
- scope is always `full`; `universe_ids` = all parsed ids. A synthetic fixture in `data/fixtures/sis_sections_page_synthetic.json` must be created from the swagger definitions (`ClassSection`, `EnrollmentStatus`) with 3 sections including one cancelled and one with seat reservations.

### 5c. `berkeleytime.py` (`name = "berkeleytime"`)

- `POST https://berkeleytime.com/api/graphql` JSON `{"id": <op id>, "variables": {...}}` (use `requests`; this host is not blocked). Op ids from `data/fixtures/berkeleytime_persisted_ops.json` — load the file, pick the entry whose `variableNames` match what we send (GetClass needs `sessionId`).
- `fetch(...)`: `GetCatalog(year, semester)` → one row per class's `primarySection` (`is_primary=True`, `section_id` is NOT returned by GetCatalog: set `section_id = f"bt:{subject}:{courseNumber}:{number}"` and `section_status=None`), scope `full`. This source is for cross-checks and emergencies; document that ids are not SIS ids.
- `get_class(term, subject, catalog_number, class_number) -> dict` and `get_enrollment_history(term, subject, catalog_number, section_number) -> list[dict]` for the cross-check script.

## 6. Orchestration (`scraper/fetch.py`, run as `python -m scraper.fetch`)

CLI:

```
--term "Spring 2027"          required
--source auto|sis_api|classes_site|berkeleytime   default auto: sis_api if both env creds set, else classes_site
--data-root PATH              default ./data-branch
--priority-file PATH          default config/priority_courses.txt (classes_site only); pass "none" to disable
--n-shards INT                default 8 (classes_site); 0 disables sharding (priority only)
--run-index INT               default: number of runs already present today (drives shard rotation)
--time-budget-s FLOAT         default 1500 (25 min)
--min-interval-s FLOAT        default 1.0
--max-concurrency INT         default 2
--force-baseline              write a baseline even if one exists today
--limit INT                   debug: cap sections fetched
--dry-run                     fetch and print summary, write nothing
```

Behaviour: choose source → fetch → `rows_to_table` → decide kind (`baseline` if no baseline today or `--force-baseline`, else `delta` via `compute_delta(latest_state(...), table, universe_ids if scope=="full" else None)`) → `write_snapshot` → write `status.json` `{last_run_at, term_id, source, kind, scope, n_observed, n_written, n_missing, sweep_seconds}` → print a one-line summary. Exit codes: `0` success; `2` zero sections observed (workflow fails loudly, nothing written); `3` term not published yet (classes_site only; log and exit non-zero so it shows in Actions, but monitor treats it as expected before Oct 4). Logging to stderr with timestamps.

`config/priority_courses.txt`: one pattern per line, `SUBJECT` or `SUBJECT CATALOG` with `*` wildcard on catalog (e.g. `COMPSCI *`, `DATA *`, `STAT *`, `EECS *`, `EL ENG *`, `MATH 1*`, `MATH 5*`, `ECON 1`, `ECON 100*`, `PSYCH 1`, `UGBA 10`, `PHYSICS 7*`, `CHEM 1A`, `CHEM 3*`, `MCELLBI *`, `INTEGBI *`, `POL SCI 1`, `SOCIOL 1`, `PHILOS *`, `ENGLISH R1*`, `COLWRIT R*`, `L&S *`, `IND ENG *`, `NUC ENG *`). Lines starting with `#` are comments.

## 7. Gap report (`scraper/gaps.py`)

```python
def gap_report(data_root: Path, term_id: str, since_hours: float = 24) -> dict
# {"n_runs": int, "largest_gap_min": float, "p95_gap_min": float, "share_gaps_le_45min": float, "first": iso, "last": iso, "by_scope": {...}}
```

CLI `python -m scraper.gaps --data-root ... --term-id ... --hours 24 --fail-if-gap-min 90 --fail-if-runs-lt 40` exits 1 when a threshold is breached. Used by `monitor.yml` and by `CLAIMS.md`.

## 8. GitHub Actions

`.github/workflows/scrape.yml`: `schedule: cron "7,37 * * * *"` + `workflow_dispatch` (inputs: term, source, force_baseline); `concurrency: {group: scrape, cancel-in-progress: false}`; `permissions: {contents: write}`; `timeout-minutes: 29`. Steps: checkout `main`; checkout `data` branch into `data-branch/` (`actions/checkout` with `ref: data`, `path: data-branch`, `fetch-depth: 1`); `actions/setup-python@v5` 3.12 with pip cache; `pip install -r requirements.txt`; run fetch with `SIS_CLASS_APP_ID`/`SIS_CLASS_APP_KEY` from secrets (empty when not set); commit in `data-branch` as `github-actions[bot]` and push with up to 3 `git pull --rebase` retries. Never fail the job on "nothing to commit"; do fail on exit code 2.

`.github/workflows/monitor.yml`: daily at 15:10 UTC + dispatch; `permissions: {contents: read, issues: write}`; checkout data branch; run `python -m scraper.gaps ... --fail-if-gap-min 90 --fail-if-runs-lt 40`; on failure create or update a single open issue titled `Scraper gap alert` with the report (use `gh issue list --search`, then `create` or `comment`).

`.github/workflows/ci.yml`: on push and pull_request to any branch; python 3.12; `pip install -r requirements.txt`; `pytest -q`.

`scripts/bootstrap_data_branch.sh`: creates the orphan `data` branch with a README and `snapshots/.gitkeep`, pushes it. Idempotent.

## 9. Probe scripts

- `probe/probe_sources.py --term "Fall 2026"`: for each source available, fetch these 5 sections and print the raw payload and the parsed row: `COMPSCI 61A LEC 001`, `DATA C100 LEC 001`, `STAT 134 LEC 001` (impacted), `ECON 1 LEC 001` (large), `AEROENG 1 SEM 001` (small seminar), `AEROENG 10 LEC 001` (reserved seats).
- `probe/crosscheck_berkeleytime.py --term "Fall 2026" --n 20`: pick 20 section refs from the classes_site catalog, fetch each live from classes_site and the same section's latest from Berkeleytime `GetClass` (match on `sectionId`), print a table of both counts and the number that agree exactly on enrolled/waitlisted/max. Writes `docs/crosscheck_<date>.md`.

## 10. Tests (`tests/`, pytest, offline)

- `test_schema.py`: valid rows round-trip; wrong dtype, missing column, duplicate section_id all raise `SchemaError`.
- `test_storage.py`: paths, atomic write, refuse overwrite, metadata round-trip, `compute_delta` (changed/unchanged/new/tombstone), `latest_state` across baseline + 2 deltas.
- `test_rebuild.py`: synthetic 1-day run set: baseline + 5 deltas including a priority-scope run and a `missing_ids` entry; assert exact equality with the all-full-tables panel and correct `observed` flags.
- `test_classes_site.py`: parse the real fixture section page and listing; term facet discovery from the listing fixture (`Fall 2026` → `8588`); `TermNotPublished` for `Spring 2031`; `ParseError` on a page without the blob; `fetch` with a fake client returning one 500-then-200 and one 404 → the 404 id lands in `missing_ids`.
- `test_sis_api.py`: parse the synthetic page fixture; cancelled section skipped; pagination stops on 404 with a fake transport.
- `test_berkeleytime.py`: parse the saved GetCatalog-shaped fixture (`berkeleytime_getclass_compsci61a_fa26.json` for get_class) and a small hand-written GetCatalog fixture.
- `test_http.py`: retry on 500 then success; no retry on 404; rate limiter spacing ≥ min_interval with a fake clock; gzip decoding.
- `test_gaps.py`: known timestamps → known largest gap and share ≤ 45 min.
- `test_fetch_cli.py`: `--dry-run` with a fake source writes nothing; exit code 2 on zero rows; baseline/delta decision.

`pytest -q` must pass with zero network access (monkeypatch `HttpClient.get` / `requests.post`).

## 11. Addendum (2026-09-18, after writing the foundations)

- `scraper/schema.py` and `scraper/sources/base.py` are already written and are the reference implementations of sections 1 and 5. Import from them; do not redefine `TermSpec`, `PrioritySpec`, `FetchResult`, `shard_of`, `SnapshotRow`, `SNAPSHOT_SCHEMA`, `COUNT_FIELDS`.
- `Source.fetch` signature is `fetch(term, *, priority=None, shard=None, time_budget_s=None, limit=None)`; `shard` is `(k, n)`.
- classes.berkeley.edu section pages carry the SIS term id as an attribute: `data-term="2268" data-term-name="Fall 2026"`. `parse_section_page` must read `data-term` and use it as `term_id`; if it differs from `term.sis_term_id`, log a warning and keep the page value. This is how Spring 2027's id gets confirmed.
- Berkeleytime `GetClass` requires `sessionId` (`"1"`) and uses the second op id in the fixture (`variableNames` include `sessionId`). Fixture of a real response: `data/fixtures/berkeleytime_getclass_compsci61a_fa26.json` (108 secondary sections).
- Priority-scope delta files store `observed_ids` in metadata (JSON list) so rebuild never needs the priority file history.
- `pytest.ini` at the repo root sets `pythonpath = .` and `testpaths = tests`.

## 12. Integration addendum (2026-09-18, after the five modules landed and the live smoke test)

Clarifications recorded while integrating; each one keeps the signatures above.

- `course_key` is `"<SUBJECT> <CATALOG>"` with the section 1 space-free subject in every source: `"ELENG 16A"`, `"POLSCI 1"`, `"NUCENG 10"`. Measured on the live Fall 2026 listing (6,131 sections, 172 subjects): classes.berkeley.edu itself spells every subject without spaces and has no `L&S` subject, so this is the display form too. SIS (`subjectArea.code`) and Berkeleytime spell some subjects with spaces (`EL ENG`); sis_api and berkeleytime strip them, and classes_site strips them as well should a spaced form ever appear. Berkeleytime's synthetic id is `bt:ELENG:16A:001`.
- `PrioritySpec` normalizes both patterns and keys by removing spaces inside the subject part (`EL ENG *` -> `ELENG *`), because the section 6 patterns `EL ENG *`, `POL SCI 1`, `IND ENG *` and `NUC ENG *` matched nothing on the live site (0 of the 53 ELENG, 63 POLSCI, 30 INDENG and 108 NUCENG sections were selected before the fix). A bare multi-word subject must be written without spaces (`ELENG`) or with a wildcard. `priority_sha` is still the hash of the raw file text; the header comment of `config/priority_courses.txt` was updated (no data existed yet, so no sha history is affected).
- `ClassesSiteSource._select` schedules priority matches before shard members so a time-budget cutoff trims the rotating shard, never the priority list. Measured 2026-09-18: 886 priority sections and 5,245 remainder; shard sizes at `n_shards` 8 / 12 / 16 are 613 to 701 / 402 to 458 / 293 to 356, i.e. 1,499 to 1,587 / 1,288 to 1,344 / 1,179 to 1,242 section pages per run. Section pages take about 1 s each (rate limit 1/s, concurrency 2); listing pages about 1.8 s each and are fetched sequentially, so the first run of a UTC day (cache miss on `catalog/<term_id>/sections.json`) spends about 630 s of its 1,500 s budget on the 341-page listing. Consequences at the section 6 defaults: cache-hit runs fetch all 886 priority pages plus most of the shard; the first run of the day fetches the priority list and little of the shard; every cutoff lands in `missing_ids` and rebuild marks those rows `observed=False` (censoring, section 3). `--n-shards 12` in `scrape.yml` would make cache-hit runs complete; fetching listing pages through `get_many` (the facet link text `Fall 2026 (6131)` gives the page count up front) would roughly halve the listing cost. Neither is applied here.
- Section 5a's `discover_term_facet_id` and `list_sections` are instance methods of `ClassesSiteSource` (the client is the instance's), and `list_sections(facet_id, max_pages=None, *, term_id=None)` only reads or writes `catalog/<term_id>/sections.json` when `term_id` is given and the listing is complete (`max_pages is None`). A listing capped by `--limit` or `--catalog-max-pages` sets `universe_ids = None` so no tombstones are computed against a partial universe.
- `probe/crosscheck_berkeleytime.py`: Berkeleytime's `GetClass` returns some classes with `primarySection: null` and no sections (seen live for `AEROENG 198 GRP 3`, a group study), so not every section can be compared. The probe lists such a section as `error`, excludes it from the agreement fractions, and draws the next candidate (at most `2n` attempts) so the report always has `n` comparable sections; exit 1 only on a disagreement or fewer than `n` comparable sections.
- Live smoke test on 2026-09-18 against Fall 2026 (facet `8588`): section pages carry `data-term="2268"`, which is what `status.json` and the parquet metadata record; 25-section baseline, 0-row delta, rebuild, gap report, Spring 2027 `TermNotPublished` (exit 3), Berkeleytime GetCatalog (15,842 classes in about 50 s), a two-run priority/shard sequence with `observed_ids` metadata, and the six-section probe all behaved as specified.

### 12a. Review fixes (2026-09-19, storage / rebuild / schema / fetch / gaps)

Each bullet keeps the signatures above; new behaviour is reachable through added keyword arguments with defaults, new helpers, and new metadata keys.

- Day-boundary zombies. `latest_state(data_root, term_id, as_of_date, *, seed_from_previous_days=True, lookback_days=7)` still returns `None` when the day has no baseline for the term, but otherwise starts from the state carried from the previous `lookback_days` UTC days: new `carried_state(data_root, term_id, as_of_date, *, lookback_days=7)` applies every file of the term in `[as_of_date - lookback_days, as_of_date]` in time order as upserts (no baseline required; `None` when the window holds no file of the term). So the first full-scope delta after a baseline tombstones a carried id that is neither in the baseline nor in `universe_ids`, and a shard first seen on day 2 with values unchanged since day 1 writes no rows. A complete full-scope baseline is written as `baseline_with_tombstones(carried_state(...), observed, universe_ids, run_started_at, source)` = every observed row followed by the rows of new `compute_tombstones(...)`: `section_status="GONE"`, counts and identity copied from the carried row, `source` = the current source, `fetched_at` = run start. `n_observed` counts observed rows only; `n_written` includes tombstones. An id last seen more than `lookback_days` ago and never tombstoned is outside the comparison state (accepted; rebuild still carries it).
- Tombstones never cross sources. `compute_delta(previous, observed, universe_ids, fetched_at, source=None)` and `compute_tombstones` skip previous rows whose `source` differs from the current source (`source` if given, else the source of the observed rows; when nothing was observed and no source is given the previous row's source is used). fetch.py names its source on every call. Before writing a delta, fetch.py reads the metadata of the day's latest baseline for the term (new `latest_baseline_meta(data_root, term_id, as_of_date)`); when its `source` differs from the current source the run logs both sources and exits 1 without writing. `--force-baseline` starts a fresh baseline for the new source instead; nothing is tombstoned across sources then either, so rows of the old source that vanish are only tombstoned once the new source has re-observed them.
- Partial full-scope sweeps are marked. New metadata key `complete` (`"true"` / `"false"`; absent in files written before 2026-09-19, read back as `None`) = `result.universe_ids is not None and --limit not given` (every source sets `universe_ids=None` when a sweep is cut short by its time budget or `--limit`). `observed_ids` is persisted for every priority-scope run and for every incomplete run, whatever the scope; it is omitted only for a complete full sweep (this supersedes the "only when scope is priority" rule of sections 3 and 11). Rebuild's observed set is `observed_ids - missing_ids` whenever the key is present, regardless of scope, and the carried state minus `missing_ids` for a complete full sweep. Under `--limit` fetch.py never tombstones, whatever universe the source reports. `status.json` gains `missing_share` and `complete`.
- `GONE` rows count as observed in every scope, including priority-scope runs (the section 3 tombstone rule), until the section reappears.
- The kind decision is term-aware: `decide_kind(data_root, today, force_baseline, term_id=None)` looks for a baseline of that term on the UTC day, so a second term on the same day gets its own baseline instead of a delta against nothing.
- Schema strictness: `rows_to_table` raises `SchemaError` for a non-integer value (float with or without a fractional part, str, bool) in an integer field and for a `fetched_at` that is not a timezone-aware datetime. pyarrow would otherwise truncate `3.5` to `3` and stamp a naive datetime as UTC. Aware non-UTC datetimes are converted to UTC as before.
- Coverage gate. `python -m scraper.fetch --max-missing-share FLOAT` (default 0.5): when `n_missing / (n_observed + n_missing)` exceeds it, nothing is written and the exit code is `4` (`EXIT_LOW_COVERAGE`), checked after the zero-rows exit `2` and also under `--dry-run`. Section 6's exit-code list gains `4 low coverage (nothing written)`. `scraper.gaps` reads `n_observed` and `missing_ids` from each file's metadata and the report gains `median_missing_share` and `max_missing_share` over the window (`None` without runs; runs with nothing in scope are skipped); `python -m scraper.gaps --fail-if-missing-share-gt FLOAT` (default: no check) exits 1 when the median exceeds it. `scrape.yml` and `monitor.yml` are unchanged by this addendum; the monitor may add `--fail-if-missing-share-gt 0.5`.

## 13. Review fixes and the discovery rewrite (2026-09-19)

Applied after the first Actions run and the three-lens review. Each item names the section it amends.

### 5a. classes_site discovery no longer uses the listing

The full robots.txt of classes.berkeley.edu disallows `/search/` (the 2026-09-18 read was truncated at 40 lines), so `discover_term_facet_id`, `list_sections`, `parse_listing_page`, `parse_term_facets` and `find_term_facet_id` are gone. Replacement:

- The section universe is built from Berkeleytime `GetCatalog(year, semester)` through an injectable `catalog_provider(term) -> list[dict]` (default: `BerkeleytimeSource().execute("GetCatalog", ...)`). `catalog_refs(classes, term)` keeps every class whose primary section component is not in `SELF_STUDY_COMPONENTS` (IND, GRP, FLD, TUT, INT, SLF, PRA, REC, SES, CLN, WOR, REA, WBD, VOL, DEM: measured on 2026-09-19, none of them carries a waitlist) and derives the page path with `section_slug`: `/content/<year>-<semester>-<subject>-<catalog>-<class#>-<component>-<class#>` (lower-cased, subject spaces removed; the section number of a primary section equals its class number on all 3,640 listed Fall 2026 primaries).
- `SectionRef` gained `last_status: int | None` and `probed_at: str | None`; `section_id` is `""` until the page is fetched once, and `parse_section_page` adopts the page's `ucb.enrollment.available.id` in that case (it still raises ParseError on a mismatch when the id is known). Shard membership uses `SectionRef.key` (the page path) because the id may be unknown.
- The catalog lives at `catalog/<term_id>/catalog.json` (`version` 2, `refreshed_at`, `sections[]` with the fields above). `load_or_refresh_catalog(term)` refreshes from the provider when the file is missing or older than 24 h, merges by page path so learned ids and probe state survive (`merge_catalog`), falls back to the cached copy when the provider fails or returns nothing, and raises `TermNotPublished` only when the provider returns no classes and nothing is cached. A legacy `sections.json` (listing era) seeds the catalog once, minus self-study components. The file is rewritten only when its content changed.
- Non-printed classes answer 404 (2,434 of 6,074 catalog primaries for Fall 2026): the entry is marked `last_status=404` with `probed_at`, skipped by later runs, and re-probed after `ABSENT_REPROBE_AFTER` (7 days) on refresh runs only, at most `MAX_REPROBES_PER_RUN` (300) per run. A 404 on a section whose id is known also lands in `missing_ids`. Transport errors, budget cutoffs and parse errors never change the catalog; they land in `missing_ids` only when the id is known (a never-fetched section cannot be "missing" from the panel).
- Selection order: priority sections by `PrioritySpec.rank` (index of the first matching pattern in the priority file, then course key, then path), then shard `k` of `n` of the non-priority remainder (`shard=None` with a priority list means priority only; `priority=None` means everything), then the due re-probes. The priority file is therefore ordered by importance.
- Full scope `universe_ids` = ids of live entries whose id is known. `catalog_max_pages` is accepted and ignored.
- Sizing (Fall 2026, 2026-09-19): 3,640 live primaries, 702 priority, remainder 2,938; with 8 shards a run fetches about 1,070 pages, which fits the 1,200 s budget at about one page per second. The 12-shard suggestion in section 12 is withdrawn.

### 4. HttpClient

`user_agent` defaults to `config.USER_AGENT` (the only definition; sis_api and berkeleytime import it too). `timeout_s` defaults to 20. New keyword-only `max_body_bytes` (4 MiB): bodies are read in chunks and gzip is inflated with a bounded `zlib.decompressobj`; over the cap raises a non-retryable `HttpError` with `body_too_large`. `get(url, headers=None, *, deadline=None)` stops retrying once the monotonic `deadline` has passed and `get_many` passes its deadline to every worker. Retry-After is parsed in both delay-seconds and HTTP-date form (`parse_retry_after`), honoured up to `RETRY_AFTER_MAX_S` (600) while the exponential part stays capped at 60 s, and any 429 (or 5xx with Retry-After) pushes the shared limiter forward so every worker pauses.

### 5b, 5c. Transports

`requests_get_json` / `requests_post_json` return `(status, body, retry_after_s)` (the 2-tuple is still accepted), never follow redirects (`allow_redirects=False`; any 3xx is a hard error so credentials are never re-sent to another host), and read bodies with `stream=True` under a cap (16 MiB SIS, 64 MiB Berkeleytime). sis_api page workers share a `_not_before` deadline: one 429 pauses all of them; backoff carries jitter.

### 6 and 8. CLI and workflows

`--time-budget-s` defaults to 1200 and scrape.yml passes it explicitly (29-minute job timeout minus checkout, install, in-flight retries and the push). The run-log artifact uploads on `always()`, and an `always()` step prints the log tail and the data-branch status so a cancelled run still shows how far it got. Scheduled runs take the term from the `SCRAPE_TERM` repository variable (set to `Fall 2026` on 2026-09-19; switch to `Spring 2027` on Oct 4). Storage-semantics fixes (day-boundary tombstones, cross-source guard, `complete` metadata, term-aware baseline decision, coverage threshold and exit code 4, gap-report missing-share fields) are recorded in section 12 by the agent that made them.

## 14. Discovery by node id (2026-09-19, supersedes the Berkeleytime catalog in section 13)

A diagnostic run from a GitHub-hosted runner showed berkeleytime.com answering 403 (Cloudflare) to every client, so the section 13 catalog refresh never ran in production. Discovery now uses two robots-allowed resources of classes.berkeley.edu itself:

- `GET /rss.xml`: the 10 newest nodes, each with `<guid>` = node id, a title of the form `2026 Fall AEROENG 10 001 LEC 001`, and the `/content/` alias.
- `GET /node/<id>`: the section page for that id (200, identical to its alias, carrying `<link rel="canonical">`, `<title>`, `data-history-node-id` and `data-term`) or 404.

State: `catalog/site.json` holds `max_node_probed` (every id at or below it has been probed) and `max_node_seen` (the newest feed id). Each run: read the feed, add its section items to the catalog of their own term (`catalog/<term_id>/catalog.json`, one per term; self-study components excluded), then probe ids `max_node_probed + 1 .. min(max_node_seen, max_node_probed + MAX_NODE_PROBES_PER_RUN)` through `get_many` with at most `NODE_PROBE_BUDGET_SHARE` (30%) of the run budget. A probed page that is a section of the run's term is parsed once and counts as that run's observation (`prefetched`), so enumeration is not wasted work; sections of other terms are recorded in their catalogs; non-section nodes and 404s are skipped. The watermark advances over the contiguous prefix of attempted ids only, so a budget cutoff never skips ids. On the very first run the watermark starts `INITIAL_LOOKBACK_NODES` (2,000) below the newest feed id. When the feed is unreadable the stored watermark is used; with neither, enumeration is skipped for that run.

Spring 2027: the registrar publishes the schedule on Oct 4; its sections appear as new nodes above the watermark and are enumerated over the following runs (about 6,000 nodes at 400 per run, roughly 15 runs). `TermNotPublished` (exit 3) is raised only when the term's catalog is still empty after discovery. The SIS term id is read from `data-term` on the pages, as before.

`SectionRef` gained `node_id`; `CATALOG_VERSION` is 3; `catalog_provider` is gone from `ClassesSiteSource` (new keyword `max_node_probes`); `load_catalog(term)` replaces `load_or_refresh_catalog`. The 7-day re-probe of absent slugs is kept (at most 100 per run, every run) for sections that disappear.

## 15. Snapshot file format (2026-09-19, amends section 2)

`write_snapshot` writes the run metadata once, into the Parquet footer through `ParquetWriter.add_key_value_metadata`, with zstd compression and no column statistics. Files written before this change carry the same keys in the Arrow schema (and therefore twice in the file). `read_raw_metadata(path)` returns the key-value pairs from either layout; `read_meta` and `read_snapshot` use it, so both layouts read identically. Effect: a 43-row delta went from about 30 KB to about 15 KB, a 900-row baseline from 61 KB to about 48 KB; the projected data-branch growth for the Spring 2027 cycle drops from about 250 MB to about 150 MB. Nothing about the schema, the semantics, or the paths changed.

## 16. Request policy in scrape.yml (2026-09-23, amends sections 4, 8 and 13)

The CLI defaults are unchanged (`--min-interval-s 1.0`, `--max-concurrency 2`, section 6). `scrape.yml` passes `--min-interval-s 0.5 --max-concurrency 4` explicitly, as it does for `--time-budget-s`: the section 4 limiter spaces request *starts* at least 0.5 s apart across every worker, and at most 4 requests are in flight. `max_concurrency` bounds outstanding connections, not the rate; the rate ceiling is `1/min_interval_s`, and a run's throughput is `min(1/min_interval_s, max_concurrency/latency)`. The change answers the slowdown logged in docs/DATA_LOG.md from 2026-09-21T14:37Z (pages at 2 to 5 s with 20 s read timeouts, nine exit-4 runs on Sep 22 to 23): at the defaults throughput was 2/latency, under 1 per second. Four workers keep 1 per second up to 4 s of latency; the 0.5 s spacing gives headroom for the data-driven priority list (about 1,100 matches) and Spring 2027 node discovery (400 probes per run). At 5 s latency, the top of the observed range, four workers give 0.8 pages per second, about 1,100 of 1,290 in 1,380 s, so a slow-end run still trims about 190 shard-tail sections; read the first runs at the new rate against that.

## 17. The priority list is generated (2026-09-24, amends section 6)

`config/priority_courses.txt` is no longer hand-written: `python -m analysis.priority_from_flows` writes it from the reconstructed waitlist joins of the finished cycles (the courses of the most-joined sections, plus every course whose joins over all its sections reach `--min-course-joins`), one exact course key per line in joins order, no wildcards. The pattern listing in section 6 describes the hand-written file that ran until this change. `--catalog <catalog.json> --n-shards 12` prints what a run fetches with the candidate and the current list (live sections matched, their courses, the per-run selection over the shards), which is where the numbers in the data-log `priority_list` rows come from. Installing a candidate changes `priority_sha`; the data-log row records the command, the numbers and both shas.

## 18. Course title and instructors in the catalog (2026-09-24, amends section 14 and the catalog entry of section 5a as rewritten in section 13)

`SectionRef` gains `title` and `instructors`: the strings the section page prints in its `sf--course-title` and `sf--instructors` elements, whitespace collapsed, `""` until a page has been read. `parse_section_meta(html) -> (title, instructors)` reads them off the page a run fetches anyway, so they cost no request. `parse_section_ref` fills them during discovery; both write paths (the ordinary fetch and the adoption of pages read during discovery) rewrite a catalog entry when either differs from what the page now says, alongside the existing id and status rule, and keep the learned value when the page lacks the element; `merge_catalog` takes a fresh non-empty value over a learned one. Limitation of that rule: a section whose page stops printing an instructor keeps the last-known name (a missing element is read as a template quirk, not a removal), so anything built on these fields treats them as last-known. `catalog.json` keeps `version` 3 because `from_dict` defaults both keys, so entries written earlier load unchanged and fill in as their pages are read (the first run after the change rewrites the entries it fetched, about 1,280, then only real changes). The snapshot schema of section 1 is untouched. The site reads only exported JSON; the exporter can read these fields off the catalog on the data branch to build the search's `titles.json` (MASTER_PLAN Q4).

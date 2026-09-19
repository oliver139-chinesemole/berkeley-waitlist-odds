# Claims

Every number or capability that appears on the resume for this project, with the exact command that reproduces it. This table is the audit, the interview prep, and the source for README numbers (docs/FINISH_PLAN_WAITLIST.md section 1.3). Re-run every row at the end of every step and before any resume update. If the `claims-audit` skill is installed, it does this; otherwise run each command by hand.

Rules:
- Result is what the command printed. Do not type a result you did not see.
- Date is the UTC date the Result was last produced. `-` means the check has never been run.
- If reality and the resume disagree, the resume changes, not the number.

Status on 2026-09-18: the scraper is built and not live. Nothing below has been measured. The resume block still says "Spring 2026 enrollment cycle". That cycle ended and cannot be backfilled; the only cycle this project can capture is Spring 2027 (Oct 2026 to Feb 10, 2027). The resume must say "Spring 2027" once the data exists.

Commands assume `source .venv/bin/activate` from the repo root, `export GH_REPO=oliver139-chinesemole/berkeley-waitlist-odds`, and a clone of the `data` branch at `./data-branch` (docs/RUNBOOK.md step 6). `<TERM_ID>` is `2268` for Fall 2026 test runs and `2272` for Spring 2027 (expected value; confirm on the first Spring 2027 run per docs/DESIGN_A2.md section 11).

| Claim | Check (exact command) | Result | Date |
| --- | --- | --- | --- |
| Resume: zero-cost pipeline (Python, GitHub Actions, Parquet) capturing 30-minute snapshots of enrollment and waitlist counts across sections through the Spring 2027 enrollment cycle. Pass: `share_gaps_le_45min >= 0.95` over the whole cycle and about 48 runs per day. | `python -m scraper.gaps --data-root ./data-branch --term-id 2272 --hours $(python -c "import datetime as d; print(max(1, int((d.datetime.now(d.timezone.utc)-d.datetime(2026,10,12,tzinfo=d.timezone.utc)).total_seconds()//3600)))")` | not yet run | - |
| Resume: flow reconstruction separating waitlist admits, joins, and drops under documented FIFO assumptions. Pass: `docs/ASSUMPTIONS.md` exists and the synthetic-recovery test passes within its stated error. | `test -f docs/ASSUMPTIONS.md && python -m pytest tests/test_flows_synthetic.py -q` (test file name is fixed in step A4; update this cell when it lands) | not yet run | - |
| Resume: Kaplan-Meier and Cox proportional hazards, stratified by course, position, and enrollment phase. Pass: every figure and table rebuilds from raw Parquet with one command; output includes the PH assumption check and out-of-sample concordance, Brier score, and calibration. | `make analysis` (target defined in step A5) | not yet run | - |
| Resume tech line: GitHub Pages. Pass: the public lookup page returns 200 and reads its numbers from precomputed JSON under `site/data/`. | `curl -sS -o /dev/null -w '%{http_code}\n' https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/` (JSON file name is fixed in step A6; add a second curl for it then) | not yet run | - |
| Snapshot count per day. Target about 48; the monitor alerts below 40. | `python -m scraper.gaps --data-root ./data-branch --term-id <TERM_ID> --hours 24` and read `n_runs` | not yet run | - |
| Share of snapshot intervals at or under 45 minutes. Target 0.95 or higher. | `python -m scraper.gaps --data-root ./data-branch --term-id <TERM_ID> --hours 24 --fail-if-gap-min 90 --fail-if-runs-lt 40; echo "exit $?"` and read `share_gaps_le_45min` and `largest_gap_min` (exit 0 means both thresholds held) | not yet run | - |
| Sweep time per run, in seconds. Must stay under the 1500 s budget and stable across a week. | `git -C ./data-branch pull -q && python -c "import json; d=json.load(open('./data-branch/status.json')); print(d['last_run_at'], d['source'], d['scope'], d['n_observed'], d['sweep_seconds'])"` | not yet run | - |
| $0 recurring cost. Pass: repo is public (unmetered Actions minutes) and the billing page shows $0.00 for Actions and Storage for the month. | `gh repo view oliver139-chinesemole/berkeley-waitlist-odds --json visibility -q .visibility` prints `PUBLIC`; then open https://github.com/settings/billing and record the Actions and Storage charges | not yet run | - |
| Cross-check agreement with Berkeleytime on 20 sections. Pass: enrolled, waitlisted, and max agree exactly for all 20 fetched at the same time. | `python probe/crosscheck_berkeleytime.py --term "Fall 2026" --n 20` (writes docs/crosscheck_<date>.md; record "k of 20 agree") | not yet run | - |
| Test suite green, locally and in CI on main. | `python -m pytest -q` and `gh run list --workflow ci.yml --branch main --limit 1` | not yet run | - |

## Rows to add later

- Section count and row count for the resume bullet ("~X,000 sections, ~Y million rows"): the command is `python -m scraper.rebuild` output shape once step A4 lands. Do not fill the resume placeholders before then.
- Headline result (for example, median cleared position in a department) from step A5.
- Lookup tool usage (unique visitors from GoatCounter) from step A7. Screenshot the analytics page and keep it out of the repo.

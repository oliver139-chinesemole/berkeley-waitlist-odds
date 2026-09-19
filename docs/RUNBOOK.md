# Runbook

For Oliver. Section 1 is the go-live checklist (step A3), in order. Section 2 explains what a run does. Section 3 is what to do when a run fails. Section 4 is the weekly check.

Setup for every command below, from the repo root:

```
source .venv/bin/activate
export GH_REPO=oliver139-chinesemole/berkeley-waitlist-odds
```

`GH_REPO` is needed because the `origin` remote uses the SSH host alias `github-chinesemole`, and `gh` cannot map that alias to github.com on its own. With the variable set, every `gh` command knows which repo it is talking to.

## 1. Go-live checklist

### Step 1. Create the public repo and push main

`gh` is installed (`~/.local/bin/gh`) but not logged in. `gitleaks` is not installed. The SSH alias `github-chinesemole` exists in `~/.ssh/config`.

```
gh auth login
```

Pick GitHub.com, SSH, and log in as `oliver139-chinesemole`. If `gh` already holds another account, run `gh auth switch` afterwards and confirm with `gh auth status`.

Scan history for secrets before the first public push (the plan requires zero findings):

```
brew install gitleaks
gitleaks detect --source . --redact
```

Create the repo. Either command line:

```
gh repo create oliver139-chinesemole/berkeley-waitlist-odds --public --description "Waitlist-clearing odds for UC Berkeley courses: 30-minute enrollment snapshots and survival analysis"
```

or in the browser at https://github.com/new: owner `oliver139-chinesemole`, name `berkeley-waitlist-odds`, Public, no README, no .gitignore, no license (the repo already has history; adding any of those creates a conflicting first commit).

Add the remote through the SSH alias and push:

```
ssh -T git@github-chinesemole
git remote add origin git@github-chinesemole:oliver139-chinesemole/berkeley-waitlist-odds.git
git push -u origin main
```

The `ssh -T` line should print `Hi oliver139-chinesemole! You've successfully authenticated`. If it greets a different user, the alias points at the wrong key; fix `~/.ssh/config` before pushing.

Check:

```
gh repo view --json visibility,defaultBranchRef -q '.visibility + " " + .defaultBranchRef.name'
```

prints `PUBLIC main`. CI (`ci.yml`) runs on the push; `gh run list --workflow ci.yml --limit 1` should show success within a few minutes.

### Step 2. Create the data branch

```
bash scripts/bootstrap_data_branch.sh
git ls-remote --heads origin data
```

The second command prints one line ending in `refs/heads/data`. The script is idempotent; re-running it is safe.

### Step 3. Let workflows write to the repo

In the browser: Settings > Actions > General > Workflow permissions > select "Read and write permissions" > Save. Also confirm "Allow all actions and reusable workflows" is selected at the top of the same page.

Or from the command line:

```
gh api -X PUT repos/oliver139-chinesemole/berkeley-waitlist-odds/actions/permissions/workflow -f default_workflow_permissions=write -F can_approve_pull_request_reviews=false
gh api repos/oliver139-chinesemole/berkeley-waitlist-odds/actions/permissions/workflow
```

Check: the second command prints `"default_workflow_permissions": "write"`. Without this, `scrape.yml` cannot push to the `data` branch and `monitor.yml` cannot open issues.

### Step 4. Add the SIS API secrets (only once the access request is approved)

```
gh secret set SIS_CLASS_APP_ID
gh secret set SIS_CLASS_APP_KEY
gh secret list
```

Each `set` prompts for the value; nothing is echoed. Before adding them, confirm the credentials work from your laptop:

```
SIS_CLASS_APP_ID=... SIS_CLASS_APP_KEY=... python -m scraper.fetch --term "Fall 2026" --source sis_api --limit 25 --dry-run
```

Once both secrets exist, the next scheduled run switches from `classes_site` to `sis_api` on its own (section 2). Add a `source_switch` row to docs/DATA_LOG.md with the `last_run_at` of the first `sis_api` run from `status.json`. Also add an `access` row with the request id the day you submit the request, and another when it is approved.

Nothing else waits on this step. Go on to step 5 with `classes_site`.

### Step 5. First manual run against Fall 2026

```
gh workflow run scrape.yml -f term="Fall 2026"
gh run list --workflow scrape.yml --limit 1
gh run watch
```

`gh run watch` asks which run to follow; pick the one you just started. It exits when the run finishes (up to 29 minutes). Then verify a baseline landed on the `data` branch:

```
git fetch origin data
git ls-tree -r --name-only origin/data snapshots/
git show origin/data:status.json
```

Pass: a file `snapshots/date=YYYY-MM-DD/HHMM-baseline.parquet` exists, and `status.json` shows `"kind": "baseline"`, `"term_id": "2268"`, `n_observed` in the hundreds or more, `n_missing` small relative to `n_observed`.

Also check that the Linux runner was not blocked by classes.berkeley.edu (docs/PHASE0.md, the ALPN note). Grep the log:

```
gh run view --log $(gh run list --workflow scrape.yml --limit 1 --json databaseId -q '.[0].databaseId') | grep -c ' 403 '
```

`0` is the answer you want. Record the outcome either way in docs/DATA_LOG.md (there is an open `note` row asking for it).

### Step 6. Let the schedule run 48 hours, then read the gap report

Do nothing for two days. The schedule (`7,37 * * * *`) should produce about 96 runs. Then:

```
git clone --branch data --single-branch git@github-chinesemole:oliver139-chinesemole/berkeley-waitlist-odds.git data-branch
python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 48
python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 24 --fail-if-gap-min 90 --fail-if-runs-lt 40; echo "exit $?"
gh run list --workflow scrape.yml --limit 100 --json conclusion -q 'map(select(.conclusion=="success")) | length'
```

Later refreshes are `git -C data-branch pull -q`. The `data-branch/` directory is the same path the workflow uses and the default for `--data-root`, and it is already listed in `.gitignore`, so the nested clone never shows up in `git status`.

Pass: at least 90 of 96 expected runs succeeded, `largest_gap_min` under 90, `share_gaps_le_45min` at or above 0.95, the second gaps command exits 0. Then check that sweep time is stable:

```
for c in $(git -C data-branch log --format=%H -n 10 -- status.json); do git -C data-branch show $c:status.json | python -c "import json,sys; d=json.load(sys.stdin); print(d['last_run_at'], d['kind'], d['scope'], d['n_observed'], d['n_missing'], d['sweep_seconds'])"; done
```

`sweep_seconds` should sit well under 1500 and not trend upward; `n_missing` should be near zero. Run the monitor once by hand and confirm it succeeds and opens no issue:

```
gh workflow run monitor.yml
gh run list --workflow monitor.yml --limit 1
gh issue list --search "Scraper gap alert" --state open
```

Write the results into CLAIMS.md (snapshot count, share of intervals, sweep time rows) with the date.

### Step 7. On Oct 4, confirm Spring 2027 and switch the default term

The registrar publishes the Spring 2027 Schedule of Classes on Sun Oct 4, 2026. On or after that day:

```
curl -sS -A 'berkeley-waitlist-odds/0.1 (+mailto:oliver139@berkeley.edu)' 'https://classes.berkeley.edu/search/class' | grep -o 'Spring 2027 ([0-9,]*)'
python -m scraper.fetch --term "Spring 2027" --source classes_site --limit 5 --dry-run; echo "exit $?"
```

Exit 3 means the term is not on the site yet; try again the next day. Exit 0 means it is published. Read the log for the `data-term` value taken from the section pages. It should be `2272`. If it is anything else, do not change code by hand: tell Claude Code, because the derivation in `scraper/sources/base.py` and the `2272` references in CLAIMS.md and docs/DATA_LOG.md need review.

Switch the workflow default. In `.github/workflows/scrape.yml`, change the default term from `Fall 2026` to `Spring 2027` (both the `workflow_dispatch` input default and whatever the scheduled run uses). Commit on a branch, push, merge to main through a PR so CI runs. Then force a baseline for the new term:

```
gh workflow run scrape.yml -f term="Spring 2027" -f force_baseline=true
gh run watch
git fetch origin data && git show origin/data:status.json
```

Pass: `status.json` shows `"term_id": "2272"` (or the confirmed id) and `"kind": "baseline"`. Add a `term_switch` row to docs/DATA_LOG.md with the `last_run_at` of that run. The Fall 2026 files stay on the `data` branch as test data; everything downstream filters by `term_id`.

Deadline: Mon Oct 12, 2026. Phase 1 opens Mon Oct 26.

### Step 8. Weekly Sunday check

See section 4. Put a recurring reminder in your calendar for every Sunday through Feb 14, 2027.

## 2. How the scraper picks a source and a mode

Reference: docs/DESIGN_A2.md sections 2, 5, and 6.

Source:
- `--source auto` (what the workflow passes): `sis_api` if both `SIS_CLASS_APP_ID` and `SIS_CLASS_APP_KEY` are set (repo secrets in Actions, environment variables locally), otherwise `classes_site`.
- `berkeleytime` is never chosen automatically. Its rows carry ids like `bt:COMPSCI:61A:001`, not SIS section ids, and cover primary sections only. Use it for cross-checks and emergencies.

Scope (which sections a run looks at):
- `sis_api`: `full` every run. One term is 130 to 330 paged requests and takes minutes.
- `classes_site` with the default `config/priority_courses.txt`: `priority`. Every section whose course matches the list (roughly 600 to 900) is fetched every run. The remaining sections are split into 8 shards by a hash of the section id, and shard `run_index mod 8` is added to the run, where `run_index` defaults to the number of runs already on the `data` branch for that UTC day. With 48 runs a day every section is seen about every 4 hours.
- `classes_site --priority-file none`: `full`. About 6,100 pages at 1 request per second is about 1.7 hours, which does not fit the 25-minute budget. Do not schedule it.
- The section list for a term comes from `catalog/<term_id>/sections.json` on the `data` branch, rebuilt from the listing pages when it is older than 24 hours.

Kind (what gets written):
- The first run of a UTC day writes `snapshots/date=YYYY-MM-DD/HHMM-baseline.parquet` with every section it observed.
- Every later run writes `HHMM-delta.parquet` with only the rows whose counts changed since the last observation of that section, plus tombstone rows (`section_status = "GONE"`) when a full-scope run no longer sees a section.
- `--force-baseline` (workflow input `force_baseline`) writes a baseline regardless.
- `status.json` is rewritten by every run: `last_run_at, term_id, source, kind, scope, n_observed, n_written, n_missing, sweep_seconds`.

Time and politeness:
- 1500 s budget per run; the job itself is killed at 29 minutes. Requests to classes.berkeley.edu start no faster than one per second with two in flight. Sections not fetched by the deadline, plus any HTTP or parse failure, go to `missing_ids` in the parquet metadata and are treated as unobserved by `scraper/rebuild.py`.
- Every request carries `User-Agent: berkeley-waitlist-odds/<version> (+https://github.com/oliver139-chinesemole/berkeley-waitlist-odds; mailto:oliver139@berkeley.edu)`.

Exit codes: `0` success; `2` zero sections observed, nothing written, the job fails; `3` term not published on classes.berkeley.edu (expected for Spring 2027 before Oct 4, a problem after).

## 3. What to do when a run fails

Data gaps are permanent. Aim to have the fix merged within 24 hours.

1. Read the Actions log.

```
gh run list --workflow scrape.yml --status failure --limit 5
gh run view <run-id> --log-failed
```

   Map the exit code: `2` means the site was down, blocked the runner, or every page failed to parse. `3` means the term is not on the site. Any other code: read the traceback. A run cancelled at 29 minutes means the time budget did not hold; look at the `sweep_seconds` trend (section 1, step 6).

2. Check what last landed.

```
git fetch origin data && git show origin/data:status.json
git log origin/data --format='%cI %s' -n 5
```

   `last_run_at` is when data last landed. A successful run with a large `n_missing` means the site was slow or partly failing; that is a partial gap, log it too.

3. If the log shows `403` from classes.berkeley.edu, test from your laptop:

```
curl -sS -o /dev/null -w '%{http_code}\n' -A 'berkeley-waitlist-odds/0.1 (+mailto:oliver139@berkeley.edu)' https://classes.berkeley.edu/content/2026-fall-aeroeng-10-001-lec-001
```

   If curl gets `200` and the runner got `403`, the site's rule changed (docs/PHASE0.md, the ALPN note). Do not add browser impersonation. Options in order: `sis_api` if credentials exist; a manual dispatch with `-f source=berkeleytime` as a stopgap (primary sections only, non-SIS ids, mark it in DATA_LOG); otherwise stop and reassess per docs/SPEC.md Route B.

4. If runs stopped without any failure, the schedule itself is the problem. GitHub delays or drops scheduled runs at busy minutes and disables schedules in repos it considers inactive.

```
gh workflow view scrape.yml
gh workflow enable scrape.yml
gh workflow run scrape.yml
```

5. If the push to the `data` branch failed after its three rebase retries, something else wrote to the branch. Two scheduled runs cannot overlap (concurrency group `scrape`), so the cause is usually a manual push. Re-dispatch the workflow; the next run writes a fresh file.

6. If `monitor.yml` opened a `Scraper gap alert` issue, it keeps commenting on the same issue daily until the thresholds hold again. Close it by hand once the gap report passes: `gh issue close <number>`.

7. Write the docs/DATA_LOG.md row: `start_utc` is the `createdAt` of the first failed or missing run (or the last good `last_run_at`), `end_utc` is `last_run_at` of the first good run after the fix, kind `outage`, note what happened and what changed. Fill `end_utc` in when the outage ends, not before.

8. Code fixes go through the normal loop: branch, failing test first, CI green, merge. Never patch on the `data` branch.

## 4. Weekly Sunday check (about 2 minutes)

```
gh run list --workflow scrape.yml --limit 10
gh run list --workflow monitor.yml --limit 1
gh issue list --search "Scraper gap alert" --state open
git -C data-branch pull -q && python -m scraper.gaps --data-root ./data-branch --term-id 2272 --hours 168
python - <<'EOF'
import glob
import pyarrow.parquet as pq
path = sorted(glob.glob("data-branch/snapshots/date=*/*-baseline.parquet"))[-1]
table = pq.read_table(path)
meta = table.schema.metadata or {}
print(path, table.num_rows, meta.get(b"source"), meta.get(b"scope"), meta.get(b"missing_ids"))
df = table.to_pandas()
cols = ["section_number", "component", "enrolled_count", "enroll_capacity", "waitlist_count", "waitlist_capacity", "status"]
print(df[df["course_key"] == "COMPSCI 61A"][cols].head(10).to_string())
EOF
```

Use `--term-id 2268` before the Oct 4 switch. What you are looking for:
- The newest run is less than an hour old and the last ten are green.
- No open `Scraper gap alert` issue, and the monitor's last run succeeded.
- `share_gaps_le_45min` at or above 0.95 for the week, `n_runs` near 336.
- The COMPSCI 61A counts are within a few of the live section page on classes.berkeley.edu (URL pattern in docs/PHASE0.md; the snapshot is up to 30 minutes old). `missing_ids` is empty or short.

If anything is off, go to section 3.

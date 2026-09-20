# Berkeley Waitlist Odds: where the project stands and what is left

Written 2026-09-20 03:55 UTC (session 4); updated 2026-09-20 19:50 UTC after the full Fall 2026 install (PR #5). Give this file to a Claude Code session, or read it yourself, to know the stage, what is still to build, what only Oliver can do, and what happens on which date. It is a snapshot; `docs/dev/HANDOFF.md` carries the detail, `docs/dev/BACKFILL_BACKTEST.md` the backfill plan with findings, `CLAIMS.md` the measured numbers, `CLAUDE.md` the current-step line.

## 1. In one paragraph

The scraper is live (30-minute snapshots of Fall 2026 as the test term, self-dispatching chain on GitHub Actions, data on the `data` branch). The whole analysis pipeline exists and has been exercised on real data: flows, virtual waitlisters, Kaplan-Meier, Cox, an IPCW backtest, precomputed site JSON, and a lookup page (v2) that reads the clearing curve at the asker's own days left. Because Spring 2027 collection cannot start before Oct 26, the site is fed from the finished Fall 2026 cycle as recorded in Berkeleytime's public history: all 6,016 eligible sections are pulled, analysed, backtested and installed (department-level curves, labelled as Berkeleytime's data), and the Spring 2026 pull for the cross-term test is running. What remains is mostly operating and publishing, not building: read the cross-term result and settle department versus bucket-only curves, install the data-driven priority list before Oct 26, switch the term on Oct 4, run the first own-data analysis in November, and Oliver's own launch items (resume, post, browser pass).

## 2. Stage map

| Step | What | Status |
| --- | --- | --- |
| A0 dates and access | Registrar dates, API Central request | Done. SIS API denied to students; classes.berkeley.edu is primary. |
| A1 data route | Probe sources, cross-check | Done (`docs/PHASE0.md`; 20 of 20 cross-checks agree). |
| A2 scraper and storage | Schema, Parquet per run, rebuild, gaps, 3 sources, workflows | Done (295+ tests then; 322 now). |
| A3 go live and monitor | Chain, heartbeat, monitor, data log | **Running.** First full day on the chain passed (46 runs, 97.8% of gaps at or under 45 min, exit 0 at 19:42Z Sep 20); issue #1 closed after the 18:11Z monitor run. Open: Oliver's Sunday check. |
| A4 flow reconstruction | Flows, position model, ASSUMPTIONS, synthetic validation | Done. |
| A5 survival analysis | Calendar, cohort, KM, Cox, PH check, sensitivity, out of sample, `make analysis` | Done on the full Fall 2026 backfill; headline results in CLAIMS.md. Cox at scale needed a linear-time score residual (`analysis/coxfast.py`). |
| A6 publish | Site, methodology, README | Site v2 with department-level Fall 2026 estimates (PR #5); README hero plot from the backfill. Open: a pass in a real browser; site v3 in PR #4 (another session). |
| A7 ship | Resume, r/berkeley post, LinkedIn | Oliver's; not started. |
| B0 backfill patch | `analysis/backfill.py`, `analysis/backtest.py`, cohort fix | Done (PR #2, merged as 4711e1c). |
| B1 pilot and gap question | 300 sections, gap report, Spring 2026 probe | Done. Berkeleytime dark for every section Aug 19 22:45Z to Sep 1 18:30Z; gap rule 180 min; Spring 2026 histories exist. |
| B2 full pull | Fall 2026 and Spring 2026, every eligible section | Fall done (6,016 sections, fetch 02:44Z to 09:42Z with the laptop asleep part of the night); Spring running since 19:29Z Sep 20. |
| B3 analysis and backtest | Reports, cross-term test, CLAIMS rows | Fall done and installed (PR #5): course cells no better than buckets, so the site serves department curves; Cox helps within a regime, extrapolates badly across phases; cross-term run pending the Spring pull. |
| B4 site fixes | Horizon, deadline headline, positions, uncertainty, source label, IPCW out of sample | Done (PR #2). |
| B5 priority list from data | Rank courses by reconstructed joins | Tool done; Fall-only candidate covers 91% of joins (live list 48%); install after the Spring pull, before Oct 26. |
| B6 repo hygiene | LICENSE, homepage, docs/dev, GoatCounter, resume paragraphs | LICENSE, homepage, docs/dev done. Open: GoatCounter (needs Oliver's account); the two "resume says Spring 2026" paragraphs come out after Oliver fixes the resume line. |

## 3. Running right now (2026-09-20 19:50Z)

The full Fall 2026 pull, build, analysis and backtests are done and installed on branch `backfill-full` (install commit a7240f4, PR #5; its timestamp is the pre-registration date for the Spring 2027 cross-term test). A detached script under `caffeinate` is still pulling Spring 2026 (started 19:29Z, about 3,700 sections at one request per 2 s), then builds it, runs `analysis.run --backfill-dir backfill/2262 --no-site`, and runs the three cross-term backtests (fit on Spring 2026, score Fall 2026 at 14 d, 28 d and the deadline) into `reports/backtest_2268/cross_term_*`. Log: the session scratchpad's `full_pull2.log`; outputs land in the working tree and need a commit.

A separate session (oliverguo-16) is building site v3 in a worktree at `/Users/oliverguo/berkeley-waitlist-odds-site` (branch `site-v3`, draft PR #4): a new exporter (`make site-data`) and pages that replace `site/index.html` and `analysis/export.py` wholesale. It follows `meta.estimate_level` and rebases onto the install commit; it must not be merged before its rebase produces the new files, or the live page shows the empty state.

Peer sessions: several Claude Code sessions have been open on this checkout. Run `ListAgents` and `git log -3` first, and tell an open peer before switching branches.

## 4. Still to implement or run (in order)

1. **When the Spring chain prints `=== done`**: read `analysis/out/2262/report.md` and `reports/backtest_2268/cross_term_*/report.md` (`python -m analysis.backtest_summary`). The cross-term run answers whether department curves transfer across terms: if `dept` loses to `bucket` there too, switch the site to bucket-only curves (`export_site_tables` would need a `level="bucket"`; the page copy follows) and say so in the methodology; if it wins, keep department level. Add the Spring 2026 pull to `docs/DATA_LOG.md` (sections, segments, gap share) and a CLAIMS row for the cross-term result. Commit the Spring report as `reports/report_2262_berkeleytime.md` and the cross-term reports; the site JSON does not change unless the level does.
2. **Redeploy after each site/data change**: `gh workflow run pages.yml`, then `curl -sS https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/data/meta.json | python -m json.tool | head` must show `berkeleytime_history` and `estimate_level`.
3. **B5, before Oct 26**: `python -m analysis.priority_from_flows --flows backfill/2268/flows.parquet backfill/2262/flows.parquet --identity backfill/2268/identity.parquet backfill/2262/identity.parquet --top-sections N` with N chosen so `sections_matched` stays near 900 (a run fetches about 917 priority pages plus a shard in 1,380 s; with N=900 on Fall alone the candidate matched 1,122 sections because course patterns match every section of a course); install it as `config/priority_courses.txt`, add a `priority_list` row to `docs/DATA_LOG.md` with the new `priority_sha` and the coverage numbers (Fall-only candidate: 91% of joins vs 48% for the hand-written list).
4. **Headline results** are in `CLAIMS.md` (row "Headline results"); the README carries the hero plot. Re-measure both if the level changes.
5. **Oct 4 term switch** (`docs/RUNBOOK.md` step 7). Deadline for Spring collection to be running: Oct 12.
6. **Nov 9 onward**: first `make analysis TERM=2272` on own data; the weekly `analysis.yml` replaces `site/data` on its own once the own-data cohort has 10 clearings.
7. **Jan to Feb 2027**: refit after Phase 2 closes; the real cross-term backtest, Fall 2026 (frozen at a7240f4) against Spring 2027; final numbers after Feb 10.
8. **Optional model work**: the Cox model extrapolates badly across the Phase 1 to Phase 2 shift (`days_to_instruction` linear, phase dummies absent from a Phase 1 fit): a spline or phase-specific baselines; the position model never clears a "tail" joiner in an empty queue when a seat opens (documented limitation of aggregate counts).

## 5. Only Oliver can do these

- Send the two-sentence note to the Berkeleytime team (ASUC OCTO); the pull is already running with a User-Agent that carries your email.
- Open the live page in a real browser (phone and laptop, light and dark) once the backfilled JSON is published; the sessions had no browser. Check the headline sentence, the floor note, the look-back state (`?today=2026-09-15`), and the pooled tag.
- Create a GoatCounter site and add its script to both pages before anything is shared; visits cannot be backfilled.
- Fix the resume line to "Spring 2027 enrollment cycle", then delete the two paragraphs that mention it (`CLAIMS.md` status paragraph, `docs/dev/FINISH_PLAN_WAITLIST.md` section 3).
- Sunday two-minute check through Feb 14 (`docs/RUNBOOK.md` section 4). Billing page shows $0 (CLAIMS row).
- A7: the r/berkeley post (soft launch before Nov 23 if the numbers hold; main launch two weeks before Fall 2027 Phase 1), resume bullets from `CLAIMS.md`, pin the repo, LinkedIn, the private interview page (why IPCW; why resample by section; why selection ignores today's waitlist; what Fall 2026 could not validate).

## 6. Dates that drive everything

| Date | What |
| --- | --- |
| Oct 4 | Spring 2027 schedule publishes: term switch (item 5 above). |
| Oct 12 | Drop-dead: Spring 2027 collection must be running. |
| Oct 26 | Phase 1 opens. Priority list (item 4) must be installed before this. |
| Nov 9 to 22 | First own-data analysis; soft launch if it holds. |
| Nov 23 | Phase 2 opens. |
| Jan 11 / Jan 19 / Feb 5 / Feb 10, 2027 | Adjustment period; instruction; last automatic waitlist run; add/drop deadline (freeze). |

## 7. Facts a new session must not rediscover

- classes.berkeley.edu: stdlib `urllib` only (the site rejects `requests`/`httpx` TLS handshakes); never request `/search/`; discovery by `/rss.xml` and `/node/<id>`. Berkeleytime is Cloudflare-403 from GitHub runners: the backfill runs from a laptop only.
- Berkeleytime `GetEnrollment` returns run-length history with real SIS `sectionId`; the gateway rejects the second recorded op (schema dropped `seatReservationTypes`), the first works; one request per 2 s. Poll spacing at changes was 15 min from July 2026 but 45 to 130 min in March to June, hence the 180-minute gap rule. Every section was dark Aug 19 22:45Z to Sep 1 18:30Z: Fall 2026 validates Phase 1 and Phase 2 clearing only; the backtest scores only observable horizons (14 and 28 days).
- Only `scrape.yml` writes the `data` branch; only `analysis.yml` commits to `main` on its own; workflows dispatch each other with the built-in token. Data gaps are permanent and logged in `docs/DATA_LOG.md` (rows are never edited; corrections are new rows).
- `backfill/` is gitignored Berkeleytime data, labelled `berkeleytime_history`, never a collection claim. The resume's collection claims are about Spring 2027 only.
- Tests: `python -m pytest` (addopts already has `-q`; a second `-q` hides the summary line), 322 tests in about 60 s; `tests/test_site.py` needs node (`~/.nvm/versions/node/*/bin/node`).
- `CLAIMS.md` numbers are copied from command output, never typed.

## 8. How to resume

```
cd /Users/oliverguo/berkeley-waitlist-odds && source .venv/bin/activate
git status && git log -3 --oneline && git branch --show-current     # expect backfill-full (or main after PR #3 merges)
git -C data-branch pull -q
python -m pytest                                                     # 322 passed
gh run list --workflow scrape.yml --limit 4                          # chain alive?
grep -E "^=== |^exit " <scratchpad>/full_pull.log | tail            # if the pull is still running; else see backfill/2268/meta.json
```

Prompt to paste into a new Claude Code session:

```
Continue the Berkeley Waitlist Odds project at /Users/oliverguo/berkeley-waitlist-odds. Read docs/dev/STATUS.md
first (stage, what is left, dates), then docs/dev/HANDOFF.md and the Current step line in CLAUDE.md. Run ListAgents
and git log -3 before editing (other sessions may be open on this checkout). Do the first open item in STATUS.md
section 4 that is due, through the build loop in docs/dev/FINISH_PLAN_WAITLIST.md section 1.2. Rules: never commit
to the data branch by hand; only analysis.yml commits to main on its own; every number in CLAIMS.md is copied from
command output; backfilled Berkeleytime data is labelled berkeleytime_history and never a collection claim; the site
never shows simulated numbers.
```

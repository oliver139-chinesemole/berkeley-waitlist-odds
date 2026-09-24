# Berkeley Waitlist Odds: where the project stands and what is left

Written 2026-09-20 03:55 UTC (session 4); updated 2026-09-21 00:30 UTC after the Spring 2026 pull and the cross-term backtest (PR #6). Give this file to a Claude Code session, or read it yourself, to know the stage, what is still to build, what only Oliver can do, and what happens on which date. It is a snapshot; `docs/dev/HANDOFF.md` carries the detail, `docs/dev/BACKFILL_BACKTEST.md` the backfill plan with findings, `CLAIMS.md` the measured numbers, `CLAUDE.md` the current-step line.

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
| A6 publish | Site, methodology, README | Site v2 with course-level Fall 2026 estimates (PR #6); README hero plot from the backfill. Open: a pass in a real browser; site v3 in PR #4 (another session); the Spring 2026 source decision. |
| A7 ship | Resume, r/berkeley post, LinkedIn | Oliver's; not started. |
| B0 backfill patch | `analysis/backfill.py`, `analysis/backtest.py`, cohort fix | Done (PR #2, merged as 4711e1c). |
| B1 pilot and gap question | 300 sections, gap report, Spring 2026 probe | Done. Berkeleytime dark for every section Aug 19 22:45Z to Sep 1 18:30Z; gap rule 180 min; Spring 2026 histories exist. |
| B2 full pull | Fall 2026 and Spring 2026, every eligible section | Done: Fall 6,016 sections (fetch 02:44Z to 09:42Z Sep 20, laptop asleep part of the night), Spring 6,131 sections (19:29Z to 23:16Z under caffeinate). |
| B3 analysis and backtest | Reports, cross-term test, CLAIMS rows | Done. Within Fall 2026 nothing beat the bucket across the Phase 1 to 2 shift; across terms (Spring 2026 fitted, Fall 2026 scored) course beats dept beats bucket at every horizon, so the site serves course curves. Cox ranks well, calibrates badly: report only. |
| B4 site fixes | Horizon, deadline headline, positions, uncertainty, source label, IPCW out of sample | Done (PR #2). |
| B5 priority list from data | Rank courses by reconstructed joins | Installed in draft PR #9 (branch `p5-priority-list`): top 1,500 sections' courses plus every course with at least 100 joins, both cycles; 1,213 live sections in 661 courses per run, 89.2% of joins covered (hand list 47.7%), 51.0% of queued section-terms. |
| B6 repo hygiene | LICENSE, homepage, docs/dev, GoatCounter, resume paragraphs | LICENSE, homepage, docs/dev done. Open: GoatCounter (needs Oliver's account); the two "resume says Spring 2026" paragraphs come out after Oliver fixes the resume line. |

## 3. State right now (2026-09-21 00:30Z)

Both finished cycles are pulled, built and analysed: Fall 2026 (6,016 sections, installed as the site's data, PR #5) and Spring 2026 (6,131 sections, 2 of 202 days dark, adjustment period and first weeks of instruction observed). The cross-term backtest (fit on Spring 2026, score Fall 2026) is done: course curves beat department curves beat the position bucket at every observable horizon, so the site's estimate level is back to `course` (PR #6 re-exports `site/data`; `meta.estimate_level` course). Nothing is running in the background. Install commit a7240f4 (2026-09-20 19:49Z) is the pre-registration point for the Spring 2027 cross-term test.

A separate session (oliverguo-16) built site v3 in a worktree (`/Users/oliverguo/berkeley-waitlist-odds-site`, branch `site-v3`, PR #4, ready for Oliver's review): a new exporter (`make site-data ESTIMATE_LEVEL=course`) and pages that replace `site/index.html` and `analysis/export.py` wholesale, with an Accuracy page from `reports/backtest_2268`. It must be rebuilt at course level before merging.

Peer sessions: several Claude Code sessions have been open on this checkout. Run `ListAgents` and `git log -3` first, and tell an open peer before switching branches.

**Decision taken 2026-09-24 (P4, draft PR #11 on `site-v3`):** the page serves Spring 2026 for Spring 2027, course level, labelled; Fall 2026 stays frozen at a7240f4 for the pre-registered test. Fall 2026 gives own curves to courses carrying 62.0% of Spring 2026's reconstructed joins, Spring 2026 99.5%; Phase 1 joiners at positions 1 to 5 got in within 14 days 66% of the time in Spring 2026 against 48% in Fall 2026, and Spring 2026's Phase 1 horizons (68 to 82 days to instruction) match Spring 2027's (65 to 85). Numbers and the export command in the data-log decision row on that branch.

**2026-09-23 22:40Z (session 6):** collection degraded from 2026-09-21 14:37Z (classes.berkeley.edu pages at 2 to 5 s with 20 s read timeouts; the runs that wrote nothing observed 402 to 547 of about 1,290, the rest 667 to 1,311; nine runs on Sep 22 to 23 exited 4 and wrote nothing; issue #7). Draft PR #8 (branch `p2-throughput`) raises the request policy in scrape.yml to 2 per second with 4 in flight, logs the outage and the decision in docs/DATA_LOG.md, and installs docs/dev/MASTER_PLAN.md, which now leads: read its section 12 for what was verified on Sep 23. The same PR restricts analysis.yml's site-data replacement to term 2272: the Fall 2026 own-data cohort had 209 post-deadline clearings on Sep 23 and would have displaced the backfill on Sunday Sep 27. Nothing changes until #8 is merged.

## 4. Still to implement or run (in order)

1. **Done 2026-09-21:** Spring 2026 pulled and analysed, cross-term backtests read, level set to course, reports and rows committed (PR #6). Remaining from it: nothing except Oliver's source decision above.
2. **Redeploy after each site/data change**: `gh workflow run pages.yml`, then `curl -sS https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/data/meta.json | python -m json.tool | head` must show `berkeleytime_history` and `estimate_level`.
3. **B5, installed 2026-09-24 (draft PR #9, branch `p5-priority-list`)**: `python -m analysis.priority_from_flows ... --top-sections 1500 --min-course-joins 100 --catalog ...` over both cycles: 1,013 exact course patterns, 1,213 live sections in 661 courses per run (the hand list fetched 1,047 in 429), selection 1,415 to 1,473 with one shard, 89.2% of reconstructed joins and 51.0% of queued section-terms covered (hand list 47.7% and 29.7%); `priority_sha` and the numbers in the data-log row. MATH 1A/1B no longer exist (calculus is MATH 51/52). Merge after #8.
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

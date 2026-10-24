# Berkeley Waitlist Odds: where the project stands and what is left

Written 2026-09-20 03:55 UTC (session 4); renewed in full 2026-09-25 08:00 UTC (session 8) after sessions 6 and 7 merged the collection stack and opened the site stack. Renewed in part 2026-09-25 19:45Z (session 9): section 3's pull-request table and merge order, section 4's list, the tests line. Renewed 2026-10-23 22:50Z (session 11, unattended): sections 1, 4, 5 and 6 rewritten, section 2's rows corrected, a dated update at the top of section 3; `docs/dev/NEXT_2026-10-23.md` leads from here (it replaces section 4 as it stood and `docs/dev/NEXT_SITE_2026-09-25.md`). Give this file to a Claude Code session, or read it yourself, to know the stage, every open branch and pull request, what is still to build, what only Oliver can do, and what happens on which date. It is a snapshot; `docs/dev/MASTER_PLAN.md` leads on scope and build order, `docs/dev/HANDOFF.md` carries each session's detail (session 7 has a note for Oliver at its top), `docs/dev/SITE_HANDOFF.md` is the website's own ledger, `docs/dev/BACKFILL_BACKTEST.md` the backfill findings, `CLAIMS.md` the measured numbers, `CLAUDE.md` the current-step line. Every number below was printed by a command on 2026-09-25 between 07:45Z and 08:00Z unless a date says otherwise; the 2026-10-23 numbers were printed on 2026-10-23 between 22:39Z and 23:10Z.

## 1. In one paragraph

Every PR from sessions 7 to 10 (#4, #11, #15 to #32) merged into `main` on 2026-09-25; `main` has had no human commit since, only the four weekly `analysis.yml` commits (Sep 27, Oct 4, Oct 11, Oct 18), which touch `reports/report_2268.md` and four PNGs and are noise (`docs/dev/NEXT_2026-10-23.md` 4.2). **The scraper is still collecting Fall 2026 (term 2268).** The chain is healthy (`status.json` at 22:21Z on 2026-10-23: delta, 1,457 observed, 0 missing, 814.6 s), but Fall 2026's add deadline passed on Sep 11, so its deltas carry only post-deadline changes (337 of the 1,010 October runs wrote rows, 7,379 in all, mostly drops; the last eight runs of Oct 23 wrote 0) and not one Spring 2027 row exists; the Oct 4 term switch in `docs/RUNBOOK.md` step 7 never happened and the Oct 12 drop-dead passed. Spring 2027 Phase 1 opens Mon Oct 26, the cycle this project exists to capture. The Spring 2027 catalog is discovered (`catalog/2272/catalog.json` on `data` at 5ada7c4: 7,551 sections, every `section_id` empty), but selecting from it as the code stood would pick 3,878 to 3,933 pages a run against about 2,468 the 1,380 s budget holds at the last Fall run's rate (1,457 pages in 814.6 s; the plan's 2,370 used an earlier 1.72 pages/s), and the coverage check would not see the cut because it counts only known ids (NEXT 1.1 and 1.2; fixed in PR #43 `scrape-spring-selection`, reviewed, to merge before the switch: a section is selected when its class number is below 100, or when its component is the one carrying the course's lowest class number, and every selected page that yields no row counts as missing; 1,184 to 1,238 pages a run). The site serves Spring 2026 Berkeleytime curves as the Spring 2027 forecast (course level, 2,114 courses, 299,826 clearings); `live/latest.json` (1,443 rows, term 2268) and `status.json` are written every run; `titles.json` was never exported, so title search is dead on the live site (NEXT 4.1). Tests: 442 passed on `main`. From here `docs/dev/NEXT_2026-10-23.md` is the plan: the switch this weekend (Oliver, after the selection PR merges), the first-week checks, stopping the automatic site swap before the first own-data Sunday, then the open items.

## 2. Stage map

| Step | What | Status |
| --- | --- | --- |
| A0 dates and access | Registrar dates, API Central request | Done. SIS API denied to students; classes.berkeley.edu is primary. |
| A1 data route | Probe sources, cross-check | Done (`docs/PHASE0.md`; 20 of 20 cross-checks agree, repeated 2026-09-23 in `docs/crosscheck_2026-09-23.md`). |
| A2 scraper and storage | Schema, Parquet per run, rebuild, gaps, 3 sources, workflows | Done. Request policy and catalog titles added Sep 24 (PRs #8, #10; `docs/DESIGN_A2.md` sections 16 to 18). |
| A3 go live and monitor | Chain, heartbeat, monitor, data log | **Running on the wrong term** (2026-10-23): the chain is healthy (1,457 observed, 0 missing, 814.6 s at 22:21Z), but Fall 2026's add deadline passed on Sep 11, so most runs write 0 rows and the rest post-deadline drops, and no Spring 2027 row exists; the switch to 2272 is section 4 items 1 and 2. |
| A4 flow reconstruction | Flows, position model, ASSUMPTIONS, synthetic validation | Done. |
| A5 survival analysis | Calendar, cohort, KM, Cox, PH check, sensitivity, out of sample, `make analysis` | Done on both backfilled cycles; headline results in `CLAIMS.md`. Cox at scale uses `analysis/coxfast.py` (linear-time score residual). |
| A6 publish | Site, methodology, README | v3 live on `main` since 2026-09-25 (Spring 2026 curves served for Spring 2027, course level). Open: title search not live (`titles.json`, NEXT 4.1); the Oct 26 copy and the board's term guard are in PR #42 (reviewed, not merged); Oliver's phone pass. |
| A7 ship | Resume, r/berkeley post, LinkedIn | Oliver's; not started. |
| B0 to B4 backfill and backtest | Module, pilot, full pulls, analysis, site fixes | Done (PRs #2, #5, #6). Fall 2026 install commit a7240f4 is the pre-registration point for the Spring 2027 test. |
| B5 priority list from data | Rank courses by reconstructed joins | Done and live (PR #9, merged 2026-09-24 09:14Z): 1,013 course patterns, 1,213 live sections in 661 courses per run, 89.2% of both cycles' joins covered (hand list 47.7%); `priority_sha` 613469f9… in every run's footer since 09:37Z Sep 24. |
| B6 repo hygiene | LICENSE, homepage, docs/dev, GoatCounter, resume paragraphs | LICENSE, homepage, docs/dev done. Open: GoatCounter (Oliver's account); the two "resume says Spring 2026" paragraphs come out after Oliver fixes the resume line. |
| MASTER_PLAN P items | P1 merge #4; P2 throughput; P3 live file; P4 source; P5 list; P6 GoatCounter | P1 to P5 done (merged 2026-09-24 and 25). P6 is Oliver's. |
| MASTER_PLAN Q items (search) | Q1 to Q8 | Q1 to Q3, Q5, Q7, Q8 done; Q4 merged but not live (NEXT 4.1); Q6's candidates and department browse done, its logged miss event open. |
| MASTER_PLAN S items (sections) | S1 to S9 | S1 to S3, S5, S6 done; S4, S7 to S9 open (S4 and S8 need own Spring data). |
| MASTER_PLAN U items (design) | U1 to U8 | U3, U4, U7 done; U8 3 of 8 findings fixed, 5 deferred for Oliver; U1, U2, U5, U6 open. |

## 3. State right now (2026-09-25 08:00Z)

**Update 2026-10-23 22:50Z (session 11, unattended; plan `docs/dev/NEXT_2026-10-23.md`).** `main` is at 926645e: 55881a7 plus the four weekly analysis commits. The table below is history (every row merged on 2026-09-25). The one PR open before this session was #33 (`s10-merge-docs`, session 10's docs); this session's docs branch `docs-2026-10-23` carries its commits, so #33 can be closed when that branch merges. Draft PRs opened this session after a subagent review of each diff, none merged: **#43** `scrape-spring-selection` (NEXT 1.1, 1.2 and the RUNBOOK/Makefile/monitor text; 3 commits, 450 tests; **merge first, then the switch**), **#42** `site-term-guards` (NEXT 1.4, 1.5 plus a fourth dated string on the Methods page; 2 commits, 458 tests), and `docs-2026-10-23` (NEXT 4.3: this file, CLAUDE.md, HANDOFF, SITE_HANDOFF, MASTER_PLAN section 3; its PR supersedes #33). Review verdicts and the rulings are in HANDOFF session 11. **Batch 2 (Oct 24, 00:08Z to 07:00Z, after Oliver's second review `docs/dev/NEXT_2026-10-23_batch2.md`):** PR #45 `titles-live` (NEXT 4.1; stacked on #43; 454 tests), PR #46 `analysis-swap-gate` (NEXT section 3; 457 tests; its first commit df35894 is the stopgap, cherry-pickable alone if the rest slips past Oct 31); the review leftovers landed on #43 (39b77cc) and #42 (84f84a5); the three code branches merge together with one expected conflict on analysis.yml's run line and one on DATA_LOG's appended rows, 469 tests on the merged tree. Scraper at 22:21Z: term 2268, delta, 1,457 observed, 0 missing, 0 written, 814.6 s; `live/latest.json` 1,443 rows, term 2268; data branch at 5ada7c4. The main checkout is still on `backfill-full`; three plain worktrees `/Users/oliverguo/bwo-scrape`, `bwo-site` and `bwo-docs` hold the three branches.

**Update 2026-09-25 20:10Z (session 10, Oliver present).** Every PR in the table below is merged into `main`, on Oliver's instruction, in the merge order given at the end of this section: #15 (bed1aaa), #32 (9c0f8d0), #18 (3b6bce4), #21 (6bdc3e7), #4 (d397833), #11 (cdbf2e7), #17 (3c2057c), #16 (e8d4bdc), #19 (68aacd4), #20 (37e49a1), #24 (d6e73e8), #29 (2bae56b), #22 (dce3de4), #31 (71a474d), #23 (7a613c2), #25 (5b6e498), #26 (20c7d24), #27 (b7fc82c), #30 (9bae5db), #28 (55881a7). `main` is at 55881a7. Six branches needed `main` merged in first; each resolution is a merge commit on the branch (`site-v3` 0a3e214, `c6-title-search` 90a6f64, `c3-fallback-ladder` e897905, `c2-status-line` 58d9a14, `c5-dept-pages` 6ad6bf0, `c6-titles-export` 540df32) and docs/dev/HANDOFF.md session 10 says what each kept. `pages.yml` deployed 9bae5db at 20:01Z (#28 touched no site file); every page and data file answers 200 and the deployed files carry the status line, the ladder, the title matcher and `dept.html`; live `data/meta.json` reads `term_name` Spring 2026, `forecast_term_name` Spring 2027, `estimate_level` course, 2,114 courses, 2,902 sections. `python -m pytest` on the merged tree: 442 passed. Still to appear: `live/latest.json` on the `data` branch (written by the next `scrape.yml` run, now that #4's step is on `main`) and `data/titles.json` on the site (`make site-data` has not run with a catalog since #28). No branch was deleted; the plain worktree `/Users/oliverguo/bwo-merge` used for the resolutions is removed at the close of session 10. The rest of this section is the state as read at 08:00Z and 19:45Z.

**Branches and checkouts.** `main` is at a5b36df (merge of PR #14). Merged on 2026-09-24 on Oliver's instruction, in order: #8 (7294879, request policy, MASTER_PLAN installed, analysis.yml guard on term 2272), #9 (71882a7, generated priority list), #10 (45f2e07, catalog titles and instructors), #12 (0165599, `PrioritySpec.rank` dict lookup, session 6 handoff), #13 (f0f0e44, `docs/dev/SITE_HANDOFF.md`), #14 (a5b36df, the data-log row for the first run at the new policy). The main checkout at `/Users/oliverguo/berkeley-waitlist-odds` sits on `backfill-full` at 7f348ed (PR #6's commit; stale but clean, only an untracked `.claude/`); leave it, and work in worktrees. The site worktree `/Users/oliverguo/berkeley-waitlist-odds-site` is on `site-v3` at ea61bf4. Seventeen more worktrees exist under `.claude/worktrees/`: the named ones from sessions 6 to 8 (`p2-throughput`, `p4-spring-source`, `p5-priority-list`, `q7-titles`, `s6-followups`, `s7-orchestrator` (locked), `s8-status` (this file)) and ten `agent-*` ones from session 7's subagents on the branches `u3-u4-design`, `s1-s3-fixture`, `s1-s3-board`, `q1-q3-search` and `review-*`. Every PR branch is pushed; the worktrees can go with `git worktree remove <path>` (`git worktree unlock` first for the locked one) once their PRs merge. No other Claude session was open at 07:49Z.

**Open pull requests** (state read from GitHub at 19:45Z; every one MERGEABLE, every head's CI green unless noted):

| PR | Branch → base | State | What |
| --- | --- | --- | --- |
| #4 | `site-v3` → `main` | open, not draft, **MERGEABLE** (head 5325cbc) | Site v3. `main` a5b36df merged in as a3e0f21 (session 9, B1: methodology keeps site-v3's sentence, the three ledgers keep both sides); the B1 review's one-line CLAIMS fix 5325cbc. |
| #11 | `p4-spring-source` → `site-v3` | draft, rebased (45751af), Rebase notes in its body | P4: the page serves Spring 2026 for Spring 2027. |
| #15 | `s7-docs` → `main` | draft | Sessions 7 and 8 docs; the session 9 docs PR (the session 9 docs PR (`s9-docs`, stacked on `s7-docs`)) is stacked on it. |
| #16 | `u3-u4-design` → `site-v3` | draft, rebased (5112604) | U3 palette as tokens, U4 type; three decisions for Oliver. |
| #17 | `q1-q3-search` → `site-v3` | draft, rebased (797021b) plus the Rebase-notes commit 23ec3ec | Course search Q1 to Q3, Q5, Q6 part, Q8; the fixture and names now hold on Spring 2026 data. |
| #18 | `agent-definitions` → `main` | draft | The seven `.claude/agents/*.md` definitions. |
| #19 | `s1-s3-fixture` → `site-v3` | draft, rebased (ea3fce5), Rebase notes in its body | The board fixture, harness hooks, the A3 contract. |
| #20 | `s1-s3-board` → `s1-s3-fixture` | draft, rebased (b39ef8b) | A3: the live section board. |
| #21 | `claims-remeasure-2026-09-25` → `main` | draft | The three scraper CLAIMS rows re-measured 24 h after the request policy. |
| #22 | `design-followups` → `u3-u4-design` | draft, reviewed, approved | Dark `--tint`; `--s1` at 3.02:1 on white (2.76:1 on `--bg`, Oliver's call). |
| #23 | `board-followups` → `s1-s3-board` | draft, reviewed, approved | Partial-null rows never "open"; phone rows; em-dash tests. VoiceOver pass needed. |
| #24 | `search-followups` → `q1-q3-search` | draft, reviewed, approved (one fix round) | Comma-spelt Guide names, the course page's "Showing X for" line, guards, one comparator. |
| #25 | `s6-crosslist` → `board-followups` | draft, reviewed, approved | S6: cross-listed sections are separate rows, a contract test and one sentence. |
| #26 | `c3-fallback-ladder` → `site-v3` | draft, reviewed, approved (one fix round) | S5: the fallback ladder printed with every curve. |
| #27 | `c2-status-line` → `site-v3` | draft, reviewed, one Important fixed and re-reviewed | B2: the data-status sentence read live from the data branch's `status.json`. |
| #28 | `c6-titles-export` → `site-v3` | draft, reviewed, approved (one fix round); merge after #11 and rebase | Q4 exporter: `titles.json` from the catalog; `--catalog`, `--titles-only`. |
| #29 | `c6-title-search` → `search-followups` | draft, reviewed, approved (one fix round) | Q4 matcher: title and instructor search, lazy-loaded, stop words. |
| #30 | `c5-dept-pages` → `site-v3` | draft, reviewed, approved (one fix round) | Department pages at `dept.html?subject=CODE`. |
| #31 | `u8-copy-audit` → `design-followups` | draft, verified from the diff | U8 copy audit: the findings file, three one-line label fixes, five deferred for Oliver. |

**Merge order:** #15 (with the session 9 docs PR (`s9-docs`, stacked on `s7-docs`)), #18 and #21 any time. Then #4, #11, `gh workflow run pages.yml`, the curl loop (SITE_HANDOFF section 2). Then #17, #16, #19, #20 (proven to merge in that order, B3). Then the follow-ups, each rebased onto `main` once its base has merged: #24, #29 (on #17); #22, #31 (on #16); #23, #25 (on #20); #26, #27, #30 (on `site-v3`); #28 last, after #11, with its three noted conflicts.

**Scraper, measured at 07:49Z.** `python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 24`: `n_runs` 47 (1 baseline, 46 deltas, all priority scope), `largest_gap_min` 31.064, `p95_gap_min` 30.482, `share_gaps_le_45min` 1.0, `median_missing_share` 0.0, `max_missing_share` 0.1872 (the 00:37Z run). `status.json`: last run 2026-09-25T07:07:40Z, 1,453 observed, 0 missing, 816.754 s, shard 2/12; the 07:37Z run was in progress. No 429 or 403 has appeared, so RUNBOOK item 9's rollback has not fired and the flags are untouched. The four latency episodes since the policy change have `note` rows in `docs/DATA_LOG.md` on PR #15: 19:07Z Sep 24 (198 missing, all but 2 in the shard tail), 22:37Z (2 missing, sweep 1,342.8 s), 00:37Z Sep 25 (243 missing, 30 on the priority list, the episode began with the run), 06:07Z (1 missing, 1,381.5 s). The arithmetic (`docs/DESIGN_A2.md` section 16): at 4 in flight the budget covers about 1,450 pages up to 3.8 s a page; `--max-concurrency 6` would reach about 5.7 s a page at the same 2-per-second ceiling. That change is Oliver's to make, with a `decision` row.

**Live site.** v2 on `main`, `data/meta.json` generated 2026-09-21T01:56Z: Fall 2026, `berkeleytime_history`, `estimate_level` course, 2,050 courses, 220,196 clearings. `live/latest.json` is a 404 on the `data` branch until PR #4 merges (its `scrape.yml` step lives on `site-v3`). The Sunday Sep 27 `analysis.yml` run will not touch `site/data`: since PR #8 the guard requires term 2272 as well as 10 clearings (the Fall 2026 own-data cohort had 209 post-deadline clearings on Sep 23 and would have displaced the backfill).

**Tests.** `python -m pytest` on `main`'s tree: 342 passed (07:58Z). On `site-v3` after the merge of `main` (a3e0f21): 375 passed; the integration of the whole stack (session 9, B3): 388 passed. Each follow-up PR carries its own count in its body.

## 4. Still to implement or run (in order)

The order of work is `docs/dev/NEXT_2026-10-23.md` (NEXT below); this list is its summary.

1. **Merge PR #43 `scrape-spring-selection`** (Oliver): primary-like selection (a section is selected when its class number is below 100, or when its component is the one carrying the course's lowest class number) and a coverage count that sees unfetched pages. Without it the first Spring runs would silently collect about 60% of the priority list and none of the shards, and nothing would alert (NEXT 1.1, 1.2).
2. **The switch** (Oliver, Sat or Sun Oct 24 to 25; NEXT 1.3): `gh variable set SCRAPE_TERM --body "Spring 2027"`, `gh workflow run scrape.yml -f term="Spring 2027"`, then `status.json` must read `2272 baseline`, `complete True`, observed close to `selected=` in the run log. If the PR cannot merge by Sunday evening, switch anyway. Afterwards: the `term_switch` and zero-row `note` rows in `docs/DATA_LOG.md`, and close the first false "fewer than 40 runs" monitor issue.
3. **Merge PR #42 `site-term-guards`** (Oliver): the Oct 26 copy, the Methods sentence and the board's term guard (NEXT 1.4, 1.5); look at the course page on a phone after `pages.yml`. Merge PR #44 (`docs-2026-10-23`) and close #33; then PR #45 (`titles-live`, stacked on #43).
4. **First week of Phase 1** (NEXT section 2): the daily gap command on 2272; `selected=` against `observed=` in each run log; the three CLAIMS scraper rows re-measured on the first full 24 h; the `--max-concurrency` 4 to 6 call if a run exits 4; one sentence in DESIGN_A2 and ASSUMPTIONS that priority-scope runs write no tombstones.
5. **Before Sunday Nov 1: merge PR #46 `analysis-swap-gate`** (NEXT section 3): the `site/data` swap now needs a `workflow_dispatch` with `publish_own=true`, keeps `backtest.json` and `titles.json`, carries the prereg fields only from a meta of the same term and source, and the weekly run censors gaps over 180 min in the position walk. If the full PR cannot land by Oct 31, cherry-pick its first commit df35894 alone. Merging it is the decision to keep the Spring 2026 curves for the whole Spring 2027 cycle; before any deliberate publish, the Accuracy and About copy needs rewording (RUNBOOK section 5).
6. **Title search: merge PR #45 `titles-live`** (NEXT 4.1; stacked on #43): `site/data/titles.json` from the Spring 2027 catalog's primary-like entries (1,425 of the index's 2,114 courses), `--catalog` in `analysis.run`, the weekly run and `make analysis`, a test that pins the shipped file. Follow-ups: a weekly `--titles-only` refresh; `make analysis` lacks `--max-interval-min 180`.
7. **Weekly-commit noise** (NEXT 4.2): stop committing `reports/figures_<term>/` and `reports/report_<term>.md` from the weekly run; delete the committed Fall 2026 ones; one copy of the validation figure.
8. **Small code items** (NEXT 4.4), then the open MASTER_PLAN items (its section 3, updated 2026-10-23): Q6's logged miss event, S4, S7 to S9, U1, U2, U5, U6, U8's five deferred findings, L11, L15, C5, C6, I7 (I5, I6 and I8 have been on the insights page since v3).
9. **Jan to Feb 2027:** refit after Phase 2 closes; the pre-registered cross-term test: Fall 2026 frozen at a7240f4 (CLAIMS, DATA_LOG) and the served Spring 2026 curves at 7f348ed (`prereg_commit` in `site/data/meta.json`), both scored unchanged against Spring 2027 after Feb 10.
10. **Optional model work:** the Cox model extrapolates badly across the Phase 1 to Phase 2 shift (`days_to_instruction` linear, phase dummies absent from a Phase 1 fit): a spline or phase-specific baselines; the position model never clears a "tail" joiner in an empty queue when a seat opens (documented limitation of aggregate counts).

## 5. Only Oliver can do these

- Merge PR #43 (`scrape-spring-selection`), then run the three commands in NEXT 1.3 (needs `gh` logged in as oliver139-chinesemole). Target: Saturday or Sunday Oct 24 to 25.
- Close or ignore the first false "fewer than 40 runs" monitor issue on switch day; do not loosen the threshold.
- Decide NEXT section 3 (recommended: no automatic swap) and the `--max-concurrency` 4 to 6 question; a `decision` row in `docs/DATA_LOG.md` either way.
- Merge PR #42 (`site-term-guards`), PR #44 (docs; then close #33, whose commits it carries), PR #46 (`analysis-swap-gate`, before Nov 1) and PR #45 (`titles-live`, after #43); look at the live site on a phone; check `https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/data/meta.json` still says Spring 2026 / Spring 2027 after the next `pages.yml`.
- PR #16's three design decisions and PR #17's two (HANDOFF session 9 item 2), still open; the VoiceOver pass on the board.
- Create a GoatCounter site and add its tag to every page before any link is shared (P6); visits cannot be backfilled.
- Fix the resume line to "Spring 2027 enrollment cycle", then delete the two paragraphs that mention it (`CLAIMS.md` status paragraph, `docs/dev/FINISH_PLAN_WAITLIST.md` section 3); the resume line itself once Spring numbers exist (CLAIMS row 1).
- The two-sentence note to the Berkeleytime team (ASUC OCTO), if not already sent; both pulls ran with a User-Agent carrying his email.
- Sunday two-minute check through Feb 14 (`docs/RUNBOOK.md` section 4). Billing page shows $0 (CLAIMS row).
- Custom domain (optional, about $12 a year, before the r/berkeley post). A7: the post (soft launch before Nov 23 if the numbers hold; main launch two weeks before Fall 2027 Phase 1), resume bullets from `CLAIMS.md`, pin the repo, LinkedIn, the private interview page.

## 6. Dates that drive everything

| Date | What |
| --- | --- |
| Oct 4 and Oct 12 | The planned switch date and the drop-dead both passed with the scraper still on Fall 2026 (NEXT section 0). |
| Oct 24 to 25 | Merge PR #43, then the switch (NEXT 1.3). Partial Spring data beats more zero-row runs: switch by Sunday evening even if the PR is not in. |
| Oct 26 (Monday) | Phase 1 opens. The first daily gap check on 2272 (NEXT section 2). The first daily monitor after the switch opens a false "fewer than 40 runs" issue. |
| 24 h after the switch | First full day of Spring data: the three CLAIMS scraper rows re-measured. |
| Nov 1 (Sunday) | The first weekly `analysis.yml` that may pass the 10-clearing guard and replace `site/data`: the swap gate (NEXT section 3) must be merged before it, or that run stopped by hand. |
| Nov 15 / Nov 23 | Phase 1 for continuing students ends; Phase 2 opens. |
| Jan 11 / Jan 19 / Feb 5 / Feb 10, 2027 | Adjustment period; instruction; last automatic waitlist run; add/drop deadline (freeze). |

## 7. Facts a new session must not rediscover

- classes.berkeley.edu: stdlib `urllib` only (the site rejects `requests`/`httpx` TLS handshakes); never request `/search/`; discovery by `/rss.xml` and `/node/<id>`. Berkeleytime is Cloudflare-403 from GitHub runners: the backfills ran from a laptop only (`caffeinate -i`, or the laptop sleeps and a two-hour fetch takes seven).
- Since 2026-09-21T14:37Z classes.berkeley.edu answers in 2 to 5 s with 20 s read timeouts in episodes of about fifteen minutes. `scraper/http.py`'s limiter spaces request *starts*, so throughput is concurrency over latency; the policy is 2 starts per second with 4 in flight (`docs/DESIGN_A2.md` section 16), the budget 1,380 s. A 429 or 403 is the rollback trigger (RUNBOOK item 9).
- Berkeleytime `GetEnrollment` returns run-length history with real SIS `sectionId`; the gateway rejects the second recorded op, the first works; one request per 2 s; gap rule 180 min. Fall 2026 was dark for every section Aug 19 22:45Z to Sep 1 18:30Z (so it validates Phase 1 and 2 clearing only); Spring 2026 has no such hole and observes the instruction phase, which is why the page serves it.
- Backtest verdicts: within Fall 2026 nothing beats the position bucket across the Phase 1 to 2 shift; across terms (Spring 2026 fitted, Fall 2026 scored) course beats department beats bucket at every horizon, so `estimate_level` is `course`. Cox ranks well and calibrates badly: report only. `analysis/coxfast.py` makes the cluster-robust Cox linear-time.
- MATH 1A and 1B no longer exist in Fall 2026: calculus is MATH 51 and 52 (Spring 2026 keys still say 1A/1B).
- The priority list is generated (`analysis/priority_from_flows.py`); any edit changes `priority_sha`; log it in `docs/DATA_LOG.md`. Only `scrape.yml` writes the `data` branch; only `analysis.yml` commits to `main` on its own (site data for term 2272 only); workflows dispatch each other with the built-in token. Data gaps are permanent and logged (rows are never edited; corrections are new rows).
- `backfill/`, `analysis/out/` and `data-branch/` are gitignored and exist only in the main checkout. In a worktree, clone the data branch with `git clone -q --depth 1 --branch data --single-branch git@github-chinesemole:oliver139-chinesemole/berkeley-waitlist-odds.git data-branch`; read `status.json` live through `gh api repos/<owner>/<repo>/contents/status.json?ref=data --jq .content | base64 -d` (the raw URL is cached about 5 min).
- Worktrees made by `EnterWorktree` live under `.claude/worktrees/<name>` on branch `worktree-<name>`; push with `git push -u origin HEAD:<clean-name>`. Their guard refuses `git -C`, command substitution around git, chained git commands and heredocs whose text mentions git: write scripts and long docs with the Write tool and run them by path, commit with `git commit -F <file> -- <paths>`. The Agent tool has no effort field; `.claude/agents/*.md` (PR #18) must exist at session start. Use the main checkout's `.venv/bin/python` from any worktree.
- Tests: `python -m pytest` (addopts already has `-q`; a second `-q` hides the summary line); `tests/test_site.py` needs node (`~/.nvm/versions/node/*/bin/node`). The browser smoke runs locally with `NODE_PATH=/Users/oliverguo/paddleiq/node_modules`.
- `CLAIMS.md` numbers are copied from command output, never typed. `backfill/` is Berkeleytime's data, labelled `berkeleytime_history`, never a collection claim; the resume's collection claims are about Spring 2027 only.

## 8. How to resume

```
cd /Users/oliverguo/berkeley-waitlist-odds && source .venv/bin/activate
git fetch --all -q && git worktree list && git branch --show-current   # main checkout stays on backfill-full; work in a worktree
gh pr list --state open                                                 # section 3's table, live
(cd data-branch && git pull -q) && python -m scraper.gaps --data-root ./data-branch --term-id 2272 --hours 24   # 2268 until the switch
gh run list --workflow scrape.yml --limit 4                             # chain alive?
python -m pytest                                                        # on a worktree of main
```

Prompt to paste into a new Claude Code session:

```
Continue the Berkeley Waitlist Odds project at /Users/oliverguo/berkeley-waitlist-odds. Read docs/dev/STATUS.md
first (the state as of 2026-10-23), then docs/dev/NEXT_2026-10-23.md (the plan from Oct 23, which section 4 summarises),
docs/dev/HANDOFF.md session 11 and the Current step line in CLAUDE.md. Run ListAgents and
git log -3 before editing; the main checkout is on backfill-full and stays there, so work in a worktree. Do the
first open item in STATUS.md section 4 that is due, through the build loop in docs/dev/FINISH_PLAN_WAITLIST.md
section 1.2. Rules: never commit to the data branch by hand; only analysis.yml commits to main on its own; every
number in CLAIMS.md is copied from command output; backfilled Berkeleytime data is labelled berkeleytime_history
and never a collection claim; the site never shows simulated numbers; no merges and no rate-flag changes without
Oliver's word.
```

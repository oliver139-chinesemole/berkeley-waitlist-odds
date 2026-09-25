# Berkeley Waitlist Odds: where the project stands and what is left

Written 2026-09-20 03:55 UTC (session 4); renewed in full 2026-09-25 08:00 UTC (session 8) after sessions 6 and 7 merged the collection stack and opened the site stack. Renewed in part 2026-09-25 19:45Z (session 9): section 3's pull-request table and merge order, section 4's list, the tests line. Give this file to a Claude Code session, or read it yourself, to know the stage, every open branch and pull request, what is still to build, what only Oliver can do, and what happens on which date. It is a snapshot; `docs/dev/MASTER_PLAN.md` leads on scope and build order, `docs/dev/HANDOFF.md` carries each session's detail (session 7 has a note for Oliver at its top), `docs/dev/SITE_HANDOFF.md` is the website's own ledger, `docs/dev/BACKFILL_BACKTEST.md` the backfill findings, `CLAIMS.md` the measured numbers, `CLAUDE.md` the current-step line. Every number below was printed by a command on 2026-09-25 between 07:45Z and 08:00Z unless a date says otherwise.

## 1. In one paragraph

The scraper is live on Fall 2026 as the test term and, since 2026-09-24 09:37Z, runs at the request policy of PR #8 (request starts at most 2 per second, 4 pages in flight) with the priority list generated from both finished cycles' reconstructed waitlist joins (PR #9): a clean run observes about 1,430 to 1,455 sections with 0 missing in 820 to 1,100 s of the 1,380 s budget, and no run has been lost since. classes.berkeley.edu still has latency episodes of about fifteen minutes (four in the twelve hours to 06:30Z on Sep 25; one of them cost 30 priority sections), so `--max-concurrency` 4 to 6 is an open decision for Oliver. Both finished cycles are backfilled from Berkeleytime's public history, analysed and backtested (course curves transfer across terms; Cox is report-only); the live site is still v2, serving Fall 2026 course-level curves. Site v3 (eight pages, PR #4) is built and reviewed, and the page is decided to serve Spring 2026 for Spring 2027 (PR #11 on it), but PR #4 now conflicts with `main` in four files after the Sep 24 merges and must take a merge of `main` before Oliver can merge it. Session 7 added, all stacked on `site-v3` and reviewed: course search (PR #17), palette and fonts (PR #16), the live section board with its fixture and contract (PRs #19 and #20), plus the subagent definitions (PR #18) and the session's docs (PR #15, which carries this file). What remains before Phase 1 on Oct 26 is mostly merging and dated operations: the site stack in order, the CLAIMS re-measure after 09:37Z today, the Oct 4 term switch, and Oliver's decisions.

## 2. Stage map

| Step | What | Status |
| --- | --- | --- |
| A0 dates and access | Registrar dates, API Central request | Done. SIS API denied to students; classes.berkeley.edu is primary. |
| A1 data route | Probe sources, cross-check | Done (`docs/PHASE0.md`; 20 of 20 cross-checks agree, repeated 2026-09-23 in `docs/crosscheck_2026-09-23.md`). |
| A2 scraper and storage | Schema, Parquet per run, rebuild, gaps, 3 sources, workflows | Done. Request policy and catalog titles added Sep 24 (PRs #8, #10; `docs/DESIGN_A2.md` sections 16 to 18). |
| A3 go live and monitor | Chain, heartbeat, monitor, data log | **Running.** 24 h to 07:07Z Sep 25: 47 runs, largest gap 31.1 min, every gap under 45 min, median missing share 0.0. Issues #1 and #7 closed. Open: the CLAIMS re-measure after 09:37Z Sep 25 (section 4 item 4), Oliver's Sunday check. |
| A4 flow reconstruction | Flows, position model, ASSUMPTIONS, synthetic validation | Done. |
| A5 survival analysis | Calendar, cohort, KM, Cox, PH check, sensitivity, out of sample, `make analysis` | Done on both backfilled cycles; headline results in `CLAIMS.md`. Cox at scale uses `analysis/coxfast.py` (linear-time score residual). |
| A6 publish | Site, methodology, README | v2 live on `main` (Fall 2026, course level). v3 in PR #4, conflicting with `main` (section 3). README hero plot from the backfill. Open: Oliver's browser pass. |
| A7 ship | Resume, r/berkeley post, LinkedIn | Oliver's; not started. |
| B0 to B4 backfill and backtest | Module, pilot, full pulls, analysis, site fixes | Done (PRs #2, #5, #6). Fall 2026 install commit a7240f4 is the pre-registration point for the Spring 2027 test. |
| B5 priority list from data | Rank courses by reconstructed joins | Done and live (PR #9, merged 2026-09-24 09:14Z): 1,013 course patterns, 1,213 live sections in 661 courses per run, 89.2% of both cycles' joins covered (hand list 47.7%); `priority_sha` 613469f9… in every run's footer since 09:37Z Sep 24. |
| B6 repo hygiene | LICENSE, homepage, docs/dev, GoatCounter, resume paragraphs | LICENSE, homepage, docs/dev done. Open: GoatCounter (Oliver's account); the two "resume says Spring 2026" paragraphs come out after Oliver fixes the resume line. |
| MASTER_PLAN P items | P1 merge #4; P2 throughput; P3 live file; P4 source; P5 list; P6 GoatCounter | P2 and P5 done (PRs #8, #9). P4 decided: Spring 2026 (PR #11). P1 and P3 wait on the #4 merge. P6 is Oliver's. |
| MASTER_PLAN Q items (search) | Q1 to Q8 | Q7 done (PR #10). Q1, Q2, Q3, Q5, Q6 (candidates and the "Showing X for" line) and Q8 in PR #17. Q4 (title and instructor search) and Q6's logged miss event open. |
| MASTER_PLAN S items (sections) | S1 to S9 | S1 to S3 in PRs #19 (fixture, harness hook, contract) and #20 (the board, `scraper/live.py`'s two columns and wider selection). S4 to S9 open; S4 and S8 need own data. |
| MASTER_PLAN U items (design) | U1 to U8 | U3 and U4 in PR #16 (three decisions for Oliver in its body). U7 in PR #20 (blue status ramp). U1, U2, U5, U6, U8 open. |

## 3. State right now (2026-09-25 08:00Z)

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

1. **Merge the docs and collection PRs** (Oliver, any time): #15 with the session 9 docs PR on it, #18, #21. The agents directory must exist at session start, so the first session after #18 is the first that can use the per-agent effort levels (session 9 installed the seven files by hand and ran agents on the `opus` alias).
2. **Land site v3 (done up to the merge).** #4 is MERGEABLE (`main` merged in as a3e0f21, review fix 5325cbc). Oliver's browser pass, then merge #4, then #11 (rebased), then `gh workflow run pages.yml`, then `curl -s https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/data/meta.json | python -m json.tool | head` must show `term_name` Spring 2026, `forecast_term_name` Spring 2027, `estimate_level` course, `data_source` berkeleytime_history, and every page and data file returns 200 (the loop in SITE_HANDOFF section 2; add `dept.html?subject=COMPSCI` once #30 is in).
3. **After #4:** the next scrape run writes `live/latest.json` (check it with `gh api repos/oliver139-chinesemole/berkeley-waitlist-odds/contents/live/latest.json?ref=data --jq .size`, about 160 KB); merge #17, #16, #19, #20 in that order (already rebased, proven together in B3); then the follow-ups as their bases land (section 3's merge order), each rebased onto `main` first; `pages.yml` again. Before the Spring 2027 switch: wire `run_analysis(catalog=)` and `--catalog data-branch/catalog/<term>/catalog.json` into `analysis.run` and the weekly workflow so `titles.json` (PR #28) survives a weekly run, then `make site-data` once with `--catalog` and commit `titles.json`.
4. **CLAIMS re-measure: done** (PR #21, 2026-09-25 18:12Z: 47 runs, share of gaps under 45 min 1.0, largest 31.1 min, sweep 878.351 s for 1,434 sections with 0 missing; the sweep row now names the 1,380 s budget). Next re-measure with the Oct 4 term switch.
5. **Oliver's concurrency call:** `--max-concurrency 4` to `6` in `scrape.yml` with a `decision` row naming him, or leave it; the latency episodes decide (section 3).
6. **Oct 4 term switch** (`docs/RUNBOOK.md` step 7): `gh variable set SCRAPE_TERM --body "Spring 2027"`, dispatch a forced baseline, confirm `data-term` 2272 in the pages, add a `term_switch` row; read `selected=` in the first Spring 2027 run's log against the budget before touching the priority list size. Drop-dead for Spring collection running: Oct 12.
7. **Oct 4 to Oct 26, site, as time allows** (MASTER_PLAN section 5): S4 to S7, Q4 to Q6's remainder, department pages, L13, B2 (status line read live from the data branch), U5 to U8; then U1 and U2 (the timeline and the queue strip, held back from unattended sessions).
8. **Nov 9 onward:** first `make analysis TERM=2272` on own data; the weekly `analysis.yml` replaces `site/data` on its own once the 2272 cohort has 10 clearings and already writes the v3 layout; `backtest.json` is by hand (`make backtest TERM=2272`, then `python -m analysis.export_backtest --reports reports/backtest_2272 --term-id 2272 --term-name "Spring 2027" --out site/data/backtest.json`). Soft launch before Nov 23 if the numbers hold.
9. **Jan to Feb 2027:** refit after Phase 2 closes; the pre-registered cross-term test, Fall 2026 frozen at a7240f4 against Spring 2027; final numbers after Feb 10.
10. **Optional model work:** the Cox model extrapolates badly across the Phase 1 to Phase 2 shift (`days_to_instruction` linear, phase dummies absent from a Phase 1 fit): a spline or phase-specific baselines; the position model never clears a "tail" joiner in an empty queue when a seat opens (documented limitation of aggregate counts).

## 5. Only Oliver can do these

- Merges, in the order of section 3; the browser pass on #4's pages (phone and laptop, light and dark, `?today=2026-09-15` for the look-back) and, once #16 is rebased, its palette and fonts on a real screen (each push's `site-smoke` artifact has the screenshots; run 36074407105 for #16's head).
- PR #16's three decisions (Atkinson Hyperlegible Next in place of Atkinson Hyperlegible; the gold focus ring as its own chrome token; `--rust` on error text and the pooled tag until U2 gives it seats held back) and PR #17's two (the Internet Archive 2025-05-27 snapshot as the subject-name source; DISSTD, ENERES, MBN and QTP unnamed).
- `--max-concurrency` 4 to 6, or not (section 4 item 5).
- Create a GoatCounter site and add its tag to every page before any link is shared (P6); visits cannot be backfilled.
- Fix the resume line to "Spring 2027 enrollment cycle", then delete the two paragraphs that mention it (`CLAIMS.md` status paragraph, `docs/dev/FINISH_PLAN_WAITLIST.md` section 3).
- The two-sentence note to the Berkeleytime team (ASUC OCTO), if not already sent; both pulls ran with a User-Agent carrying his email.
- Sunday two-minute check through Feb 14 (`docs/RUNBOOK.md` section 4). Billing page shows $0 (CLAIMS row).
- Custom domain (optional, about $12 a year, before the r/berkeley post). A7: the post (soft launch before Nov 23 if the numbers hold; main launch two weeks before Fall 2027 Phase 1), resume bullets from `CLAIMS.md`, pin the repo, LinkedIn, the private interview page.

## 6. Dates that drive everything

| Date | What |
| --- | --- |
| Sep 25, 09:37 UTC | 24 h at the new request policy: CLAIMS rows 7 to 9 re-measure (section 4 item 4). |
| Sep 27 (Sunday), 15:23 UTC | Weekly `analysis.yml` run; guarded to term 2272, so `site/data` stays as it is. Oliver's Sunday check. |
| Oct 4 | Spring 2027 schedule publishes: term switch (section 4 item 6). |
| Oct 12 | Drop-dead: Spring 2027 collection must be running. |
| Oct 26 | Phase 1 opens. The generated priority list is already installed. |
| Nov 9 to 22 | First own-data analysis; soft launch if it holds. |
| Nov 23 | Phase 2 opens. |
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
(cd data-branch && git pull -q) && python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 24
gh run list --workflow scrape.yml --limit 4                             # chain alive?
python -m pytest                                                        # on a worktree of main
```

Prompt to paste into a new Claude Code session:

```
Continue the Berkeley Waitlist Odds project at /Users/oliverguo/berkeley-waitlist-odds. Read docs/dev/STATUS.md
first (every branch, PR and measurement as of 2026-09-25), then docs/dev/MASTER_PLAN.md (scope and build order),
docs/dev/HANDOFF.md session 7 (the note for Oliver) and the Current step line in CLAUDE.md. Run ListAgents and
git log -3 before editing; the main checkout is on backfill-full and stays there, so work in a worktree. Do the
first open item in STATUS.md section 4 that is due, through the build loop in docs/dev/FINISH_PLAN_WAITLIST.md
section 1.2. Rules: never commit to the data branch by hand; only analysis.yml commits to main on its own; every
number in CLAIMS.md is copied from command output; backfilled Berkeleytime data is labelled berkeleytime_history
and never a collection claim; the site never shows simulated numbers; no merges and no rate-flag changes without
Oliver's word.
```

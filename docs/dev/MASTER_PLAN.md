# Berkeley Waitlist Odds: master plan

Written 2026-09-23, verified against the repo at 21:07 UTC. Home: `docs/dev/MASTER_PLAN.md`. Amended 2026-09-23 22:30 UTC after a second verification against the repo, the Actions logs and the `data` branch: section 1 item 1, the A3 row in section 2, P2 in section 3.1, section 7's first paragraph, the series command in section 9, and section 12 (new). Everything else is the original text.

This file consolidates and supersedes `SITE_V3_PLAN.md`, `REPO_SCAN_2026-09-20.md`, `SITE_V4_PLAN.md` and `COURSE_SEARCH_SPEC.md`. Where those files disagree with this one, this one is current. Keep `COURSE_SEARCH_SPEC.md` for the search fixture detail and `SITE_V3_PLAN.md` for the per-feature wireframes; everything else is folded in here. (Only `SITE_V3_PLAN.md` is in the repository, on `site-v3`; see section 12.)

Verified by fetching raw file contents on `main`, `site-v3`, `backfill-full` and the `data` branch. GitHub's API was rate-limited, so PR numbers, issue states and repository variables are inferred from `CLAUDE.md` and `STATUS.md` rather than observed — section 12 settles them.

---

## 1. Where the project actually stands

**Working:** the scraper chain has run continuously since Sep 19; the Fall 2026 backfill (6,016 sections, 493,364 virtual waitlisters, 220,196 clearings) is analysed, backtested and published; Spring 2026 is pulled and the cross-term backtest is done; the live site serves real course-level estimates; the README hero is the real Berkeleytime figure; headline results are in `CLAIMS.md`.

**Not working, in order of how much it costs:**

1. **The scraper is losing sections right now, and losing whole runs.** Coverage on Sep 20 was 0 to 4 missing of about 1,290 selected in 45 of 47 runs (19 missing at 00:07Z while discovery finished, 557 at 11:37Z). From 2026-09-21 14:37Z the site's pages take 2 to 5 s with 20-s read timeouts, runs miss 100 to 600 sections, and on Sep 22 to 23 nine runs exceeded `--max-missing-share 0.5`, exited 4 and wrote nothing (ten since the slowdown began, counting Sep 21 18:07Z); three in a row made the two-hour hole behind issue #7. The 24 h ending 2026-09-23 22:01Z: 41 runs, 90% of gaps at or under 45 min, median missing share 0.2431. After Oct 26 every missed section is a permanent hole in the only data this project can claim as its own.
2. **Site v3 is built and unmerged.** Branch `site-v3` has five pages plus `about.html`, `course.html`, `404.html`, `og.png`, `favicon.svg`, split data and a working course matcher. `main` has none of it. Everything downstream is blocked on this merge.
3. **The site is off-season.** Published data is Fall 2026, whose deadline (Sep 11) and add/drop (Sep 16) have passed, so every lookup correctly renders the look-back state and is useless to a student today. Spring 2027 publishes Oct 4.
4. **No section-level anything,** which is what students actually open a waitlist tool for.
5. **No analytics.** GoatCounter is still absent from every page, and visits cannot be backfilled.

## 2. Done since the earlier plans — do not redo

| Item | Evidence |
| --- | --- |
| Full Fall 2026 backfill, analysis, backtest | `meta.json` on `main`: `berkeleytime_history`, 220,196 events, generated 2026-09-21T01:56Z |
| Spring 2026 pull and cross-term backtest | `STATUS.md` section 2, B2/B3 rows |
| Estimate level decided (`course`, not `dept`) | `estimate_level: course`; the cross-term test reversed the one-evening dept default |
| Site data published and deployed | Live methodology page carries the Sep 21 text |
| README hero replaced with the real figure | README line 62: `reports/figures_2268_berkeleytime/hero.png` |
| Headline results in CLAIMS | CLAIMS row "Headline results" |
| 24 h cadence check passed on Sep 20, issue #1 closed | CLAIMS rows 5 to 7 re-measured then; `STATUS.md` A3. **Since overtaken:** issue #7 opened 2026-09-23 15:07Z and rows 5 to 7 fail on Sep 23; re-measure them 24 h after P2 lands (section 12) |
| Site v3 built | `site-v3`: five pages + about/course/404/og/favicon, verdict chip, copy link and text, compare, `aria-sort`, split data |
| `scraper/live.py` written | On `site-v3` only, with the right per-section columns |

## 3. Outstanding, audited

Status key: **branch** = written on `site-v3`, not on `main`; **open** = not written; **Oliver** = only he can do it.

### 3.1 Blocking

| ID | Item | Status | Due |
| --- | --- | --- | --- |
| P1 | Merge PR #4 (site v3), run `pages.yml`, curl every page | branch | this week |
| P2 | Scraper throughput: `--min-interval-s 0.5 --max-concurrency 4` in `scrape.yml` (request starts at most 2 per second, 4 pages in flight). `scraper/http.py` already has the worker pool and the global start limiter, so there is no job matrix and still one writer on `data`. Cause and numbers: `docs/DATA_LOG.md` rows dated 2026-09-21, 22 and 23; contract note in `docs/DESIGN_A2.md` section 16 | draft PR, branch `p2-throughput` | **before Oct 4**; nothing changes until it is merged to `main` |
| P3 | Merge the `scraper/live.py` step so `data/live/latest.json` starts being written (404 today) | branch | this week |
| P4 | Decide Spring 2026 vs Fall 2026 curves — it changes every number on the site | Oliver | this week |
| P5 | Rebuild `config/priority_courses.txt` from both cycles' flows (`analysis/priority_from_flows.py` exists; the file's hash is unchanged, so it has not been run). Cover every section that carried a waitlist, then most-joined courses | open | **before Oct 26** |
| P6 | GoatCounter on every page before any link is shared | Oliver | before sharing |

### 3.2 Sections — the feature you asked for

| ID | Item | Status |
| --- | --- | --- |
| S1 | Live section board: one row per section with enrolled/capacity, waitlist/capacity, seats open, seats open but reserved, "read N minutes ago" | open |
| S2 | Reserved-seat line per row using `open_reserved` — "4 seats open, all reserved". Nothing else at Berkeley shows a student this | open |
| S3 | Staleness warning when a section is off the priority list and the number is six hours old | open |
| S4 | Section history export: daily waitlist series, admits per week, deepest position that cleared | open |
| S5 | Section fallback ladder — section, course, department, bucket — printed on the page. A section-level curve only where n ≥ 30 | open |
| S6 | Cross-listed sections shown as separate rows with their own counts, never merged | open |
| S7 | "Which section should I waitlist": queue depth, historical admits per week, deepest position cleared, side by side. Not a model output | open |
| S8 | Recent openings feed from consecutive own snapshots | open (needs own data) |
| S9 | Watchlist in `localStorage` + `Notification` while the tab is open. No backend, no promises | open |

The plumbing is nearly free: the snapshot schema already carries `component`, `section_number`, `enrolled_count`, `enroll_capacity`, `waitlist_count`, `waitlist_capacity`, `reserved_count`, `open_reserved`, and `scraper/live.py` already emits them. S1 to S3 are wiring once P3 lands.

### 3.3 Course search

The v3 matcher already handles `cs61a`, `CS 61A`, `comp sci 61a`, `data 8` → `DATA C8`, and about 60 subject aliases, ranked by `joins`. What is missing:

| ID | Item | Status |
| --- | --- | --- |
| Q1 | Full subject names (`computer science 61a`, `mechanical engineering 40`) — generate `config/subject_names.json` from the catalog, keep hand-written nicknames in a separate file | open |
| Q2 | Filler stripping (`berkeley cs61a`, `cs61a discussion`), split suffix (`cs 61 a`), bare number (`61a`) | open |
| Q3 | Fuzzy subject only: Damerau-Levenshtein ≤1 up to five characters, ≤2 above. **Numbers are never fuzzed** | open |
| Q4 | Title and instructor search (`data structures`, `linear algebra`, `hilfinger`). Needs `titles.json`, lazy-loaded so a plain code query never fetches it | open |
| Q5 | "Showing COMPSCI 61A for *compsi 61a*" whenever a fuzzy or title match fires | open |
| Q6 | Miss handling: three nearest candidates, browse-by-department path, and a logged miss event | open |
| Q7 | Parse course title and instructor from section pages into the catalog — zero extra requests | open, **before Oct 4** |
| Q8 | `tests/fixtures/course_queries.csv`, about 150 rows, run in pytest and in the node harness | open |

Titles exist in no file the project keeps. Berkeleytime's `GetCatalog` has them for the two backfilled cycles; Q7 is the durable route for Spring 2027.

### 3.4 Design

The v3 pages are accessible and anonymous. The direction, in one line: **a line, and a clock.**

| ID | Item | Status |
| --- | --- | --- |
| U1 | Term timeline across every page (Phase 1, Phase 2, adjustment, instruction, last run) with today as a gold tick; the clearing chart shares its horizontal scale so curves line up with the calendar | open |
| U2 | Queue strip as the hero: N ticks for the real waitlist length, your position in gold, shaded through where the line historically reached by your deadline. Also the favicon and the OG image | open |
| U3 | Palette: cool blue-cast surfaces (`--bg #F2F5F9`, `--ink #10202E`, `--line #C9D4E0`), `--blue #003262` for data, `--gold #FDB515` for *you* and *now* only, `--rust #8C4A1F` for seats held back. Dark: `--bg #0B1622`, `--paper #13202E`, `--ink #E6EDF5`, `--blue #7FB2E5` | open |
| U4 | Type: Source Serif 4 for headlines and the big figure, Atkinson Hyperlegible for interface text, both self-hosted in `site/assets/fonts/`, subset variable woff2, 60 KB total, system fallback. Scale 12.8/16/20/25/31/39/49/61. `tabular-nums lining` on every figure | open |
| U5 | Density splits by page: Lookup and Board dense and phone-first at 38 rem and 68 rem; Insights and Accuracy at 64 rem with air, because those two are the portfolio | open |
| U6 | One animation: the queue strip fills left to right on a result, gold tick drops in. One signal: the freshness dot. `prefers-reduced-motion` turns both off | open |
| U7 | Section status as a blue ramp (open, waitlist, full, full-and-reserved), never red/green | open |
| U8 | No all-caps labels, no single accented word in a headline, no monospace face standing in for "data" — tabular figures do that job | open |

### 3.5 Everything else outstanding from the v3 list

| ID | Item | Status |
| --- | --- | --- |
| L11 | My waitlists in `localStorage` | open (no `localStorage` anywhere on the branch) |
| L13 | "What this number cannot see" checklist in the registrar's wording | open |
| L15 | Outcome form: course, position, date joined, outcome. The only individual-level ground truth available | open |
| C5, C6 | Row sparklines; CSV download of the current view | open |
| D4 | Sections table with live counts (= S1) | open |
| I5 to I8 | Admits per day against the calendar with the Aug 19 to Sep 1 outage shaded; exit composition; Cox forest plot; hardest and easiest courses | open |
| B2 | Data-status line read from the data branch's `status.json` | open |
| X7 | Playwright screenshots in CI — the only way a Claude Code session can see the page | open |
| X8 | Custom domain, before the r/berkeley post | Oliver, optional |
| — | Department pages (`/dept/COMPSCI`), which is what search engines and subreddit sidebars link | open |
| — | Off-season home page: countdown to Oct 26 plus last cycle's summary, instead of a form that answers with history | open |

### 3.6 Oliver only

| Item | Due |
| --- | --- |
| Browser pass: phone and laptop, light and dark, including `?today=2026-09-15` | after P1 |
| Spring 2026 vs Fall 2026 decision (P4) | this week |
| GoatCounter account and script (P6) | before sharing |
| Fix the resume line to "Spring 2027 enrollment cycle", then delete the two paragraphs that mention it (`CLAIMS.md` status paragraph, `FINISH_PLAN_WAITLIST.md` section 3, line 119) — both still present | this week |
| Sunday two-minute check through Feb 14 | weekly |
| A7 ship: r/berkeley post, resume bullets from `CLAIMS.md`, pin the repo, LinkedIn, the private interview page | Nov onward |

## 4. Dates

| Date | What |
| --- | --- |
| Oct 4 | Spring 2027 publishes. Term switch: `gh variable set SCRAPE_TERM --body "Spring 2027"`, forced baseline, confirm `data-term` 2272, `term_switch` row. **P2 and Q7 must land before this.** |
| Oct 12 | Drop-dead for Spring 2027 collection to be running |
| Oct 26 | Phase 1 opens. **P5 must be installed before this.** |
| Nov 9 to 22 | First own-data analysis; soft launch if the numbers hold |
| Nov 23 | Phase 2 opens |
| Jan 11 / Jan 19 / Feb 5 / Feb 10 | Adjustment; instruction; last automatic waitlist run; add/drop deadline and freeze |

## 5. Build order

**This week** — P1, P3, P4, P6, the resume-line fix, the browser pass, and the off-season home page.

**Before Oct 4** — P2 (throughput), Q1 to Q3 (search that works without the catalog code), Q7 (titles from section pages), S1 to S3 (live board), U1 to U4 (timeline, queue strip, palette, type), X7 (Playwright in CI).

**Oct 4 to Oct 26** — P5 (priority list), S4 to S7 (section history and the ladder), Q4 to Q6, Q8, department pages, L13, B2, U5 to U8.

**Oct 26 onward** — S8, S9, L11, L15, C5, C6, I5 to I8, soft launch before Nov 23.

**Jan to Feb** — refit after Phase 2, the pre-registered cross-term test, final numbers after Feb 10, A6 and A7.

Ordering rule: anything that touches collection (P2, P5, Q7) beats anything that touches the site, because collection gaps are permanent and site work is not.

## 6. Decisions outstanding

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | Merge PR #4 now, or hold for v4 work | Merge now. Everything else is blocked behind it and v4 is additive. |
| 2 | Spring 2026 or Fall 2026 curves | Spring 2026. Same season as Spring 2027, no two-week hole, instruction phase observed — exactly where Fall 2026 is blind. |
| 3 | Live board as a tab, or only inside the course page | Both, and make the board the home page during the term. |
| 4 | Section-level odds | Only where n ≥ 30, ladder printed. Never a curve a section did not earn. |
| 5 | Openings feed | Build it. The alternative is people refreshing the registrar's page. |
| 6 | Notifications | Tab-open only. No service worker, no backend. |
| 7 | Self-hosted fonts | Yes. Biggest visual return for 60 KB. |
| 8 | Custom domain | Optional, about $12/year, worth it before the r/berkeley post. Pages redirects the old URL. |

## 7. What can't be undone

**Collection gaps are permanent.** On Sep 23 the scraper missed a quarter of its selection at the median and lost whole runs several times a day (section 1). After Oct 26 that is data this project can never recover and cannot claim. P2 and P5 are the two items with a real deadline.

**The pre-registration is already set.** The frozen Fall 2026 model is commit `a7240f4`. Every "committed before the outcomes existed" claim points at it, so do not quietly refit that model before February.

**Analytics cannot be backfilled.** Any link shared before GoatCounter exists is a visit you can never count, and "lookups served" is a resume row.

## 8. Standing rules for any session

- Static files only, no build step, no external scripts, no external fonts except GoatCounter and self-hosted faces in `site/assets/fonts/`.
- The site reads exported JSON and never computes a statistic.
- No simulated numbers outside the labelled methodology figure.
- Berkeleytime-derived numbers keep their `berkeleytime_history` label everywhere they appear.
- Only `scrape.yml` writes the `data` branch; only `analysis.yml` commits to `main` on its own; the `live/latest.json` step stays `continue-on-error`.
- Every number in `CLAIMS.md` is copied from command output, never typed.
- Run `ListAgents` and `git log -3` before editing — several sessions have shared this checkout.

## 9. Verification

```
gh pr list -R oliver139-chinesemole/berkeley-waitlist-odds --state open
gh run list -R oliver139-chinesemole/berkeley-waitlist-odds --workflow scrape.yml --limit 6
gh variable list -R oliver139-chinesemole/berkeley-waitlist-odds
git -C data-branch pull -q && python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 24
curl -s https://oliver139-chinesemole.github.io/berkeley-waitlist-odds/data/meta.json | python3 -m json.tool | head -20
curl -sI https://raw.githubusercontent.com/oliver139-chinesemole/berkeley-waitlist-odds/data/live/latest.json | head -1
```

The gaps command is the one that matters this week: if `median_missing_share` is climbing, P2 is urgent rather than scheduled. The per-run series behind it (one line per snapshot, observed and missing counts from the footers):

```
python -c "from pathlib import Path; from scraper import storage; [print(p.name, m.n_observed, len(m.missing_ids)) for p in storage.list_snapshots(Path('data-branch')) for m in [storage.read_meta(p)]]" | tail -50
```

## 10. Running this as a team

The session that reads this file should orchestrate rather than do everything itself. Claude Code offers four mechanisms; they are not interchangeable.

| Mechanism | What it gives you | Fit here |
| --- | --- | --- |
| **Subagents** | Delegated workers inside one session, each with its own context, reporting a summary back to the lead. They cannot message each other. | **Use this.** It is stable, on by default, and matches the work. |
| **Agent view** (`claude agents`) | One screen to dispatch and monitor background sessions. Research preview. | Useful for watching long items like the full pull. |
| **Agent teams** | Multiple coordinated sessions with a shared task list, where teammates message each other directly, managed by a lead. Experimental and off by default; needs v2.1.32+ and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"` in `settings.json`. | Only if the parallel work outgrows subagents. |
| **Dynamic workflows** | A script running many subagents and cross-checking their results. | Overkill for this repo. |

Docs: https://code.claude.com/docs/en/agents and https://docs.claude.com/en/docs/claude-code/sub-agents

### 10.1 Defining a subagent, its model, and its effort

Subagents are Markdown files with YAML frontmatter in `.claude/agents/` (project, check them into git) or `~/.claude/agents/` (all projects), or passed for one session with the `--agents` CLI flag as JSON. Fields used here: `name`, `description` (this drives automatic delegation, so make it specific), `tools`, `model`, and `effort`.

**Model.** All agents here run Opus 5.5. The `opus` alias resolves to Opus 5.5 on the Anthropic API; pin `claude-opus-5-5` if you want it fixed against future alias movement. Opus 5.5 requires Claude Code v2.1.280 or later — run `claude update` first. A definition's `model` field takes precedence over `CLAUDE_CODE_SUBAGENT_MODEL`, unless `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` is set; leave both unset. (Not confirmed from the session on Sep 23; see section 12.)

**Effort.** Opus 5.5 supports `low`, `medium`, `high`, `xhigh` and `max` — `xhigh` is what the `/effort` slider labels "Extra". Subagent frontmatter accepts an `effort` field, which overrides the session level while that agent runs. Two things to know: Opus 5.5 defaults to `medium`, unlike every other model, so an agent with no `effort` field runs at medium; and `CLAUDE_CODE_EFFORT_LEVEL` beats frontmatter, so leave that variable unset or the per-agent levels below do nothing.

```yaml
---
name: scraper-ops
description: Scraper throughput, shards, run budgets, gap reports, priority list. Use for anything touching scraper/ or .github/workflows/scrape.yml.
tools: Read, Edit, Bash, Grep, Glob
model: opus          # Opus 5.5; pin claude-opus-5-5 to fix the version
effort: max
---
```

### 10.2 The agents this project wants

| Agent | Owns | Effort | Why that level |
| --- | --- | --- | --- |
| `scraper-ops` | P2 throughput, P5 priority list, Q7 title parsing | `max` | Shard and budget arithmetic that must be right the first time; a missed section is permanent |
| `analysis` | S4 section history export, I5 to I8 | `max` | Censoring, IPCW, the n ≥ 30 thresholds. A wrong call here publishes a wrong number |
| `site-builder` | P1 merge, off-season home, S1 to S3 board | `xhigh` | Multi-file wiring against live data, reversible if wrong |
| `design` | U1 to U8 | `xhigh` | Many small judgment calls; deep but not agonised |
| `reviewer` | Reads each diff against section 8 before a PR | `xhigh` | Adversarial reading against a fixed rule list |
| `search` | Q1 to Q6, Q8 fixture | `high` | Well scoped, and the fixture catches what reasoning would not |
| `explore` | "Where is X", call sites, reading the codebase | `low` | Lookups, not judgment. The built-in Explore agent runs on Haiku and is cheaper still; use `model: opus, effort: low` only if you want everything on one model |

Anthropic's own guidance on `max`: it can improve performance on demanding tasks but shows diminishing returns and is prone to overthinking, so test before adopting broadly. If `scraper-ops` or `analysis` starts circling, drop them to `xhigh`.

Docs: https://code.claude.com/docs/en/model-config and https://docs.claude.com/en/docs/claude-code/sub-agents

### 10.3 Rules the orchestrator must hold

**Worktrees are mandatory.** On Sep 19 three sessions ran on this one checkout and one found a commit it had not made. Give every agent its own worktree and its own branch — the `superpowers:using-git-worktrees` skill is installed for exactly this. Never let two agents work in the same checkout.

**Serialize the shared contracts.** `analysis/export.py`, `site/data/*`, `docs/DESIGN_A6.md` and `CLAIMS.md` are touched by several workstreams. The orchestrator edits those itself, or hands them to one agent at a time, never two in parallel. `scrape.yml` has exactly one writer by design.

**Nothing starts before P1.** The PR #4 merge is upstream of every site item; parallel work on top of an unmerged branch produces conflicts, not speed.

**Safe to run in parallel** (different modules, no shared files): `scraper-ops` on P2, `search` on Q1 to Q3, `analysis` on S4, `design` on U3 and U4.

**Verify from the repo, not from reports.** An agent saying it finished is not evidence. The orchestrator runs the tests, reads the diff, and checks `git log` before believing anything — the same discipline `CLAIMS.md` already applies to numbers.

**One PR per agent per item, draft, for Oliver's review.** No agent merges.

## 11. Prompt for Claude Code

```
Continue the Berkeley Waitlist Odds project at /Users/oliverguo/berkeley-waitlist-odds. Read
docs/dev/MASTER_PLAN.md first, then docs/dev/STATUS.md and the Current step line in CLAUDE.md. Run ListAgents and
git log -3 before editing; several sessions have shared this checkout.

Orchestrate this rather than doing it all yourself, using subagents (not agent teams). Follow section 10: define
the agents in 10.2 in .claude/agents/, every one of them on Opus 5.5 (model: opus, or pin claude-opus-5-5) with
the effort field set to the level given in that table — max for scraper-ops and analysis, xhigh for site-builder,
design and reviewer, high for search, low for explore. Check that CLAUDE_CODE_EFFORT_LEVEL and
CLAUDE_CODE_SUBAGENT_MODEL are unset first, since either would override the per-agent fields, and confirm Claude
Code is v2.1.280 or later so Opus 5.5 resolves. Give each agent its own git worktree and branch
(superpowers:using-git-worktrees), and keep the shared files named in 10.3 to yourself. Verify every agent's work
from the repo — tests, diff, git log — never from its own report. One draft PR per item, for my review; no agent
merges.

Work section 5 in order, one item per branch with a draft PR, and stop for my review before each merge. Start with
P2 (scraper throughput) rather than site work if the gaps command in section 9 shows median_missing_share above
0.05 — collection gaps are permanent and site work is not. Nothing parallel starts before P1 is merged.

Per-item rules from section 3: the section board never claims to know a student's own position and every row says
how long ago it was read; reserved seats use the registrar's own wording; a section-level clearing cell is served
only where n >= 30 with the fallback ladder printed; cross-listed courses are separate rows, never merged; course
numbers are never fuzzy-matched, only subjects; a fuzzy or title match always tells the user which query it
answered; titles.json is lazy-loaded. For any design work follow section 3.4 exactly — the term timeline and the
queue strip are the two structural ideas, gold means only "you" and "now", and the chart's x-axis shares the
timeline's scale.

Use superpowers:brainstorming to confirm scope before each item, superpowers:writing-plans for the plan,
superpowers:test-driven-development while building, frontend-design for visual passes, and
design:accessibility-review before each PR. Hold every standing rule in section 8. Keep tests/test_site.py green,
update docs/DESIGN_A6.md to match what you build, and update the Current step line in CLAUDE.md at the end of the
session.
```

## 12. Verified 2026-09-23 22:00 UTC

Checked from the repo, the Actions run logs and the `data` branch (the section 9 commands plus the snapshot footers), not from reports.

**Settled facts.** PR #4 is open, mergeable, all four checks green, untouched since 2026-09-21 03:05Z. Issue #1 closed 2026-09-20; issue #7 ("Scraper gap alert") was opened by the 15:07Z monitor run on 2026-09-23. `SCRAPE_TERM` is `Fall 2026`. `live/latest.json` on `data` is a 404. The live `meta.json` carries `berkeleytime_history`. `CLAUDE_CODE_EFFORT_LEVEL` and `CLAUDE_CODE_SUBAGENT_MODEL` are unset. A peer session (`oliverguo-d3`) was open on the main checkout; nothing was running in the background.

**Corrections to this plan.**
- P2's cause is latency, not the request budget. Successful runs on Sep 23 show no errors, only 2.4 s per page (1,163 pages in 1,381 s); failed runs show 7 to 42 read timeouts each. The client's limiter spaces request starts 1 s apart no matter how many workers, so with 2 workers throughput is 2/latency, under 1 per second, and one 20-s timeout stalls half the pool. The fix is two flags on the existing client, not a job matrix; the original section 1 quoted 2.4% to 9.6% from two runs; the day's median missing share was 0.2431 (24 h ending 22:01Z), and nine runs on Sep 22 to 23 wrote nothing, ten counting Sep 21 18:07Z.
- Of the four files this plan supersedes, only `docs/dev/SITE_V3_PLAN.md` (branch `site-v3`) exists in either checkout. `REPO_SCAN_2026-09-20.md`, `SITE_V4_PLAN.md` and `COURSE_SEARCH_SPEC.md` are not in the repository. If the course-search fixture detail lives elsewhere, add it under `docs/dev/` before Q8.
- Section 10's model names could not be checked from the session: `claude` is not on the shell's PATH, and the model ids this environment knows are `claude-opus-5` and `claude-fable-5-1`. Agent files should use the `opus` alias and pin a version only after `claude --version` and the model list confirm it.

**Items this plan lacked, now in the build order.**
- `docs/DATA_LOG.md` rows for the slowdown since 2026-09-21 14:37Z, the 2026-09-22 22:37Z to 2026-09-23 00:37Z outage (A4 reads outage rows as censoring rules) and the rate decision. In the P2 PR.
- After the merge: a `note` row for the first run at the new rate with its `n_observed` and `sweep_seconds`.
- Close issue #7 after the first 24 h window with no exit-4 run and `largest_gap_min` under 90 (`gh issue close 7`).
- Re-measure CLAIMS rows 5 to 7 (snapshots per day, share of gaps at or under 45 min, sweep time) 24 h after P2 lands; on Sep 23 they fail.
- `analysis.yml` replaced `site/data` whenever the own-data cohort had 10 clearings, whatever the term. The Fall 2026 own-data cohort, collected only after that term's last automatic waitlist run, showed 209 clearings on 2026-09-23 and would have displaced the Berkeleytime backfill (220,196 events) on Sunday Sep 27. The guard now also requires term 2272 (in the P2 PR; decision row in the data log).
- The live methodology page said "one request per second"; corrected in the P2 PR. The `site-v3` branch's copy of `site/methodology.html` carries the same sentence: change it there before P1 merges.

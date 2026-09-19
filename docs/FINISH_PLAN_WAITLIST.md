# Finish Berkeley Waitlist Odds — Instructions for Claude Code

Owner: Oliver Guo · Written: Fri Sept 18, 2026 · Repo: Berkeley Waitlist Odds (Python, GitHub Actions, Parquet, lifelines, GitHub Pages)

**How to use this file.** Drop it into this repo at `docs/FINISH_PLAN_WAITLIST.md` and paste the block from section 1.4 into `CLAUDE.md` at the repo root. Claude Code loads `CLAUDE.md` at session start and follows the `@` import. Steps use `- [ ]` checkboxes; every step ends in a check you can run. If the check already passes, tick it and move on.

**Priority across the three repos:** waitlist scraper (hard external deadline) → PaddleIQ → Waivy → waitlist analysis once data exists. This repo is first. Steps A1 to A3 outrank everything in the other two repos until the scraper is live.

---

## 0. Setup check for this repo (Oliver, about 10 minutes)

Plugins enabled on claude.ai sync into Claude Code sessions on recent versions and appear as `synced` in the Installed tab, so check before installing. If you already did this for another repo, only the project-scope items are new.

- [ ] `claude --version` is v2.1.273 or later. Update with `npm install -g @anthropic-ai/claude-code@latest`, `brew upgrade claude-code`, or the native installer.
- [ ] `/plugin list` shows: `superpowers`, `data`, `design`, `ui-ux-pro-max`, `humanizer`, `pyright-lsp`, `github`, `security-guidance`. If `/plugin` is not available in the VS Code panel, run `claude` in the integrated terminal, or `claude plugin list` from the shell.
- [ ] Install whatever is missing:

```
/plugin install superpowers@claude-plugins-official
/plugin marketplace add anthropics/knowledge-work-plugins
/plugin install data@knowledge-work-plugins
/plugin install design@knowledge-work-plugins
/plugin marketplace add nextlevelbuilder/ui-ux-pro-max-skill
/plugin install ui-ux-pro-max
/plugin install pyright-lsp@claude-plugins-official      # first: pip install pyright
/plugin install github@claude-plugins-official
/plugin install security-guidance@claude-plugins-official
```

  `humanizer`: if it does not sync, find it in the `/plugin` Discover tab, or copy the skill folder to `~/.claude/skills/humanizer/`. If the `ui-ux-pro-max` command fails, install it from the Discover tab.
- [ ] Scopes. User scope: `superpowers`, `data`, `humanizer`, `github`, `security-guidance`. Project scope in this repo: `pyright-lsp`, and `design` plus `ui-ux-pro-max` (only needed from step A6). Every plugin adds context cost to every turn; the install panel shows the estimate.
- [ ] Sanity check. Start a session in this repo and ask: "Which skills and plugins do you have loaded?" The answer should name the superpowers skills. If not, run `/reload-plugins` and look at the `/plugin` Errors tab.

---

## 1. Operating rules (for Claude Code)

### 1.1 Rules

1. **Goal.** Make every claim in this project's block on Oliver's resume verifiably true, then make the project public-ready: live link, clean public repo, README, reproducible numbers.
2. **Definition of done.** (a) Every resume claim passes its check in `CLAIMS.md`. (b) CI is green on `main`. (c) The live URL works from a cold browser on a phone. (d) The repo is public with a README and no secrets in history. (e) The resume is updated to match what was built. If reality and the resume disagree, the resume changes, not the count.
3. **Skills first.** Before any response or action, check which skills, plugins, subagents, and MCP servers are loaded and invoke every skill that applies (`superpowers:using-superpowers`). Announce the skill you are using. Do not assume a skill exists; look. If a skill named in this file is not loaded, say so once, then apply the same discipline by hand.
4. **Session protocol.** State the step at the start. Work steps in order. At the end, update the `Current step` line in `CLAUDE.md` and the tracker at the bottom of this file.
5. **No invented facts about systems.** Do not guess API endpoints, field names, table names, or file paths. Write a probe or run a command that discovers them. `docs/SPEC.md` already exists in this repo and wins any conflict with this file on implementation detail.
6. **Constraints.** $0 recurring cost. No always-on paid servers, no paid databases. GitHub Actions and GitHub Pages free tiers only, public repo. Python for the scraper, Python or R for analysis. Oliver knows pandas, NumPy, dplyr, ggplot2; skip basics.
7. **Style.** Concise. One recommended approach with the tradeoff in a line. Runnable deliverables over prose.
8. **Oliver writes his own resume bullets and the Reddit post.** Draft with him; do not ghostwrite final copy.

### 1.2 The build loop (how every step gets executed)

This file is the roadmap. It has no file paths or test code because those must come from reading the actual repo. Each step below becomes a task-level plan through this loop:

1. `superpowers:brainstorming` — classify the step (spike, bounded, architectural), present the design, get Oliver's approval. Keep it proportionate: where `docs/SPEC.md` or this file already settles the design, present a short design that cites it instead of re-interviewing. Approval is still required before code.
2. `superpowers:writing-plans` — write the task-level plan to `docs/superpowers/plans/YYYY-MM-DD-<step>.md`: exact files, failing test first, commands, expected output.
3. `superpowers:using-git-worktrees` — one isolated branch per step. Never build on `main`.
4. `superpowers:subagent-driven-development` to execute (fresh subagent per task, review after each). Use `superpowers:executing-plans` only when running the plan in a separate session. Inside tasks, `superpowers:test-driven-development`.
5. Anything red (test, build, deploy, scraper run): `superpowers:systematic-debugging` before proposing a fix. Read the real logs first.
6. `superpowers:verification-before-completion` — before ticking a checkbox or writing a result into `CLAIMS.md`, run the check and show the output. "Should work" is not done.
7. `superpowers:requesting-code-review`, then `superpowers:finishing-a-development-branch`.
8. Independent work goes through `superpowers:dispatching-parallel-agents`. Steps below say where.

**Analysis** runs through the `data` plugin inside the same loop: `data:explore-data` before modeling, `data:statistical-analysis` during, `data:create-viz` for figures, `data:validate-data` before any number leaves the repo.

**Public UI** is built with `ui-ux-pro-max` (and `frontend-design` if loaded), then reviewed with `design:design-critique`, `design:accessibility-review`, and `design:ux-copy`.

**Clock rule.** Steps A1 to A3 are on a 10-day deadline. Brainstorming there is a short in-chat design against `docs/SPEC.md`. Do not write a new spec.

**Public prose** (README, methodology page) gets a `humanizer` pass. Resume bullets and the Reddit post are Oliver's; run `humanizer` on them only if he asks.

**Not needed for this project:** `cowork-plugin-management`, `ui-ux-pro-max:slides`, `ui-ux-pro-max:banner-design`, `data:data-context-extractor`.

### 1.3 CLAIMS.md

This repo gets a `CLAIMS.md`: a table mapping every number or capability on the resume to the exact command, query, or test that reproduces it, plus the current result and date. Example row: `30-minute snapshots | gap report script | 97.2% of intervals ≤ 45 min | 2026-11-20`. It is the audit, the interview prep, and the README source at once.

- [x] If `~/.claude/skills/claims-audit/` does not exist yet, use `superpowers:writing-skills` to create it as a personal skill: read `CLAIMS.md`, re-run every check, update the result and date columns, report any row that failed or changed. Run it at the end of every step and before any resume update. (One skill serves all three repos.)

### 1.4 Block to paste into CLAUDE.md

```markdown
@docs/FINISH_PLAN_WAITLIST.md

## How to work in this repo
- Before any response or action, check loaded skills and invoke every one that applies
  (superpowers:using-superpowers). Announce which skill you are using.
- Execute every step through the build loop in docs/FINISH_PLAN_WAITLIST.md section 1.2.
  Each step lists its skills and plugins.
- If a named skill or plugin is not loaded, say so once and continue with the same
  discipline by hand.
- Current step: A1. Update this line at the end of every session.
```

This repo already has a `CLAUDE.md` importing `@docs/SPEC.md`. Add the import and the block under what is there; do not replace it.

---

## 2. Calendar

| Window | Work | Exit condition |
| --- | --- | --- |
| **Today, Sept 18** | Section 0; A0 | API Central request ID in hand; Phase 1 date written below |
| Sept 19 – 20 | A1 probe | `docs/PHASE0.md` names the source |
| Sept 21 – 25 | A2 scraper and storage | Tests green; workflow runs on manual dispatch |
| **Mon Sept 28** | A3 live target (2 weeks before earliest plausible Phase 1) | About 48 snapshots/day landing, gap monitor on |
| **Sun Oct 11** | Drop-dead date | Anything after this loses Phase 1 data permanently |
| Oct – early Nov | A4 flow reconstruction, in the gaps around PaddleIQ and Waivy | Synthetic recovery test passes |
| Nov 9 – 22 | A5 interim analysis on Phase 1 data; A6 site v1 | First real KM curves; site live |
| Jan 2027 | Phase 2 closes, adjustment period opens; refit | Out-of-sample validation done |
| ~Feb 10, 2027 | Add/drop deadline (Wed of week 4); freeze dataset | Final analysis and methodology page |
| Before mid-April 2027 | A7 ship ahead of Fall 2027 Phase 1 | Reddit post up, tool in use |

Phase 1 for spring has historically opened on the 2nd or 3rd Monday of October, so plan for **Oct 12, 2026** as the worst case. Confirm the real date on the registrar's Student Enrollment Calendar today and write it here: `Phase 1 opens: Mon Oct 26, 2026` (continuing students; Schedule of Classes published Oct 4; confirmed 2026-09-18 from the registrar's Google Calendar ICS).

---

## 3. Claims to make true

**Reality check first.** The resume says snapshots were captured "through the Spring 2026 enrollment cycle." That cycle ended in early 2026 and cannot be backfilled at 30-minute resolution. The only cycle this project can capture is **Spring 2027 enrollment** (mid-October 2026 through about Feb 10, 2027). Every bullet depends on the scraper being live before Phase 1 opens.

| Resume claim | Check |
| --- | --- |
| Zero-cost pipeline, GitHub Actions + Parquet, 30-minute snapshots across sections through an enrollment cycle | Actions history shows about 48 successful runs/day; gap report shows 95%+ of intervals at or under 45 min across the cycle; billing page shows $0 |
| Flow reconstruction separating admits, joins, drops under documented FIFO assumptions | `docs/ASSUMPTIONS.md` exists; synthetic-data test recovers known flows within stated error |
| Kaplan–Meier and Cox PH, stratified by course, position, enrollment phase | Analysis reproduces from raw Parquet with one command; PH assumption checked; out-of-sample calibration reported |
| GitHub Pages in the tech line | Public lookup page live and reading precomputed JSON |

---

## 4. Steps

### A0. Today (Oliver, 30 minutes, before anything else)

- [x] Submit the API Central request for the SIS Class API. Outcome 2026-09-19: API Central is not granting access to students at this time. The classes.berkeley.edu route is the primary; a sponsored request is optional.
- [x] Confirm Spring 2027 Phase 1, Phase 2, and adjustment period dates on the registrar's Student Enrollment Calendar. Write them into section 2 and into `CLAUDE.md`.
- [x] Confirm the repo is public (unmetered Actions minutes). If it is private, flip it now.

### A1. Phase 0 — discover the data route (Sept 19 – 20)

**Skills:** `superpowers:brainstorming` on the spike path (the output is an answer, not code you keep). `superpowers:dispatching-parallel-agents`, one subagent per candidate source. `superpowers:verification-before-completion` on the hand cross-check.

Do not wait on API approval. Probe all candidates in parallel and take the first that passes.

- [x] Write `probe/probe_sources.py`. For each candidate, fetch 5 known sections (2 impacted CS/DATA/STAT courses, 1 large lecture, 1 small seminar, 1 course with reserved seats) and print the raw response.
  - Candidate 1: SIS Class API through API Central (needs approved credentials). The Spring 2027 term ID should follow the SIS convention `2` + `YY` + `2/5/8`, i.e. `2272`. Confirm it in the probe; do not hardcode it on this file's word.
  - Candidate 2: the public class schedule site (classes.berkeley.edu). Check whether section pages or their network calls expose enrolled, capacity, waitlisted, and waitlist capacity as JSON.
  - Candidate 3: Berkeleytime's public API (open source, asuc-octo/berkeleytime). Fallback, and a cross-check for your own counts.
- [ ] Pass criteria: returns `enrolled_count`, `enroll_capacity`, `waitlist_count`, `waitlist_capacity` per section; no login; a full-catalog sweep finishes in under 10 minutes; terms of use permit it. Note reserved-seat fields if present.
- [x] Write the decision to `docs/PHASE0.md`: source chosen, exact endpoint and fields observed, rate limits seen, sweep time, fallback source.
- [x] Cross-check 20 sections against CalCentral or Berkeleytime by hand. Counts must match.

### A2. Scraper and storage (Sept 21 – 25)

**Skills:** full build loop (1.2), with the clock rule. `superpowers:test-driven-development`: record fixtures and write the failing tests before `fetch.py`. `pyright-lsp` and `security-guidance` active.

- [x] `scraper/fetch.py`: one sweep over all Spring 2027 sections. Retries with exponential backoff, a polite request rate, a descriptive User-Agent with your email. Record `fetched_at` (actual UTC fetch time), never the scheduled time.
- [x] Snapshot schema, one row per section per snapshot: `fetched_at, term_id, section_id, course_key, component, enrolled_count, enroll_capacity, waitlist_count, waitlist_capacity, status, source`. Pin dtypes in a pyarrow schema and validate every write against it.
- [x] Storage layout, unless `docs/SPEC.md` already settles it: **one Parquet file per snapshot, never rewritten**, on a dedicated `data` branch, at `snapshots/date=YYYY-MM-DD/HHMM.parquet`. Full baseline once a day; change-only rows otherwise (a section appears only if a count changed since the last snapshot). Reason: rewriting a daily file 48 times stores 48 blobs in git history and blows through GitHub's size limits by December. Append-only deltas stay small.
- [x] `scraper/rebuild.py`: reconstructs the full panel (every section at every timestamp) from baseline + deltas. Test: rebuild equals a full-snapshot run on the same day, row for row.
- [x] Unit tests with recorded fixtures: schema validation, delta logic, rebuild round-trip, behavior on a 500 response and on a missing section.
- [x] Workflow `.github/workflows/scrape.yml`:

```yaml
on:
  schedule:
    - cron: "7,37 * * * *"   # off :00/:30 — GitHub delays or drops runs at peak minutes
  workflow_dispatch:
concurrency:
  group: scrape
  cancel-in-progress: false
permissions:
  contents: write
```

- [x] Credentials live in repo secrets only. Run `gitleaks detect --source . --redact` before the first public push; expect zero findings.

### A3. Go live and monitor (by Mon Sept 28)

**Skills:** `superpowers:verification-before-completion` (evidence is Actions run history, not a local run). `github` plugin or `gh run list` to read it. `superpowers:systematic-debugging` on any failed run.

- [ ] Let it run 48 hours. Check: at least 90 of 96 expected snapshots landed, no schema failures, sweep time stable.
- [x] `monitor.yml`, daily: compute the largest gap between snapshots in the last 24 hours; if it exceeds 90 minutes or fewer than 40 snapshots landed, open a GitHub issue (which emails you). Scheduled workflows can be delayed, dropped, or auto-disabled; you need to hear about it the same day.
- [x] `docs/DATA_LOG.md`: one line for every outage, schema change, or source switch, with timestamps. These become censoring rules later.
- [ ] Oliver: recurring 2-minute Sunday check through February. Open the Actions tab, open the newest snapshot, confirm counts look sane.

### A4. Flow reconstruction (build Oct – early Nov while data accumulates)

**Skills:** full build loop. `superpowers:test-driven-development`: the synthetic-recovery test is written first and fails first. `data:statistical-analysis` for the error metrics.

- [x] Per section, per interval, difference the counts and classify: enrolled +1 with waitlist −1 is a waitlist admit; waitlist −1 with enrolled flat is a waitlist drop; waitlist +1 is a join; enrolled −1 is an enrolled drop; a capacity increase followed by bulk movement is an expansion event. Flag intervals where more than one story fits.
- [x] Write `docs/ASSUMPTIONS.md`. It must cover: (1) flows are net within a 30-minute window, so simultaneous join + drop is invisible and flows are lower bounds; (2) FIFO ordering; (3) waitlist drops have unobserved positions, so compute three scenarios: all drops ahead (optimistic), all behind (pessimistic), uniform over the list (central); (4) reserved seats break pure FIFO and can hold a waitlist still while open seats exist; (5) batch waitlist processing clusters admits in time; (6) gaps from `DATA_LOG.md` are censoring, not zero flow.
- [x] Synthetic validation: simulate individual students on a FIFO waitlist with known join, admit, and drop times; aggregate to 30-minute counts; run reconstruction; report recovery error per flow type. This test is the evidence behind the word "documented" on the resume.

### A5. Survival analysis (interim Nov 9 – 22, final after ~Feb 10)

**Skills, in order:** `data:explore-data` to profile the rebuilt panel (null rates, gaps, impossible transitions, sections that vanish). `data:statistical-analysis` for KM, log-rank, Cox, PH checks. `data:create-viz` or `data:data-visualization` for figures. `data:validate-data` on the full analysis before any number goes on the site or the resume. `superpowers:verification-before-completion` on `make analysis`.

- [ ] Unit of analysis: a virtual waitlister defined by `(section, join_time, position_at_join)`. Under FIFO they advance one spot per admit and per drop ahead of them. Event: position reaches zero by admit. Censor at dataset end, section cancellation, or a logged data gap.
- [ ] Kaplan–Meier with `lifelines.KaplanMeierFitter`, stratified by position bucket (1–5, 6–15, 16–40, 41+), course level, department, and phase at join. Log-rank tests between strata. Plot with confidence bands.
- [ ] Cox PH with `CoxPHFitter`: covariates log(position), waitlist/capacity ratio, course level, department group, phase at join, days until instruction begins, reserved-seat indicator if available. `cluster_col="section_id"` for robust standard errors. Run `check_assumptions`; stratify any covariate that fails.
- [ ] Sensitivity: refit under the optimistic and pessimistic drop scenarios. Report how far the headline number moves.
- [ ] Out-of-sample: fit on Phase 1 joins, predict Phase 2 joins. Report concordance, Brier score for "cleared within 14 days," and a decile calibration plot.
- [ ] `make analysis` reproduces every figure and table from raw Parquet. Pin versions in `requirements.txt`.
- [ ] Write the two or three headline results in plain English, with numbers. These go on the resume and the site.

### A6. Publish (site v1 by Nov 22, final by March)

**Skills:** `data:build-dashboard` is the fastest route to a self-contained static page with charts and filters. `ui-ux-pro-max:ui-ux-pro-max` and `ui-ux-pro-max:ui-styling` for the look. `design:ux-copy` for how a probability is worded to a stressed student. `design:accessibility-review` and `design:design-critique` before launch. `humanizer` on the methodology page and README.

- [ ] Precompute `site/data/*.json`: per course and position bucket, P(clear by first day of instruction), median days to clear, n. Fall back to a pooled department-level estimate when n < 30, and label it pooled.
- [ ] Static GitHub Pages site: search a course, enter a position, see probability, a KM curve, sample size, last-updated date. No backend.
- [ ] Methodology page: data source, cadence, assumptions, limitations, validation results. Link the repo.
- [ ] README: what it is, one hero plot, pipeline diagram, how to reproduce, limitations, `CLAIMS.md` link.

### A7. Ship

**Skills:** `claims-audit`. `humanizer` only if Oliver asks for a pass on his own draft.

- [ ] Oliver writes the r/berkeley post; time it for the two weeks before Fall 2027 Phase 1 (mid-April 2027). A soft launch before Phase 2 in mid-November is worth doing if site v1 is up.
- [ ] Update the resume: "Spring 2027 enrollment cycle," the real section count, the real snapshot count, one headline result.

---

## 5. Finish line

**Skills:** `claims-audit`. `humanizer` on anything public. `design:design-critique` on the portfolio page for this project.

- [ ] `claims-audit` passes on every row.
- [ ] Repo is public, pinned on your GitHub profile, with a description and topics. Keep the real commit history; do not squash it away.
- [ ] Portfolio site: replace this project's illustrative charts and placeholders with real output from the repo; remove any status badge that no longer applies.
- [ ] Resume truth pass on this project's block: walk `CLAIMS.md` against the PDF line by line, update any number that moved, add the live link and the GitHub link.
- [ ] Interview prep, one private page kept out of the repo: the hardest bug, one design decision you would reverse, and the limitation you would raise yourself before an interviewer does.
- [ ] LinkedIn: add the project with its live link.

---

## 6. Status tracker (update at the end of every session)

```
Last updated: 2026-09-19
Phase 1 opens: Mon Oct 26, 2026 (registrar ICS; schedule publishes Oct 4)   API Central request: DENIED 2026-09-19 (not granting access to students); site route is primary
Setup (section 0): plugins not installed in this environment; work done by hand   Source chosen (A1): classes.berkeley.edu section pages via Berkeleytime catalog (SIS API primary once approved); docs/PHASE0.md

Step: A3 | blockers: none (API closed to students; site route is primary; cron cadence still ramping) | scraper live: yes since 2026-09-19 12:27Z (schedule) | snapshots landed: 1 baseline (911 sections)
Done: A0 dates; A1 probe + 20/20 cross-check; A2 scraper, storage, rebuild, gaps, 3 sources, workflows, 214 tests; repo public with data branch; review fixes (robots, budget, day-boundary tombstones, cross-source guard, coverage gate)
Next session: check cron cadence (3 scheduled runs in the first 7 h; escalate per RUNBOOK 3.4 if still sparse), verify catalog/site.json appeared on the data branch, then start A4 (ASSUMPTIONS.md, analysis/flows.py, synthetic recovery test); Oliver: Sunday checks, Oct 4 term switch
```

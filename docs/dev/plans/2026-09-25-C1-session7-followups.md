# C1: session 7's deferred findings, three small PRs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three draft PRs, each stacked on the branch it follows up, closing the findings session 7's reviewers deferred: search (`q1-q3-search`), the section board (`s1-s3-board`) and the palette (`u3-u4-design`).

**Architecture:** Three independent tasks, run in parallel by three agents, each in its own worktree branched from the named base branch (after B2 rebased those bases onto `site-v3` at 5325cbc). No task touches another's files: search edits `site/assets/site.js` (matcher functions), `site/course.html` (the "Showing X for" line), `scripts/subject_names.py`, `config/subject_names.json`, the query fixture and `tests/test_site.py`; the board task edits `site/course.html` (board rendering), `site/assets/site.css` (the board's phone rule only), `tests/test_site_live.py`, `tests/fixtures/latest_sample.json` and `docs/DESIGN_A6.md` (one paragraph); the design task edits `site/assets/site.css` (token values only). The two `site.css` edits are disjoint (a media query for the board versus token values) and the two `course.html` edits are disjoint, so they merge; each PR body records what it touched.

**Tech Stack:** static HTML/CSS/JS, node 22 (`/Users/oliverguo/.nvm/versions/node/v22.23.2/bin/node`), Python 3.12 (`/Users/oliverguo/berkeley-waitlist-odds/.venv/bin/python`), Playwright via `NODE_PATH=/Users/oliverguo/paddleiq/node_modules`.

**Spec:** `docs/dev/NEXT_SITE_2026-09-25.md` section 4, "Shared items", C1; rules in its section 5; decision rule in its section 6. Contract: `docs/DESIGN_A6.md` on the base branch.

## Global Constraints

- Static files only; no build step; no external scripts or fonts; the site reads exported JSON and never computes a statistic.
- Never red or green; gold only for "you" and "now"; section status and buckets on the blue ramp `--s1`…`--s4`; no all-caps labels; tabular figures.
- Berkeleytime-derived numbers keep their `berkeleytime_history` label. Fixtures never ship under `site/`.
- One draft PR per task, base = the branch named in the task, reviewer findings in the PR body; `tests/test_site.py` stays green; `docs/DESIGN_A6.md` matches what was built, in the same PR.
- The contract test in `tests/test_site_live.py` is extended, never loosened.
- Worktree guard: no `git -C`, no command substitution around git, no heredocs whose text mentions git; scripts through the Write tool, run by path; commit with `git commit -F <file>`.
- No merges; no rate-flag, priority-list or `scrape.yml` changes.

## Review Focus

1. A query that matched before the search changes and stops matching after: Task 1 adds fixture rows only and never edits an existing row's expected key.
2. A board row with `waitlist_count` null but counts present shown as "open" because the null rule covered only two of the three fields: Task 2's test covers each field null on its own and all three null.
3. The board's two-line phone rule leaking into other tables: Task 2's media query is scoped to the board's own selector.
4. A `--s1` raised for contrast that also breaks the ramp's ordering: Task 3 pastes the four ramp values with their luminance so the ramp stays monotone.
5. `--tint`'s new dark value used where the light value was assumed (the band fill): Task 3's smoke in both schemes on the chart pages.

---

### Task 1: search follow-ups (agent `search`, effort high; base `q1-q3-search`; branch `search-followups`)

**Files:** `site/assets/site.js` (matcher, `searchCourses`, `relatedCourses`), `site/course.html`, `scripts/subject_names.py`, `config/subject_names.json`, `tests/fixtures/course_queries.csv`, `tests/test_site.py`, `docs/DESIGN_A6.md` (course-search subsection).

- [ ] **Step 1 (fixture first):** add rows to `tests/fixtures/course_queries.csv` for a comma-suffixed Guide name reached by the name route (pick two subjects whose Guide name has a comma in `config/subject_names.json`, for example "Business Administration, Undergraduate" → a `UGBA` course, "Art, History of" → a `HISTART` course present in `index.json`), expected layer `name`; run `node tests/site/queries.mjs` and watch them fail.
- [ ] **Step 2:** in `scripts/subject_names.py`, normalise a Guide name of the form `X, Y` to `Y X` ("Business Administration, Undergraduate" → "Undergraduate Business Administration"; "Art, History of" → "History of Art") and keep the original spelling as an alias so both match; apply to `config/subject_names.json`; `python scripts/subject_names.py --check` passes.
- [ ] **Step 3:** `site/course.html` prints the same "Showing COMPSCI 61A for *query*" line `index.html` prints when `BWO.matchCourse` reports a fuzzy (or name/nickname) layer for the `?c=` query; harness test in `tests/test_site.py` (render `course.html` with `?c=compsi 61a`, assert the line).
- [ ] **Step 4:** `BWO.searchCourses` returns `[]` when the index is not loaded (the guard `matchCourse` has); `relatedCourses` uses the one shared comparator the matcher ranks by; the test that asserts the fixture's layer set equals `BWO.LAYERS` reads `BWO.LAYERS` from the page instead of repeating the list.
- [ ] **Step 5:** `node tests/site/queries.mjs` all rows matched; `python -m pytest tests/test_site.py` and the full suite green; DESIGN_A6's course-search subsection names the comma rule and the course page's line. Draft PR against `q1-q3-search`: "Search follow-ups: comma names, the course page's Showing line, guards, one comparator".

### Task 2: board follow-ups (agent `site-builder`, effort xhigh; base `s1-s3-board`; branch `board-followups`)

**Files:** `site/course.html` (board rendering), `site/assets/site.css` (one media query for the board), `tests/test_site_live.py`, `tests/fixtures/latest_sample.json`, `docs/DESIGN_A6.md`.

- [ ] **Step 1 (tests first):** extend `tests/test_site_live.py` with fixture rows where exactly one of `enrolled_count`, `enroll_capacity`, `waitlist_count` is null, and one where all three are null; assert each renders the em-dash status cell with `aria-label="not read"` and no `status-open|waitlist|full|reserved` class; the existing rows unchanged. Watch the new assertions fail.
- [ ] **Step 2:** the null rule in `course.html`: any null among those three fields → em dash with `aria-label="not read"`, never "open". One sentence in DESIGN_A6's board paragraph.
- [ ] **Step 3:** below 38 rem the six-column board renders as two-line rows (section and status on the first line; counts, seats and read-time on the second), CSS only, scoped to the board's table selector; no colour change; `tabular-nums` kept. A harness assertion that the markup carries the class the rule targets. Local smoke at 390 by 844 in both schemes pasted; the board rendered through the harness at the fixture pasted.
- [ ] **Step 4:** `python -m pytest tests/test_site_live.py tests/test_site.py tests/test_live.py` green; full suite green; draft PR against `s1-s3-board`: "Board follow-ups: null counts are not open, phone rows, tests for the em-dash branches".

### Task 3: design follow-ups (agent `design`, effort xhigh; base `u3-u4-design`; branch `design-followups`)

**Files:** `site/assets/site.css` only (token values in the two `:root` blocks and their comment).

- [ ] **Step 1:** give `--tint` its own value in the dark block, with the value and its use in the token comment. (Correction after the review: `--tint` styles only the header nav hover, not the band fill or a chart wash as this plan first said; the implementer set the dark value for that use, and the reviewer confirmed the deviation was right.)
- [ ] **Step 2:** raise `--s1` (the lightest ramp step: the "open" status and the first bucket curve) so its contrast on `--paper` white is at least 3:1 in the light scheme, staying a blue; keep `--s1` lighter than `--s2` lighter than `--s3` lighter than `--s4` in both schemes; paste the four values per scheme with their relative luminance and the `--s1` on paper ratio, computed by a small script.
- [ ] **Step 3:** no other pixel change: the diff touches only token lines and comments in `site/assets/site.css`; `grep -n gold site/assets/site.css` unchanged from the base's proof (10 lines).
- [ ] **Step 4:** local smoke in both schemes, both viewports, all pages: "36 renders, 0 with problems" with zero axe violations of any impact, pasted; draft PR against `u3-u4-design`: "Design follow-ups: a dark --tint, and --s1 at 3:1 on paper"; the body lists the ramp values so `board-followups` (#20 uses `--s1`…`--s4`) can rebase.

### Task 4: review (agent `reviewer`, one per task, in parallel)

Each reviewer gets the task's brief, the implementer's report and a diff package of the PR branch against its base; verifies from the diff against the Global Constraints and the task's steps.

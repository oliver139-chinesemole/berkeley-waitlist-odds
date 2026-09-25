# C2, C3, C4: the live data-status line, the fallback ladder, cross-listed sections

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two draft PRs on `site-v3` (the live status sentence on every page; the fallback ladder printed with every curve) and one written finding (whether cross-listed sections arrive as distinct rows in `live/latest.json`), all from `docs/dev/NEXT_SITE_2026-09-25.md` section 4 (C2, C3, C4).

**Architecture:** C2 and C3 run in parallel on two agents, each in its own worktree from `origin/site-v3` (5325cbc). They touch different code: C2 adds one function to `site/assets/site.js` (`BWO.liveStatusHtml` or similar, in its own block near `sourceHtml`) and the status container on every page; C3 changes the sentences `site/index.html` and `site/course.html` print under a curve (`BWO.pooledSentence`/`levelNote` become the ladder). Both add harness tests to `tests/test_site.py` (append-only, different test names) and a paragraph each to `docs/DESIGN_A6.md` (different sections). C4 is read-only.

**Tech Stack:** static HTML/JS, node 22, Python 3.12, the harness `tests/site/harness.js`.

**Spec:** `docs/dev/NEXT_SITE_2026-09-25.md` section 4, C2, C3, C4; rules in section 5; decisions in section 6.

## Global Constraints

- Static files only; no external scripts; the site reads exported JSON and never computes a statistic (a relative time or a count is not a statistic; a probability is).
- C2's fetch is a data read from this project's own `data` branch through `https://raw.githubusercontent.com/oliver139-chinesemole/berkeley-waitlist-odds/data/status.json` (CORS `*`, cached about five minutes): the sentence says "about N min ago", never seconds; on any failure the page renders exactly as today; the fetch starts after `DOMContentLoaded` and never blocks first paint; no number from that line ever enters `CLAIMS.md`.
- C3's sentences use the registrar's words, no promise, no adjective; the section rung names no number.
- Berkeleytime-derived numbers keep their `berkeleytime_history` label; never red or green; gold only for "you" and "now".
- One draft PR per task against `site-v3`; `tests/test_site.py` green; `docs/DESIGN_A6.md` updated in the same PR; `design:ux-copy` on every new visitor-facing sentence, findings in the PR body.
- Worktree guard as in the other plans.

## Review Focus

1. C2's sentence painted before `meta.json`'s status (the line must be additive, after the existing status line, and never replace it): pinned by the harness test that the existing status text is unchanged with and without the fixture.
2. A malformed `status.json` (missing `last_run_at`) throwing in the page script and blanking the status: pinned by a test with a truncated fixture.
3. C3 printing a course-level rung for a cell that is pooled (mislabelling the department curve as the course's): pinned by tests on the synthetic export where `COMPSCI 0` at 6-15 is pooled to the department.
4. The section rung phrased as a promise ("coming in October"): pinned by a test asserting the exact sentence.
5. C2 and C3 both editing the same lines of `site.js` and conflicting on merge: pinned by the architecture note (separate functions, separate sections) and by the orchestrator's integration merge after both PRs.

---

### Task 1: C2, the live data-status sentence (agent `site-builder`, effort xhigh; branch `c2-status-line`)

- [ ] **Step 1 (tests first):** `tests/fixtures/status_sample.json` shaped exactly like the data branch's `status.json` (`complete`, `kind`, `last_run_at`, `missing_share`, `n_missing`, `n_observed`, `n_written`, `scope`, `shard`, `snapshot`, `source`, `sweep_seconds`, `term_id`, `version`; copy the field set from `scraper/fetch.py`'s writer or the live file). A harness hook that serves the absolute status URL from a file when an environment variable names one (`HARNESS_STATUS_FILE`; a 404 when unset), added as its own small block in `tests/site/harness.js` `fetchStub` so it merges next to the `HARNESS_LIVE_FILE` hook that PR #19 adds on another branch. Tests in `tests/test_site.py`: with the fixture and a pinned now (`?today=` already pins the date; pin the clock the way the harness allows, or assert the "about N min ago" shape with a regex), the line appears on `index.html` and `about.html` after the existing status sentence, naming `n_observed`, `n_missing` and the relative time; without the fixture (404) the status HTML equals today's exactly; with a truncated JSON file the page renders as today and logs nothing to the visitor. Watch them fail first.
- [ ] **Step 2:** `BWO.liveStatus(container)` in `site/assets/site.js` (its own function, its own block): fetch after `DOMContentLoaded`, parse, append one sentence: "Last snapshot about N min ago: N sections read, N not reached." (numbers with thousands separators, "1 section" singular), nothing when the fetch or the parse fails. Call it from every page's status setup after the existing line is set.
- [ ] **Step 3:** `docs/DESIGN_A6.md`: the field list read, the URL, the cache note, the failure behaviour, and the rule that no number from this line enters `CLAIMS.md`.
- [ ] **Step 4:** `python -m pytest tests/test_site.py` and the full suite green; local smoke both schemes pasted (the smoke has no status file: the line is absent, say so); `design:ux-copy` on the sentence; draft PR against `site-v3`: "Data status read live from the data branch (B2)".

### Task 2: C3, the fallback ladder (agent `site-builder`, effort xhigh; branch `c3-fallback-ladder`)

- [ ] **Step 1 (tests first):** in `tests/test_site.py`, on the synthetic export the existing tests use (`course_site` and `full_site` fixtures): a course with its own curve prints "This curve: COMPSCI 0, positions 1 to 5, n = <cell n>"; a department-pooled cell prints "This curve: the COMPSCI department, positions 6 to 15 (COMPSCI 0 had <n_course> cases, fewer than 30), n = <pool n>"; an all-course cell prints "This curve: all courses, positions 41 and up (…), n = <n>"; every result also prints the section rung "Section curves need this project's own Spring 2027 snapshots; none exist before Oct 26, 2026." exactly; on `course.html` the same ladder appears under the chart. Watch them fail first.
- [ ] **Step 2:** `BWO.ladderHtml(resolved, entry, bucket, meta)` in `site/assets/site.js`, replacing the pooled sentence in `index.html` and `course.html` (keep `BWO.pooledSentence` for callers, have it return the ladder's first sentence). The department name: `config/subject_names.json` is not on `site-v3`, so use the subject code ("the COMPSCI department"); leave a one-line note in the PR that PR #17 brings full names and the ladder can read them then.
- [ ] **Step 3:** `docs/DESIGN_A6.md` Lookup and Course sections: the ladder's three rungs and the section rung's fixed sentence.
- [ ] **Step 4:** `python -m pytest tests/test_site.py` and the full suite green; local smoke both schemes pasted; `design:ux-copy` on the four sentences, findings in the PR body; draft PR against `site-v3`: "S5: the fallback ladder printed with every curve".

### Task 3: C4, cross-listed sections (agent `explore`, read-only)

- [ ] From `scraper/schema.py`, `scraper/live.py` (on `origin/s1-s3-board`) and `tests/fixtures/latest_sample.json`, and from the catalog on the data branch if it records cross-listings: do cross-listed sections arrive as distinct `section_id`s with their own counts (expected: yes, SIS ids differ), and does any file carry the cross-listing itself (a key, a title, a note)? Answer with file paths, line numbers and short quotes; no judgment. The orchestrator turns a "yes" into a contract-test brief for a later session and a "no" into a handoff note.

### Task 4: review (agent `reviewer`, one per PR)

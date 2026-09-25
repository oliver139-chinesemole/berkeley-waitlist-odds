# B1: make PR #4 mergeable (merge `main` into `site-v3`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #4 (`site-v3` → `main`) reports MERGEABLE again, with `main` at a5b36df merged into `site-v3` and the four known conflicts resolved the way `docs/dev/NEXT_SITE_2026-09-25.md` section 4 B1 says.

**Architecture:** One merge commit on `site-v3`, made in a fresh worktree of `origin/site-v3`. The four conflicting files are ledgers or one sentence; every other file merges cleanly (a dry run on 2026-09-25 08:00Z confirmed exactly these four). The implementer does the merge and the methodology sentence; the orchestrator resolves the three ledger files itself before the commit (they are shared contracts, NEXT_SITE section 1).

**Tech Stack:** git, Python 3.12 (`/Users/oliverguo/berkeley-waitlist-odds/.venv/bin/python`), node 22 (`/Users/oliverguo/.nvm/versions/node/v22.23.2/bin/node`), Playwright via `NODE_PATH=/Users/oliverguo/paddleiq/node_modules`.

**Spec:** `docs/dev/NEXT_SITE_2026-09-25.md` section 4, Track B, B1 (brainstorm classification: bounded; the design is that section, cited here rather than rewritten).

## Global Constraints

- Push only to `site-v3` (the one branch the spec allows a direct push to), never `--force`.
- No merges of PRs; no rate-flag, priority-list or `scrape.yml` changes; no edits to existing `docs/DATA_LOG.md` rows.
- `site/methodology.html`: keep `site-v3`'s request-rate sentence (commit ea61bf4: names no number, links the data log, says the priority list is generated), drop v2's.
- `CLAIMS.md`, `CLAUDE.md` (the `Current step` line) and `docs/dev/HANDOFF.md`: keep both sides; `main`'s entries after `site-v3`'s in date order.
- The worktree guard: no `git -C`, no command substitution around git, no heredocs whose text mentions git; scripts written with the Write tool and run by path; commit with `git commit -F <file>`.
- Tests: `python -m pytest` (no second `-q`) must pass; `tests/test_site.py` under node.

## Review Focus

1. A fifth conflicting file that the dry run did not show (for example a test that both sides touched): the spec says stop and diff before choosing. Pinned by Task 1 step 3 (the conflict list must be exactly the four).
2. `site/methodology.html` resolved to v2's sentence by mistake, so the live page names a request rate again: pinned by Task 2's grep (no "one request per second" or "two requests per second" in the file; "generated from" present).
3. A ledger row lost in `CLAIMS.md`: pinned by Task 3's row count (the merged table has every row of both sides: main's 20 data rows including the cross-term row, site-v3's site rows).
4. The `CLAUDE.md` current-step line duplicated or halved: pinned by Task 3's check that the file has exactly one `- Current step:` line.
5. A test that passes on each side but fails merged (main's `tests/test_run.py` predictor list against site-v3's exporter): pinned by Task 4's full suite.

---

### Task 1: Merge `main` into `site-v3` in a fresh worktree (implementer: `site-builder`)

**Files:**
- Modify (merge): every file `main` changed since 4f3ea7c; conflicts expected only in `CLAIMS.md`, `CLAUDE.md`, `docs/dev/HANDOFF.md`, `site/methodology.html`.

**Interfaces:**
- Consumes: `origin/site-v3` at ea61bf4, `origin/main` at a5b36df.
- Produces: a worktree at `.claude/worktrees/b1-merge` on a branch from `origin/site-v3` with the merge in progress (not yet committed), `site/methodology.html` resolved, the three ledger files left conflicted for the orchestrator.

- [ ] **Step 1: Create the worktree from `origin/site-v3`**

`EnterWorktree` with name `b1-merge`; then, in it, `git fetch origin site-v3` and `git checkout -b b1-merge origin/site-v3`. Confirm `git log --oneline -1` prints `ea61bf4`.

- [ ] **Step 2: Start the merge**

Run: `git merge --no-commit --no-ff origin/main`
Expected: "Automatic merge failed; fix conflicts and then commit the result."

- [ ] **Step 3: Confirm the conflict list is exactly the four**

Run: `git diff --name-only --diff-filter=U`
Expected, and nothing else:
```
CLAIMS.md
CLAUDE.md
docs/dev/HANDOFF.md
site/methodology.html
```
If any other path appears: stop, run `git diff <path>` and paste it in the report; do not resolve it.

- [ ] **Step 4: Resolve `site/methodology.html`**

Take the `site-v3` side of every hunk (`git checkout --ours -- site/methodology.html`), then check the file by hand: it must contain "generated from the previous cycles" (the B1 sentence from ea61bf4) and the link to `docs/DATA_LOG.md`, and must not contain "one request per second", "two requests per second" or "at most 2 requests". Run:
`grep -c "generated from" site/methodology.html` → 1 or more; `grep -ciE "requests? per second" site/methodology.html` → 0.
Also confirm the file still carries the v3 shell (`assets/site.css`, the nav with `aria-current`) with `grep -c 'assets/site.css' site/methodology.html` → 1.

- [ ] **Step 5: Stage that file and report**

`git add site/methodology.html`. Leave `CLAIMS.md`, `CLAUDE.md` and `docs/dev/HANDOFF.md` conflicted (do not touch them). Report: the worktree path, the conflict list from step 3, the grep outputs from step 4, and `git status --short | head -20`.

### Task 2: Resolve the three ledgers (orchestrator)

**Files:**
- Modify: `CLAIMS.md`, `CLAUDE.md`, `docs/dev/HANDOFF.md` in the Task 1 worktree.

- [ ] **Step 1: `CLAIMS.md`**

Open the conflict hunks. Each hunk is rows appended by both sides. Keep both sides' rows; order: main's rows (cross-term backtest, cadence re-measures) then site-v3's site rows, matching the table's date order. After editing: `grep -c "^<<<<<<<\|^=======\|^>>>>>>>" CLAIMS.md` → 0; count of lines starting with `| ` equals main's count plus site-v3's site-only rows (compute both with `git show origin/main:CLAIMS.md | grep -c "^| "` and `git show origin/site-v3:CLAIMS.md | grep -c "^| "`, and explain the merged number).

- [ ] **Step 2: `CLAUDE.md`**

Keep main's `Current step` line (session 6's close, from a5b36df) and append site-v3's clause about PR #4 to its end, before "Update this line at the end of every session." Check `grep -c "^- Current step:" CLAUDE.md` → 1 and no conflict markers.

- [ ] **Step 3: `docs/dev/HANDOFF.md`**

Both sides added session entries between the same anchors. Keep every entry: session 5 (site-v3's) before session 6 (main's); site-v3's "What is left" edits and main's both stay where they were. Check no conflict markers and that `grep -c "^## Session" docs/dev/HANDOFF.md` equals the union (session 4, 5, 6 at least).

- [ ] **Step 4: Stage the three files**

`git add CLAIMS.md CLAUDE.md docs/dev/HANDOFF.md`; `git diff --name-only --diff-filter=U` → empty.

### Task 3: Tests and smoke on the merged tree (implementer: `site-builder`, same worktree)

- [ ] **Step 1: Full suite**

Run: `/Users/oliverguo/berkeley-waitlist-odds/.venv/bin/python -m pytest` with `PATH` including node 22.
Expected: all passed (360 on site-v3 plus main's additions; record the number). If `tests/test_run.py` fails on the predictor list, report it: the exporter on site-v3 already exports the five predictors, so a failure means a real merge error, not a test to edit.

- [ ] **Step 2: Local smoke**

`python -m http.server 8000 -d site` in the background, then `NODE_PATH=/Users/oliverguo/paddleiq/node_modules node tests/site/smoke.mjs http://127.0.0.1:8000 <scratch>/shots-b1 2027-01-10 "COMPSCI 61A"`.
Expected: "36 renders, 0 with problems". Paste the last line.

- [ ] **Step 3: Commit the merge**

Write the commit message with the Write tool to a scratch file: subject "Merge main (a5b36df) into site-v3: collection stack, session 6 and 7 docs", body listing the four conflicts and how each was taken (methodology: site-v3's sentence; the three ledgers: both sides in date order), the test count and the smoke line, ending with the Co-Authored-By trailer. Run `git commit -F <file>`.

- [ ] **Step 4: Push to `site-v3` and confirm the PR is mergeable**

`git push origin HEAD:site-v3` (no force). Then poll `gh pr view 4 --json mergeable -q .mergeable` until it reads MERGEABLE (GitHub recomputes within a minute), and `gh run list --branch site-v3 --limit 4` shows `ci` and `site-smoke` for the new head; wait for both to complete and record the conclusions.

- [ ] **Step 5: Comment on PR #4**

`gh pr comment 4 --body-file <file>` with: "merged main at a5b36df as <sha>; the four conflicts and how each was taken: …; tests N passed; smoke 36 renders, 0 with problems; CI <run ids> green."

### Task 4: Review (reviewer)

Brief: the diff of the merge commit against `origin/site-v3` limited to the four resolved files (`git diff ea61bf4 <sha> -- CLAIMS.md CLAUDE.md docs/dev/HANDOFF.md site/methodology.html`), plus the merge's own conflict list from Task 1 step 3. Verify: the methodology sentence is site-v3's; every ledger row from both sides is present once; the current-step line is single; no file outside those four differs from what a clean three-way merge produces (`git diff <sha> origin/main -- . ':!CLAIMS.md' ':!CLAUDE.md' ':!docs/dev/HANDOFF.md' ':!site/methodology.html'` shows only site-v3's own changes).

# B2 and B3: rebase the site stack onto the new `site-v3` head and prove it integrates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After B1, the five draft PRs stacked on `site-v3` (#11, #17, #16, #19, #20) each sit on the new `site-v3` head with green CI, base unchanged (`site-v3`, and `s1-s3-fixture` for #20), so Oliver's later merge sequence is mechanical; and a throwaway worktree proves that `site-v3` + #11 + #17 + #16 + #19 + #20 merge in order with the full suite, the live-board tests, the query fixture and the browser smoke green.

**Architecture:** One worktree, one branch at a time, in the order #11, #17, #16, #19, #20 (#20 onto the rebased #19). `git rebase <new base>`, resolve, full suite, `tests/test_site.py` under node, `git push --force-with-lease`, wait for CI, and a "Rebase notes" paragraph on the PR when a conflict needed a resolution. Then a separate throwaway worktree for the integration merge; deleted at the end.

**Tech Stack:** git, Python 3.12 (`/Users/oliverguo/berkeley-waitlist-odds/.venv/bin/python`), node 22, Playwright via `NODE_PATH=/Users/oliverguo/paddleiq/node_modules`.

**Spec:** `docs/dev/NEXT_SITE_2026-09-25.md` section 4, Track B, B2 and B3 (and the A2 paragraph it points at for the expected conflict points).

## Global Constraints

- Bases stay as they are: #11, #17, #16, #19 → `site-v3`; #20 → `s1-s3-fixture`. They retarget to `main` only after #4 merges (not this session).
- The only force-push allowed is `--force-with-lease` on the branch being rebased. No merges of PRs. No rate-flag, priority-list or `scrape.yml` command changes (the #20 comment line stays as #20 wrote it).
- A mechanical conflict is taken and recorded; a conflict needing a code decision takes the **later** branch's intent (spec section 6) and is recorded as "Rebase notes" in that PR's body.
- Expected conflict points from the spec: `site/assets/site.css` between #16 (tokens) and #20 (the `--s1`…`--s4` ramp classes and the stale note; #19's body still says the warning token is `--warn`, after #16 it is `--rust`); `site/assets/site.js` between #17 (matcher) and #20 (board rendering); `docs/DESIGN_A6.md` (subsections appended by #17, #16 and #20). These appear in B3's integration merge, not in the B2 rebases (each branch rebases onto `site-v3` alone).
- Worktree guard: no `git -C`, no command substitution around git, scripts and long files through the Write tool.

## Review Focus

1. A rebase that silently drops a commit (a branch whose commit count after the rebase is lower than before): pinned by each task's `git rev-list --count` comparison.
2. #11's `site/data/*` (Spring 2026 export) overwritten by `site-v3`'s Fall 2026 files during the rebase: pinned by Task 1's `meta.json` check (`term_name` Spring 2026 after the rebase).
3. #11's methodology edit undoing B1's sentence (the branch predates ea61bf4): pinned by Task 1's grep (no "requests per second", "generated from" present, and #11's Spring 2026 wording present).
4. #20 rebased onto the old #19 head instead of the rebased one: pinned by Task 5's `git merge-base` check.
5. The integration tree passing pytest but failing the query fixture or the live-board test under node: pinned by Task 6 running both explicitly.

---

### Task 1: rebase #11 (`p4-spring-source`) onto `site-v3`

- [ ] **Step 1:** In the B2 worktree: `git fetch origin`, `git checkout -b p4-spring-source origin/p4-spring-source`, record `before=$(git rev-list --count origin/site-v3..HEAD)` by reading the number (do not use command substitution near git in a guarded worktree; run the two commands separately and note the numbers).
- [ ] **Step 2:** `git rebase origin/site-v3`. Expected conflicts: `site/methodology.html` (B1's sentence versus #11's Spring 2026 wording: keep both, B1's sentence and #11's term wording), `CLAIMS.md` (#11's site-source row appended after main's rows), `CLAUDE.md` (keep the rebased base's line and re-apply #11's clause), `docs/DATA_LOG.md` (#11's decision row appended after main's rows, in date order), `README.md` and `docs/RUNBOOK.md` if main touched the same lines (keep both edits).
- [ ] **Step 3:** After the rebase: `git rev-list --count origin/site-v3..HEAD` equals the number from step 1 (2); `grep -c "generated from" site/methodology.html` ≥ 1; `grep -ciE "requests? per second" site/methodology.html` = 0; `python -c "import json; print(json.load(open('site/data/meta.json'))['term_name'])"` prints `Spring 2026`.
- [ ] **Step 4:** Full suite and `tests/test_site.py` under node green; `git push --force-with-lease origin p4-spring-source`; CI (`ci`, `site-smoke`) green on the new head; `gh pr view 11 --json mergeable` MERGEABLE. Add "Rebase notes" to the PR body if any resolution was more than mechanical.

### Task 2: rebase #17 (`q1-q3-search`) onto `site-v3`

Same steps; expected clean (its files are untouched by main's changes). Commit count before and after: 5.

### Task 3: rebase #16 (`u3-u4-design`) onto `site-v3`

Same steps; expected clean. Commit count: 6. After the rebase, `du -ch site/assets/fonts/* | tail -1` still reads 56K and `grep -c gold site/assets/site.css` matches the PR body's proof (10 lines).

### Task 4: rebase #19 (`s1-s3-fixture`) onto `site-v3`

Same steps; expected clean. Commit count: 5. `python -m pytest tests/test_site_live.py` → 1 passed, 1 xfailed.

### Task 5: rebase #20 (`s1-s3-board`) onto the rebased `s1-s3-fixture`

- [ ] Steps as Task 1 with base `origin/s1-s3-fixture` (after Task 4's push). Expected conflicts: `docs/DESIGN_A2.md` (main appended sections 16 to 18; #20 edits the data-branch layout paragraph: keep both), `docs/RUNBOOK.md` (main's request-policy text and #20's live-file paragraph: keep both), `.github/workflows/scrape.yml` (main changed the fetch flags, #20 changed one comment line on the live step: keep both; the command line of the live step must not change).
- [ ] After: `git merge-base HEAD origin/s1-s3-fixture` equals the rebased #19 head; commit count 9 (14 minus #19's 5); `python -m pytest tests/test_live.py tests/test_site_live.py tests/test_site.py` green; `grep -n "continue-on-error: true" .github/workflows/scrape.yml` still shows the live step; push with lease; CI green.

### Task 6: B3, the integration proof (throwaway worktree `site-v3-integrated`)

- [ ] **Step 1:** New worktree from `origin/site-v3` (after B1), branch `site-v3-integrated`, no PR.
- [ ] **Step 2:** `git merge --no-ff origin/p4-spring-source`, then `origin/q1-q3-search`, `origin/u3-u4-design`, `origin/s1-s3-fixture`, `origin/s1-s3-board`, in that order. Resolve each conflict on the spot; record every conflict and its resolution. Where a resolution is a code decision (site.css ramp versus tokens; site.js matcher versus board), fix it on the later branch of the pair with a "Rebase notes" commit and re-run Task 5's or Task 3's push, so Oliver's merges stay clean; then redo the integration merge from that branch.
- [ ] **Step 3:** Checks, all pasted into the handoff: `python -m pytest` (count); `python -m pytest tests/test_site.py tests/test_site_live.py` under node; `node tests/site/queries.mjs` (all fixture queries matched); `HARNESS_LIVE_FILE=tests/fixtures/latest_sample.json HARNESS_NOW=2027-01-10T12:00:00+00:00 node tests/site/harness.js site/course.html site "?c=COMPSCI+61A&today=2027-01-10"` renders the board rows; the local smoke in both schemes ("36 renders, 0 with problems"); `du -ch site/assets/fonts/*`.
- [ ] **Step 4:** `git worktree remove` the integration worktree and delete its branch; nothing is pushed from it.

### Task 7: review (reviewer)

Brief: the five rebased heads against their pre-rebase heads (`git range-diff` per branch, written to a file), the integration checks' output, and this plan. Verify: commit counts preserved; no content change beyond conflict resolutions; every recorded resolution matches the spec's rule; bases unchanged on GitHub (`gh pr view N --json baseRefName`).

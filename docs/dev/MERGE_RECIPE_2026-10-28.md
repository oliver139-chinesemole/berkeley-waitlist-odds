# Merge recipe, 2026-10-28 (the integration agent's report, verbatim)

Written by session 11's integration agent after merging the fourteen code and site branches (every open PR except the docs PR #44 and #33) into `integration-2026-10-28` (head 8f6422d on main 0927c45): 596 tests, 190 of 190 fixture queries, 41 smoke renders clean. Two ways to land the work: PR by PR in the order below, taking each resolved file from the integration commit named; or retarget every stacked PR to main (`gh pr edit <n> --base main`, because this repository does not delete merged branches, so GitHub never retargets them itself) and fast-forward main to `integration-2026-10-28` while main is still 0927c45, which marks every PR merged. If the Sunday weekly run moves main first, expect a modify/delete conflict on `reports/`; delete those files.

# Integration of the batch-5 draft PRs (2026-10-28)

Branch `integration-2026-10-28` (pushed from the scratch worktree `/Users/oliverguo/bwo-integ5`, local branch `integ-batch5`), head **8f6422d**, on main **0927c45**. It is a plain branch with no PR. Fourteen branches are merged with `git merge --no-edit`, in the order below, one merge commit each. Every resolution was done by hand and keeps both sides. No cross-branch fix was needed.

## Result

- Full suite on the merged tree: **596 passed** in 134 s (`export PATH=/Users/oliverguo/.nvm/versions/node/v22.23.2/bin:$PATH; /Users/oliverguo/berkeley-waitlist-odds/.venv/bin/python -m pytest`).
- `node tests/site/queries.mjs`: **190 of 190 fixture queries matched**, `"failures":[]`.
- Extra check: the browser smoke (`tests/site/export_fixture.py` served locally, `NODE_PATH=/Users/oliverguo/paddleiq/node_modules node tests/site/smoke.mjs ... 2027-01-10`) gave 41 renders, 0 with problems.
- Extra check: every `def`, every module-level constant and every added line from each branch is present in the merged tree, unless a branch that contains it later replaced it. The scripted check found nothing missing.
- All workflow files parse as YAML.
- `docs-2026-10-23` (#44, docs/dev and CLAUDE.md only) is not in the list. `git merge-tree` shows it merges cleanly on top of 8f6422d. #33 is also not included.

## Merge order and outcome

| # | Branch (PR) | Base of the PR | Merge commit | Conflicts |
| --- | --- | --- | --- | --- |
| 1 | scrape-spring-selection (#43) | main | a51b9c1 | none |
| 2 | titles-live (#45) | scrape-spring-selection | d60919e | none |
| 3 | make-analysis-interval (#47) | titles-live | 78d17a3 | none |
| 4 | scraper-followups (#48) | scrape-spring-selection | be39335 | none |
| 5 | site-term-guards (#42) | main | 9dc3138 | none |
| 6 | site-prereg-copy (#49) | site-term-guards | 2d61d44 | none |
| 7 | site-hygiene (#52) | site-prereg-copy | 47b8856 | none |
| 8 | site-audit-a (#55) | site-hygiene | 30ed8d8 | none |
| 9 | site-audit-c (#56) | site-audit-a | **d09dfe2** | `tests/test_site.py` |
| 10 | site-audit-b (#54) | site-hygiene | **6e2913f** | `docs/DESIGN_A6.md` |
| 11 | analysis-swap-gate (#46) | main | **b678bb0** | `.github/workflows/analysis.yml`, `docs/DATA_LOG.md`, `tests/test_workflows.py` |
| 12 | weekly-noise (#50) | analysis-swap-gate | **4f08419** | `docs/DESIGN_A5.md`, `tests/test_workflows.py` |
| 13 | cli-tests (#51) | weekly-noise | a1c3cf7 | none |
| 14 | analysis-deadline-cut (#53) | main | **8f6422d** | `analysis/run.py`, `tests/test_run.py` |

## The resolutions, file by file

The covering tests were run after each conflicting merge, before its commit.

### 9. site-audit-c (#56): `tests/test_site.py`

One hunk, in `test_the_title_layer_is_skipped_silently_without_titles`.
- **Ours (#45)** builds a copy of the shipped `site/data` without `titles.json` and drops its `meta.titles_file`, five lines starting at `# the committed site/data with its titles file and meta key taken out`.
- **Theirs (#56)** changes the `expression` line so it returns `a.nearest.map((r) => r.key)` instead of `a.nearest.length > 0`.

**Keep #45's five setup lines, and use #56's `expression` line in place of #45's.** Git auto-merges the rest of the function: `render(bare, ...)` comes from #45 and `assert out["eval"] == ["miss", "miss", []]` comes from #56. #45's `test_the_committed_site_data_ships_title_search` stays as it is.

Covering run: `tests/test_site.py tests/test_site_live.py`, 160 passed.

### 10. site-audit-b (#54): `docs/DESIGN_A6.md`

One hunk: the `### Insights (insights.html)` paragraph.
- **#56** added this parenthetical after "Grid: bucket by 7, 14, 28 days and the longest follow-up, with intervals": `("at least" past the reach, as on Courses; the departments' table twin too)`.
- **#54** rewrote the paragraph: the division sentence ("moved faster" / "at about the same pace") and the inversion note.

**Take #54's paragraph and put #56's parenthetical back into its "Grid:" sentence.** The sentence then reads: `Grid: bucket by 7, 14, 28 days and the longest follow-up, with intervals ("at least" past the reach, as on Courses; the departments' table twin too). All-course curves. ...`

`site/insights.html` (both PRs edit it) and `tests/test_site.py` merge cleanly.

Covering run: `tests/test_site.py tests/test_site_live.py`, 173 passed.

### 11. analysis-swap-gate (#46): three files

**`.github/workflows/analysis.yml`.** One hunk: the "Run the analysis" command plus the comment and name of the next step.
- Take #46's side: its comment block and the step name `Publish own-data site files only on a publish_own dispatch`.
- On the run line, add #45's guard after `--meta-from`.
- The `CATALOG:` env line and #45's two comment lines above `env:` merge cleanly; keep them.
- The final line is:
  ```
  python -m analysis.run --data-root data-branch --term-id "${{ steps.term.outputs.term_id }}" --out analysis/out --site-dir analysis/out/site_candidate --max-interval-min 180 --meta-from site/data/meta.json $(test -f "$CATALOG" && echo --catalog "$CATALOG") 2>&1 | tee analysis.log
  ```

**`docs/DATA_LOG.md`.** Keep both appended rows, in time order: #43's `2026-10-23T23:05Z` decision row first, then #46's `2026-10-24T06:24Z` decision row. Neither row is edited.

**`tests/test_workflows.py`.** One hunk, after `test_scrape_workflow_passes_the_budget_shards_and_request_policy`.
- Keep #47's `test_make_analysis_censors_gaps_over_180_min_like_the_weekly_run`.
- Follow it with #46's `_dispatch_input` helper and #46's renamed `def test_analysis_workflow_replaces_site_data_only_on_a_publish_own_dispatch_for_spring_2027() -> None:`, which replaces the old `..._only_for_spring_2027` def line.
- `MAKEFILE` and `_analysis_recipe` at the top are outside the hunk and stay.

`analysis/run.py` merges cleanly (#45's `catalog=` and #46's `--meta-from`/`carried_meta`).

Covering run: `tests/test_workflows.py tests/test_run.py tests/test_run_meta.py tests/test_export.py`, 43 passed.

### 12. weekly-noise (#50): two files

**`docs/DESIGN_A5.md`.** One hunk: the `titles.json` row of the site-files table.
- Keep #45's row, which has the primary-like sentence and "among those entries" / "their names".
- After "Keys sorted, so a re-export is byte-identical apart from `generated_at`.", insert #50's sentence: "A full export restamps `generated_at`; under `--titles-only` it is when the file's content last changed (a refresh that changes nothing keeps it)."

**`tests/test_workflows.py`.** One hunk: the module constants. The kept block is:
```
ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"


def _analysis_recipe() -> str:
    ...
```
That is #50's `ROOT`/`WORKFLOWS`, then #47's `MAKEFILE` and `_analysis_recipe()` unchanged.

`analysis.yml`, `export.py`, `run.py`, RUNBOOK and the deleted `reports/` files merge cleanly.

Covering run: `tests/test_workflows.py tests/test_export.py tests/test_run.py tests/test_run_meta.py tests/test_site.py`, 193 passed.

### 14. analysis-deadline-cut (#53): two files

**`analysis/run.py`.** Four hunks, all resolved by keeping both sides, #45's first:
1. **Signature of `run_analysis`:** `catalog: Path | str | None = None,` then `cut_at_last_auto: str | None = None,`.
2. **Docstring:** #45's text ("...stands in for the coming one;" plus the two `catalog` lines), then #53's four `cut_at_last_auto` lines. Drop #53's duplicate "site counts down to ... coming one." line.
3. **CLI flags:** #45's `p.add_argument("--catalog", ...)`, then #53's `p.add_argument("--cut-at-last-auto", ...)` block.
4. **Call site:** `catalog=args.catalog,` then `cut_at_last_auto=args.cut_at_last_auto,`.

The body (`cut_at` on the cohorts and the meta, `catalog=catalog` into `export_site_tables`) merges cleanly.

**`tests/test_run.py`.** Two hunks:
1. **Imports:** `import analysis.run as run` (#45), then `from analysis.calendar import TermCalendar, last_auto_cut` (#53).
2. **Test functions:** keep #45's `_two_course_catalog`, `test_run_writes_titles_from_the_catalog` and `test_cli_passes_the_catalog_to_the_run`. Then, after two blank lines, add all of #53's: `_regime_warnings`, `test_spans_phase1_end`, `test_cox_fit_across_phase1_end_logs_one_warning`, `test_cut_at_last_auto_is_off_by_default_and_cuts_when_asked` and `test_cli_cut_flag_defaults_off_and_takes_an_instant`.

Covering run: `tests/test_run.py tests/test_run_meta.py tests/test_export.py tests/test_calendar.py tests/test_cohort.py tests/test_synthetic.py tests/test_workflows.py`, 85 passed.

## Cross-branch fixes

None. The one real interaction is between #45's shipped `site/data/titles.json` and #56's "no Did you mean" expectation in the titles-skipped test. The resolution itself handles it: #45's titles-free copy of site/data is combined with #56's `[]` nearest-keys assertion, and no extra commit is needed.

## Batch 6 (2026-10-29): four PRs not yet in the integration branch

#59 `scrape-partial-sweeps` (on #48), #58 `catalog-stubs` (on #45), #60 `export-options` (on #58; its head merges #58's last commit), #61 `site-review-oct29` (on #56). Order with the rest: #43, #42, #44, #45, #47, #48, **#59**, #49, #52, #55, #56, **#61**, #54, #46, #50, #51, #53, **#58**, **#60**. `integration-2026-10-30` (1ecb970, on origin) is `integration-2026-10-28` plus #59, #61 and #60 in that order, resolved by keeping both sides: `docs/DATA_LOG.md` (rows from both), `docs/DESIGN_A6.md` (the Insights paragraph: the division rule and inversion note, then #61's tail sentence), `analysis/export.py` (`write_titles` and `titles_payload` both take `loaded=`), `analysis/run.py` (`--cut-at-last-auto` beside `--reach-min-at-risk`, `--interval-min-sections`, `--exits-at-last-auto`; the `--catalog` help text from #60), `tests/test_run.py` (both test sets). Result: 664 tests, 190 of 190 queries, 41 smoke renders. Two default-off "last automatic run" helpers now coexist (`--cut-at-last-auto` from #53, `--exits-at-last-auto` from #60); they give the same instant for 2262, 2268 and 2272 and should share one function later.

## How Oliver lands it

### Option A: PR by PR in GitHub (merge commits, not squash)

Merge in the order of the table above.

**Retarget each stacked PR first.** `delete_branch_on_merge` is off and no base branch is deleted, so GitHub will not retarget these PRs to main by itself. A stacked PR left on its old base merges into that branch, not into main. Retarget each one before merging it:
```
gh pr edit <n> --base main
```
The stacked PRs are #45, #47, #48, #49, #52, #55, #56, #54, #50 and #51. #43, #42, #46 and #53 already target main.

**Conflicts.** Nine PRs merge cleanly. When a PR reports conflicts, resolve them as in the section above. GitHub's web editor shows two-way markers; the doc and workflow hunks are easy there, and the test files are easier locally.

The exact resolved files are already committed on `integration-2026-10-28`. While main holds exactly the earlier PRs of this list (and no other commit touching these files), resolve each conflicting PR on its own branch like this:
```
git switch <branch> && git merge origin/main
git checkout <sha> -- <files>
git commit --no-edit && git push
```
Then merge the PR in GitHub.

| PR | `<sha>` | `<files>` |
| --- | --- | --- |
| #56 | d09dfe2 | tests/test_site.py |
| #54 | 6e2913f | docs/DESIGN_A6.md |
| #46 | b678bb0 | .github/workflows/analysis.yml docs/DATA_LOG.md tests/test_workflows.py |
| #50 | 4f08419 | docs/DESIGN_A5.md tests/test_workflows.py |
| #53 | 8f6422d | analysis/run.py tests/test_run.py |

A merge is symmetric in content and has the same merge base whichever way it runs, so each resulting file is identical to the one on this branch.

### Option B: one step

1. Retarget the ten stacked PRs to main:
   ```
   for n in 45 47 48 49 52 55 56 54 50 51; do gh pr edit $n --base main; done
   ```
2. Merge `integration-2026-10-28` into main. While main is still 0927c45, that is a fast-forward:
   ```
   git push origin integration-2026-10-28:main
   ```
   Or open a PR from the branch and merge it with a merge commit.
3. GitHub marks each PR merged once its head commit is reachable from its base, main. Check with `gh pr list --state open`. Any PR left open (a draft GitHub did not mark) can be marked ready, or closed with a comment that names the integration merge.

If main has moved before then, merge instead of fast-forwarding. The likely mover is the Sunday Nov 1 15:23Z weekly analysis run, which still commits `reports/` until #50 lands. A modify/delete conflict on `reports/report_2268.md` and `reports/figures_2268/*` resolves by deleting them (`git rm`), as #50's own merge of main (7563982) did.

Either way, run `pages.yml` afterwards. #44 (docs) merges cleanly on top, and #33 closes once #44 is in.

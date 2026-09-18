# Plan: A2 scraper and storage (2026-09-18)

Design: `docs/DESIGN_A2.md` is the binding contract (files, signatures, storage layout, tests). This plan records how it was executed and how it is verified.

## Execution

Five modules built in parallel by separate agents with disjoint file ownership (core storage, classes_site + http, sis_api + berkeleytime, orchestration + workflows, docs), then one integration pass (full pytest, live smoke against Fall 2026 with `--limit 25`, Berkeleytime cross-check), then a three-lens adversarial review (data semantics, operations, politeness/security) with three refuters per finding, then a fix pass.

## Verification commands (run from the repo root with `.venv` active)

```
python -m pytest -q
python -m scraper.fetch --term "Fall 2026" --source classes_site --data-root /tmp/wl --limit 25 --priority-file none --n-shards 0 --dry-run
python -m scraper.fetch --term "Fall 2026" --source classes_site --data-root /tmp/wl --limit 25 --priority-file none --n-shards 0
python -m scraper.fetch --term "Fall 2026" --source classes_site --data-root /tmp/wl --limit 25 --priority-file none --n-shards 0
python -c "from scraper.rebuild import rebuild_panel; from pathlib import Path; p=rebuild_panel(Path('/tmp/wl'),'2268'); print(p.shape, p.observed.mean())"
python -m scraper.gaps --data-root /tmp/wl --term-id 2268 --hours 24
python probe/crosscheck_berkeleytime.py --term "Fall 2026" --n 20
```

Expected: tests green; first fetch writes `snapshots/date=<today>/HHMM-baseline.parquet` with about 25 rows; second writes `HHMM-delta.parquet` with 0 or a few rows and metadata `n_observed` about 25; rebuild returns 2 runs x 25 sections with `observed` true; gap report shows 2 runs; cross-check agrees on at least 18 of 20 within 15-minute drift.

## Exit criteria for A2 (from docs/FINISH_PLAN_WAITLIST.md)

- [ ] Tests green.
- [ ] Workflow runs on manual dispatch (needs the GitHub repo; see docs/RUNBOOK.md).
- [ ] gitleaks clean before the first public push.

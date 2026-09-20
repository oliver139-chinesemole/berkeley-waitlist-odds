# Analysis entry points. `make analysis` runs on the data branch; the backfill
# targets run on Berkeleytime's public history for a finished term (laptop only:
# Berkeleytime blocks GitHub's runners). See docs/BACKFILL_BACKTEST.md.
TERM ?= 2268
TERM_NAME ?= Fall 2026
DATA_ROOT ?= ./data-branch
BACKFILL_RAW ?= backfill/raw/$(TERM)
BACKFILL_DIR ?= backfill/$(TERM)
PILOT ?= 300
COHORT ?= analysis/out/$(TERM)/cohort_central.parquet

.PHONY: test flows analysis backfill-pilot backfill backfill-analysis backtest

test:
	python -m pytest -q

flows:
	python -m analysis.flows --data-root $(DATA_ROOT) --term-id $(TERM) --out analysis/out/flows_$(TERM).parquet

analysis:
	python -m analysis.run --data-root $(DATA_ROOT) --term-id $(TERM) --out analysis/out --site-dir site/data

# First $(PILOT) sections of the seeded permutation (a subset of the full pull), then build.
backfill-pilot:
	python -m analysis.backfill fetch --term "$(TERM_NAME)" --cache $(BACKFILL_RAW) --limit $(PILOT)
	python -m analysis.backfill build --term "$(TERM_NAME)" --cache $(BACKFILL_RAW) --out $(BACKFILL_DIR)

# Every eligible section; resumable, rerun until `failed` is 0 or stable.
backfill:
	python -m analysis.backfill fetch --term "$(TERM_NAME)" --cache $(BACKFILL_RAW)
	python -m analysis.backfill build --term "$(TERM_NAME)" --cache $(BACKFILL_RAW) --out $(BACKFILL_DIR)

backfill-analysis:
	python -m analysis.run --backfill-dir $(BACKFILL_DIR) --term-id $(TERM) --out analysis/out --site-dir site/data

backtest:
	python -m analysis.backtest --cohort $(COHORT) --term-id $(TERM) --split temporal --which days:14 --out reports/backtest_$(TERM)/temporal_days14
	python -m analysis.backtest --cohort $(COHORT) --term-id $(TERM) --split temporal --which days:28 --out reports/backtest_$(TERM)/temporal_days28
	python -m analysis.backtest --cohort $(COHORT) --term-id $(TERM) --split grouped --which days:14 --out reports/backtest_$(TERM)/grouped_days14
	python -m analysis.backtest --cohort $(COHORT) --term-id $(TERM) --split temporal --which deadline --out reports/backtest_$(TERM)/temporal_deadline
	python -m analysis.backtest --cohort $(COHORT) --term-id $(TERM) --split temporal --which instruction --out reports/backtest_$(TERM)/temporal_instruction

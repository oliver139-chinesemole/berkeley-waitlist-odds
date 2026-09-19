# Analysis entry points. `make analysis` arrives in step A5.
TERM ?= 2268
DATA_ROOT ?= ./data-branch

.PHONY: test flows

test:
	python -m pytest -q

flows:
	python -m analysis.flows --data-root $(DATA_ROOT) --term-id $(TERM) --out analysis/out/flows_$(TERM).parquet

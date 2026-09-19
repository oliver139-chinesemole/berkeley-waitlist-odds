# Plan: A4 flow reconstruction (2026-09-19)

Design: docs/DESIGN_A4.md (binding). Executed the same day: analysis/panel.py, analysis/flows.py, analysis/positions.py with tests written alongside (tests/test_panel.py, test_flows.py, test_positions.py); the simulator and the synthetic recovery test (analysis/synthetic.py, tests/test_synthetic.py, tests/test_flows_synthetic.py) were built by a separate agent against the contract and drove one rule revision (FIFO admits) and two position-model fixes. docs/ASSUMPTIONS.md section 7 records the measured recovery.

Verification: `python -m pytest tests/test_flows_synthetic.py -q -s` prints the recovery table; `make flows TERM=2268` runs on the data branch.

# Plan: A5 survival analysis (2026-09-19, code only; data from Oct 26)

Design: docs/DESIGN_A5.md (binding). Executed: analysis/calendar.py, cohort.py, survival.py, export.py, figures.py, profile.py, run.py and `make analysis`; tests on simulated cohorts and on the A4 simulator's panel (tests/test_calendar.py, test_cohort.py, test_survival.py, test_run.py, test_profile.py). The weekly workflow analysis.yml runs the same command on the runner.

Verification: `make analysis TERM=<term>` writes analysis/out/<term>/report.md; on Fall 2026 test data the cohort has no clearing events and the report says so. Real numbers, the README hero plot and the headline sentences come from the first Spring 2027 run in November.

# Backtest: Fall 2026 cross_term (days:14)

Split `cross_term`, horizon `days:14`: 531568 training rows, 183335 scored test rows, 0 test rows past their horizon at joining and 310029 whose follow-up ended before their horizon (neither scored).

## Coverage: test rows that could be followed to their horizon, by phase

| phase | n | observable | share_observable |
| --- | --- | --- | --- |
| adjustment | 23844 | 0 | 0.000 |
| after | 5800 | 0 | 0.000 |
| before | 4377 | 4375 | 1.000 |
| between | 37094 | 9405 | 0.254 |
| instruction | 66506 | 34928 | 0.525 |
| phase1 | 169975 | 105812 | 0.623 |
| phase2 | 185768 | 28815 | 0.155 |

Every number here is produced by `python -m analysis.backtest`; nothing is edited by hand. `gain` is the baseline's Brier score minus the predictor's (positive is better) with a 95% section-bootstrap interval; `skill` is `1 - brier / brier_baseline`; `share_unknown` is the share of test rows censored before their horizon (weight 0 under IPCW); `share_fallback` is the share of rows the predictor could not cover and scored with the bucket baseline.

## Predictors

| predictor | n_test | brier_rows | share_unknown | brier | auc | brier_baseline | gain | gain_ci_low | gain_ci_high | skill | share_fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bucket | 183335 | 183335 | 0.000 | 0.259 | 0.616 | 0.259 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dept | 183335 | 183335 | 0.000 | 0.254 | 0.657 | 0.259 | 0.005 | 0.001 | 0.009 | 0.020 | 0.000 |
| course | 183335 | 183335 | 0.000 | 0.250 | 0.695 | 0.259 | 0.009 | 0.004 | 0.016 | 0.037 | 0.000 |
| site | 183335 | 183335 | 0.000 | 0.303 | 0.600 | 0.259 | -0.044 | -0.053 | -0.034 | -0.169 | 0.391 |
| cox | 183335 | 183335 | 0.000 | 0.274 | 0.725 | 0.259 | -0.015 | -0.020 | -0.010 | -0.059 | 0.051 |

## By enrollment phase of the test rows

| phase | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| before | 4375 | 0.000 | 0.428 | 0.412 | 0.363 | 0.351 | 0.583 |
| between | 9405 | 0.000 | 0.378 | 0.374 | 0.382 | 0.449 | 0.264 |
| instruction | 34928 | 0.000 | 0.193 | 0.181 | 0.174 | 0.243 | 0.176 |
| phase1 | 105812 | 0.000 | 0.269 | 0.266 | 0.262 | 0.313 | 0.310 |
| phase2 | 28815 | 0.000 | 0.238 | 0.236 | 0.236 | 0.285 | 0.219 |

## By position bucket

| position_bucket | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1-5 | 125311 | 0.000 | 0.259 | 0.251 | 0.238 | 0.260 | 0.273 |
| 6-15 | 40047 | 0.000 | 0.281 | 0.277 | 0.286 | 0.375 | 0.288 |
| 16-40 | 15614 | 0.000 | 0.225 | 0.242 | 0.270 | 0.453 | 0.263 |
| 41+ | 2363 | 0.000 | 0.108 | 0.115 | 0.139 | 0.386 | 0.198 |

## Calibration: dept

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 18334.000 | 18334.000 | 0.329 | 0.181 |
| 1 | 18333.000 | 18333.000 | 0.486 | 0.360 |
| 2 | 18334.000 | 18334.000 | 0.581 | 0.422 |
| 3 | 18333.000 | 18333.000 | 0.623 | 0.440 |
| 4 | 18334.000 | 18334.000 | 0.667 | 0.477 |
| 5 | 18333.000 | 18333.000 | 0.684 | 0.600 |
| 6 | 18333.000 | 18333.000 | 0.689 | 0.531 |
| 7 | 18334.000 | 18334.000 | 0.735 | 0.615 |
| 8 | 18333.000 | 18333.000 | 0.785 | 0.586 |
| 9 | 18334.000 | 18334.000 | 0.877 | 0.706 |

## Calibration: cox

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 18334.000 | 18334.000 | 0.340 | 0.205 |
| 1 | 18333.000 | 18333.000 | 0.510 | 0.300 |
| 2 | 18334.000 | 18334.000 | 0.610 | 0.333 |
| 3 | 18333.000 | 18333.000 | 0.683 | 0.275 |
| 4 | 18334.000 | 18334.000 | 0.731 | 0.451 |
| 5 | 18333.000 | 18333.000 | 0.794 | 0.513 |
| 6 | 18333.000 | 18333.000 | 0.851 | 0.611 |
| 7 | 18334.000 | 18334.000 | 0.901 | 0.717 |
| 8 | 18333.000 | 18333.000 | 0.949 | 0.729 |
| 9 | 18334.000 | 18334.000 | 0.982 | 0.783 |

## Calibration: site

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 18334.000 | 18334.000 | 0.067 | 0.356 |
| 1 | 18333.000 | 18333.000 | 0.365 | 0.348 |
| 2 | 18334.000 | 18334.000 | 0.618 | 0.437 |
| 3 | 18333.000 | 18333.000 | 0.710 | 0.557 |
| 4 | 18334.000 | 18334.000 | 0.710 | 0.579 |
| 5 | 18333.000 | 18333.000 | 0.713 | 0.439 |
| 6 | 18333.000 | 18333.000 | 0.770 | 0.358 |
| 7 | 18334.000 | 18334.000 | 0.814 | 0.491 |
| 8 | 18333.000 | 18333.000 | 0.928 | 0.680 |
| 9 | 18334.000 | 18334.000 | 0.994 | 0.673 |

## Notes

- IPCW weights floored at G >= 0.05; Brier self-normalised by the weights; AUC is the weighted Mann-Whitney statistic; intervals from 200 section bootstraps
- cross-term: fit on the training cohort, scored on this term
- 310029 test rows could not be followed to their horizon (a gap or the end of the data came first) and were not scored; see coverage by phase

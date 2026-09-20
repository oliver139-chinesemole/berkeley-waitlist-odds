# Backtest: Fall 2026 grouped (days:14)

Split `grouped`, horizon `days:14`: 1973456 training rows, 183335 scored test rows, 0 test rows past their horizon at joining and 310029 whose follow-up ended before their horizon (neither scored).

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
| bucket | 183335 | 183335 | 0.000 | 0.236 | 0.602 | 0.236 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dept | 183335 | 183335 | 0.000 | 0.234 | 0.652 | 0.236 | 0.003 | -0.000 | 0.005 | 0.012 | 0.000 |
| course | 183335 | 183335 | 0.000 | 0.234 | 0.652 | 0.236 | 0.003 | -0.000 | 0.005 | 0.012 | 0.000 |
| site | 183335 | 183335 | 0.000 | 0.252 | 0.604 | 0.236 | -0.015 | -0.018 | -0.012 | -0.065 | 1.000 |
| cox | 183335 | 183335 | 0.000 | 0.203 | 0.753 | 0.236 | 0.034 | 0.030 | 0.037 | 0.143 | 0.051 |

## By enrollment phase of the test rows

| phase | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| before | 4375 | 0.000 | 0.350 | 0.336 | 0.336 | 0.426 | 0.257 |
| between | 9405 | 0.000 | 0.282 | 0.283 | 0.283 | 0.359 | 0.208 |
| instruction | 34928 | 0.000 | 0.227 | 0.223 | 0.223 | 0.199 | 0.197 |
| phase1 | 105812 | 0.000 | 0.234 | 0.230 | 0.230 | 0.258 | 0.198 |
| phase2 | 28815 | 0.000 | 0.226 | 0.231 | 0.231 | 0.231 | 0.217 |

## By position bucket

| position_bucket | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1-5 | 125311 | 0.000 | 0.247 | 0.242 | 0.242 | 0.259 | 0.211 |
| 6-15 | 40047 | 0.000 | 0.238 | 0.237 | 0.237 | 0.263 | 0.203 |
| 16-40 | 15614 | 0.000 | 0.166 | 0.180 | 0.180 | 0.185 | 0.150 |
| 41+ | 2363 | 0.000 | 0.093 | 0.108 | 0.108 | 0.108 | 0.082 |

## Calibration: dept

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 18334.000 | 18334.000 | 0.203 | 0.218 |
| 1 | 18333.000 | 18333.000 | 0.339 | 0.341 |
| 2 | 18334.000 | 18334.000 | 0.430 | 0.367 |
| 3 | 18333.000 | 18333.000 | 0.501 | 0.471 |
| 4 | 18334.000 | 18334.000 | 0.571 | 0.563 |
| 5 | 18333.000 | 18333.000 | 0.595 | 0.550 |
| 6 | 18333.000 | 18333.000 | 0.606 | 0.515 |
| 7 | 18334.000 | 18334.000 | 0.638 | 0.505 |
| 8 | 18333.000 | 18333.000 | 0.696 | 0.725 |
| 9 | 18334.000 | 18334.000 | 0.782 | 0.665 |

## Calibration: cox

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 18334.000 | 18334.000 | 0.151 | 0.095 |
| 1 | 18333.000 | 18333.000 | 0.255 | 0.215 |
| 2 | 18334.000 | 18334.000 | 0.333 | 0.338 |
| 3 | 18333.000 | 18333.000 | 0.408 | 0.410 |
| 4 | 18334.000 | 18334.000 | 0.483 | 0.529 |
| 5 | 18333.000 | 18333.000 | 0.563 | 0.618 |
| 6 | 18333.000 | 18333.000 | 0.625 | 0.411 |
| 7 | 18334.000 | 18334.000 | 0.701 | 0.701 |
| 8 | 18333.000 | 18333.000 | 0.793 | 0.761 |
| 9 | 18334.000 | 18334.000 | 0.917 | 0.840 |

## Calibration: site

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 18334.000 | 18334.000 | 0.337 | 0.195 |
| 1 | 18333.000 | 18333.000 | 0.530 | 0.391 |
| 2 | 18334.000 | 18334.000 | 0.546 | 0.380 |
| 3 | 18333.000 | 18333.000 | 0.662 | 0.556 |
| 4 | 18334.000 | 18334.000 | 0.680 | 0.581 |
| 5 | 18333.000 | 18333.000 | 0.683 | 0.586 |
| 6 | 18333.000 | 18333.000 | 0.690 | 0.594 |
| 7 | 18334.000 | 18334.000 | 0.690 | 0.566 |
| 8 | 18333.000 | 18333.000 | 0.695 | 0.545 |
| 9 | 18334.000 | 18334.000 | 0.700 | 0.524 |

## Notes

- IPCW weights floored at G >= 0.05; Brier self-normalised by the weights; AUC is the weighted Mann-Whitney statistic; intervals from 200 section bootstraps
- 5 folds grouped by course; every row scored once out of fold
- 310029 test rows could not be followed to their horizon (a gap or the end of the data came first) and were not scored; see coverage by phase

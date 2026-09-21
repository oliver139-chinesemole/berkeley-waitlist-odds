# Backtest: Fall 2026 cross_term (days:28)

Split `cross_term`, horizon `days:28`: 531568 training rows, 71330 scored test rows, 0 test rows past their horizon at joining and 422034 whose follow-up ended before their horizon (neither scored).

## Coverage: test rows that could be followed to their horizon, by phase

| phase | n | observable | share_observable |
| --- | --- | --- | --- |
| adjustment | 23844 | 0 | 0.000 |
| after | 5800 | 0 | 0.000 |
| before | 4377 | 4370 | 0.998 |
| between | 37094 | 906 | 0.024 |
| instruction | 66506 | 0 | 0.000 |
| phase1 | 169975 | 66054 | 0.389 |
| phase2 | 185768 | 0 | 0.000 |

Every number here is produced by `python -m analysis.backtest`; nothing is edited by hand. `gain` is the baseline's Brier score minus the predictor's (positive is better) with a 95% section-bootstrap interval; `skill` is `1 - brier / brier_baseline`; `share_unknown` is the share of test rows censored before their horizon (weight 0 under IPCW); `share_fallback` is the share of rows the predictor could not cover and scored with the bucket baseline.

## Predictors

| predictor | n_test | brier_rows | share_unknown | brier | auc | brier_baseline | gain | gain_ci_low | gain_ci_high | skill | share_fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bucket | 71330 | 71330 | 0.000 | 0.282 | 0.507 | 0.282 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dept | 71330 | 71330 | 0.000 | 0.273 | 0.608 | 0.282 | 0.009 | 0.005 | 0.014 | 0.034 | 0.000 |
| course | 71330 | 71330 | 0.000 | 0.258 | 0.671 | 0.282 | 0.025 | 0.017 | 0.032 | 0.087 | 0.000 |
| site | 71330 | 71330 | 0.000 | 0.262 | 0.636 | 0.282 | 0.021 | 0.011 | 0.032 | 0.073 | 0.400 |
| cox | 71330 | 71330 | 0.000 | 0.292 | 0.792 | 0.282 | -0.010 | -0.016 | -0.004 | -0.036 | 0.071 |

## By enrollment phase of the test rows

| phase | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| before | 4370 | 0.000 | 0.399 | 0.371 | 0.330 | 0.291 | 0.485 |
| between | 906 | 0.000 | 0.378 | 0.405 | 0.427 | 0.406 | 0.284 |
| phase1 | 66054 | 0.000 | 0.273 | 0.264 | 0.250 | 0.258 | 0.280 |

## By position bucket

| position_bucket | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1-5 | 50645 | 0.000 | 0.252 | 0.242 | 0.223 | 0.228 | 0.279 |
| 6-15 | 14617 | 0.000 | 0.349 | 0.338 | 0.330 | 0.328 | 0.320 |
| 16-40 | 5349 | 0.000 | 0.386 | 0.387 | 0.387 | 0.379 | 0.337 |
| 41+ | 719 | 0.000 | 0.271 | 0.272 | 0.280 | 0.401 | 0.298 |

## Calibration: dept

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 7133.000 | 7133.000 | 0.478 | 0.289 |
| 1 | 7133.000 | 7133.000 | 0.651 | 0.416 |
| 2 | 7133.000 | 7133.000 | 0.708 | 0.564 |
| 3 | 7133.000 | 7133.000 | 0.733 | 0.536 |
| 4 | 7133.000 | 7133.000 | 0.735 | 0.608 |
| 5 | 7133.000 | 7133.000 | 0.751 | 0.658 |
| 6 | 7133.000 | 7133.000 | 0.777 | 0.539 |
| 7 | 7133.000 | 7133.000 | 0.792 | 0.506 |
| 8 | 7133.000 | 7133.000 | 0.854 | 0.644 |
| 9 | 7133.000 | 7133.000 | 0.920 | 0.717 |

## Calibration: cox

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 7133.000 | 7133.000 | 0.536 | 0.138 |
| 1 | 7133.000 | 7133.000 | 0.711 | 0.199 |
| 2 | 7133.000 | 7133.000 | 0.758 | 0.262 |
| 3 | 7133.000 | 7133.000 | 0.827 | 0.470 |
| 4 | 7133.000 | 7133.000 | 0.878 | 0.558 |
| 5 | 7133.000 | 7133.000 | 0.920 | 0.633 |
| 6 | 7133.000 | 7133.000 | 0.950 | 0.756 |
| 7 | 7133.000 | 7133.000 | 0.973 | 0.800 |
| 8 | 7133.000 | 7133.000 | 0.990 | 0.786 |
| 9 | 7133.000 | 7133.000 | 0.997 | 0.875 |

## Calibration: site

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 7133.000 | 7133.000 | 0.090 | 0.268 |
| 1 | 7133.000 | 7133.000 | 0.398 | 0.419 |
| 2 | 7133.000 | 7133.000 | 0.643 | 0.523 |
| 3 | 7133.000 | 7133.000 | 0.710 | 0.596 |
| 4 | 7133.000 | 7133.000 | 0.710 | 0.671 |
| 5 | 7133.000 | 7133.000 | 0.711 | 0.454 |
| 6 | 7133.000 | 7133.000 | 0.762 | 0.481 |
| 7 | 7133.000 | 7133.000 | 0.806 | 0.539 |
| 8 | 7133.000 | 7133.000 | 0.919 | 0.745 |
| 9 | 7133.000 | 7133.000 | 0.993 | 0.780 |

## Notes

- IPCW weights floored at G >= 0.05; Brier self-normalised by the weights; AUC is the weighted Mann-Whitney statistic; intervals from 200 section bootstraps
- cross-term: fit on the training cohort, scored on this term
- 422034 test rows could not be followed to their horizon (a gap or the end of the data came first) and were not scored; see coverage by phase

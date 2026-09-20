# Backtest: Fall 2026 temporal (days:14)

Split `temporal`, horizon `days:14`: 211446 training rows, 63743 scored test rows, 0 test rows past their horizon at joining and 218175 whose follow-up ended before their horizon (neither scored).

## Coverage: test rows that could be followed to their horizon, by phase

| phase | n | observable | share_observable |
| --- | --- | --- | --- |
| adjustment | 23844 | 0 | 0.000 |
| after | 5800 | 0 | 0.000 |
| instruction | 66506 | 34928 | 0.525 |
| phase2 | 185768 | 28815 | 0.155 |

Every number here is produced by `python -m analysis.backtest`; nothing is edited by hand. `gain` is the baseline's Brier score minus the predictor's (positive is better) with a 95% section-bootstrap interval; `skill` is `1 - brier / brier_baseline`; `share_unknown` is the share of test rows censored before their horizon (weight 0 under IPCW); `share_fallback` is the share of rows the predictor could not cover and scored with the bucket baseline.

## Predictors

| predictor | n_test | brier_rows | share_unknown | brier | auc | brier_baseline | gain | gain_ci_low | gain_ci_high | skill | share_fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bucket | 63743 | 63743 | 0.000 | 0.291 | 0.613 | 0.291 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dept | 63743 | 63743 | 0.000 | 0.308 | 0.630 | 0.291 | -0.017 | -0.024 | -0.010 | -0.060 | 0.000 |
| course | 63743 | 63743 | 0.000 | 0.314 | 0.658 | 0.291 | -0.023 | -0.034 | -0.011 | -0.079 | 0.000 |
| site | 63743 | 63743 | 0.000 | 0.278 | 0.644 | 0.291 | 0.013 | -0.000 | 0.025 | 0.044 | 0.099 |
| cox | 63743 | 63743 | 0.000 | 0.581 | 0.591 | 0.291 | -0.290 | -0.301 | -0.280 | -0.995 | 0.034 |

## By enrollment phase of the test rows

| phase | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| instruction | 34928 | 0.000 | 0.318 | 0.338 | 0.346 | 0.285 | 0.677 |
| phase2 | 28815 | 0.000 | 0.258 | 0.272 | 0.275 | 0.270 | 0.463 |

## By position bucket

| position_bucket | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1-5 | 44124 | 0.000 | 0.271 | 0.290 | 0.295 | 0.261 | 0.627 |
| 6-15 | 13729 | 0.000 | 0.355 | 0.370 | 0.377 | 0.323 | 0.533 |
| 16-40 | 5145 | 0.000 | 0.306 | 0.319 | 0.320 | 0.319 | 0.359 |
| 41+ | 745 | 0.000 | 0.221 | 0.221 | 0.230 | 0.217 | 0.231 |

## Calibration: dept

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 6375.000 | 6375.000 | 0.048 | 0.470 |
| 1 | 6374.000 | 6374.000 | 0.143 | 0.496 |
| 2 | 6374.000 | 6374.000 | 0.228 | 0.613 |
| 3 | 6374.000 | 6374.000 | 0.279 | 0.581 |
| 4 | 6375.000 | 6375.000 | 0.365 | 0.742 |
| 5 | 6374.000 | 6374.000 | 0.422 | 0.738 |
| 6 | 6374.000 | 6374.000 | 0.440 | 0.688 |
| 7 | 6374.000 | 6374.000 | 0.466 | 0.634 |
| 8 | 6374.000 | 6374.000 | 0.556 | 0.793 |
| 9 | 6375.000 | 6375.000 | 0.664 | 0.825 |

## Calibration: cox

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 6375.000 | 6375.000 | 0.008 | 0.524 |
| 1 | 6374.000 | 6374.000 | 0.016 | 0.560 |
| 2 | 6374.000 | 6374.000 | 0.022 | 0.585 |
| 3 | 6374.000 | 6374.000 | 0.029 | 0.624 |
| 4 | 6375.000 | 6375.000 | 0.037 | 0.673 |
| 5 | 6374.000 | 6374.000 | 0.047 | 0.696 |
| 6 | 6374.000 | 6374.000 | 0.060 | 0.698 |
| 7 | 6374.000 | 6374.000 | 0.078 | 0.739 |
| 8 | 6374.000 | 6374.000 | 0.107 | 0.757 |
| 9 | 6375.000 | 6375.000 | 0.246 | 0.723 |

## Calibration: site

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 6375.000 | 6375.000 | 0.004 | 0.519 |
| 1 | 6374.000 | 6374.000 | 0.093 | 0.440 |
| 2 | 6374.000 | 6374.000 | 0.228 | 0.572 |
| 3 | 6374.000 | 6374.000 | 0.364 | 0.656 |
| 4 | 6375.000 | 6375.000 | 0.461 | 0.725 |
| 5 | 6374.000 | 6374.000 | 0.537 | 0.574 |
| 6 | 6374.000 | 6374.000 | 0.571 | 0.687 |
| 7 | 6374.000 | 6374.000 | 0.722 | 0.749 |
| 8 | 6374.000 | 6374.000 | 0.866 | 0.805 |
| 9 | 6375.000 | 6375.000 | 0.980 | 0.853 |

## Notes

- IPCW weights floored at G >= 0.05; Brier self-normalised by the weights; AUC is the weighted Mann-Whitney statistic; intervals from 200 section bootstraps
- temporal split at 2026-07-20T00:00:00+00:00; training rows censored at the split
- 218175 test rows could not be followed to their horizon (a gap or the end of the data came first) and were not scored; see coverage by phase

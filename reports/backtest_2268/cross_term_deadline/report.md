# Backtest: Fall 2026 cross_term (deadline)

Split `cross_term`, horizon `deadline`: 531568 training rows, 52227 scored test rows, 20079 test rows past their horizon at joining and 421058 whose follow-up ended before their horizon (neither scored).

## Coverage: test rows that could be followed to their horizon, by phase

| phase | n | observable | share_observable |
| --- | --- | --- | --- |
| adjustment | 23844 | 0 | 0.000 |
| before | 4377 | 0 | 0.000 |
| between | 37094 | 0 | 0.000 |
| instruction | 52227 | 52227 | 1.000 |
| phase1 | 169975 | 0 | 0.000 |
| phase2 | 185768 | 0 | 0.000 |

Every number here is produced by `python -m analysis.backtest`; nothing is edited by hand. `gain` is the baseline's Brier score minus the predictor's (positive is better) with a 95% section-bootstrap interval; `skill` is `1 - brier / brier_baseline`; `share_unknown` is the share of test rows censored before their horizon (weight 0 under IPCW); `share_fallback` is the share of rows the predictor could not cover and scored with the bucket baseline.

## Predictors

| predictor | n_test | brier_rows | share_unknown | brier | auc | brier_baseline | gain | gain_ci_low | gain_ci_high | skill | share_fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bucket | 52227 | 52227 | 0.000 | 0.225 | 0.667 | 0.225 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dept | 52227 | 52227 | 0.000 | 0.213 | 0.720 | 0.225 | 0.012 | 0.007 | 0.018 | 0.053 | 0.000 |
| course | 52227 | 52227 | 0.000 | 0.206 | 0.742 | 0.225 | 0.019 | 0.012 | 0.027 | 0.085 | 0.000 |
| site | 52227 | 52227 | 0.000 | 0.295 | 0.569 | 0.225 | -0.071 | -0.092 | -0.054 | -0.314 | 0.364 |
| cox | 52227 | 52227 | 0.000 | 0.315 | 0.733 | 0.225 | -0.090 | -0.101 | -0.079 | -0.401 | 0.030 |

## By enrollment phase of the test rows

| phase | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| instruction | 52227 | 0.000 | 0.225 | 0.213 | 0.206 | 0.295 | 0.315 |

## By position bucket

| position_bucket | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1-5 | 39339 | 0.000 | 0.223 | 0.212 | 0.204 | 0.266 | 0.325 |
| 6-15 | 9816 | 0.000 | 0.234 | 0.222 | 0.216 | 0.365 | 0.301 |
| 16-40 | 2852 | 0.000 | 0.221 | 0.201 | 0.200 | 0.454 | 0.240 |
| 41+ | 220 | 0.000 | 0.133 | 0.120 | 0.139 | 0.395 | 0.128 |

## Calibration: dept

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 5223.000 | 5269.079 | 0.115 | 0.171 |
| 1 | 5223.000 | 5296.749 | 0.259 | 0.354 |
| 2 | 5222.000 | 5268.990 | 0.367 | 0.470 |
| 3 | 5223.000 | 5270.097 | 0.443 | 0.599 |
| 4 | 5223.000 | 5312.881 | 0.503 | 0.634 |
| 5 | 5222.000 | 5296.052 | 0.562 | 0.726 |
| 6 | 5223.000 | 5248.240 | 0.609 | 0.717 |
| 7 | 5222.000 | 5410.265 | 0.639 | 0.681 |
| 8 | 5223.000 | 5296.086 | 0.677 | 0.778 |
| 9 | 5223.000 | 5282.288 | 0.796 | 0.840 |

## Calibration: cox

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 5223.000 | 5250.286 | 0.059 | 0.165 |
| 1 | 5223.000 | 5273.909 | 0.115 | 0.340 |
| 2 | 5222.000 | 5292.055 | 0.156 | 0.471 |
| 3 | 5223.000 | 5304.908 | 0.194 | 0.555 |
| 4 | 5223.000 | 5304.433 | 0.231 | 0.635 |
| 5 | 5222.000 | 5312.775 | 0.271 | 0.676 |
| 6 | 5223.000 | 5311.574 | 0.316 | 0.727 |
| 7 | 5222.000 | 5282.821 | 0.369 | 0.803 |
| 8 | 5223.000 | 5278.443 | 0.442 | 0.807 |
| 9 | 5223.000 | 5339.523 | 0.575 | 0.789 |

## Calibration: site

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 5223.000 | 5327.572 | 0.021 | 0.581 |
| 1 | 5223.000 | 5341.772 | 0.314 | 0.462 |
| 2 | 5222.000 | 5312.254 | 0.562 | 0.506 |
| 3 | 5223.000 | 5294.887 | 0.709 | 0.628 |
| 4 | 5223.000 | 5285.271 | 0.710 | 0.644 |
| 5 | 5222.000 | 5320.447 | 0.710 | 0.581 |
| 6 | 5223.000 | 5308.984 | 0.765 | 0.500 |
| 7 | 5222.000 | 5268.859 | 0.830 | 0.634 |
| 8 | 5223.000 | 5248.410 | 0.937 | 0.698 |
| 9 | 5223.000 | 5242.273 | 0.993 | 0.746 |

## Notes

- IPCW weights floored at G >= 0.05; Brier self-normalised by the weights; AUC is the weighted Mann-Whitney statistic; intervals from 200 section bootstraps
- cross-term: fit on the training cohort, scored on this term
- 421058 test rows could not be followed to their horizon (a gap or the end of the data came first) and were not scored; see coverage by phase

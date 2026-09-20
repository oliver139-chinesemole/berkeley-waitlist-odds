# Backtest: Fall 2026 temporal (deadline)

Split `temporal`, horizon `deadline`: 211446 training rows, 52227 scored test rows, 20079 test rows past their horizon at joining and 209612 whose follow-up ended before their horizon (neither scored).

## Coverage: test rows that could be followed to their horizon, by phase

| phase | n | observable | share_observable |
| --- | --- | --- | --- |
| adjustment | 23844 | 0 | 0.000 |
| instruction | 52227 | 52227 | 1.000 |
| phase2 | 185768 | 0 | 0.000 |

Every number here is produced by `python -m analysis.backtest`; nothing is edited by hand. `gain` is the baseline's Brier score minus the predictor's (positive is better) with a 95% section-bootstrap interval; `skill` is `1 - brier / brier_baseline`; `share_unknown` is the share of test rows censored before their horizon (weight 0 under IPCW); `share_fallback` is the share of rows the predictor could not cover and scored with the bucket baseline.

## Predictors

| predictor | n_test | brier_rows | share_unknown | brier | auc | brier_baseline | gain | gain_ci_low | gain_ci_high | skill | share_fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bucket | 52227 | 52227 | 0.000 | 0.305 | 0.658 | 0.305 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dept | 52227 | 52227 | 0.000 | 0.317 | 0.666 | 0.305 | -0.011 | -0.020 | -0.005 | -0.037 | 0.000 |
| course | 52227 | 52227 | 0.000 | 0.321 | 0.653 | 0.305 | -0.015 | -0.026 | -0.002 | -0.049 | 0.000 |
| site | 52227 | 52227 | 0.000 | 0.282 | 0.606 | 0.305 | 0.023 | 0.006 | 0.040 | 0.077 | 0.098 |
| cox | 52227 | 52227 | 0.000 | 0.548 | 0.691 | 0.305 | -0.243 | -0.254 | -0.232 | -0.796 | 0.030 |

## By enrollment phase of the test rows

| phase | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| instruction | 52227 | 0.000 | 0.305 | 0.317 | 0.321 | 0.282 | 0.548 |

## By position bucket

| position_bucket | n | share_unknown | brier_bucket | brier_dept | brier_course | brier_site | brier_cox |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1-5 | 39339 | 0.000 | 0.300 | 0.314 | 0.317 | 0.280 | 0.591 |
| 6-15 | 9816 | 0.000 | 0.335 | 0.339 | 0.342 | 0.291 | 0.450 |
| 16-40 | 2852 | 0.000 | 0.295 | 0.297 | 0.309 | 0.292 | 0.327 |
| 41+ | 220 | 0.000 | 0.154 | 0.150 | 0.163 | 0.175 | 0.161 |

## Calibration: dept

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 5223.000 | 5287.556 | 0.036 | 0.331 |
| 1 | 5223.000 | 5311.570 | 0.106 | 0.370 |
| 2 | 5222.000 | 5268.310 | 0.163 | 0.544 |
| 3 | 5223.000 | 5321.035 | 0.216 | 0.536 |
| 4 | 5223.000 | 5273.566 | 0.261 | 0.603 |
| 5 | 5222.000 | 5249.072 | 0.321 | 0.680 |
| 6 | 5223.000 | 5250.404 | 0.370 | 0.694 |
| 7 | 5222.000 | 5391.598 | 0.399 | 0.686 |
| 8 | 5223.000 | 5309.948 | 0.450 | 0.726 |
| 9 | 5223.000 | 5287.669 | 0.581 | 0.805 |

## Calibration: cox

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 5223.000 | 5272.768 | 0.004 | 0.307 |
| 1 | 5223.000 | 5303.157 | 0.009 | 0.374 |
| 2 | 5222.000 | 5299.261 | 0.013 | 0.468 |
| 3 | 5223.000 | 5306.733 | 0.017 | 0.537 |
| 4 | 5223.000 | 5311.548 | 0.021 | 0.578 |
| 5 | 5222.000 | 5289.576 | 0.027 | 0.669 |
| 6 | 5223.000 | 5285.616 | 0.034 | 0.712 |
| 7 | 5222.000 | 5275.518 | 0.045 | 0.762 |
| 8 | 5223.000 | 5272.337 | 0.062 | 0.801 |
| 9 | 5223.000 | 5334.214 | 0.164 | 0.765 |

## Calibration: site

| decile | n | weight | predicted | observed |
| --- | --- | --- | --- | --- |
| 0 | 5223.000 | 5352.067 | 0.012 | 0.486 |
| 1 | 5223.000 | 5341.003 | 0.147 | 0.428 |
| 2 | 5222.000 | 5305.962 | 0.291 | 0.538 |
| 3 | 5223.000 | 5282.319 | 0.420 | 0.597 |
| 4 | 5223.000 | 5279.550 | 0.508 | 0.623 |
| 5 | 5222.000 | 5323.998 | 0.551 | 0.590 |
| 6 | 5223.000 | 5302.293 | 0.609 | 0.571 |
| 7 | 5222.000 | 5265.351 | 0.766 | 0.679 |
| 8 | 5223.000 | 5254.127 | 0.890 | 0.703 |
| 9 | 5223.000 | 5244.060 | 0.987 | 0.763 |

## Notes

- IPCW weights floored at G >= 0.05; Brier self-normalised by the weights; AUC is the weighted Mann-Whitney statistic; intervals from 200 section bootstraps
- temporal split at 2026-07-20T00:00:00+00:00; training rows censored at the split
- 209612 test rows could not be followed to their horizon (a gap or the end of the data came first) and were not scored; see coverage by phase

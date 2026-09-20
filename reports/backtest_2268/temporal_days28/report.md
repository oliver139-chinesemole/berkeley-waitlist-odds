# Backtest: Fall 2026 temporal (days:28)

Split `temporal`, horizon `days:28`: 211446 training rows, 0 scored test rows, 0 test rows past their horizon at joining and 281918 whose follow-up ended before their horizon (neither scored).

## Coverage: test rows that could be followed to their horizon, by phase

| phase | n | observable | share_observable |
| --- | --- | --- | --- |
| adjustment | 23844 | 0 | 0.000 |
| after | 5800 | 0 | 0.000 |
| instruction | 66506 | 0 | 0.000 |
| phase2 | 185768 | 0 | 0.000 |

Every number here is produced by `python -m analysis.backtest`; nothing is edited by hand. `gain` is the baseline's Brier score minus the predictor's (positive is better) with a 95% section-bootstrap interval; `skill` is `1 - brier / brier_baseline`; `share_unknown` is the share of test rows censored before their horizon (weight 0 under IPCW); `share_fallback` is the share of rows the predictor could not cover and scored with the bucket baseline.

## Predictors

_none_

## By enrollment phase of the test rows

_none_

## By position bucket

_none_

## Calibration: dept

_none_

## Calibration: cox

_none_

## Calibration: site

_none_

## Notes

- IPCW weights floored at G >= 0.05; Brier self-normalised by the weights; AUC is the weighted Mann-Whitney statistic; intervals from 200 section bootstraps
- temporal split at 2026-07-20T00:00:00+00:00; training rows censored at the split
- 281918 test rows could not be followed to their horizon (a gap or the end of the data came first) and were not scored; see coverage by phase
- too few scored rows (0); need 50

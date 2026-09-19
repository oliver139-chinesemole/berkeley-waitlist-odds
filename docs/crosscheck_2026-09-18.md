# Cross-check: classes.berkeley.edu vs Berkeleytime GetClass, Fall 2026

Run at 2026-09-18 20:48:26 UTC by `probe/crosscheck_berkeleytime.py`. Counts are enrolled/waitlisted/maxEnroll/maxWaitlist. Berkeleytime is at most 15 minutes old, so differences of a few seats are drift, not error; differences over 10 seats are flagged. A section Berkeleytime does not index (or that failed to fetch) is listed as `error`, excluded from the comparison, and replaced by the next candidate.

- compared: **20** sections (21 attempted)
- agree exactly: **20/20**
- within 15-minute drift (<= 10 seats): **0/20**
- disagree (> 10 seats): **0/20**
- could not compare (excluded): **1**

| # | section | id | site enr/wl/cap/wlcap | berkeleytime enr/wl/cap/wlcap | max diff | verdict | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | AEROENG 1 SEM 001 | 30013 | 62/0/70/0 | 62/0/70/0 | 0 | agree |  |
| 2 | AEROENG 10 LEC 001 | 30174 | 60/0/64/15 | 60/0/64/15 | 0 | agree |  |
| 3 | AEROENG 100 LEC 001 | 30590 | 17/0/45/20 | 17/0/45/20 | 0 | agree |  |
| 4 | AEROENG 122 LEC 001 | 34575 | 26/0/35/10 | 26/0/35/10 | 0 | agree |  |
| 5 | AEROENG C124 LEC 01 | 34205 | 12/0/24/5 | 12/0/24/5 | 0 | agree |  |
| 6 | AEROENG C136 LEC 01 | 32487 | 7/0/10/10 | 7/0/10/10 | 0 | agree |  |
| 7 | AEROENG C136S LAB 201 | 32489 | 2/0/30/30 | 2/0/30/30 | 0 | agree |  |
| 8 | AEROENG C162 LEC 001 | 30198 | 36/0/45/20 | 36/0/45/20 | 0 | agree |  |
| 9 | AEROENG C166 LEC 001 | 30420 | 24/0/35/25 | 24/0/35/25 | 0 | agree |  |
| 10 | AEROENG C193P LEC 001 | 30581 | 4/4/25/15 | 4/4/25/15 | 0 | agree |  |
| 11 | AEROENG 198 GRP 3 | 34946 | 18/0/25/5 | - | - | error | berkeleytime: sectionId not found in GetClass |
| 12 | AEROSPC 1A LEC 001 | 21802 | 9/0/60/2 | 9/0/60/2 | 0 | agree |  |
| 13 | AEROSPC 1A LEC 002 | 24252 | 2/0/25/2 | 2/0/25/2 | 0 | agree |  |
| 14 | AEROSPC 2A LEC 001 | 21801 | 12/0/35/1 | 12/0/35/1 | 0 | agree |  |
| 15 | AEROSPC 2A LEC 002 | 24253 | 2/0/30/1 | 2/0/30/1 | 0 | agree |  |
| 16 | AEROSPC 100 LAB 001 | 21555 | 22/0/68/2 | 22/0/68/2 | 0 | agree |  |
| 17 | AEROSPC 135A SEM 001 | 21556 | 16/0/25/2 | 16/0/25/2 | 0 | agree |  |
| 18 | AFRICAM R1B LEC 001 | 23475 | 17/1/18/4 | 17/1/18/4 | 0 | agree |  |
| 19 | AFRICAM 5A LEC 001 | 21560 | 98/1/95/0 | 98/1/95/0 | 0 | agree |  |
| 20 | AFRICAM 10A REC 001 | 25443 | 6/0/10/2 | 6/0/10/2 | 0 | agree |  |
| 21 | AFRICAM 11A REC 001 | 21551 | 12/0/12/2 | 12/0/12/2 | 0 | agree |  |

# Cross-check: classes.berkeley.edu vs Berkeleytime GetClass, Fall 2026

Run at 2026-09-23 22:30:42 UTC by `probe/crosscheck_berkeleytime.py`. Counts are enrolled/waitlisted/maxEnroll/maxWaitlist. Berkeleytime is at most 15 minutes old, so differences of a few seats are drift, not error; differences over 10 seats are flagged. A section Berkeleytime does not index (or that failed to fetch) is listed as `error`, excluded from the comparison, and replaced by the next candidate.

- compared: **20** sections (26 attempted)
- agree exactly: **20/20**
- within 15-minute drift (<= 10 seats): **0/20**
- disagree (> 10 seats): **0/20**
- could not compare (excluded): **6**

| # | section | id | site enr/wl/cap/wlcap | berkeleytime enr/wl/cap/wlcap | max diff | verdict | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | COMPSCI 10 LEC 001 | 29122 | 173/0/185/40 | 173/0/185/40 | 0 | agree |  |
| 2 | COMPSCI 152 LEC 001 | 32048 | 141/0/160/40 | 141/0/160/40 | 0 | agree |  |
| 3 | COMPSCI 152 DIS 107 | 34724 | 0/0/1/0 | - | - | error | berkeleytime: ParseError: GetClass: no class for COMPSCI 152 107 (Fall 2026) |
| 4 | COMPSCI 152 DIS 108 | 34725 | 0/0/1/0 | - | - | error | berkeleytime: ParseError: GetClass: no class for COMPSCI 152 108 (Fall 2026) |
| 5 | COMPSCI 152 LAB 999L | 34580 | 141/0/160/40 | - | - | error | berkeleytime: ParseError: GetClass: no class for COMPSCI 152 999L (Fall 2026) |
| 6 | COMPSCI 160 LEC 001 | 30511 | 74/0/77/0 | 74/0/77/0 | 0 | agree |  |
| 7 | COMPSCI 160 DIS 103 | 34664 | 24/0/26/0 | - | - | error | berkeleytime: ParseError: GetClass: no class for COMPSCI 160 103 (Fall 2026) |
| 8 | COMPSCI 161 LEC 001 | 29080 | 201/0/260/300 | 201/0/260/300 | 0 | agree |  |
| 9 | COMPSCI 162 LEC 001 | 29172 | 197/0/220/150 | 197/0/220/150 | 0 | agree |  |
| 10 | COMPSCI 164 LEC 001 | 29440 | 93/0/118/200 | 93/0/118/200 | 0 | agree |  |
| 11 | COMPSCI 168 LEC 001 | 28960 | 375/0/394/500 | 375/0/394/500 | 0 | agree |  |
| 12 | COMPSCI 169A LEC 001 | 30514 | 104/0/120/80 | 104/0/120/80 | 0 | agree |  |
| 13 | COMPSCI 170 LEC 001 | 29114 | 302/0/360/300 | 302/0/360/300 | 0 | agree |  |
| 14 | COMPSCI 171 LEC 001 | 32146 | 43/0/104/20 | 43/0/104/20 | 0 | agree |  |
| 15 | COMPSCI 180 LEC 001 | 30495 | 209/1/214/150 | 209/1/214/150 | 0 | agree |  |
| 16 | COMPSCI 184 LEC 001 | 32147 | 85/0/140/20 | 85/0/140/20 | 0 | agree |  |
| 17 | COMPSCI 186 LEC 001 | 29984 | 231/0/267/150 | 231/0/267/150 | 0 | agree |  |
| 18 | COMPSCI 188 LEC 001 | 29087 | 453/0/545/175 | 453/0/545/175 | 0 | agree |  |
| 19 | COMPSCI 189 LEC 001 | 29078 | 519/68/520/300 | 519/68/520/300 | 0 | agree |  |
| 20 | COMPSCI 189 DIS 115 | 34607 | 0/0/1/0 | - | - | error | berkeleytime: ParseError: GetClass: no class for COMPSCI 189 115 (Fall 2026) |
| 21 | COMPSCI 189 DIS 116 | 34608 | 0/0/1/0 | - | - | error | berkeleytime: ParseError: GetClass: no class for COMPSCI 189 116 (Fall 2026) |
| 22 | COMPSCI 194 LEC 061A | 34649 | 62/0/80/10 | 62/0/80/10 | 0 | agree |  |
| 23 | COMPSCI 194 LEC 244 | 32394 | 7/0/15/10 | 7/0/15/10 | 0 | agree |  |
| 24 | COMPSCI 194 LEC 245 | 32395 | 0/0/5/10 | 0/0/5/10 | 0 | agree |  |
| 25 | COMPSCI 194 LEC 302 | 15113 | 13/0/16/10 | 13/0/16/10 | 0 | agree |  |
| 26 | COMPSCI 252A LEC 001 | 32050 | 20/0/29/10 | 20/0/29/10 | 0 | agree |  |

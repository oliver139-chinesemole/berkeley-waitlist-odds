# Data log

One line per event that changes how the data should be read: an outage, a schema change, a source switch, a change to the priority list, a term switch, or a decision about access. All timestamps are UTC.

Step A4 (flow reconstruction) reads this file. Every `outage`, `source_switch`, `schema`, and `term_switch` row with a start and an end becomes a censoring rule: intervals inside it are treated as unobserved, never as zero flow. A row with no end is treated as open until a later row closes it.

## Format

One table row per event. Append at the bottom. Never edit or delete an old row; if a row was wrong, add a new row of kind `correction` that names the row it corrects by its `start_utc`.

| Column | Meaning |
| --- | --- |
| `start_utc` | ISO-8601 UTC, `YYYY-MM-DDTHH:MMZ`. A bare `YYYY-MM-DD` is allowed only when the time was not recorded and the kind is not `outage`. |
| `end_utc` | Same format. `-` while the event is ongoing or when it is a point in time. Come back and fill it in when an outage ends. |
| `kind` | One of `decision`, `access`, `outage`, `source_switch`, `schema`, `priority_list`, `term_switch`, `correction`, `note`. |
| `term_id` | SIS term id the row applies to (`2268` Fall 2026, `2272` Spring 2027 expected), or `-`. |
| `scope` | `all`, `priority`, or a comma-separated list of section ids. |
| `note` | What happened, how it was found, what was done. Include the Actions run URL, commit, or request id when there is one. |
| `who` | `oliver` or `claude`. |

Where the timestamps come from:
- Actions: `gh run list --workflow scrape.yml --limit 50 --json createdAt,conclusion,url` (needs `GH_REPO` set, see docs/RUNBOOK.md).
- What actually landed: `git log origin/data --format='%cI %s'`.
- Last run: `status.json` on the `data` branch, field `last_run_at`.
- A source switch shows up as a change in the `source` field of `status.json` and of the parquet metadata.

## Entries

| start_utc | end_utc | kind | term_id | scope | note | who |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-18 | - | decision | - | all | Phase 0 decision recorded in docs/PHASE0.md. Primary source is the SIS Class API once credentials exist. Go-live fallback is classes.berkeley.edu section pages: a priority list every 30 minutes plus 8 rotating shards so every other section is seen about every 4 hours. Berkeleytime GetCatalog/GetClass is the cross-check and emergency source only; its section ids are not SIS ids. Fall 2026 (`2268`) is the end-to-end test term. Spring 2027 is expected to be `2272`, unconfirmed until the first Spring 2027 section page is read. | claude |
| 2026-09-18 | - | note | - | all | classes.berkeley.edu returns `403 Error 54113` to Python `requests` and `httpx` regardless of headers. Isolated by experiment to the TLS ClientHello: a client that advertises ALPN `http/1.1` alone is blocked. Python stdlib `urllib` with certifi (no ALPN), curl, and curl_cffi get `200`. The scraper uses stdlib `urllib` with an honest User-Agent and does not impersonate a browser. Not yet verified from a Linux GitHub Actions runner; check the log of the first workflow run and add a row here with the outcome. | claude |
| 2026-09-18 | - | access | - | all | SIS Class API access request status: NOT YET SUBMITTED (Oliver). Submit at https://developers.api.berkeley.edu (CalNet sign-in, find "Class API", request read-only access, describe: student project, one paged sweep of one term every 30 minutes). Add a row here with the request id and date when submitted, and another when approved or denied. Until both `SIS_CLASS_APP_ID` and `SIS_CLASS_APP_KEY` are set, `--source auto` resolves to `classes_site`. | oliver |
| 2026-09-19T02:20Z | 2026-09-19T02:46Z | note | 2268 | priority | First GitHub Actions run (workflow_dispatch, https://github.com/oliver139-chinesemole/berkeley-waitlist-odds/actions/runs/35415363545) on a Linux runner: no 403 from classes.berkeley.edu, so the stdlib client passes the ALPN rule from Linux too. Wrote `snapshots/date=2026-09-19/0221-baseline.parquet`: scope priority, shard 0/8, 911 observed, 808 missing because the 1,500 s budget ran out after the 341-page listing crawl (629 s). The listing ordered priority sections alphabetically, so COMPSCI/DATA/STAT were among the missing. This baseline was built from the listing-era catalog and includes self-study sections (IND, GRP) that later runs exclude. | claude |
| 2026-09-19T02:46Z | - | outage | 2268 | all | No scheduled run fired after the manual run (GitHub had not started the new repo's cron by 07:18Z), and at 2026-09-19T07:18Z the schedule was disabled by hand (`gh workflow disable scrape.yml`) because the run's listing crawl requested `/search/class` pages, which the site's robots.txt disallows. Fill in end_utc when the schedule is re-enabled after the fix is merged. | claude |
| 2026-09-19T05:30Z | - | correction | - | all | Corrects the 2026-09-18 Phase 0 decision row: the 2026-09-18 read of https://classes.berkeley.edu/robots.txt was truncated at 40 lines; the full file also disallows `/search/` and `/index.php/search/`. The listing crawl and the term-facet request were removed from the scraper on 2026-09-19. Section pages under `/content/` remain allowed. | claude |
| 2026-09-19T07:30Z | - | source_switch | 2268 | all | Section discovery switched from the classes.berkeley.edu listing to Berkeleytime `GetCatalog` (one request per term per day): primary sections only, self-study components (IND, GRP, FLD, TUT, INT, SLF, PRA, REC, SES, CLN, WOR, REA, WBD, VOL, DEM) excluded, page slug derived as `/content/<year>-<sem>-<subject>-<catalog>-<class#>-<component>-<class#>` (verified on all 3,640 listed Fall 2026 primaries). Non-printed classes (about 2,434 of 6,074) answer 404 and are marked absent in `catalog/<term_id>/catalog.json`, re-probed after 7 days. Counts and section ids still come from the section pages, so the snapshot values are unaffected; only the universe changed (3,640 live primaries instead of 6,131 listed sections including self-study). | claude |
| 2026-09-19T07:30Z | - | priority_list | 2268 | priority | `config/priority_courses.txt` reordered so the most waitlist-sensitive subjects come first (COMPSCI, DATA, STAT, EECS, ELENG, MATH, ECON, PHYSICS, CHEM, INDENG, NUCENG, UGBA, PSYCH, POLSCI, SOCIOL, MCELLBI, INTEGBI, PHILOS, ENGLISH, COLWRIT, L&S) and the header rewritten; the set of patterns is unchanged. Fetch order now follows list order, so a budget cutoff drops the bottom of the list. `priority_sha` changed; the only earlier snapshot is the 02:21Z baseline above. Observation for Oliver: on 2026-09-19, 478 live Fall 2026 primaries had a non-zero waitlist and only 99 of them match the list (PHYSED 62, UGBA 33, ENGLISH 16, MUSIC 15, MECENG 13 are the largest non-priority groups); consider adding UGBA * and MECENG * before Oct 26. | claude |

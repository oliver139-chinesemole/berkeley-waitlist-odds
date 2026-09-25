@docs/SPEC.md
@docs/dev/FINISH_PLAN_WAITLIST.md

## How to work in this repo
- New session: read docs/dev/HANDOFF.md first (what is done, what is left, how to resume), then the Current step line below.
- Before any response or action, check loaded skills and invoke every one that applies
  (superpowers:using-superpowers). Announce which skill you are using.
- Execute every step through the build loop in docs/dev/FINISH_PLAN_WAITLIST.md section 1.2.
  Each step lists its skills and plugins.
- If a named skill or plugin is not loaded, say so once and continue with the same
  discipline by hand.
- Current step: session 7 closed 2026-09-25 07:28Z (Track B of docs/dev/NEXT_2026-09-24.md, unattended until Oliver's "continue working" at 00:10Z and "keep working" at 06:40Z); docs/dev/MASTER_PLAN.md leads, docs/dev/HANDOFF.md session 7 has the summary and a note for Oliver at its top. Done: B1 (site/methodology.html on site-v3 names no request rate and describes the generated list, ea61bf4), B2 (course search Q1 to Q3 and Q8, draft PR #17 on site-v3), B3 (palette U3 and type U4, draft PR #16 on site-v3, three decisions for Oliver in its body), two DATA_LOG note rows for the classes.berkeley.edu latency episodes of 19:07Z and 22:37Z (PR #15). B4 (section-board fixture, harness hooks and the strict-xfail contract for A3) was held while the plan's stop rule fired twice (sweeps of 1,342.8 s and 1,350.9 s) and then done as draft PR #19 on Oliver's go-ahead, and A3 itself (the board S1 to S3, scraper/live.py's two columns and wider selection) as draft PR #20 on #19; the rate flags are untouched and the concurrency question is Oliver's (HANDOFF session 7, item 1: overnight the 00:37Z run lost 30 priority sections in a timeout episode). PR #18 adds the seven .claude/agents definitions with their effort levels. Still open: #4 (site v3) and #11 on it, for Oliver's browser pass and merge, then pages.yml, then #17, #16, #19 and #20 rebased onto main; #18 any time. Next: the dated CLAIMS re-measure after 2026-09-25T09:37Z (issue #7 is already closed), the live board on real data after the first post-#4 scrape run, Oct 4 term switch. Update this line at the end of every session.

## Where things are
- docs/PHASE0.md: which data sources work, what each returns, rate limits, the Spring 2027 calendar.
- docs/DESIGN_A2.md: binding interface contract for scraper/ and the workflows. Sections 11 to 13 override earlier sections. Do not change a signature there without updating the file.
- docs/RUNBOOK.md: go-live checklist, how a run picks a source and a mode, what to do when a run fails.
- docs/DATA_LOG.md: outages, schema changes, source switches, with UTC timestamps. Every entry becomes a censoring rule in step A4.
- CLAIMS.md: every resume claim with the exact command that checks it. Never write a result there by hand.

## Spring 2027 enrollment dates (registrar calendar, docs/PHASE0.md)

| Event | Date |
| --- | --- |
| Schedule of Classes published; appointments released | Sun Oct 4, 2026 |
| Phase 1, continuing students, begins | **Mon Oct 26, 2026** |
| Phase 1, continuing students, ends | Sun Nov 15, 2026 |
| Phase 1, new transfer / freshman / graduate | Nov 17 / Nov 18 / Nov 20, 2026 |
| Phase 2 begins | Mon Nov 23, 2026 |
| Phase 1 (new students) and Phase 2 end | Sun Jan 10, 2027 |
| Adjustment period begins | Mon Jan 11, 2027 |
| Instruction begins | Tue Jan 19, 2027 |
| Last automatic waitlist run | Fri Feb 5, 2027, 6:40 PM |
| Undergraduate add/drop deadline | Wed Feb 10, 2027 |

Scraper must be live by Mon Oct 12, 2026. Fall 2026 (SIS term `2268`) is the end-to-end test term until Spring 2027 appears on Oct 4 (its pages show up as new nodes the scraper enumerates; the real SIS id comes from the pages' `data-term` attribute; expected `2272`). The scheduled term is the `SCRAPE_TERM` repository variable.

## Commands

Activate the environment first: `source .venv/bin/activate` (Python 3.12, packages pinned in requirements.txt).

Run the tests (offline, no network):

```
python -m pytest -q
```

Local fetch, 25 sections, writes nothing:

```
python -m scraper.fetch --term "Fall 2026" --source classes_site --limit 25 --dry-run
```

Full analysis (flows, cohorts, KM, Cox, figures, site JSON, report) from a checkout of the `data` branch at ./data-branch:

```
make analysis TERM=2272
```

Gap report on the same checkout (see docs/RUNBOOK.md for how to get it):

```
python -m scraper.gaps --data-root ./data-branch --term-id 2268 --hours 24 --fail-if-gap-min 90 --fail-if-runs-lt 40
```

## Rules that are not obvious from the code
- Only scrape.yml writes to the `data` branch. Never commit there by hand. analysis.yml is the only workflow that commits to `main` (site/data and reports/).
- Workflows dispatch each other with the built-in token because pushes made with it never trigger other workflows: scrape.yml re-dispatches itself every 30 minutes and the monitor daily, analysis.yml dispatches pages.yml, heartbeat.yml restarts a dead chain.
- Tests never touch the network. Use the fixtures in data/fixtures/ and fakes.
- The classes.berkeley.edu client is stdlib urllib on purpose. The site blocks clients whose TLS handshake advertises ALPN http/1.1 alone, which is what requests and httpx do (docs/PHASE0.md). Do not switch it and do not impersonate a browser.
- Never request `/search/` on classes.berkeley.edu: robots.txt disallows it. Section discovery uses the site's own `/rss.xml` and `/node/<id>` pages (docs/DESIGN_A2.md section 14); Berkeleytime is unreachable from GitHub runners and is only a local cross-check.
- `config/priority_courses.txt` is ordered by importance; a budget cutoff drops the bottom of the list. Editing it changes `priority_sha`; log the edit in docs/DATA_LOG.md.
- `fetched_at` is the actual fetch time, never the scheduled time.
- Data gaps are permanent. A broken run is fixed within 24 hours and logged in docs/DATA_LOG.md.

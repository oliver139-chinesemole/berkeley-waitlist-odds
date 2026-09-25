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
- Current step: session 9 closed 2026-09-25 19:45Z (docs/dev/NEXT_SITE_2026-09-25.md, Track B, unattended); docs/dev/MASTER_PLAN.md leads, docs/dev/STATUS.md section 3 has every open PR with its state, docs/dev/HANDOFF.md session 9 has the note for Oliver at its top. Done: CLAIMS scraper rows re-measured (PR #21); main merged into site-v3 so PR #4 is MERGEABLE again (a3e0f21 + 5325cbc); #11, #17, #16, #19, #20 rebased onto it with green CI and proven to merge in order (388 tests); follow-up PRs, each reviewed and approved: #22 design, #23 board, #24 search, #25 cross-listing, #26 fallback ladder, #27 live status line, #28 titles exporter, #29 title search, #30 department pages, #31 U8 audit. Nothing merged, no rate-flag change; one latency episode logged (18:07Z). Next: Oliver merges in STATUS section 3's order (#15 with the session 9 docs PR, #18, #21; #4, #11, pages.yml; #17, #16, #19, #20; then the follow-ups rebased onto main), his decisions in HANDOFF session 9 item 2, his phone for the board (VoiceOver); before the Spring 2027 switch wire the catalog into analysis.run so titles.json survives the weekly run; Oct 4 term switch. Update this line at the end of every session.

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

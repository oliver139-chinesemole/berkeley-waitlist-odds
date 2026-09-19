# Phase 0 — Data route decision

Written 2026-09-18 from live probes (see `data/fixtures/` for the raw responses). Every endpoint and field below was observed, not guessed.

## Decision

| Rank | Source | Role | Status |
| --- | --- | --- | --- |
| 1 | **SIS Class API** (`https://gateway.api.berkeley.edu/sis/v1/classes/sections`) | Primary once credentials arrive. One full-term sweep is ~130–330 paged requests and finishes in minutes. Returns every field we need including seat reservations. | **Denied 2026-09-19:** API Central states it is not granting access to students at this time. The adapter stays in the code (`sis_api`) in case a faculty or ASUC sponsor opens it later; for Spring 2027 the classes.berkeley.edu route is the primary. `api-central.berkeley.edu` no longer resolves (NXDOMAIN); the portal is https://developers.api.berkeley.edu. |
| 2 | **classes.berkeley.edu section pages** | **Primary for Spring 2027** (the API is closed to students). No login. Each section page embeds the SIS `enrollmentStatus` JSON verbatim in `drupalSettings.ucb.enrollment`. | **Working now** with the Python stdlib client. See rate-limit notes; a full sweep is ~6,100 pages. |
| 3 | **Berkeleytime public GraphQL gateway** (`POST https://berkeleytime.com/api/graphql`, persisted operations only) | Cross-check of our counts, and a safety net. `GetCatalog(year, semester)` returns every class with the primary section's latest counts in one 12.5 MB response; `GetEnrollment` returns a section's full 15-minute history. | **Working now.** Third-party data; used to validate, not as the primary dataset. |

## Evidence

### Source 1: SIS Class API

- Swagger 2.0 spec (from Berkeleytime's vendored copy, `data/fixtures/sis_class_api_swagger.json`): host `gateway.api.berkeley.edu`, basePath `/sis`, scheme https.
- Endpoints: `GET /v1/classes/sections` with query params `term-id`, `page-number`, `page-size` (Berkeleytime uses `page-size=50` and fires 50 pages concurrently); `GET /v1/classes/sections/terms/{term-id}/updated/enrollments?updated-after=&updated-before=` (delta endpoint, worth testing once we have credentials).
- Auth: request headers `app_id` and `app_key` (confirmed in Berkeleytime `lib/sections.ts`). Unauthenticated requests return `403 Authentication failed`.
- Section fields we consume (SIS names): `id`, `number`, `component.code`, `status.code`, `class.number`, `class.course.subjectArea.code`, `class.course.catalogNumber.formatted`, `class.session.id`, `class.session.term.id`, `class.session.term.name`, `association.primary`, `enrollmentStatus.{status.code, enrolledCount, reservedCount, waitlistedCount, minEnroll, maxEnroll, maxWaitlist, openReserved, seatReservations[]}`.
- Term id convention: Fall 2026 is `2268` in Berkeleytime's data, so Spring 2027 should be `2272` (`2` + `27` + `2`). Confirm with the Terms API or the first Spring 2027 section page before hardcoding.

### Source 2: classes.berkeley.edu

- Listing: `GET /search/class?f[0]=term:<facet-id>&page=<n>` renders 18 sections per page (Fall 2026 facet `8588`, 6,131 sections, 341 pages), but **`/search/` is disallowed by robots.txt** (see below), so the scraper does not use it. The section universe comes from Berkeleytime's `GetCatalog` instead: every catalog class has a primary section whose page slug is `/content/<year>-<sem>-<subject>-<catalog>-<class#>-<component>-<class#>` (the section number of a primary section equals its class number; verified on all 3,640 listed Fall 2026 primaries, 0 exceptions). About 40% of catalog classes are not printed in the public schedule (MBA, EWMBA, LAW, non-printed seminars) and return 404; those slugs are remembered in `catalog/<term_id>/catalog.json` and re-probed after 7 days on the daily refresh run. Self-study components (IND, GRP, FLD, TUT, ...) are excluded: they never carry a waitlist.
- Section page: `GET /content/<year>-<sem>-<subject>-<catalog>-<class#>-<component>-<section#>` (for example `/content/2026-fall-aeroeng-10-001-lec-001`), ~27 KB. The `<script data-drupal-selector="drupal-settings-json">` blob contains `ucb.enrollment.available.enrollmentStatus` (live counts) and `ucb.enrollment.history` (same plus `seatReservations`). Fixture: `data/fixtures/classes_section_drupalsettings_ucb.json`.
- No JSON route exists: `?_format=json`, `/jsonapi`, `/section/<id>`, `/class/<id>` all 404 or 406.
- Spring 2027 is not on the site yet. The registrar publishes the Spring 2027 Schedule of Classes on **Oct 4, 2026**; the scraper detects the term through Berkeleytime's `GetCatalog(2027, Spring)` returning classes and confirms the SIS term id from the first section page's `data-term` attribute.
- robots.txt (full file read 2026-09-19; the 2026-09-18 read was truncated at 40 lines) disallows `/search/`, `/index.php/search/`, `/admin/`, `/user/*`, `/node/add/`, `/core/`, `/profiles/` and a few README files. `/content/` section pages are allowed. Discovery therefore never touches `/search/`.
- **Client fingerprint block:** the site sits behind Varnish and returns `403 Error 54113` to Python `requests` and `httpx` regardless of headers, but `200` to curl, `curl_cffi`, and the Python stdlib `urllib` with certifi. Isolated by experiment (2026-09-18): a stdlib SSL context passes with any cipher list and with TLS 1.2 only, and fails the moment it advertises ALPN `http/1.1` alone, which is exactly what urllib3 and httpx do. The rule keys on the ALPN extension, not on our User-Agent or on the OS, so a Linux GitHub Actions runner using stdlib `urllib` (no ALPN) is expected to pass; verify on the first workflow run. The scraper uses `urllib` with an honest User-Agent (`berkeley-waitlist-odds/<ver> (+mailto:oliver139@berkeley.edu)`) and does not impersonate a browser. If the site ever objects or blocks this too, stop and reassess per `docs/SPEC.md` Route B.
- Latency: 0.2–3.3 s per section page, mostly cache misses; about one page per second at the polite rate (1 request/s, 2 connections). The first Actions run (2026-09-19, Linux runner) confirmed the stdlib client passes the ALPN block and fetched 911 pages in 1,500 s. The universe is 3,640 live primary sections (Fall 2026), of which 702 match the priority list, so a run fetches the priority list plus one of 8 rotating shards (~370 pages): about 1,070 pages inside a 1,200 s budget. Priority sections are fetched in the order of the priority file, so a cutoff drops the least important first. Remainder cadence is 4 hours.

### Source 3: Berkeleytime

- Gateway accepts only `POST {"id": <sha256 of the operation document>, "variables": {...}}`; the ids live in `apps/backend/src/bootstrap/graphql/generated/persistedOperations.ts` in the public repo. Copied to `data/fixtures/berkeleytime_persisted_ops.json`.
- `GetTerms` lists Spring 2027 (session 1 starts 2027-01-19). `GetEnrollmentTimeframes(2027, Spring)` returns the same phase dates as the registrar calendar.
- `GetCatalog(2026, Fall)`: 15,842 classes, 46 s, 12.5 MB; each with `primarySection.enrollment.latest.{status, enrolledCount, maxEnroll, waitlistedCount, maxWaitlist}`.
- `GetClass` returns all sections of a class with `sectionId` and latest counts. `GetEnrollment` returns one section's history at 900 s granularity (COMPSCI 61A LEC 001, Fall 2026: 734 points since 2026-03-22).
- Implication for the resume story: Berkeleytime already holds a 15-minute enrollment and waitlist history, publicly queryable. The novelty of this project is the waitlist-clearing model and the lookup tool, not the raw snapshots. The README should say so.

## Spring 2027 enrollment dates (registrar Google Calendar, ICS in `data/fixtures/registrar_enrollment_calendar.ics`)

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

Scraper must be live by **Mon Oct 12, 2026** (two weeks before Phase 1). Fall 2026 (facet `8588`, SIS term `2268`) is used to test the pipeline end to end before then.

## Cross-check

20 sections must match between our parsed counts and Berkeleytime's `GetClass` latest counts at the same time. Script: `probe/crosscheck_berkeleytime.py`. Result is recorded in `CLAIMS.md` once run.

## Open items for Oliver

1. ~~Submit the SIS Class API access request~~ Done 2026-09-19: API Central does not grant access to students at this time. Optional: ask a faculty member or the ASUC OCTO Berkeleytime team to sponsor a request; until then the site route is the plan.
2. Decide whether a 4-hour full sweep from classes.berkeley.edu is acceptable as the fallback, or whether the fallback should be Berkeleytime's `GetCatalog` every 30 minutes (one request, primary sections only, third-party data).

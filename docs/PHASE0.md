# Phase 0 — Data route decision

Written 2026-09-18 from live probes (see `data/fixtures/` for the raw responses). Every endpoint and field below was observed, not guessed.

## Decision

| Rank | Source | Role | Status |
| --- | --- | --- | --- |
| 1 | **SIS Class API** (`https://gateway.api.berkeley.edu/sis/v1/classes/sections`) | Primary once credentials arrive. One full-term sweep is ~130–330 paged requests and finishes in minutes. Returns every field we need including seat reservations. | **Blocked on Oliver:** request access at https://developers.api.berkeley.edu (CalNet + Data Owner approval). `api-central.berkeley.edu` no longer resolves (NXDOMAIN). |
| 2 | **classes.berkeley.edu section pages** | Fallback and the source we go live with if credentials are not approved by Oct 12. No login. Each section page embeds the SIS `enrollmentStatus` JSON verbatim in `drupalSettings.ucb.enrollment`. | **Working now** with the Python stdlib client. See rate-limit notes; a full sweep is ~6,100 pages. |
| 3 | **Berkeleytime public GraphQL gateway** (`POST https://berkeleytime.com/api/graphql`, persisted operations only) | Cross-check of our counts, and a safety net. `GetCatalog(year, semester)` returns every class with the primary section's latest counts in one 12.5 MB response; `GetEnrollment` returns a section's full 15-minute history. | **Working now.** Third-party data; used to validate, not as the primary dataset. |

## Evidence

### Source 1: SIS Class API

- Swagger 2.0 spec (from Berkeleytime's vendored copy, `data/fixtures/sis_class_api_swagger.json`): host `gateway.api.berkeley.edu`, basePath `/sis`, scheme https.
- Endpoints: `GET /v1/classes/sections` with query params `term-id`, `page-number`, `page-size` (Berkeleytime uses `page-size=50` and fires 50 pages concurrently); `GET /v1/classes/sections/terms/{term-id}/updated/enrollments?updated-after=&updated-before=` (delta endpoint, worth testing once we have credentials).
- Auth: request headers `app_id` and `app_key` (confirmed in Berkeleytime `lib/sections.ts`). Unauthenticated requests return `403 Authentication failed`.
- Section fields we consume (SIS names): `id`, `number`, `component.code`, `status.code`, `class.number`, `class.course.subjectArea.code`, `class.course.catalogNumber.formatted`, `class.session.id`, `class.session.term.id`, `class.session.term.name`, `association.primary`, `enrollmentStatus.{status.code, enrolledCount, reservedCount, waitlistedCount, minEnroll, maxEnroll, maxWaitlist, openReserved, seatReservations[]}`.
- Term id convention: Fall 2026 is `2268` in Berkeleytime's data, so Spring 2027 should be `2272` (`2` + `27` + `2`). Confirm with the Terms API or the first Spring 2027 section page before hardcoding.

### Source 2: classes.berkeley.edu

- Listing: `GET /search/class?f[0]=term:<facet-id>&page=<n>`; 18 sections per page; Fall 2026 facet id is `8588` with 6,131 sections across 341 pages. The listing row shows only "N Unreserved Seats", not waitlist counts.
- Section page: `GET /content/<year>-<sem>-<subject>-<catalog>-<class#>-<component>-<section#>` (for example `/content/2026-fall-aeroeng-10-001-lec-001`), ~27 KB. The `<script data-drupal-selector="drupal-settings-json">` blob contains `ucb.enrollment.available.enrollmentStatus` (live counts) and `ucb.enrollment.history` (same plus `seatReservations`). Fixture: `data/fixtures/classes_section_drupalsettings_ucb.json`.
- No JSON route exists: `?_format=json`, `/jsonapi`, `/section/<id>`, `/class/<id>` all 404 or 406.
- Spring 2027 term facet does not exist yet. The registrar publishes the Spring 2027 Schedule of Classes on **Oct 4, 2026**; the scraper must discover the facet id from the listing page rather than hardcode it.
- robots.txt disallows only `/core/`, `/profiles/`, `/README.md`. `/content/` and `/search/` are allowed.
- **Client fingerprint block:** the site sits behind Varnish and returns `403 Error 54113` to Python `requests` and `httpx` regardless of headers, but `200` to curl, `curl_cffi`, and the Python stdlib `urllib` with certifi. The block keys on the TLS cipher list urllib3 uses, not on our User-Agent. The scraper uses `urllib` with an honest User-Agent (`berkeley-waitlist-odds/<ver> (+mailto:oliver139@berkeley.edu)`) and does not impersonate a browser.
- Latency: 0.2–3.3 s per section page, mostly cache misses. At 1 request/s a full 6,100-page sweep is ~1.7 hours, so a 30-minute cadence for the whole catalog is not possible from this source. Design: a **priority list** (impacted CS/DATA/STAT/EECS/popular breadths, ~600–900 sections) every 30 minutes, plus a full sweep of all sections every 4 hours. Sweep time, rate, and priority list are configurable.

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

1. Submit the SIS Class API access request at https://developers.api.berkeley.edu (sign in with CalNet, find "Class API", request access, describe: student project, read-only, one paged sweep of one term every 30 minutes). Save the request id in `docs/DATA_LOG.md`.
2. Decide whether a 4-hour full sweep from classes.berkeley.edu is acceptable as the fallback, or whether the fallback should be Berkeleytime's `GetCatalog` every 30 minutes (one request, primary sections only, third-party data).

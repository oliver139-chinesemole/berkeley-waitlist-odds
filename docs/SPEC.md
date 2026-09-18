# Project Spec: Berkeley Waitlist Odds — Enrollment Scraper + Survival Analysis

**Owner:** Oliver Guo (UC Berkeley, Applied Math + Statistics, class of 2028)
**Purpose:** Portfolio project for summer 2027 analytics/data science internship applications
**Status:** Not started. HARD DEADLINE: the scraper must be live before Spring 2027 Phase 1 enrollment opens (mid-to-late October 2026). The dataset only exists if collection is running — it cannot be backfilled.
**Budget constraint:** $0 recurring cost. Everything runs on free tiers (GitHub Actions, GitHub Pages).

## Instructions for an AI assistant reading this document

This spec is complete enough to implement from. When helping Oliver:

1. Work through phases in order; each phase has acceptance criteria — do not move on until they pass.
2. Oliver knows Python (pandas, NumPy) and R (dplyr, ggplot2 from STAT 133). Default to Python for the scraper and either language for analysis.
3. Do not invent API endpoints. Phase 0 discovers the real data access route; everything downstream depends on what Phase 0 finds.
4. Keep architecture zero-recurring-cost. No paid databases, no always-on servers. If you propose infrastructure, it must be free at this project's scale.
5. Oliver writes the resume bullets and Reddit post himself — draft them with him, don't ghostwrite silently.

## 1. Project summary

**One sentence:** Continuously snapshot UC Berkeley course enrollment and waitlist counts during an enrollment cycle, then model the probability and timing of a waitlist spot clearing, and publish a lookup tool for students.

**Why this project (context for the AI):**
- [Berkeleytime](https://berkeleytime.com) already shows enrollment-over-time charts, so a plain enrollment tracker is redundant. The gap is *waitlist clearing odds*: "you're #12 on the waitlist — how likely are you to get in, and by when?" Nobody publishes this.
- The high-frequency snapshot dataset is a moat: it only exists if someone collects it in real time during an enrollment cycle.
- Survival analysis (Kaplan–Meier, Cox proportional hazards) is the statistically correct tool and showcases Oliver's applied-math/stats major — it's not what a typical CS student would reach for.
- Real users (Berkeley students during the enrollment scramble) turn this from a toy into a product with a measurable-usage resume bullet.

**Target resume bullets (drafts — final numbers filled in after launch):**
- "Built a zero-cost data pipeline (Python, GitHub Actions, Parquet) capturing 30-minute snapshots of enrollment and waitlist counts for ~X,000 Berkeley course sections across a full enrollment cycle (~Y million rows)"
- "Modeled waitlist-clearing dynamics with Kaplan–Meier estimators and Cox proportional hazards regression; published a lookup tool used by N students during Spring 2027 enrollment"

## 2. Timeline

| When | Milestone |
|---|---|
| Sept 2026 | Phase 0 (data access) + Phase 1 (scraper MVP) done; scraper running in production |
| Oct 2026 | Spring 2027 Phase 1 enrollment opens — scraper must be capturing. Phase 2 (data quality) hardening |
| Nov–Dec 2026 | Phase 2 continues through Phase 2 enrollment; start Phase 3 (analysis) on partial data |
| Early Jan 2027 | Phase 4 (site) built; launch (Phase 5) at the start of the January adjustment period, when waitlist anxiety peaks |
| Feb 2027 | Final write-up, README polish, resume bullets with real numbers |

Check the actual Spring 2027 enrollment dates on the [Office of the Registrar's enrollment calendar](https://registrar.berkeley.edu/registration/enrollment/) and put the scraper-live deadline 2 weeks before Phase 1 opens.

## 3. Phase 0 — Data access (do this first; everything depends on it)

Goal: one working method that returns, for every (or many) course sections in a term: section ID, course name, enrolled count, enrollment cap, waitlist count, waitlist cap, section status.

Try these routes in order:

**Route A — Official SIS APIs via API Central (preferred).**
UC Berkeley exposes a Class API, Course API, and Term API through [API Central](https://api-central.berkeley.edu/apis) (run by Engineering & Integration Services). Requests are authenticated with a client ID + secret key pair and rate limited. The [Student API listing](https://api-central.berkeley.edu/api/29) is a starting point. Berkeleytime itself pulls from these APIs ([their data docs](https://docs.berkeleytime.com/core/data/index.html) confirm the three APIs and the auth model).
- Action: sign in to API Central with CalNet, look for the Class API, and request credentials. In the request, describe the project honestly (student data project analyzing waitlist dynamics, ~1 request/section-batch/30min, read-only).
- If credentials are granted, this is the route. Respect the rate limits they state.

**Route B — classes.berkeley.edu (fallback).**
The public class schedule at [classes.berkeley.edu](https://classes.berkeley.edu) displays enrollment and waitlist counts without login. It is a dynamic site, so:
- Open browser devtools → Network tab → filter XHR/fetch while searching for a class. Identify the JSON endpoint(s) the page calls, their parameters, and pagination.
- Reproduce those calls in Python `requests`. Verify the JSON contains enrolled/max/waitlist fields per section.
- Check `https://classes.berkeley.edu/robots.txt` and comply with it. Throttle to ≤1 request/second, set a User-Agent identifying the project with a contact email, cache aggressively, and scrape during off-peak hours where possible. Public, login-free, factual data at polite rates is standard practice, but stop and reassess if the site blocks or objects.

**Route C — read Berkeleytime's open-source code for reference.**
The [Berkeleytime repo](https://github.com/asuc-octo/berkeleytime) (see the datapuller/backend packages) shows exactly how a student org consumes the SIS APIs — field names, term/section ID conventions, update strategies. Read it before designing the schema regardless of which route wins. Do not copy code wholesale; it's a reference for conventions.

**Acceptance criteria:** a standalone script `probe.py` that fetches ≥100 sections for the current term and prints section_id, course, enrolled, enrolled_max, waitlist, waitlist_max. Decision recorded in the README: which route, what rate limit, what auth.

**Scope decision to make here:** all ~10k sections vs. a subset. Preference: all sections if one full sweep fits within rate limits at a 30-minute cadence; otherwise all sections at 2–4 hour cadence + a high-priority list (top ~500 chronically waitlisted courses: CS, Data, Stat, EECS, popular breadths) at 30-minute cadence.

## 4. Phase 1 — Scraper MVP

**Architecture (zero-cost):**
- Python 3.11+, `requests` + `tenacity` (retries with exponential backoff), `pandas`/`pyarrow`.
- Scheduler: [GitHub Actions scheduled workflow](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule) (`cron: "*/30 * * * *"` — note Actions cron has jitter/occasional skips; that's acceptable, snapshots are timestamped). Free tier is 2,000 min/month for private repos and unmetered for public repos — make the repo public.
- Storage: append-only Parquet files committed to the repo, partitioned by date (`data/snapshots/date=2026-10-15/HHMM.parquet`). At ~10k sections × 48 snapshots/day this stays well within GitHub limits if columns are compact (ints + short strings, snappy compression). If a file approaches 50 MB/day, reduce columns or gzip. Alternative: a single SQLite file has merge-conflict problems with concurrent commits — prefer Parquet-per-run.
- Each run: fetch → normalize → write one Parquet → `git commit && push` from the workflow.

**Snapshot schema (one row per section per snapshot):**
`ts_utc, term_id, session_id, subject, catalog_number, section_number, section_id (primary key within term), component (LEC/DIS/LAB), instruction_mode, enrolled_count, enrolled_max, waitlist_count, waitlist_max, section_status (open/closed/waitlisted)`

**Operational requirements:**
- Idempotent runs; a failed run writes nothing partial.
- On HTTP failure: retry ×3 with backoff, then log and exit 0 for transient issues but exit 1 (failing the workflow, which emails Oliver) if an entire sweep returns no data — silent death is the project-killing risk.
- A `HEARTBEAT.md` or badge showing last successful run, so a glance at the repo confirms it's alive.
- Unit tests for the parser against saved fixture responses (site/API changes should break tests, not silently corrupt data).

**Acceptance criteria:** 7 consecutive days of snapshots in the repo with no gaps > 2 hours; a notebook loads a full day and plots enrolled_count over time for one course.

## 5. Phase 2 — Data quality and event reconstruction

This is the intellectually serious part. **Key limitation to design around:** the data is *aggregate* waitlist counts, not individual positions. You never observe "student at position #12 cleared." You observe count trajectories, and individual-level quantities must be reconstructed under stated assumptions. Be explicit about this in all write-ups.

**Reconstruction logic:**
- Waitlist count changes conflate three flows: joins (+1), voluntary drops (−1), and admits into the class (−1, usually paired with enrolled_count +1 while enrolled ≤ cap).
- Between consecutive snapshots, estimate admits ≈ max(0, Δenrolled) when the section was at/near cap and waitlist declined; treat other waitlist declines as drops. FIFO waitlist assumption (Berkeley waitlists are ordered, subject to reserved-seat categories): a person who joins at position k clears when cumulative admits since their join ≥ k.
- Define the survival object: for a *hypothetical* joiner at position k on day d, time-to-clear = first time cumulative admits ≥ k; right-censored at the enrollment deadline / add deadline if never reached.
- Validate: enrolled_count should never exceed enrolled_max by much (reserved seats cause small anomalies — document them); flag sections with impossible flows; quantify snapshot gaps.

**Acceptance criteria:** a documented `events.py` that converts raw snapshots into per-section flow series (admits, joins, drops per interval) with a validation report (% of sections with anomalies), plus written assumptions in `METHODS.md`.

## 6. Phase 3 — Survival analysis

- **Kaplan–Meier curves** of time-to-clear, stratified by department, course level (lower/upper div), and position-bucket (1–5, 6–10, 11–20, 20+). Python: [lifelines](https://lifelines.readthedocs.io/). R alternative: `survival` + `survminer`.
- **Cox proportional hazards** for clearing hazard with covariates: initial position ÷ class size, department, course level, days-until-semester-start at join, enrollment phase, section capacity. Check the PH assumption (Schoenfeld residuals); if violated (likely — clearing hazard spikes at the drop deadline), use stratified Cox or piecewise models and say so.
- Headline outputs: for a course × position, P(clear by first lecture), P(clear by add deadline), median days-to-clear.
- Honest uncertainty: report CIs; small courses will be noisy — pool by department/level with a hierarchical or partial-pooling approach if needed.

**Acceptance criteria:** `analysis/` notebook producing the KM curves and Cox table; a serialized lookup table (`course → position bucket → clear probability + median days`) exported as JSON for the site.

## 7. Phase 4 — The lookup tool

- Static site on GitHub Pages (zero cost): single HTML page, client-side search over the exported JSON (a few MB is fine; split per-department JSON if large).
- UX: type a course → see "historically, position #N in this course clears with p% probability by first lecture" + the KM curve.
- Every page footer: one-line methodology + link to `METHODS.md` + "estimates from aggregate counts under FIFO assumptions; reserved seats and department policies vary."
- Analytics: [GoatCounter](https://www.goatcounter.com/) (free, privacy-friendly) to count users — this number goes on the resume.

## 8. Phase 5 — Launch

- Time the launch to the January 2027 adjustment period (peak waitlist anxiety). A soft launch during November Phase 2 enrollment is a good dry run.
- Post to r/berkeley with the tool + one interesting finding as the hook ("the median CS waitlist position that still cleared last cycle was #X"). Expect methodological pushback in comments — answering it well is interview practice.
- Track: unique visitors, top courses searched. Screenshot the analytics before the resume deadline.

## 9. Risks

| Risk | Mitigation |
|---|---|
| API access denied / endpoint changes mid-cycle | Route B fallback; parser tests fail loudly; fix within 24h (data gaps are permanent) |
| Scraper dies silently during the critical window | Failing workflow emails; heartbeat badge; check weekly |
| Aggregate counts make individual claims shaky | State assumptions prominently; present probabilities as historical frequencies under FIFO, not guarantees |
| Reserved seats distort flows in some departments | Flag and exclude or separately model high-anomaly sections |
| Berkeleytime ships the same feature | Unlikely mid-cycle; your dataset is still novel; collaboration is also a fine outcome (they're ASUC open source — contributing is resume-positive too) |

## 10. Interview talking points to be able to defend

Why survival analysis instead of logistic regression (censoring). What censoring means here and where it comes from. The FIFO and flow-decomposition assumptions and how wrong they can be. Why Cox PH, what the proportional hazards assumption is, how you tested it, what you did when it failed. Pipeline reliability decisions (why Parquet-per-run, why exit-1-on-empty-sweep). What you'd do with individual-level data if the Registrar gave it to you.

## 11. Link index

- Berkeleytime: https://berkeleytime.com · repo: https://github.com/asuc-octo/berkeleytime · data docs: https://docs.berkeleytime.com/core/data/index.html
- Berkeley API Central: https://api-central.berkeley.edu/apis · Student API: https://api-central.berkeley.edu/api/29
- Class schedule: https://classes.berkeley.edu
- Registrar enrollment dates: https://registrar.berkeley.edu/registration/enrollment/
- GitHub Actions schedules: https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule
- lifelines (Python survival analysis): https://lifelines.readthedocs.io/
- GoatCounter analytics: https://www.goatcounter.com/

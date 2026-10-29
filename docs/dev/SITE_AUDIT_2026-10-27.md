# Site audit, 2026-10-27 (for the next Claude Code session)

Every page of `site/` at `main` 0927c45 (what GitHub Pages serves) rendered with headless Chromium at 1280 px and 390 px, clock set to Pacific, at 18:20 PDT Oct 27 (01:20Z Oct 28), with the live `status.json` and `live/latest.json` fetched from the `data` branch. Pages: index (with and without a lookup, pinned and unpinned), courses, course (own curve, one-section course, title, nonsense code, empty), dept (index and `?subject=COMPSCI`), insights, accuracy, methodology, about, 404. No console errors, no failed requests, no horizontal overflow at 390 px.

Numbers below are what the pages showed; "where" is the source line on `main`. "Fixed by" names an open draft PR whose diff I compared; "open" means no PR touches it. Items 1 to 5 are what a student would notice or be misled by; the rest is copy and polish. Base copy fixes on #49's branch (`site-prereg-copy`), which already touches the Lookup copy.

## A. Wrong or misleading numbers

### 1. Every headline is a floor read far past the data, worded as a past fact

`site.js:735`: `${frequency(p)} got in by ${fmtDay(meta.deadline)}` → "About 14 in 20 got in by Feb 5, 2027". Same string in the "Copy as text" output (`index.html:76`) and the by-when table header "Share who got in" against future dates.

Two problems in one line. The tense: a Spring 2026 frequency is printed as something that happened by a 2027 date. The horizon: the page reads the curve at 101 days, and **no curve on the site reaches 101 days** (`reach_days` max 80; median 39; 54% of own-course cells end before 40 days), so the Feb 5 and Jan 19 numbers are the same end-of-curve value on every page, tagged "floor" in small print. The verdict band ("Could go either way") is then computed from a floor.

Fix: the look-back template at `site.js:728-729` already has the right wording ("got in within 80 days of joining"). Use it for the forecast too: headline "About 14 in 20 got in within N days of joining" where N = min(curve reach, days to deadline); the sentence under it keeps "the time left before the last automatic run is 101 days; the data follow joiners for 80". Table header: "Share in by then". When `capped`, say "at least" instead of "floor" in the headline sentence. Open; decision for Oliver whether the headline horizon is the reach or a fixed 28 days.

### 2. 1,288 of 2,114 courses get "Too little data to call" because they have one lecture

`site.js:706`: `r.lo == null` → "Too little data to call (one section only, no interval)". Berkeleytime history is per primary section, so 2,009 of the 2,376 own-course cells (85%) have `sections: 1` and no interval. COMPSCI 61A at positions 6 to 15: 638 joiners, 458 cleared, median 3.3 days, 100% within 28 days, verdict "Too little data to call". That is the verdict on most of the courses students will type.

Fix is in the analysis, not the site: when a cell has one section, bootstrap over join moments (or week blocks) instead of sections so an interval exists; or drop the one-section rule and print the verdict with "no interval (one section)" as the caveat. The site change is one condition at `site.js:706` plus `VERDICT_NOTE` at 711. Open. Decision for Oliver (it changes `CLAIMS.md` wording about intervals).

### 3. Headline states a frequency confidently when the verdict says the data cannot support one

STAT 135 at position 45: "About 14 in 20 got in … 70% (95% interval 69% to 100%)", by-when rows "7 days: 0% (0% to 0%)", "14 days: 42% (0% to 43%)", verdict "Too little data to call (the interval is wider than 30 points)". A nonsense code ("NOPE 999") on the lookup gets "About 10 in 20 got in … Could go either way" from the all-grad pool because `levelOf("999")` is grad (`site.js:325`), while `course.html?c=NOPE+999` correctly says "No data". "data structures" on the lookup gets "About 15 in 20" from the all-courses pool.

Fix: when the verdict is "Too little data", lead with the verdict and demote the frequency sentence to the table; when the course key is not in the index at all, the lookup should do what course.html does (no estimate, suggestions only), and offer the pool only for a real course with too few cases. `index.html` render path; `site.js:700-740`. Open (#45 makes "data structures" resolve, which removes that example but not the rule).

### 4. Day counts and "as of" date run on UTC, so they are off by one every Pacific evening

`site.js:216-235`: horizons are fractional days from the instant `now` to 00:00 UTC of the date, then rounded; `fmtShort` and `fmtDay` print with `timeZone: "UTC"`. At 18:20 PDT Oct 27 the pages said "as of Oct 28", "Phase 2 opens (in 26 days)" (27 on a Pacific calendar), "First day of class (in 83 days)" (84), "7 days from now (Nov 4)" (Nov 3), and the chart's x-axis starts at "0d Oct 28". From about 17:00 PDT every day, every date on the site is tomorrow's.

Fix: define "today" as the local calendar date at local midnight (`new Date(y, m, d)` from `new Date()`), compute horizons as whole-day differences from that, and drop `timeZone: "UTC"` from the two formatters (keep it for the `?today=` pin, which is a date). One helper; `today()` at `site.js:96`. Open.

### 5. Accuracy: the headline tests show the served curves overpredicting Fall by 15 to 22 points, with no sentence saying why

"Fit on Spring 2026, scored on Fall 2026, within 14 days": "When the estimate said about 89%, 67% got in"; 68% → 51%; 54% → 38%. Methodology already says Fall cleared markedly slower than Spring (48% vs 66% at 1 to 5 within 14 days), but the accuracy page never connects the two. A reader stops at the calibration lines. Also the first block on the page is the within-Fall temporal test where the course curve is *worse* than the baseline (−0.023), which is the opposite of the rule the methodology page states, and the explanation (Phase 2 sped everything up) is at the bottom of the methodology page, not here.

Fix (copy only, `accuracy.html`): one paragraph above the runs: what each test family means, that Spring→Fall overpredicts because Fall is the slow cycle and the direction reverses for the Spring→Spring test the site is actually making, and that the cross-cycle *ranking* (course curve beats position bucket, +0.009 to +0.025) is the result the pages rest on. Put the Spring→Fall runs first. Open.

Also on this page: "What could not be tested on Fall 2026" says no joiner's outcome at the last-run horizon is observable, two screens below a run headed "scored on Fall 2026, by the last automatic waitlist run" with 52,227 scored. One of the two is wrong; the run's `coverage` table (hidden under "Which joiners could be scored, by phase") will say which.

## B. Stale or wrong copy

6. **"Live Spring 2027 collection by this project starts Oct 26, 2026"** on every page's source line (`site.js` source sentence), "Collection for Spring 2027 starts when Phase 1 opens on Oct 26, 2026" (`methodology.html`), "Section curves need this project's own Spring 2027 snapshots; none exist before Oct 26, 2026" (`course.html`). Past tense now, and not true (nothing has been collected). Fixed by #42 for the four dated strings it names; check the course.html one is among them.
7. **"This project's last Fall 2026 snapshot ran about 37 min ago"** on every Spring 2027 page, and the course page's "Sections now" board showing Fall 2026 counts ("LEC 001 58 / 57, full, read 1 hour ago") under Spring 2027 dates. Fixed by #42 (`BWO.isForecastTerm` hides the board); the status sentence should also hide or say "Spring 2027 collection has not started" until `term_id` is 2272.
8. **Two different ages on the same page**: status line "37 min ago", board "as of 65 min ago". Both are real (`status.json` vs `live/latest.json`) but a reader sees a contradiction. One number: use `live/latest.json`'s age for the board only when it is newer than the status; otherwise print the status age. `course.html:156`. Open.
9. **About: "an outcome form will be linked from the lookup page once Spring 2027 enrollment opens."** Enrollment opened; there is no form (L15 is an open feature). Change to "may be linked later" or delete. `about.html:38`. Open.
10. **Insights: "Lower-division waitlists moved faster at positions 6 to 15: 61% got in within 14 days against 60%"**. The template at `insights.html:48` always prints the larger side as "faster"; at one point apart, with overlapping intervals, it is a non-finding. Guard: print "about the same" when the gap is under 5 points or the intervals overlap. Open.
11. **Insights table: positions 16 to 40 end at 85% and 6 to 15 at 84% against 74% for positions 1 to 5** ("Longest follow-up" column), and the Phase 1 lower-division chart's legend reads "6-15 92%, 16-40 88%, 1-5 83%". Front-of-queue joiners clearing *less* often than the back is the empty-queue tail-joiner artifact from the Sept 19 review (a hypothetical at position 1 in a queue that never moves is never cleared, while deeper positions only exist in queues that move). Either cap the table at a common horizon (28 days, where the order is right) and drop the "Longest follow-up" column, or add one sentence explaining the inversion. Open; this is the kind of thing a Berkeleytime maintainer or a stats-literate reader will quote back.
12. **Methodology: "The reports compare four predictors"** (`methodology.html:47`); the accuracy page scores five. Also "when your horizon is longer…" starts a sentence in lower case (`methodology.html:44`). Open.
13. **Lookup "Did you mean PHYSED 1, MATH 54, COMPSCI 189?"** for every unresolved input: those are the three "Try" examples, not nearest matches (`index.html` fallback). Either run `nearestSubjects`/the matcher and show real candidates or drop the "Did you mean". Open; #45's title index gives it something to match against.
14. **Footer "page generated Sep 24, 2026"** on a site whose weekly job commits every Sunday: true (the weekly run has not touched `site/data`) but it reads as abandoned. Either "curves frozen Sep 21, 2026 (7f348ed)", which is the fact that matters, or drop it. `site.js:209`. #49 adds the static prereg record; fold this in there.

## C. Polish

15. **Phone nav clips "Methods" to "M"** at 390 px (`site.css` nav; the five items do not fit at the current font size). Shorten to four items, allow wrap, or let it scroll with a fade. Open.
16. **Course chart on the phone**: tick labels at the x-axis are unreadable at 390 px (nine labels across 350 px). Halve the tick count below 480 px. `curveChart` in `site.js`. Open.
17. **"Could go either way (40% to 74%)"** printed beside a "95% interval 64% to 82%": two parenthesised ranges, one a cut-off, one an interval. Print the cut-off in the verdict note only. `site.js` verdict html. Open.
18. **"100% floor"** on the courses table (COMPSCI 61B, DATA C8, …) and the dept table: a floor at 100% is meaningless. Suppress the tag when `p >= 0.995`. `courses.html:123`, dept.html equivalent. Open.
19. **Chart legend order** is by end value ("16-40 100%, 1-5 100%, 6-15 100%, 41+ 99%"); keep bucket order. `curveChart`. Open.
20. **"Other COMPSCI courses at positions 6 to 15"** on course.html lists one course (189) of 39 because `relatedCourses` drops anything pooled to "all" (`site.js`, `relatedCourses`); either include department-pooled courses or say "with their own curve". Open.
21. **Department list shows "DISSTD"** raw among full names; one missing entry in `SUBJECT_NAMES`. Open.
22. **Look-back mode** (pinned after Feb 5) still prints "7 days from now (Feb 27)" rows under the sentence saying waitlists are no longer processed. Drop the from-now rows when `h.deadline <= 0`. `site.js:754`. Open.
23. **`?today=` pin is undocumented** on the site. Fine for tests; just confirm it is not linked anywhere public.

## D. What was not checked

- The live host itself (not reachable from this session); `main` is what `pages.yml` uploads unchanged, so the rendering is the same, but the `og.png` social card and the 404 route on Pages were not exercised.
- Screen-reader output and keyboard focus order (the Sept 9 design items: substituted typeface, gold focus ring, `--rust`, `--s1` contrast, VoiceOver) — still the open list in the session-11 file.
- Whether #42/#45/#49 as diffs cover items 6, 7 and 14 exactly as described: compared by reading the branches' HTML, not by rendering them. Render the merged tree once before closing these.

## E. Suggested order

1. Item 4 (dates) and item 1 (headline wording): one PR on #49's branch, both are template changes; the date helper has tests in `tests/test_site.py` to extend.
2. Items 6, 7, 9, 12, 14: copy, same PR or #42/#49.
3. Item 5 and 11: copy on accuracy and insights, one PR; no numbers change.
4. Items 2 and 3: Oliver decides the rule; then analysis (bootstrap) plus site.
5. The rest whenever.

# Assumptions behind the flow reconstruction

What the data can and cannot say, in plain terms. The snapshots record aggregate counts for each section: how many students are enrolled, how many are on the waitlist, and the two capacities. They never record who is where in the queue. Every individual-level quantity in this project is reconstructed from count changes under the assumptions below. Code: `analysis/flows.py` and `analysis/positions.py`; contract: docs/DESIGN_A4.md.

## 1. Net flows within an interval are lower bounds

Between two observations of a section, only the net change in each count is visible. If one student joins the waitlist and another leaves it in the same interval, the count does not move and both events are invisible. The reconstruction therefore reports the smallest set of events that explains the observed change. Every flow it reports (admits, joins, drops, direct enrolments) is a lower bound on the true number of such events in the interval. The shorter the interval, the closer the bound; priority sections are observed every 30 minutes and other sections about every 6 hours (docs/RUNBOOK.md section 2), so bounds are tighter for the courses the model cares most about.

When enrolment rises while a waitlist exists, every added seat is counted as an admit, because under FIFO (section 2) a seat cannot go to a newcomer while someone is queued; the waitlist's net change then tells how many joined or dropped on top of that. When the waitlist was empty, an enrolment rise is direct enrolment. A fall in the waitlist with no enrolment change is drops, but if the section was full it could equally be an enrolled student leaving and the head of the queue taking the seat within the same interval; such intervals are flagged `ambiguous`, as is every interval where more than one story fits, and the rule that fired is recorded so the analysis can exclude or weight them. The full rule table is docs/DESIGN_A4.md section 2. On simulated data with 30-minute sampling (section 7) this recovers about 91% of admits and 96% of joins; the shortfall is almost entirely admits that shared an interval with the enrolled drop that created their seat.

## 2. FIFO ordering

Berkeley processes waitlists in order of position: when a seat opens, the first eligible student on the list is offered it. The reconstruction assumes strict first in, first out. A student who joins at position k therefore clears once k students ahead have left the list, either by being admitted or by dropping. Position k counts the student, so position 1 clears at the next admit.

Where FIFO is known to bend, see sections 4 and 5. The model does not attempt to identify individual students; it asks what would have happened to a hypothetical student who joined at a given time and position.

## 3. Unobserved drop positions and the three scenarios

A waitlist drop is visible only as a decrease in the count. Whether the student who left was ahead of or behind a given position is unknown. Three scenarios bracket the truth for a hypothetical joiner at position k:

- Optimistic: every drop was ahead of the joiner. Position falls by admits plus drops.
- Pessimistic: every drop was behind the joiner. Position falls by admits only.
- Central: drops are spread uniformly over the other students on the list, so each drop was ahead of a joiner at position k with probability (k - 1) / (list length - 1). The expected number of people ahead falls by admits plus that share of the drops, and the joiner counts as cleared once it falls to one half, the point at which clearing is more likely than not.

The central scenario is the headline estimate; the other two are reported alongside it so a reader sees how much the answer depends on this assumption. All three agree when there are no drops.

## 4. Reserved seats break pure FIFO

Many sections hold seats for a category of students (a major, a college, new students). The section page exposes the number of reserved seats and how many of them are open. A student on the waitlist who does not belong to the reserved category can be passed over while open reserved seats exist, and a section can show open seats while the waitlist does not move. The reconstruction keeps the reserved counts on every interval (`reserved0`, `open_reserved0`) and defines "full" as enrolled at or above capacity minus open reserved seats. A first release of reserved seats to the general population appears as a burst of admits with no enrolment drops. Sections with heavy reserved-seat activity should be analysed separately or excluded; the analysis step reports how many that is.

## 5. Batch waitlist processing

Seats are not always filled the moment they open. The registrar runs the automatic waitlist process in batches, and departments can hold or manually process lists. Two consequences: an interval can show an enrolment drop with a waitlist that does not move (the seat is open but nobody has been admitted yet; flagged ambiguous when the section was full with a waitlist), and admits cluster in time. Time to clear therefore includes processing delay, which is real from the student's point of view but is not a property of the queue. The last automatic waitlist run for Spring 2027 is Feb 5, 2027 at 6:40 PM; after it, positions no longer move automatically.

## 6. Gaps are censoring, not zero flow

When the scraper did not observe a section (a missed run, a run cut short by its time budget, an outage logged in docs/DATA_LOG.md), nothing is known about that period. The reconstruction only builds intervals between consecutive observed runs, so a missed observation lengthens the interval rather than inserting a zero. Intervals that overlap a logged outage, or that contain the moment of a logged source switch or schema change, are flagged `censored`; the survival analysis stops a hypothetical waitlister's clock at the first censored interval and treats the outcome as unknown. A tombstone (a section that vanished from the site) ends its series. Intervals longer than a chosen maximum can also be censored by the analysis.

## 7. Validation on synthetic data

`tests/test_flows_synthetic.py` (simulator in `analysis/synthetic.py`) simulates individual students on FIFO waitlists with known join, admit and drop times, samples the counts every 30 minutes with 3% of observations missing, runs the reconstruction on the counts alone, and compares. Configuration `SimConfig(seed=1)`: 40 sections, 14 days, capacities 20 to 300 starting 90% full, per section per day 6 joins, 2 enrolled drops and 1.5 waitlist drops, seats filled from the head of the queue after a uniform 0 to 240 minute processing delay. Result on 2026-09-19 (26,121 intervals, 2,059 simulated students, 800 of whom cleared):

| flow | true total | recovered | error |
| --- | --- | --- | --- |
| admits | 800 | 731 | -8.6% |
| waitlist joins | 2,057 | 1,984 | -3.6% |
| waitlist drops | 593 | 589 | -0.7% |
| direct enrolments | 937 | 900 | -4.0% |
| enrolled drops | 1,156 | 1,050 | -9.2% |

Every one of the 25,499 intervals containing at most one event is recovered exactly. Every shortfall is a lower-bound effect from events sharing an interval (section 1); at 1-minute sampling the same simulation recovers admits within 1.2%.

Time to clear for the 800 students who cleared, replayed as virtual waitlisters at their sampled join time and position:

| scenario | median absolute error | bias (mean) | censored before clearing |
| --- | --- | --- | --- |
| central | 25 minutes | +225 minutes | 27 of 800 |
| optimistic | 254 minutes | -586 minutes | 1 of 800 |
| pessimistic | 503 minutes | +917 minutes | 104 of 800 |

The optimistic estimate is at or below the truth and the pessimistic estimate at or above it for 85% of students when a pessimistic run that reaches the end of the data counts as a failure, and 97% when it counts as an upper bound. By position at join, the central median error is under 30 minutes (one sampling step) for positions 1 to 10 and about 5 hours for positions 11 to 20, where a single missed admit shifts the whole queue. These are the bounds asserted by the test; the design targets it was written against (admits within 5%, central error under one hour) are recorded in the test file next to the measured values.

## 8. What individual-level data would change

With the registrar's per-student waitlist records (join time, position, outcome), sections 1, 3 and 5 would become unnecessary: flows would be observed rather than reconstructed, drop positions would be known, and processing delay could be separated from queue movement. Section 4 would still matter for interpretation, and section 6 would still apply to any period the records do not cover. The survival models in step A5 would be unchanged in form; only their inputs would be exact.

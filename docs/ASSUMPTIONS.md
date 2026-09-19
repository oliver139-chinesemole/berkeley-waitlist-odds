# Assumptions behind the flow reconstruction

What the data can and cannot say, in plain terms. The snapshots record aggregate counts for each section: how many students are enrolled, how many are on the waitlist, and the two capacities. They never record who is where in the queue. Every individual-level quantity in this project is reconstructed from count changes under the assumptions below. Code: `analysis/flows.py` and `analysis/positions.py`; contract: docs/DESIGN_A4.md.

## 1. Net flows within an interval are lower bounds

Between two observations of a section, only the net change in each count is visible. If one student joins the waitlist and another leaves it in the same interval, the count does not move and both events are invisible. The reconstruction therefore reports the smallest set of events that explains the observed change. Every flow it reports (admits, joins, drops, direct enrolments) is a lower bound on the true number of such events in the interval. The shorter the interval, the closer the bound; priority sections are observed every 30 minutes and other sections about every 6 hours (docs/RUNBOOK.md section 2), so bounds are tighter for the courses the model cares most about.

When enrolment rises and the waitlist falls in the same interval, the reconstruction pairs them as admits (one waitlisted student moved into a seat), up to the smaller of the two changes. A larger rise in enrolment is treated as direct enrolment; a larger fall in the waitlist as drops. Intervals where more than one story fits are flagged `ambiguous` and the rule that fired is recorded, so the analysis can exclude or weight them. The full rule table is docs/DESIGN_A4.md section 2.

## 2. FIFO ordering

Berkeley processes waitlists in order of position: when a seat opens, the first eligible student on the list is offered it. The reconstruction assumes strict first in, first out. A student who joins at position k therefore clears once k students ahead have left the list, either by being admitted or by dropping. Position k counts the student, so position 1 clears at the next admit.

Where FIFO is known to bend, see sections 4 and 5. The model does not attempt to identify individual students; it asks what would have happened to a hypothetical student who joined at a given time and position.

## 3. Unobserved drop positions and the three scenarios

A waitlist drop is visible only as a decrease in the count. Whether the student who left was ahead of or behind a given position is unknown. Three scenarios bracket the truth for a hypothetical joiner at position k:

- Optimistic: every drop was ahead of the joiner. Position falls by admits plus drops.
- Pessimistic: every drop was behind the joiner. Position falls by admits only.
- Central: drops are spread uniformly over the list, so a share k over the current list length was ahead. Position falls by admits plus that share of the drops.

The central scenario is the headline estimate; the other two are reported alongside it so a reader sees how much the answer depends on this assumption. All three agree when there are no drops.

## 4. Reserved seats break pure FIFO

Many sections hold seats for a category of students (a major, a college, new students). The section page exposes the number of reserved seats and how many of them are open. A student on the waitlist who does not belong to the reserved category can be passed over while open reserved seats exist, and a section can show open seats while the waitlist does not move. The reconstruction keeps the reserved counts on every interval (`reserved0`, `open_reserved0`) and defines "full" as enrolled at or above capacity minus open reserved seats. A first release of reserved seats to the general population appears as a burst of admits with no enrolment drops. Sections with heavy reserved-seat activity should be analysed separately or excluded; the analysis step reports how many that is.

## 5. Batch waitlist processing

Seats are not always filled the moment they open. The registrar runs the automatic waitlist process in batches, and departments can hold or manually process lists. Two consequences: an interval can show an enrolment drop with a waitlist that does not move (the seat is open but nobody has been admitted yet; flagged ambiguous when the section was full with a waitlist), and admits cluster in time. Time to clear therefore includes processing delay, which is real from the student's point of view but is not a property of the queue. The last automatic waitlist run for Spring 2027 is Feb 5, 2027 at 6:40 PM; after it, positions no longer move automatically.

## 6. Gaps are censoring, not zero flow

When the scraper did not observe a section (a missed run, a run cut short by its time budget, an outage logged in docs/DATA_LOG.md), nothing is known about that period. The reconstruction only builds intervals between consecutive observed runs, so a missed observation lengthens the interval rather than inserting a zero. Intervals that overlap a logged outage, or that contain the moment of a logged source switch or schema change, are flagged `censored`; the survival analysis stops a hypothetical waitlister's clock at the first censored interval and treats the outcome as unknown. A tombstone (a section that vanished from the site) ends its series. Intervals longer than a chosen maximum can also be censored by the analysis.

## 7. Validation on synthetic data

Not yet measured. `tests/test_flows_synthetic.py` simulates individual students on FIFO waitlists with known join, admit and drop times, aggregates them to 30-minute counts with observation gaps, runs the reconstruction, and compares. This section will record the simulator configuration and the recovery error per flow type and per scenario once that test exists and passes.

## 8. What individual-level data would change

With the registrar's per-student waitlist records (join time, position, outcome), sections 1, 3 and 5 would become unnecessary: flows would be observed rather than reconstructed, drop positions would be known, and processing delay could be separated from queue movement. Section 4 would still matter for interpretation, and section 6 would still apply to any period the records do not cover. The survival models in step A5 would be unchanged in form; only their inputs would be exact.

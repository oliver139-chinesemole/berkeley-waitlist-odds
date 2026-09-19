"""Enrollment phase calendar per term. See docs/DESIGN_A5.md section 2.

Dates are the registrar's Student Enrollment Calendar (docs/PHASE0.md;
ICS in data/fixtures/registrar_enrollment_calendar.ics). Phases are
evaluated on UTC dates; the seven-hour offset from Pacific time does not
matter at the resolution of a phase.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

PHASES = ("before", "phase1", "between", "phase2", "adjustment", "instruction", "after")


@dataclass(frozen=True)
class TermCalendar:
    term_id: str
    name: str
    phase1_start: date  # continuing students
    phase1_end: date  # inclusive
    phase2_start: date
    phase2_end: date  # inclusive
    adjustment_start: date
    instruction_start: date
    last_auto_waitlist: date
    add_drop_deadline: date

    def phase_at(self, when: datetime | date) -> str:
        """Phase containing ``when``: before, phase1, between, phase2,
        adjustment (up to the day before instruction), instruction (up to the
        add/drop deadline inclusive), after."""
        day = _as_date(when)
        if day < self.phase1_start:
            return "before"
        if day <= self.phase1_end:
            return "phase1"
        if day < self.phase2_start:
            return "between"
        if day <= self.phase2_end:
            return "phase2"
        if day < self.instruction_start:
            return "adjustment"
        if day <= self.add_drop_deadline:
            return "instruction"
        return "after"

    def days_to_instruction(self, when: datetime | date) -> float:
        """Days from ``when`` to 00:00 UTC on the first day of instruction (negative after it)."""
        start = datetime(self.instruction_start.year, self.instruction_start.month, self.instruction_start.day, tzinfo=timezone.utc)
        moment = when if isinstance(when, datetime) else datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return (start - moment).total_seconds() / 86400.0


def _as_date(when: datetime | date) -> date:
    if isinstance(when, datetime):
        if when.tzinfo is not None:
            when = when.astimezone(timezone.utc)
        return when.date()
    return when


SPRING_2027 = TermCalendar(
    term_id="2272",
    name="Spring 2027",
    phase1_start=date(2026, 10, 26),
    phase1_end=date(2026, 11, 15),
    phase2_start=date(2026, 11, 23),
    phase2_end=date(2027, 1, 10),
    adjustment_start=date(2027, 1, 11),
    instruction_start=date(2027, 1, 19),
    last_auto_waitlist=date(2027, 2, 5),
    add_drop_deadline=date(2027, 2, 10),
)

# Fall 2026 (the test term) from the same ICS: Phase 1 for continuing students
# Apr 13 to Jun 12, 2026; Phase 2 Jul 20 to Aug 16; adjustment from Aug 17;
# instruction Aug 26; undergraduate add/drop deadline Sep 16. The ICS carries
# no "last automatic waitlist run" row for FA26, only "Waitlist Purge" on
# Sep 26; the add/drop deadline is used as the last automatic run.
FALL_2026 = TermCalendar(
    term_id="2268",
    name="Fall 2026",
    phase1_start=date(2026, 4, 13),
    phase1_end=date(2026, 6, 12),
    phase2_start=date(2026, 7, 20),
    phase2_end=date(2026, 8, 16),
    adjustment_start=date(2026, 8, 17),
    instruction_start=date(2026, 8, 26),
    last_auto_waitlist=date(2026, 9, 16),
    add_drop_deadline=date(2026, 9, 16),
)

CALENDARS = {c.term_id: c for c in (SPRING_2027, FALL_2026)}


def calendar_for(term_id: str) -> TermCalendar:
    try:
        return CALENDARS[str(term_id)]
    except KeyError as exc:
        raise KeyError(f"no enrollment calendar for term {term_id!r}; add it to analysis/calendar.py") from exc

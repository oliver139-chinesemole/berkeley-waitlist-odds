"""Phase boundaries of the term calendars (docs/DESIGN_A5.md section 2)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from analysis.calendar import FALL_2026, PHASES, SPRING_2026, SPRING_2027, calendar_for


def test_spring_2027_phases() -> None:
    c = SPRING_2027
    assert c.phase_at(date(2026, 10, 25)) == "before"
    assert c.phase_at(date(2026, 10, 26)) == "phase1"
    assert c.phase_at(date(2026, 11, 15)) == "phase1"
    assert c.phase_at(date(2026, 11, 16)) == "between"
    assert c.phase_at(date(2026, 11, 23)) == "phase2"
    assert c.phase_at(date(2027, 1, 10)) == "phase2"
    assert c.phase_at(date(2027, 1, 11)) == "adjustment"
    assert c.phase_at(date(2027, 1, 18)) == "adjustment"
    assert c.phase_at(date(2027, 1, 19)) == "instruction"
    assert c.phase_at(date(2027, 2, 10)) == "instruction"
    assert c.phase_at(date(2027, 2, 11)) == "after"
    assert set(PHASES) >= {c.phase_at(date(2026, 1, 1)), "phase1", "phase2", "adjustment", "instruction", "after"}


def test_phase_at_accepts_aware_datetimes() -> None:
    assert SPRING_2027.phase_at(datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)) == "phase1"
    assert SPRING_2027.phase_at(datetime(2026, 10, 25, 23, 59, tzinfo=timezone.utc)) == "before"


def test_days_to_instruction() -> None:
    assert SPRING_2027.days_to_instruction(datetime(2027, 1, 18, 0, 0, tzinfo=timezone.utc)) == pytest.approx(1.0)
    assert SPRING_2027.days_to_instruction(date(2027, 1, 19)) == pytest.approx(0.0)
    assert SPRING_2027.days_to_instruction(datetime(2027, 1, 20, 12, 0, tzinfo=timezone.utc)) == pytest.approx(-1.5)


def test_fall_2026_from_the_registrar_ics() -> None:
    c = FALL_2026
    assert c.phase_at(date(2026, 6, 12)) == "phase1" and c.phase_at(date(2026, 6, 13)) == "between"
    assert c.phase_at(date(2026, 7, 20)) == "phase2" and c.phase_at(date(2026, 8, 17)) == "adjustment"
    assert c.phase_at(date(2026, 9, 16)) == "instruction" and c.phase_at(date(2026, 9, 19)) == "after"


def test_spring_2026_from_the_registrar_ics() -> None:
    c = SPRING_2026
    assert c.phase_at(date(2025, 10, 26)) == "before" and c.phase_at(date(2025, 10, 27)) == "phase1"
    assert c.phase_at(date(2025, 11, 16)) == "phase1" and c.phase_at(date(2025, 11, 17)) == "between"
    assert c.phase_at(date(2025, 11, 24)) == "phase2" and c.phase_at(date(2026, 1, 11)) == "phase2"
    assert c.phase_at(date(2026, 1, 12)) == "adjustment" and c.phase_at(date(2026, 1, 20)) == "instruction"
    assert c.phase_at(date(2026, 2, 11)) == "instruction" and c.phase_at(date(2026, 2, 12)) == "after"


def test_last_automatic_run_convention() -> None:
    """Spring 2027 has an explicit row (Feb 5, the last day to add without a fee); the
    other terms use their last day to add without a fee."""
    assert SPRING_2027.last_auto_waitlist == date(2027, 2, 5)
    assert FALL_2026.last_auto_waitlist == date(2026, 9, 11) < FALL_2026.add_drop_deadline
    assert SPRING_2026.last_auto_waitlist == date(2026, 2, 6) < SPRING_2026.add_drop_deadline


def test_calendar_for() -> None:
    assert calendar_for("2272") is SPRING_2027 and calendar_for(2268) is FALL_2026 and calendar_for("2262") is SPRING_2026
    with pytest.raises(KeyError):
        calendar_for("2275")

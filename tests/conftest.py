"""Shared test helpers: a snapshot row factory and a temporary data root.

No autouse fixtures live here. ``make_row`` is a plain function (import it
with ``from tests.conftest import make_row``) and is also exposed as the
``row_factory`` fixture.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from scraper.schema import SnapshotRow

T0 = datetime(2026, 11, 2, 7, 37, tzinfo=timezone.utc)


def make_row(**overrides: Any) -> SnapshotRow:
    """A valid SnapshotRow with sensible defaults; override any field by name."""
    row: dict[str, Any] = {
        "fetched_at": T0,
        "term_id": "2272",
        "section_id": "30174",
        "course_key": "COMPSCI 61A",
        "subject": "COMPSCI",
        "catalog_number": "61A",
        "class_number": "001",
        "section_number": "001",
        "component": "LEC",
        "is_primary": True,
        "session_id": "1",
        "enrolled_count": 1500,
        "enroll_capacity": 1600,
        "waitlist_count": 120,
        "waitlist_capacity": 300,
        "reserved_count": None,
        "open_reserved": None,
        "status": "O",
        "section_status": "A",
        "source": "sis_api",
    }
    unknown = set(overrides) - set(row)
    if unknown:
        raise KeyError(f"make_row: unknown fields {sorted(unknown)}")
    row.update(overrides)
    return row  # type: ignore[return-value]


@pytest.fixture
def row_factory():
    """The ``make_row`` factory as a fixture."""
    return make_row


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """An empty temporary data root (checkout of the data branch)."""
    root = tmp_path / "data-branch"
    root.mkdir()
    return root

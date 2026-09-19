"""Tests for scraper/schema.py (DESIGN_A2 section 1)."""
from __future__ import annotations

from datetime import datetime, timezone

import pyarrow as pa
import pytest

from scraper.schema import (
    COUNT_FIELDS,
    FIELD_NAMES,
    IDENTITY_FIELDS,
    SNAPSHOT_SCHEMA,
    SchemaError,
    rows_to_table,
    validate_table,
)
from tests.conftest import make_row


def test_valid_rows_round_trip():
    rows = [
        make_row(section_id="1", reserved_count=5, open_reserved=2, is_primary=None, section_status=None),
        make_row(section_id="2", fetched_at=datetime(2026, 11, 2, 7, 38, 12, 345678, tzinfo=timezone.utc)),
    ]
    table = rows_to_table(rows)
    assert table.schema.equals(SNAPSHOT_SCHEMA)
    assert table.num_rows == 2
    assert table.to_pylist() == rows
    validate_table(table)


def test_field_order_and_count_fields():
    assert FIELD_NAMES == tuple(SNAPSHOT_SCHEMA.names)
    assert FIELD_NAMES[0] == "fetched_at"
    assert FIELD_NAMES[-1] == "source"
    assert set(COUNT_FIELDS) | set(IDENTITY_FIELDS) | {"fetched_at"} == set(FIELD_NAMES)
    assert not set(COUNT_FIELDS) & set(IDENTITY_FIELDS)


def test_empty_rows_give_empty_table():
    table = rows_to_table([])
    assert table.num_rows == 0
    assert table.schema.equals(SNAPSHOT_SCHEMA)


def test_wrong_dtype_raises():
    with pytest.raises(SchemaError):
        rows_to_table([make_row(enrolled_count="lots")])
    with pytest.raises(SchemaError):
        rows_to_table([make_row(section_id=30174)])
    with pytest.raises(SchemaError):
        rows_to_table([make_row(enrolled_count=2**40)])


def test_missing_column_raises():
    row = dict(make_row())
    del row["waitlist_count"]
    with pytest.raises(SchemaError, match="missing"):
        rows_to_table([row])  # type: ignore[list-item]


def test_extra_column_raises():
    row = dict(make_row())
    row["bogus"] = 1
    with pytest.raises(SchemaError, match="extra"):
        rows_to_table([row])  # type: ignore[list-item]


def test_duplicate_section_id_raises():
    with pytest.raises(SchemaError, match="duplicate"):
        rows_to_table([make_row(section_id="7"), make_row(section_id="7", enrolled_count=3)])


def test_null_in_non_nullable_raises():
    with pytest.raises(SchemaError):
        rows_to_table([make_row(status=None)])
    with pytest.raises(SchemaError):
        rows_to_table([make_row(enrolled_count=None)])


def test_unknown_source_raises():
    with pytest.raises(SchemaError, match="source"):
        rows_to_table([make_row(source="craigslist")])


def test_naive_timestamp_is_rejected_or_not_silently_shifted():
    naive = datetime(2026, 11, 2, 7, 37)
    try:
        table = rows_to_table([make_row(fetched_at=naive)])
    except SchemaError:
        return
    # if pyarrow accepts it, it must be interpreted as UTC, not shifted
    assert table.to_pylist()[0]["fetched_at"] == naive.replace(tzinfo=timezone.utc)


def test_validate_table_rejects_wrong_schema():
    table = pa.table({"section_id": ["1"], "enrolled_count": [1]})
    with pytest.raises(SchemaError, match="schema mismatch"):
        validate_table(table)
    with pytest.raises(SchemaError):
        validate_table("not a table")  # type: ignore[arg-type]


def test_validate_table_rejects_duplicate_ids_in_table():
    table = rows_to_table([make_row(section_id="1"), make_row(section_id="2")])
    doubled = pa.concat_tables([table, table])
    with pytest.raises(SchemaError, match="duplicate"):
        validate_table(doubled)

"""Snapshot row schema. See docs/DESIGN_A2.md section 1.

One row per section per snapshot. The pyarrow schema is the single source of
truth; every write validates against it.
"""
from __future__ import annotations

import numbers
from datetime import datetime
from typing import TypedDict

import pyarrow as pa


class SchemaError(ValueError):
    """Raised when rows or a table do not conform to SNAPSHOT_SCHEMA."""


SNAPSHOT_SCHEMA = pa.schema(
    [
        pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("term_id", pa.string(), nullable=False),
        pa.field("section_id", pa.string(), nullable=False),
        pa.field("course_key", pa.string(), nullable=False),
        pa.field("subject", pa.string(), nullable=False),
        pa.field("catalog_number", pa.string(), nullable=False),
        pa.field("class_number", pa.string(), nullable=False),
        pa.field("section_number", pa.string(), nullable=False),
        pa.field("component", pa.string(), nullable=False),
        pa.field("is_primary", pa.bool_(), nullable=True),
        pa.field("session_id", pa.string(), nullable=False),
        pa.field("enrolled_count", pa.int32(), nullable=False),
        pa.field("enroll_capacity", pa.int32(), nullable=False),
        pa.field("waitlist_count", pa.int32(), nullable=False),
        pa.field("waitlist_capacity", pa.int32(), nullable=False),
        pa.field("reserved_count", pa.int32(), nullable=True),
        pa.field("open_reserved", pa.int32(), nullable=True),
        pa.field("status", pa.string(), nullable=False),
        pa.field("section_status", pa.string(), nullable=True),
        pa.field("source", pa.string(), nullable=False),
    ]
)

FIELD_NAMES: tuple[str, ...] = tuple(SNAPSHOT_SCHEMA.names)

# Fields whose change between two observations of the same section makes the
# section appear in a delta snapshot.
COUNT_FIELDS: tuple[str, ...] = (
    "enrolled_count",
    "enroll_capacity",
    "waitlist_count",
    "waitlist_capacity",
    "reserved_count",
    "open_reserved",
    "status",
    "section_status",
)

# Descriptive fields carried along but not compared for delta purposes.
IDENTITY_FIELDS: tuple[str, ...] = (
    "term_id",
    "section_id",
    "course_key",
    "subject",
    "catalog_number",
    "class_number",
    "section_number",
    "component",
    "is_primary",
    "session_id",
    "source",
)

SOURCES: tuple[str, ...] = ("sis_api", "classes_site", "berkeleytime")

TOMBSTONE_STATUS = "GONE"

# Integer fields: values must be real integers (pyarrow would silently truncate
# 3.5 to 3 and accept numpy floats); bools are never counts.
INTEGER_FIELDS: tuple[str, ...] = tuple(f.name for f in SNAPSHOT_SCHEMA if pa.types.is_integer(f.type))


class SnapshotRow(TypedDict, total=True):
    fetched_at: object  # datetime with tzinfo=UTC
    term_id: str
    section_id: str
    course_key: str
    subject: str
    catalog_number: str
    class_number: str
    section_number: str
    component: str
    is_primary: bool | None
    session_id: str
    enrolled_count: int
    enroll_capacity: int
    waitlist_count: int
    waitlist_capacity: int
    reserved_count: int | None
    open_reserved: int | None
    status: str
    section_status: str | None
    source: str


def rows_to_table(rows: list[SnapshotRow]) -> pa.Table:
    """Build a validated pyarrow table from row dicts.

    Raises SchemaError on a missing or extra key, a value that cannot be cast
    to the pinned dtype, a null in a non-nullable column, an unknown source,
    or a duplicate section_id. Two coercions pyarrow would perform silently
    are refused explicitly: a non-integer (float, str, bool) in an integer
    field, and a naive ``fetched_at`` (which pyarrow would stamp as UTC).
    """
    if not isinstance(rows, list):
        raise SchemaError("rows must be a list of dicts")
    expected = set(FIELD_NAMES)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SchemaError(f"row {i} is not a dict")
        keys = set(row)
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise SchemaError(f"row {i}: missing={missing} extra={extra}")
        _check_row_values(i, row)
    columns = {name: [row[name] for row in rows] for name in FIELD_NAMES}
    try:
        table = pa.Table.from_pydict(columns, schema=SNAPSHOT_SCHEMA)
    except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError, OverflowError) as exc:
        raise SchemaError(f"cannot build table: {exc}") from exc
    validate_table(table)
    return table


def _check_row_values(i: int, row: dict) -> None:
    """Refuse values pyarrow would coerce silently (see ``rows_to_table``)."""
    ts = row["fetched_at"]
    if not isinstance(ts, datetime) or ts.tzinfo is None or ts.utcoffset() is None:
        raise SchemaError(f"row {i}: fetched_at must be a timezone-aware datetime, got {ts!r}")
    for name in INTEGER_FIELDS:
        value = row[name]
        if value is None:
            continue  # nullability is checked on the table
        if isinstance(value, bool) or not isinstance(value, numbers.Integral):
            raise SchemaError(f"row {i}: {name} must be an integer, got {value!r} ({type(value).__name__})")


def validate_table(table: pa.Table) -> None:
    """Raise SchemaError unless `table` matches SNAPSHOT_SCHEMA exactly and
    has no duplicate section_id, no nulls in non-nullable columns, and only
    known sources."""
    if not isinstance(table, pa.Table):
        raise SchemaError("not a pyarrow Table")
    if not table.schema.equals(SNAPSHOT_SCHEMA, check_metadata=False):
        raise SchemaError(
            "schema mismatch:\n--- expected ---\n"
            f"{SNAPSHOT_SCHEMA}\n--- got ---\n{table.schema}"
        )
    for field in SNAPSHOT_SCHEMA:
        if not field.nullable and table.column(field.name).null_count:
            raise SchemaError(f"null in non-nullable column {field.name!r}")
    if table.num_rows:
        ids = table.column("section_id").to_pylist()
        if len(set(ids)) != len(ids):
            seen: set[str] = set()
            dups = sorted({x for x in ids if x in seen or seen.add(x)})  # type: ignore[func-returns-value]
            raise SchemaError(f"duplicate section_id values: {dups[:10]}")
        bad = sorted(set(table.column("source").to_pylist()) - set(SOURCES))
        if bad:
            raise SchemaError(f"unknown source values: {bad}")

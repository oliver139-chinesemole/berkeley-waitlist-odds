"""Offline tests for scraper.sources.berkeleytime (DESIGN_A2.md 5c)."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from scraper.schema import rows_to_table
from scraper.sources.base import ParseError, TermSpec
from scraper.sources.berkeleytime import (
    DEFAULT_OPS_PATH,
    GRAPHQL_URL,
    BerkeleytimeError,
    BerkeleytimeSource,
    load_persisted_ops,
    parse_catalog,
    select_op,
)

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"
FALL_2026 = TermSpec.from_name("Fall 2026")
NOW = datetime(2026, 9, 18, 20, 15, 7, tzinfo=timezone.utc)


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def catalog_small() -> dict[str, Any]:
    return load("berkeleytime_getcatalog_small.json")


@pytest.fixture
def ops() -> dict[str, list[Any]]:
    return load_persisted_ops(DEFAULT_OPS_PATH)


class FakeGateway:
    """Injected transport: answers by op id, or from a queue of (status, payload) for retry tests."""

    def __init__(
        self,
        by_op_id: dict[str, tuple[int, dict[str, Any]]] | None = None,
        queue: list[tuple[int, dict[str, Any]]] | None = None,
    ) -> None:
        self.by_op_id = by_op_id or {}
        self.queue = queue or []
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        self.calls.append((url, copy.deepcopy(body), dict(headers)))
        if self.queue:
            return self.queue.pop(0)
        if body["id"] in self.by_op_id:
            return self.by_op_id[body["id"]]
        return 400, {"errors": [{"message": f"unknown persisted operation {body['id']}"}]}


def make_source(transport: FakeGateway) -> tuple[BerkeleytimeSource, list[float]]:
    sleeps: list[float] = []
    return BerkeleytimeSource(transport=transport, sleep=sleeps.append, clock=lambda: NOW), sleeps


# ----------------------------------------------------------------------------- GetCatalog


def test_parse_catalog_small(catalog_small: dict[str, Any]) -> None:
    rows = parse_catalog(catalog_small, NOW, FALL_2026)
    assert [r["section_id"] for r in rows] == ["bt:COMPSCI:61A:001", "bt:DATA:C100:001", "bt:STAT:134:001"]
    cs = rows[0]
    assert cs["course_key"] == "COMPSCI 61A"
    assert cs["subject"] == "COMPSCI" and cs["catalog_number"] == "61A"
    assert cs["class_number"] == "001" and cs["section_number"] == "001"
    assert cs["component"] == "LEC"
    assert cs["is_primary"] is True
    assert cs["session_id"] == "1"
    assert cs["term_id"] == "2268"
    assert (cs["enrolled_count"], cs["enroll_capacity"], cs["waitlist_count"], cs["waitlist_capacity"]) == (1472, 1750, 0, 500)
    assert cs["reserved_count"] is None and cs["open_reserved"] is None
    assert cs["status"] == "O"
    assert cs["section_status"] is None
    assert cs["source"] == "berkeleytime"
    assert cs["fetched_at"] == NOW
    assert rows[1]["status"] == "C" and rows[2]["waitlist_count"] == 45

    table = rows_to_table(rows)  # schema-valid
    assert table.num_rows == 3


def test_parse_catalog_class_strips_subject_spaces(catalog_small: dict[str, Any]) -> None:
    """"EL ENG" -> subject ELENG, id bt:ELENG:..., course_key "ELENG 16A" (same rule as classes_site and sis_api)."""
    from scraper.sources.berkeleytime import parse_catalog_class

    entry = copy.deepcopy(catalog_small["data"]["catalog"][0])
    entry["subject"] = "EL  ENG"
    entry["courseNumber"] = "16A"
    row = parse_catalog_class(entry, NOW, FALL_2026)
    assert row is not None
    assert row["subject"] == "ELENG"
    assert row["course_key"] == "ELENG 16A"
    assert row["section_id"] == "bt:ELENG:16A:001"


def test_fetch_sends_getcatalog_and_returns_full_scope(catalog_small: dict[str, Any], ops: dict[str, list[Any]]) -> None:
    catalog_op = ops["GetCatalog"][0]
    gateway = FakeGateway({catalog_op.id: (200, catalog_small)})
    src, sleeps = make_source(gateway)

    result = src.fetch(FALL_2026)

    assert result.scope == "full"
    assert len(result.rows) == 3
    assert result.universe_ids == {"bt:COMPSCI:61A:001", "bt:DATA:C100:001", "bt:STAT:134:001"}
    assert result.missing_ids == []
    assert sleeps == []
    url, body, headers = gateway.calls[0]
    assert url == GRAPHQL_URL
    assert body == {"id": catalog_op.id, "variables": {"year": 2026, "semester": "Fall"}}
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"].startswith("berkeley-waitlist-odds/")
    rows_to_table(result.rows)


def test_fetch_limit_leaves_universe_unknown(catalog_small: dict[str, Any], ops: dict[str, list[Any]]) -> None:
    src, _ = make_source(FakeGateway({ops["GetCatalog"][0].id: (200, catalog_small)}))
    result = src.fetch(FALL_2026, limit=2)
    assert len(result.rows) == 2 and result.universe_ids is None


def test_parse_catalog_skips_classes_without_latest_and_reports_unusable_counts(catalog_small: dict[str, Any]) -> None:
    payload = copy.deepcopy(catalog_small)
    catalog = payload["data"]["catalog"]
    no_enrollment = copy.deepcopy(catalog[0])
    no_enrollment["number"] = "002"
    no_enrollment["primarySection"]["enrollment"] = None
    catalog.append(no_enrollment)
    bad_counts = copy.deepcopy(catalog[0])
    bad_counts["number"] = "003"
    bad_counts["primarySection"]["enrollment"]["latest"]["enrolledCount"] = None
    catalog.append(bad_counts)

    rows = parse_catalog(payload, NOW, FALL_2026)
    assert [r["section_id"] for r in rows] == ["bt:COMPSCI:61A:001", "bt:DATA:C100:001", "bt:STAT:134:001"]

    src, _ = make_source(FakeGateway({load_persisted_ops()["GetCatalog"][0].id: (200, payload)}))
    result = src.fetch(FALL_2026)
    assert result.missing_ids == ["bt:COMPSCI:61A:003"]
    assert "bt:COMPSCI:61A:003" in result.universe_ids
    assert "bt:COMPSCI:61A:002" not in result.universe_ids


def test_parse_catalog_rejects_missing_data() -> None:
    with pytest.raises(ParseError):
        parse_catalog({"data": {}}, NOW, FALL_2026)


# ----------------------------------------------------------------------------- GetClass / GetEnrollment


def test_get_class_parses_real_fixture(ops: dict[str, list[Any]]) -> None:
    fixture = load("berkeleytime_getclass_compsci61a_fa26.json")
    expected_op = ops["GetClass"][1]  # the entry whose sessionId is required, per the Addendum
    gateway = FakeGateway({expected_op.id: (200, fixture)})
    src, _ = make_source(gateway)

    cls = src.get_class(FALL_2026, "COMPSCI", "61A", "001")

    assert cls["primarySection"]["sectionId"] == "29147"
    assert len(cls["sections"]) == 108
    assert cls["primarySection"]["enrollment"]["latest"]["enrolledCount"] == 1472
    _, body, _ = gateway.calls[0]
    assert body["id"] == expected_op.id
    assert body["variables"] == {
        "year": 2026,
        "semester": "Fall",
        "sessionId": "1",
        "subject": "COMPSCI",
        "courseNumber": "61A",
        "number": "001",
    }


def test_get_class_null_class_raises(ops: dict[str, list[Any]]) -> None:
    src, _ = make_source(FakeGateway({ops["GetClass"][1].id: (200, {"data": {"class": None}})}))
    with pytest.raises(ParseError):
        src.get_class(FALL_2026, "COMPSCI", "999", "001")


def test_get_enrollment_history_returns_history_points(ops: dict[str, list[Any]]) -> None:
    fixture = load("berkeleytime_enrollment_datac100_fa26.json")
    responses = {op.id: (200, fixture) for op in ops["GetEnrollment"]}
    gateway = FakeGateway(responses)
    src, _ = make_source(gateway)

    history = src.get_enrollment_history(FALL_2026, "DATA", "C100", "001")

    assert len(history) == 580
    assert history[-1]["enrolledCount"] == 856 and history[-1]["status"] == "C"
    _, body, _ = gateway.calls[0]
    assert body["id"] in responses
    assert body["variables"]["sectionNumber"] == "001" and body["variables"]["sessionId"] == "1"


# ----------------------------------------------------------------------------- op selection


def test_op_selection_picks_getclass_entry_with_session_id(ops: dict[str, list[Any]]) -> None:
    variables = {"year": 2026, "semester": "Fall", "sessionId": "1", "subject": "COMPSCI", "courseNumber": "61A", "number": "001"}
    op = select_op(ops, "GetClass", variables)
    assert "sessionId" in op.variable_names
    assert op.id == ops["GetClass"][1].id == "79775dae18f1f702ad5c0d177254b33b973f126c5e21750cb7b5569ec5146a87"
    assert "$sessionId:SessionIdentifier!" in op.document


def test_op_selection_requires_variable_superset(tmp_path: Path) -> None:
    ops_file = tmp_path / "ops.json"
    ops_file.write_text(
        json.dumps(
            {
                "GetClass": [
                    {"id": "aaa", "document": "query GetClass(...)", "variableNames": ["year", "semester", "subject", "courseNumber", "number"]},
                    {"id": "bbb", "document": "query GetClass(...)", "variableNames": ["year", "semester", "sessionId", "subject", "courseNumber", "number"]},
                ],
                "GetCatalog": [{"id": "ccc", "document": "query GetCatalog(...)", "variableNames": ["year", "semester"]}],
            }
        ),
        encoding="utf-8",
    )
    ops = load_persisted_ops(ops_file)
    with_session = {"year": 2026, "semester": "Fall", "sessionId": "1", "subject": "COMPSCI", "courseNumber": "61A", "number": "001"}
    without_session = {k: v for k, v in with_session.items() if k != "sessionId"}

    assert select_op(ops, "GetClass", with_session).id == "bbb"
    assert select_op(ops, "GetClass", without_session).id == "aaa"  # closest match wins
    with pytest.raises(ValueError):
        select_op(ops, "GetCatalog", {"year": 2026, "semester": "Fall", "bogus": 1})
    with pytest.raises(ValueError):
        select_op(ops, "GetNothing", {})

    src = BerkeleytimeSource(transport=FakeGateway(), ops_path=ops_file)
    assert src.op_for("GetClass", with_session).id == "bbb"


# ----------------------------------------------------------------------------- errors and retries


def test_graphql_errors_raise_parse_error(ops: dict[str, list[Any]]) -> None:
    error_body = {"errors": [{"message": "PersistedQueryNotFound"}], "data": None}
    responses = {ops["GetClass"][1].id: (200, error_body), ops["GetCatalog"][0].id: (200, error_body)}
    src, sleeps = make_source(FakeGateway(responses))

    with pytest.raises(ParseError, match="PersistedQueryNotFound"):
        src.get_class(FALL_2026, "COMPSCI", "61A", "001")
    with pytest.raises(ParseError, match="GraphQL errors"):
        src.fetch(FALL_2026)
    assert sleeps == []  # GraphQL errors are not retried


def test_execute_retries_5xx_then_succeeds(catalog_small: dict[str, Any]) -> None:
    gateway = FakeGateway(queue=[(502, {}), (200, catalog_small)])
    src, sleeps = make_source(gateway)

    result = src.fetch(FALL_2026)

    assert len(result.rows) == 3
    assert sleeps == [1.0]
    assert len(gateway.calls) == 2


def test_non_200_without_error_body_raises_after_retries() -> None:
    gateway = FakeGateway(queue=[(503, {}), (503, {}), (503, {})])
    src, sleeps = make_source(gateway)

    with pytest.raises(BerkeleytimeError) as excinfo:
        src.fetch(FALL_2026)

    assert excinfo.value.status == 503 and excinfo.value.operation == "GetCatalog"
    assert len(sleeps) == 2  # default retries=2


def test_non_retryable_status_raises_immediately() -> None:
    gateway = FakeGateway(queue=[(401, {})])
    src, sleeps = make_source(gateway)
    with pytest.raises(BerkeleytimeError):
        src.fetch(FALL_2026)
    assert sleeps == [] and len(gateway.calls) == 1

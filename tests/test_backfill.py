"""Tests for analysis.backfill: Berkeleytime run-length history to panel, censoring
of wide crossings, the gap report, count-blind section selection and a resumable
fetch against a fake gateway. No network."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis.backfill import (
    DATA_SOURCE,
    Cache,
    backfill_flows,
    build,
    build_panel,
    fetch,
    gap_report,
    history_to_rows,
    load_backfill,
    main,
    select_sections,
)
from analysis.run import main as run_main
from scraper.sources.base import TermSpec
from scraper.sources.berkeleytime import BerkeleytimeSource, load_persisted_ops

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"
FALL = TermSpec.from_name("Fall 2026")
T0 = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def iso(m: float) -> str:
    return (T0 + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def seg(start: float, end: float, e: int, w: int, *, c: int = 100, wc: int = 20, status: str = "C") -> dict[str, Any]:
    return {
        "startTime": iso(start),
        "endTime": iso(end),
        "granularitySeconds": 900,
        "status": status,
        "enrolledCount": e,
        "waitlistedCount": w,
        "reservedCount": 0,
        "minEnroll": 0,
        "maxEnroll": c,
        "maxWaitlist": wc,
        "openReserved": 0,
        "activeReservedMaxCount": 0,
        "seatReservationCount": [],
    }


def enrollment(section_id: str, history: list[dict], *, subject: str = "COMPSCI", course: str = "61A", number: str = "001") -> dict[str, Any]:
    return {"year": 2026, "semester": "Fall", "sessionId": "1", "sectionId": section_id, "subject": subject, "courseNumber": course, "sectionNumber": number, "history": history}


def payload(enr: dict[str, Any], *, component: str = "LEC") -> dict[str, Any]:
    return {
        "key": f"{enr['subject']}|{enr['courseNumber']}|{enr['sectionNumber']}",
        "term_id": "2268",
        "term_name": "Fall 2026",
        "fetched_at": "2026-09-19T00:00:00+00:00",
        "section": {
            "subject": enr["subject"],
            "catalog_number": enr["courseNumber"],
            "class_number": enr["sectionNumber"],
            "section_number": enr["sectionNumber"],
            "session_id": "1",
            "component": component,
            "course_key": f"{enr['subject']} {enr['courseNumber']}",
        },
        "enrollment": enr,
    }


THREE_SEGMENTS = [seg(0, 120, 100, 5), seg(135, 135, 101, 4), seg(330, 600, 101, 6)]


def test_history_to_rows_emits_segment_ends_and_crossings() -> None:
    rows, crossings = history_to_rows(enrollment("777", THREE_SEGMENTS), "2268")
    stamps = [r["run_started_at"] for r in rows]
    assert stamps == [T0 + timedelta(minutes=m) for m in (0, 120, 135, 330, 600)]  # a single-poll segment gives one row
    assert [r["enrolled_count"] for r in rows] == [100, 100, 101, 101, 101] and [r["waitlist_count"] for r in rows] == [5, 5, 4, 6, 6]
    assert all(r["observed"] and r["source"] == "berkeleytime" and r["section_id"] == "777" and r["term_id"] == "2268" for r in rows)
    assert [(c["minutes"], c["t0"], c["t1"]) for c in crossings] == [(15.0, T0 + timedelta(minutes=120), T0 + timedelta(minutes=135)), (195.0, T0 + timedelta(minutes=135), T0 + timedelta(minutes=330))]


def test_backfill_flows_censors_only_wide_crossings() -> None:
    panel, identity, crossings = build_panel([payload(enrollment("777", THREE_SEGMENTS))], "2268")
    assert list(crossings["wide"]) == [False, True]
    flows = backfill_flows(panel, crossings)
    assert len(flows) == 4
    # interval 0: inside the first segment, 120 minutes of observed stillness
    assert flows.at[0, "interval_min"] == 120.0 and not flows.at[0, "censored"] and int(flows.at[0, "admits"]) == 0
    # interval 1: the 15-minute crossing carries the change (one admit off a queue of 5)
    assert flows.at[1, "interval_min"] == 15.0 and not flows.at[1, "censored"] and int(flows.at[1, "admits"]) == 1 and flows.at[1, "rule"] == "admit"
    # interval 2: the 195-minute crossing is a Berkeleytime gap: change kept, interval censored
    assert flows.at[2, "interval_min"] == 195.0 and bool(flows.at[2, "censored"]) and int(flows.at[2, "wl_joins"]) == 2
    # interval 3: inside the last segment, long but not censored
    assert flows.at[3, "interval_min"] == 270.0 and not flows.at[3, "censored"]
    assert identity.iloc[0]["section_id"] == "777" and identity.iloc[0]["course_key"] == "COMPSCI 61A" and identity.iloc[0]["is_primary"]


def test_gap_report_shares_section_time_per_day() -> None:
    h = 60.0
    # T0 is 12:00 UTC. X goes dark from T0+12h (midnight) to T0+36h (the next midnight): exactly one UTC day; Y has no gaps
    x = enrollment("1", [seg(0, 12 * h, 50, 2), seg(36 * h, 60 * h, 50, 2)])
    y = enrollment("2", [seg(0, 60 * h, 50, 0)], subject="MATH", course="1A")
    _, identity, crossings = build_panel([payload(x), payload(y)], "2268")
    report = gap_report(crossings, identity).set_index("date")
    d0, d1, d2 = [(T0 + timedelta(days=k)).date().isoformat() for k in range(3)]
    assert list(report.index) == [d0, d1, d2]
    assert report.at[d1, "share_time_in_gap"] == pytest.approx(0.5) and report.at[d1, "sections_dark"] == 1 and report.at[d1, "sections_covered"] == 2
    assert report.at[d0, "share_time_in_gap"] == 0 and report.at[d2, "share_time_in_gap"] == 0 and report.at[d0, "sections_covered"] == 2


def test_recorded_data_c100_history_has_the_august_hole() -> None:
    fixture = json.loads((FIXTURES / "berkeleytime_enrollment_datac100_fa26.json").read_text())
    enr = fixture["data"]["enrollment"]
    panel, identity, crossings = build_panel([payload(enr)], "2268")
    assert identity.iloc[0]["section_id"] == "20882" and 580 <= len(panel) <= 1160
    assert int((crossings["minutes"] > 45).sum()) == 32 and int(crossings["wide"].sum()) == 9  # 180-minute rule
    report = gap_report(crossings, identity).set_index("date")
    dark_days = [d for d in report.index if "2026-08-20" <= d <= "2026-08-31"]
    assert len(dark_days) == 12 and (report.loc[dark_days, "share_time_in_gap"] == 1.0).all()
    assert report.at["2026-08-19", "share_time_in_gap"] < 0.1 and report.at["2026-09-01", "share_time_in_gap"] > 0.7
    flows = backfill_flows(panel, crossings)
    hole = crossings.loc[crossings["minutes"].idxmax()]
    assert hole["t0"].strftime("%Y-%m-%dT%H:%M") == "2026-08-19T22:45" and hole["t1"].strftime("%Y-%m-%dT%H:%M") == "2026-09-01T18:30"
    row = flows[flows["t0"] == hole["t0"]].iloc[0]
    assert bool(row["censored"]) and row["interval_min"] == pytest.approx(hole["minutes"])
    # the longest interval of all is observed stillness inside one segment, not a gap
    widest = flows.loc[flows["interval_min"].idxmax()]
    assert widest["interval_min"] > hole["minutes"] and not bool(widest["censored"])
    assert float(flows["censored"].mean()) < 0.1


def catalog_small() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "berkeleytime_getcatalog_small.json").read_text())["data"]["catalog"]


def test_select_sections_is_count_blind_nested_and_skips_self_study() -> None:
    catalog = catalog_small()
    ind = copy.deepcopy(catalog[0])
    ind["courseNumber"] = "199"
    ind["primarySection"]["component"] = "IND"
    catalog.append(ind)
    full = select_sections(catalog, FALL, seed=0)
    assert set(full["component"]) == {"LEC"} and len(full) == 3 and "COMPSCI|199|001" not in set(full["key"])
    one = select_sections(catalog, FALL, seed=0, limit=1)
    two = select_sections(catalog, FALL, seed=0, limit=2)
    assert list(one["key"]) == list(two["key"])[:1] and list(two["key"]) == list(full["key"])[:2]
    zeroed = copy.deepcopy(catalog)
    for entry in zeroed:
        entry["primarySection"]["enrollment"]["latest"].update({"waitlistedCount": 0, "enrolledCount": 0, "maxWaitlist": 0})
    assert list(select_sections(zeroed, FALL, seed=0)["key"]) == list(full["key"])
    assert list(select_sections(catalog, FALL, seed=1)["key"]) != list(full["key"]) or len(full) < 3


class FakeGateway:
    """Answers GetCatalog with the small fixture and GetEnrollment per section;
    one section fails until ``heal`` is called."""

    def __init__(self) -> None:
        ops = load_persisted_ops()
        self.names = {op.id: name for name, entries in ops.items() for op in entries}
        self.documents = {op.id: op.document for entries in ops.values() for op in entries}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failing = {"DATA"}
        histories = {
            "COMPSCI": enrollment("29147", THREE_SEGMENTS),
            "DATA": enrollment("20882", [seg(0, 60, 700, 30), seg(75, 200, 702, 28)], subject="DATA", course="C100"),
            "STAT": enrollment("30001", [seg(0, 500, 90, 3)], subject="STAT", course="134"),
        }
        self.histories = histories

    def heal(self) -> None:
        self.failing = set()

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any], None]:
        name = self.names[body["id"]]
        self.calls.append((name, dict(body["variables"]), body["id"]))
        if name == "GetCatalog":
            return 200, {"data": {"catalog": catalog_small()}}, None
        assert name == "GetEnrollment"
        if "seatReservationTypes" in self.documents[body["id"]]:
            # what the live gateway answered on 2026-09-19 for the second recorded GetEnrollment op
            return 200, {"errors": [{"message": 'Cannot query field "seatReservationTypes" on type "Enrollment".'}], "data": None}, None
        subject = body["variables"]["subject"]
        if subject in self.failing:
            return 200, {"errors": [{"message": "boom"}], "data": None}, None
        return 200, {"data": {"enrollment": self.histories[subject]}}, None


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


def test_fetch_is_resumable_and_records_failures(tmp_path: Path, gateway: FakeGateway) -> None:
    source = BerkeleytimeSource(transport=gateway, sleep=lambda s: None, rng=lambda: 0.0)
    cache = Cache(tmp_path / "raw")
    sleeps: list[float] = []
    first = fetch(source, FALL, cache, seed=0, sleep_s=2.0, sleep=sleeps.append)
    assert (first.selected, first.cached_before, first.fetched, first.failed) == (3, 0, 2, 1)
    assert list(first.failures) == ["DATA|C100|001"] and "boom" in first.failures["DATA|C100|001"]
    assert sleeps == [2.0, 2.0]  # one pause between each pair of requests, none before the first
    assert [c[0] for c in gateway.calls] == ["GetCatalog", "GetEnrollment", "GetEnrollment", "GetEnrollment"]
    # the recorded op the gateway rejects is never retried once a working one is found
    used = [c[2] for c in gateway.calls if c[0] == "GetEnrollment"]
    assert all("seatReservationTypes" not in gateway.documents[i] for i in used) and len(set(used)) == 1
    assert cache.has_catalog() and sorted(cache.section_keys()) == ["COMPSCI|61A|001", "STAT|134|001"]
    state = json.loads(cache.state_path.read_text())
    assert state["selection"] == {"seed": 0, "limit": None, "n": 3, "term_id": "2268"} and set(state["failed"]) == {"DATA|C100|001"}

    gateway.heal()
    gateway.calls.clear()
    sleeps.clear()
    second = fetch(source, FALL, cache, seed=0, sleep_s=2.0, sleep=sleeps.append)
    assert (second.selected, second.cached_before, second.fetched, second.failed) == (3, 2, 1, 0)
    assert [c[0] for c in gateway.calls] == ["GetEnrollment"] and gateway.calls[0][1]["subject"] == "DATA"
    assert sleeps == [] and json.loads(cache.state_path.read_text())["failed"] == {}
    third = fetch(source, FALL, cache, seed=0, sleep=sleeps.append)
    assert (third.cached_before, third.fetched) == (3, 0) and gateway.calls[-1][1]["subject"] == "DATA"  # nothing new requested

    saved = cache.read_section("DATA|C100|001")
    assert saved["enrollment"]["sectionId"] == "20882" and saved["section"]["course_key"] == "DATA C100" and saved["term_id"] == "2268"


def test_build_writes_panel_flows_gap_report_and_meta(tmp_path: Path, gateway: FakeGateway) -> None:
    gateway.heal()
    source = BerkeleytimeSource(transport=gateway, sleep=lambda s: None, rng=lambda: 0.0)
    cache = Cache(tmp_path / "raw")
    fetch(source, FALL, cache, sleep=lambda s: None)
    out = tmp_path / "built"
    summary = build(cache, FALL, out)
    assert summary.sections == 3 and summary.segments == 6 and summary.crossings_wide == 1 and summary.intervals > 0
    for name in ("panel.parquet", "identity.parquet", "gaps.parquet", "flows.parquet", "gap_report.csv", "meta.json"):
        assert (out / name).exists(), name
    panel, identity, flows, meta = load_backfill(out)
    assert meta["data_source"] == DATA_SOURCE and meta["term_id"] == "2268" and meta["sections"] == 3 and meta["gap_min"] == 180.0
    assert meta["share_crossings_over_45"] == pytest.approx(1 / 3, abs=1e-4) and set(meta["crossing_minutes_quantiles"]) == {"0.5", "0.75", "0.9", "0.99"}
    assert set(identity["section_id"]) == {"29147", "20882", "30001"} and len(panel) == summary.panel_rows
    assert flows["censored"].sum() == 1 and summary.share_censored == pytest.approx(float(flows["censored"].mean()), abs=1e-4)
    assert summary.worst_days and {"date", "share_time_in_gap"} <= set(summary.worst_days[0])

    # the build CLI runs offline on the cache
    assert main(["build", "--term", "Fall 2026", "--cache", str(cache.root), "--out", str(tmp_path / "cli")]) == 0
    assert (tmp_path / "cli" / "meta.json").exists()

    # analysis.run on the backfilled term labels the site data
    assert run_main(["--backfill-dir", str(out), "--out", str(tmp_path / "aout"), "--site-dir", str(tmp_path / "site")]) == 0
    site_meta = json.loads((tmp_path / "site" / "meta.json").read_text())
    assert site_meta["data_source"] == DATA_SOURCE and site_meta["term_id"] == "2268" and site_meta["backfill"]["sections"] == 3
    report = (tmp_path / "aout" / "2268" / "report.md").read_text()
    assert "berkeleytime_history" in report
    with pytest.raises(SystemExit):
        run_main(["--backfill-dir", str(out), "--term-id", "2272", "--out", str(tmp_path / "x"), "--no-site"])


def test_get_enrollment_falls_back_when_the_first_recorded_op_is_rejected(tmp_path: Path) -> None:
    from analysis.backfill import get_enrollment

    ops = load_persisted_ops()
    ids = [op.id for op in ops["GetEnrollment"]]
    rejected = {ids[0]}
    calls: list[str] = []

    def transport(url: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any], None]:
        calls.append(body["id"])
        if body["id"] in rejected:
            return 200, {"errors": [{"message": 'Cannot query field "x" on type "Enrollment".'}], "data": None}, None
        return 200, {"data": {"enrollment": enrollment("1", THREE_SEGMENTS)}}, None

    source = BerkeleytimeSource(transport=transport, sleep=lambda s: None, rng=lambda: 0.0)
    row = {"session_id": "1", "subject": "COMPSCI", "catalog_number": "61A", "section_number": "001"}
    assert get_enrollment(source, FALL, row)["sectionId"] == "1"
    assert calls == [ids[0], ids[1]]
    assert get_enrollment(source, FALL, row)["sectionId"] == "1"
    assert calls == [ids[0], ids[1], ids[1]]  # the working op is remembered

    rejected.update(ids)
    source2 = BerkeleytimeSource(transport=transport, sleep=lambda s: None, rng=lambda: 0.0)
    with pytest.raises(Exception, match="Cannot query field"):
        get_enrollment(source2, FALL, row)

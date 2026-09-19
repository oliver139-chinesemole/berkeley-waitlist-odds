"""PrioritySpec matching against the subject spellings the sources actually produce."""
from pathlib import Path

from scraper.sources.base import PrioritySpec

PRIORITY_FILE = Path(__file__).resolve().parents[1] / "config" / "priority_courses.txt"


def test_normalize_strips_spaces_inside_the_subject() -> None:
    assert PrioritySpec.normalize(" el  eng   16a ") == "ELENG 16A"
    assert PrioritySpec.normalize("POL SCI 1") == "POLSCI 1"
    assert PrioritySpec.normalize("COMPSCI 61A") == "COMPSCI 61A"
    assert PrioritySpec.normalize("compsci") == "COMPSCI"


def test_spaced_patterns_match_space_free_course_keys() -> None:
    spec = PrioritySpec.from_text("EL ENG *\nPOL SCI 1\nNUC ENG *\nCOMPSCI *\nMATH 1*\n")
    assert spec.patterns == ("ELENG *", "POLSCI 1", "NUCENG *", "COMPSCI *", "MATH 1*")
    assert spec.matches("ELENG 16A")
    assert spec.matches("EL ENG 16A")  # sis_api / berkeleytime raw spelling, should it ever leak through
    assert spec.matches("POLSCI 1") and not spec.matches("POLSCI 2")
    assert spec.matches("NUCENG 10")
    assert spec.matches("COMPSCI 61A")
    assert spec.matches("MATH 1A") and spec.matches("MATH 16A") and not spec.matches("MATH 53")


def test_bare_subject_pattern_matches_every_catalog_number() -> None:
    spec = PrioritySpec.from_text("COMPSCI\nELENG\n")
    assert spec.matches("COMPSCI 61A") and spec.matches("ELENG 16A")
    assert not spec.matches("EECS 16A")


def test_sha_is_of_the_raw_text() -> None:
    a = PrioritySpec.from_text("EL ENG *\n")
    b = PrioritySpec.from_text("ELENG *\n")
    assert a.patterns == b.patterns and a.sha != b.sha


def test_shipped_priority_file_matches_live_site_spellings() -> None:
    """Course keys as classes.berkeley.edu listed them on 2026-09-18 (Fall 2026)."""
    spec = PrioritySpec.from_file(PRIORITY_FILE)
    for key in (
        "COMPSCI 61A", "DATA C100", "STAT 134", "EECS 16A", "ELENG 16A", "MATH 1A", "MATH 53",
        "ECON 1", "ECON 100A", "PSYCH 1", "UGBA 10", "PHYSICS 7A", "CHEM 1A", "CHEM 3A", "MCELLBI 32",
        "INTEGBI 131", "POLSCI 1", "SOCIOL 1", "PHILOS 2", "ENGLISH R1A", "COLWRIT R4A", "L&S 1",
        "INDENG 24", "NUCENG 10",
    ):
        assert spec.matches(key), key
    for key in ("ECON 2", "UGBA 101", "AEROENG 10", "PSYCH 2", "POLSCI 2", "AFRICAM R1B"):
        assert not spec.matches(key), key

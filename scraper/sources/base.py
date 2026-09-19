"""Shared types for data sources. See docs/DESIGN_A2.md section 5."""
from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from scraper.schema import SnapshotRow

SEMESTER_CODE = {"Spring": "2", "Summer": "5", "Fall": "8"}


class TermNotPublished(RuntimeError):
    """The source does not list this term yet (Spring schedules publish in early October)."""


class ParseError(ValueError):
    """A response was fetched but did not contain the expected structure."""


@dataclass(frozen=True)
class TermSpec:
    name: str  # "Spring 2027"
    year: int  # 2027
    semester: str  # "Spring" | "Summer" | "Fall"
    sis_term_id: str  # "2272"

    @property
    def berkeleytime_semester(self) -> str:
        return self.semester

    @staticmethod
    def from_name(name: str) -> "TermSpec":
        m = re.fullmatch(r"\s*(Spring|Summer|Fall)\s+(\d{4})\s*", name, flags=re.I)
        if not m:
            raise ValueError(f"term name must look like 'Spring 2027', got {name!r}")
        semester = m.group(1).capitalize()
        year = int(m.group(2))
        sis_term_id = f"2{year % 100:02d}{SEMESTER_CODE[semester]}"
        return TermSpec(name=f"{semester} {year}", year=year, semester=semester, sis_term_id=sis_term_id)


@dataclass(frozen=True)
class PrioritySpec:
    """Course patterns that get the 30-minute cadence on slow sources.

    Patterns are `SUBJECT` or `SUBJECT CATALOG` where CATALOG may end in `*`.
    Matching is case-insensitive on the course_key "SUBJECT CATALOG" and ignores
    spaces inside the subject: "EL ENG *" matches "ELENG 16A", which is how
    classes.berkeley.edu (and the schema) spell it. A bare multi-word subject is
    ambiguous ("EL ENG" reads as subject EL, catalog ENG): write it without
    spaces ("ELENG") or with a wildcard ("EL ENG *").
    """

    patterns: tuple[str, ...]
    sha: str  # sha256 of the source file content, "" when built in memory

    @staticmethod
    def from_file(path: Path | str) -> "PrioritySpec":
        text = Path(path).read_text(encoding="utf-8")
        return PrioritySpec.from_text(text)

    @staticmethod
    def from_text(text: str) -> "PrioritySpec":
        pats = []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                pats.append(PrioritySpec.normalize(line))
        return PrioritySpec(patterns=tuple(pats), sha=hashlib.sha256(text.encode("utf-8")).hexdigest())

    @staticmethod
    def normalize(course_key: str) -> str:
        """Upper-case, single-spaced, spaces removed from the subject part.

        ``"el eng 16a"`` and ``"ELENG 16A"`` both become ``"ELENG 16A"``; a value
        without a space (bare subject) is only upper-cased.
        """
        key = " ".join(course_key.upper().split())
        if " " not in key:
            return key
        subject, catalog = key.rsplit(" ", 1)
        return f"{subject.replace(' ', '')} {catalog}"

    def rank(self, course_key: str) -> int | None:
        """Index of the first pattern that matches ``course_key``, or None.

        Lower is more important: the priority file is ordered, and a run whose
        time budget runs out drops the highest ranks first.
        """
        key = self.normalize(course_key)
        subject = key.rsplit(" ", 1)[0] if " " in key else key
        for index, pat in enumerate(self.patterns):
            if " " in pat:
                if fnmatch.fnmatchcase(key, pat):
                    return index
            elif pat == subject:
                return index
        return None

    def matches(self, course_key: str) -> bool:
        return self.rank(course_key) is not None


def shard_of(section_id: str, n_shards: int) -> int:
    """Stable shard assignment for rotating full sweeps."""
    if n_shards <= 0:
        raise ValueError("n_shards must be positive")
    digest = hashlib.sha1(section_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % n_shards


@dataclass
class FetchResult:
    rows: list[SnapshotRow]
    missing_ids: list[str] = field(default_factory=list)
    universe_ids: set[str] | None = None  # every id the source considers in scope; None if unknown
    scope: str = "full"  # "full" | "priority"
    shard: str = ""  # "k/n" when a rotating shard was included, else ""
    priority_sha: str = ""

    @property
    def observed_ids(self) -> list[str]:
        return [r["section_id"] for r in self.rows]


class Source(Protocol):
    name: str

    def fetch(
        self,
        term: TermSpec,
        *,
        priority: PrioritySpec | None = None,
        shard: tuple[int, int] | None = None,
        time_budget_s: float | None = None,
        limit: int | None = None,
    ) -> FetchResult: ...

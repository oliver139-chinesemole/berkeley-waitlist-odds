"""The workflow files are the deployment knobs nothing else pins: the request policy and
budget scrape.yml passes to the fetch (DESIGN_A2 section 16) and the site-data guard in
analysis.yml (docs/DATA_LOG.md, 2026-09-23 decision rows). Text checks on purpose: no YAML
dependency, and a flag that moves out of the ``args=(...)`` line should fail loudly."""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _fetch_args() -> list[str]:
    text = (WORKFLOWS / "scrape.yml").read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip().startswith("args=(")]
    assert len(lines) == 1, lines
    m = re.fullmatch(r"\s*args=\((.*)\)", lines[0])
    assert m, lines[0]
    return m.group(1).split()


def test_scrape_workflow_passes_the_budget_shards_and_request_policy() -> None:
    args = _fetch_args()
    for flag, value in (
        ("--time-budget-s", "1380"),
        ("--n-shards", "12"),
        ("--min-interval-s", "0.5"),
        ("--max-concurrency", "4"),
    ):
        assert flag in args, (flag, args)
        assert args[args.index(flag) + 1] == value, (flag, args)


def test_analysis_workflow_replaces_site_data_only_for_spring_2027() -> None:
    text = (WORKFLOWS / "analysis.yml").read_text(encoding="utf-8")
    guard = '[ "$EVENTS" -ge 10 ] && [ "${{ steps.term.outputs.term_id }}" = "2272" ]'
    assert text.count(guard) == 1, guard
    assert 'if [ "$EVENTS" -ge 10 ]; then' not in text

"""The workflow files are the deployment knobs nothing else pins: the request policy and
budget scrape.yml passes to the fetch (DESIGN_A2 section 16) and the site-data guard in
analysis.yml (docs/DATA_LOG.md decision rows). Text checks on purpose: no YAML dependency,
and a flag that moves out of the ``args=(...)`` line should fail loudly. The swap step's
shell block is also run for real: rendered the way Actions renders ``${{ }}`` and run with
the runner's ``bash -eo pipefail`` in a directory laid out like the job's."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

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


def _dispatch_input(text: str, name: str) -> dict[str, str]:
    """The fields of one ``workflow_dispatch`` input, read by indentation."""
    lines = text.splitlines()
    start = lines.index("  workflow_dispatch:")
    end = next(k for k in range(start + 1, len(lines)) if lines[k] and not lines[k].startswith(" "))
    k = next(k for k in range(start, end) if lines[k].strip() == f"{name}:")
    indent = len(lines[k]) - len(lines[k].lstrip())
    fields: dict[str, str] = {}
    for line in lines[k + 1 : end]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        key, _, value = line.strip().partition(":")
        fields[key] = value.strip().strip("'\"")
    return fields


def test_analysis_workflow_replaces_site_data_only_on_a_publish_own_dispatch_for_spring_2027() -> None:
    text = (WORKFLOWS / "analysis.yml").read_text(encoding="utf-8")
    guard = 'if [ "$EVENTS" -ge 10 ] && [ "${{ steps.term.outputs.term_id }}" = "2272" ] && [ "${{ inputs.publish_own }}" = "true" ]; then'
    assert [l.strip() for l in text.splitlines() if l.strip().startswith('if [ "$EVENTS"')] == [guard]
    assert text.count("rm -rf site/data") == 1
    publish_own = _dispatch_input(text, "publish_own")
    assert publish_own["type"] == "boolean" and publish_own["default"] == "false", publish_own


def test_weekly_analysis_run_censors_long_gaps_and_writes_only_the_candidate() -> None:
    """The backfill censors intervals over 180 min; the weekly own-data run must too: a shard
    section is seen about every six hours (one of 12 shards per 30-min run), and without the
    flag the position walk reads such an interval's net change as ordinary flow. The run
    writes the candidate, never site/data, and keeps the published pre-registration labels
    when they describe the same term and source (analysis.run.carried_meta)."""
    text = (WORKFLOWS / "analysis.yml").read_text(encoding="utf-8")
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("python -m analysis.run ")]
    assert len(lines) == 1, lines
    args = shlex.split(lines[0].split(" 2>&1")[0])
    for flag, value in (("--max-interval-min", "180"), ("--site-dir", "analysis/out/site_candidate"), ("--meta-from", "site/data/meta.json")):
        assert flag in args and args[args.index(flag) + 1] == value, (flag, args)


def _run_blocks(text: str) -> list[str]:
    """Every ``run: |`` block of a workflow, dedented."""
    lines = text.splitlines()
    blocks = []
    for k, line in enumerate(lines):
        if line.strip() != "run: |":
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for nxt in lines[k + 1 :]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            body.append(nxt)
        blocks.append(textwrap.dedent("\n".join(body)).strip() + "\n")
    return blocks


def _render(script: str, values: dict[str, str]) -> str:
    """Substitute ``${{ expr }}`` as Actions does before bash sees the script; an
    expression the test does not know fails loudly."""

    def sub(m: re.Match) -> str:
        expr = m.group(1).strip()
        assert expr in values, f"the swap step uses an expression this test does not render: {expr}"
        return values[expr]

    return re.sub(r"\$\{\{(.*?)\}\}", sub, script)


PUBLISHED_META = {"term_id": "2262", "term_name": "Spring 2026", "data_source": "berkeleytime_history", "events": 299826, "prereg_commit": "7f348ed", "prereg_date": "2026-09-21", "titles_file": "titles.json"}
CANDIDATE_META = {"term_id": "2272", "term_name": "Spring 2027", "data_source": "own_snapshots", "events": 12}


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")


def _tree(root: Path) -> dict[str, bytes]:
    return {str(f.relative_to(root)): f.read_bytes() for f in sorted(root.rglob("*")) if f.is_file()}


def _job_dir(tmp_path: Path, candidate_meta: dict, candidate_titles: bool = False, published_titles: bool = True) -> Path:
    """A job checkout as the swap step finds it: the published site/data (Spring 2026, with
    backtest.json, the pre-registration and, unless ``published_titles`` is false, titles.json)
    and the run's own-data candidate."""
    job = tmp_path / "job"
    site = job / "site" / "data"
    _write(site / "meta.json", PUBLISHED_META if published_titles else {k: v for k, v in PUBLISHED_META.items() if k != "titles_file"})
    _write(site / "index.json", {"term_id": "2262", "courses": [{"key": "COMPSCI 61A"}]})
    _write(site / "courses" / "COMPSCI.json", {"subject": "COMPSCI", "courses": {}})
    _write(site / "backtest.json", {"term_id": "2268", "term_name": "Fall 2026", "runs": []})
    if published_titles:
        _write(site / "titles.json", {"catalog_term_id": "2272", "courses": {"COMPSCI 61A": {"title": "Structure and Interpretation of Computer Programs", "instructors": []}}})
    cand = job / "analysis" / "out" / "site_candidate"
    _write(cand / "meta.json", candidate_meta)
    _write(cand / "index.json", {"term_id": "2272", "courses": [{"key": "MATH 1A"}]})
    _write(cand / "courses" / "MATH.json", {"subject": "MATH", "courses": {}})
    if candidate_titles:
        _write(cand / "titles.json", {"catalog_term_id": "2272", "courses": {"MATH 1A": {"title": "Calculus", "instructors": []}}})
    return job


def _run_swap(job: Path, *, term_id: str, publish_own: str) -> subprocess.CompletedProcess:
    text = (WORKFLOWS / "analysis.yml").read_text(encoding="utf-8")
    blocks = [b for b in _run_blocks(text) if "rm -rf site/data" in b]
    assert len(blocks) == 1, blocks
    script = job / "swap.sh"
    script.write_text(_render(blocks[0], {"steps.term.outputs.term_id": term_id, "inputs.publish_own": publish_own}), encoding="utf-8")
    shim = job / "bin"
    shim.mkdir()
    (shim / "python").symlink_to(sys.executable)
    env = {**os.environ, "PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"}
    # the runner's `shell: bash` is `bash --noprofile --norc -eo pipefail {0}`
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)], cwd=job, env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize(
    ("trigger", "term_id", "publish_own", "events"),
    [
        ("schedule (inputs.publish_own renders empty)", "2272", "", 12),
        ("dispatch without the input (default false)", "2272", "false", 12),
        ("publish_own=true but the Fall 2026 test term", "2268", "true", 12),
        ("publish_own=true but fewer than 10 clearings", "2272", "true", 9),
    ],
)
def test_swap_step_keeps_the_published_site_data(tmp_path: Path, trigger: str, term_id: str, publish_own: str, events: int) -> None:
    job = _job_dir(tmp_path, {**CANDIDATE_META, "events": events})
    before = _tree(job / "site" / "data")
    proc = _run_swap(job, term_id=term_id, publish_own=publish_own)
    assert proc.returncode == 0, (trigger, proc.stdout, proc.stderr)
    assert _tree(job / "site" / "data") == before, trigger
    assert "keeping the published site/data" in proc.stdout and "berkeleytime_history Spring 2026 299826 clearings" in proc.stdout, proc.stdout


def test_swap_step_on_purpose_publishes_the_candidate_and_keeps_backtest_and_titles(tmp_path: Path) -> None:
    job = _job_dir(tmp_path, CANDIDATE_META)
    published = _tree(job / "site" / "data")
    proc = _run_swap(job, term_id="2272", publish_own="true")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    after = _tree(job / "site" / "data")
    # the candidate replaces everything it writes, the stale subject file goes...
    assert sorted(after) == ["backtest.json", "courses/MATH.json", "index.json", "meta.json", "titles.json"]
    assert json.loads(after["index.json"]) == {"term_id": "2272", "courses": [{"key": "MATH 1A"}]}
    # ...the two files the export does not regenerate come across the rm unchanged, and the
    # kept titles file is named in the new meta so the pages read it
    assert after["backtest.json"] == published["backtest.json"] and after["titles.json"] == published["titles.json"]
    assert json.loads(after["meta.json"]) == {**CANDIDATE_META, "titles_file": "titles.json"}
    assert "site/data replaced with the own-data estimates" in proc.stdout and "backtest.json titles.json" in proc.stdout, proc.stdout


def test_swap_step_without_a_published_titles_file_keeps_only_the_backtest(tmp_path: Path) -> None:
    """main's state until the titles PR lands: no titles.json in site/data, none in the candidate."""
    job = _job_dir(tmp_path, CANDIDATE_META, published_titles=False)
    published = _tree(job / "site" / "data")
    proc = _run_swap(job, term_id="2272", publish_own="true")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    after = _tree(job / "site" / "data")
    assert "titles.json" not in after and after["backtest.json"] == published["backtest.json"]
    assert json.loads(after["meta.json"]) == CANDIDATE_META  # no titles_file
    replaced = [l for l in proc.stdout.splitlines() if l.startswith("site/data replaced")]
    assert len(replaced) == 1 and replaced[0].endswith("kept from the published site/data: backtest.json"), proc.stdout


def test_swap_step_prefers_the_candidates_own_titles(tmp_path: Path) -> None:
    candidate_meta = {**CANDIDATE_META, "titles_file": "titles.json"}
    job = _job_dir(tmp_path, candidate_meta, candidate_titles=True)
    published = _tree(job / "site" / "data")
    proc = _run_swap(job, term_id="2272", publish_own="true")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    after = _tree(job / "site" / "data")
    assert json.loads(after["titles.json"])["courses"] == {"MATH 1A": {"title": "Calculus", "instructors": []}}
    assert after["backtest.json"] == published["backtest.json"]
    assert json.loads(after["meta.json"]) == candidate_meta


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads a mode-000 file")
def test_swap_step_fails_rather_than_commit_a_half_copied_site(tmp_path: Path) -> None:
    """A copy that fails after the rm must fail the step (the runner's `bash -e`), so the
    commit step never runs on a site/data the candidate did not fully replace."""
    job = _job_dir(tmp_path, CANDIDATE_META)
    unreadable = job / "analysis" / "out" / "site_candidate" / "courses" / "MATH.json"
    unreadable.chmod(0)
    try:
        proc = _run_swap(job, term_id="2272", publish_own="true")
    finally:
        unreadable.chmod(0o644)
    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert "site/data replaced" not in proc.stdout

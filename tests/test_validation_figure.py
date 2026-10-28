"""Tests for analysis.validation_figure: the reconstruction-validation PNG.

``make_figure`` runs the full default simulation (40 sections, 14 days) by
design, which is too slow for a test; ``sim_config`` lets a test shrink it
without touching the module's committed behaviour (no argument => the same
``SimConfig(seed=seed)`` as before this test existed).
"""
from __future__ import annotations

from pathlib import Path

from analysis.synthetic import SimConfig
from analysis.validation_figure import OUT_DIR, make_figure


def test_default_output_path_is_site_figures() -> None:
    # #50 moved the committed figure here; the README and the methodology page point at it.
    assert OUT_DIR == Path("site/figures")


def test_make_figure_writes_a_non_trivial_png_at_the_expected_name(tmp_path: Path) -> None:
    # n_sections=6, days=3 at seeds 1 and 3 are checked (not guessed) to leave enough
    # cleared students after the module's own filtering; smaller configs can leave zero
    # usable points, and the module's `ax2.scatter(pts[:, 0], pts[:, 1], ...)` raises
    # IndexError on the resulting empty 1-D array. Shrink further only after re-checking that.
    path = make_figure(tmp_path, seed=1, sim_config=SimConfig(seed=1, n_sections=6, days=3))
    assert path == tmp_path / "reconstruction_validation.png"
    assert path.exists()
    assert path.stat().st_size > 5_000  # a real two-panel figure, not a blank/near-empty PNG
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_make_figure_creates_missing_output_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    path = make_figure(nested, seed=3, sim_config=SimConfig(seed=3, n_sections=6, days=3))
    assert path.exists() and path.parent == nested

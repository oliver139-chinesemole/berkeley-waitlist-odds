"""Build a servable copy of the site with synthetic data for the browser smoke test.

    python tests/site/export_fixture.py <output dir>

Copies site/ into <output dir> and writes site/data from the synthetic cohort
tests/test_survival.py defines (the same fixture tests/test_site.py renders),
plus a backtest.json from a synthetic report directory, so every page has
something to show. Nothing here is real data; the smoke test only checks that
the pages render, stay inside the viewport and pass axe-core.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analysis.export import export_site_tables  # noqa: E402
from analysis.export_backtest import export_backtest  # noqa: E402
from tests.test_export_backtest import make_reports  # noqa: E402
from tests.test_site import CAL  # noqa: E402
from tests.test_survival import synthetic_cohort  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    out = Path(argv[0])
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    shutil.rmtree(out / "data", ignore_errors=True)
    export_site_tables(synthetic_cohort(), CAL, out / "data", n_boot=20)
    reports = make_reports(out / "_reports")
    export_backtest(reports, out / "data" / "backtest.json", term_id=CAL.term_id, term_name=CAL.name)
    shutil.rmtree(out / "_reports")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

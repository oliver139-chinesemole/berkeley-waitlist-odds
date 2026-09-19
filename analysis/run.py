"""One command from raw Parquet to tables, figures, site JSON and a report.

See docs/DESIGN_A5.md section 6. ``run_analysis`` takes in-memory inputs so
it can be tested on simulated data; ``main`` loads them from a checkout of
the data branch.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from analysis.calendar import TermCalendar, calendar_for
from analysis.cohort import build_cohort
from analysis.export import export_site_tables
from analysis.figures import plot_calibration, plot_km
from analysis.flows import interval_flows, summary as flows_summary
from analysis.panel import Outage, load_panel, parse_data_log, section_identity
from analysis.positions import SCENARIOS
from analysis.profile import profile_panel
from analysis.survival import STRATA, fit_cox_with_ph_check, headline, headline_median, km_by, km_table, logrank_table, out_of_sample

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    out_dir: Path
    flows_summary: dict
    cohort_rows: dict[str, int]
    km_tables: dict[str, pd.DataFrame]
    logrank: dict[str, pd.DataFrame]
    cox_summary: pd.DataFrame | None
    ph: pd.DataFrame | None
    cox_stratified_summary: pd.DataFrame | None
    sensitivity: pd.DataFrame
    out_of_sample: dict
    headline: dict
    site_files: tuple[Path, Path] | None
    figures: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _df_to_md(frame: pd.DataFrame, max_rows: int = 40) -> str:
    if frame is None or len(frame) == 0:
        return "_none_"
    shown = frame.head(max_rows).copy()
    for col in shown.columns:
        if shown[col].dtype.kind == "f":
            shown[col] = shown[col].map(lambda v: f"{v:.3g}" if pd.notna(v) else "")
    cols = [str(c) for c in shown.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in shown.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.tolist()) + " |")
    if len(frame) > max_rows:
        lines.append(f"| ... {len(frame) - max_rows} more rows | " + " | ".join("" for _ in cols[1:]) + " |")
    return "\n".join(lines)


def run_analysis(
    panel: pd.DataFrame,
    identity: pd.DataFrame,
    calendar: TermCalendar,
    out_dir: Path | str,
    *,
    outages: list[Outage] = (),
    max_interval_min: float | None = None,
    positions=(1, 3, 5, 10, 20, 40),
    join_every_min: float = 240,
    min_cohort_rows: int = 100,
    site_dir: Path | str | None = None,
) -> AnalysisResult:
    out_dir = Path(out_dir) / calendar.term_id
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / "figures"
    notes: list[str] = []

    prof = profile_panel(panel)
    (out_dir / "profile.md").write_text(prof.as_markdown(), encoding="utf-8")
    logger.info("profile: %d runs, %d sections, observed share %.3f", prof.runs, prof.sections, prof.observed_share)
    notes.extend(prof.notes)

    flows = interval_flows(panel, outages=list(outages), max_interval_min=max_interval_min)
    flows.to_parquet(out_dir / "flows.parquet", index=False)
    fsum = flows_summary(flows)
    logger.info("flows: %s", fsum)

    cohorts = {s: build_cohort(flows, identity, calendar, scenario=s, positions=positions, join_every_min=join_every_min) for s in SCENARIOS}
    for s, c in cohorts.items():
        c.to_parquet(out_dir / f"cohort_{s}.parquet", index=False)
    cohort = cohorts["central"]
    cohort_rows = {s: int(len(c)) for s, c in cohorts.items()}
    events = int(cohort["event"].sum()) if len(cohort) else 0
    logger.info("cohort (central): %d rows, %d events", len(cohort), events)

    km_tables: dict[str, pd.DataFrame] = {}
    logrank: dict[str, pd.DataFrame] = {}
    figures: list[Path] = []
    enough = len(cohort) >= min_cohort_rows and events >= 10
    if enough:
        for by in STRATA:
            fitters = km_by(cohort, by)
            if not fitters:
                continue
            km_tables[by] = km_table(fitters)
            km_tables[by].to_csv(out_dir / f"km_{by}.csv", index=False)
            logrank[by] = logrank_table(cohort, by)
            logrank[by].to_csv(out_dir / f"logrank_{by}.csv", index=False)
            figures.append(plot_km(fitters, by, fig_dir / f"km_{by}.png", max_days=min(60.0, float(cohort["duration_days"].max()))))
        lower_p1 = cohort[(cohort["level"] == "lower") & (cohort["phase"] == "phase1")]
        if len(lower_p1) >= min_cohort_rows and lower_p1["event"].sum() >= 10:
            figures.append(plot_km(km_by(lower_p1, "position_bucket"), "position_bucket", fig_dir / "hero.png", title="Lower-division courses, Phase 1 joiners: time to clear by position"))
    else:
        notes.append(f"cohort too small for models: {len(cohort)} rows, {events} events (need {min_cohort_rows} rows and 10 events)")

    cox_summary = ph = cox_strat = None
    if enough:
        try:
            first, ph, refit = fit_cox_with_ph_check(cohort)
            cox_summary = first.summary
            cox_summary.to_csv(out_dir / "cox.csv")
            ph.to_csv(out_dir / "cox_ph_test.csv", index=False)
            if refit is not None:
                cox_strat = refit.summary
                cox_strat.to_csv(out_dir / "cox_stratified.csv")
                notes.append(f"PH assumption failed for {sorted(set(str(c).split('=')[0] for c in ph.loc[ph['violates'], 'covariate']))}; stratified refit written")
            cox_for_headline = first
        except Exception as exc:  # noqa: BLE001 - a singular fit must not take the whole report down
            notes.append(f"Cox fit failed: {type(exc).__name__}: {exc}")
            cox_for_headline = None
    else:
        cox_for_headline = None

    sens = pd.DataFrame({"scenario": list(cohorts), "median_days_pos10_lower_phase1": [headline_median(c) for c in cohorts.values()], "rows": list(cohort_rows.values())})
    sens.to_csv(out_dir / "sensitivity.csv", index=False)

    oos = out_of_sample(cohort) if enough else {"train_rows": 0, "test_rows": 0, "concordance": float("nan"), "brier_14d": float("nan"), "brier_rows": 0, "calibration": pd.DataFrame()}
    if len(oos["calibration"]):
        oos["calibration"].to_csv(out_dir / "calibration.csv", index=False)
        figures.append(plot_calibration(oos["calibration"], fig_dir / "calibration.png", brier=oos["brier_14d"]))

    head = headline(cohort, cox_for_headline) if enough else {}
    site_files = None
    if site_dir is not None and len(cohort):
        # meta["cohort_rows"] stays the integer the exporter writes (the page prints it);
        # the per-scenario counts go under their own key.
        site_files = export_site_tables(cohort, calendar, site_dir, meta={"flows": fsum, "cohort_rows_by_scenario": cohort_rows})

    report = [
        f"# Waitlist analysis report: {calendar.name} (term {calendar.term_id})",
        "",
        "Generated by `python -m analysis.run`. Every number here reproduces from the data branch; nothing is edited by hand.",
        "",
        prof.as_markdown(),
        "",
        "## Flows",
        "",
        "`" + json.dumps(fsum) + "`",
        "",
        "## Cohort",
        "",
        f"Rows per scenario: `{json.dumps(cohort_rows)}`; events (central): {events}.",
        "",
    ]
    for note in notes:
        report.append(f"- Note: {note}")
    if notes:
        report.append("")
    for by, table in km_tables.items():
        report += [f"## Kaplan-Meier by {by}", "", _df_to_md(table), "", f"Log-rank (pairwise, {int(logrank[by]['comparisons'].iloc[0]) if len(logrank[by]) else 0} comparisons):", "", _df_to_md(logrank[by]), ""]
    if cox_summary is not None:
        report += ["## Cox proportional hazards", "", _df_to_md(cox_summary.reset_index()[["covariate", "coef", "exp(coef)", "se(coef)", "p"]] if "covariate" in cox_summary.reset_index().columns else cox_summary.reset_index()), "", "PH test:", "", _df_to_md(ph), ""]
        if cox_strat is not None:
            report += ["Stratified refit:", "", _df_to_md(cox_strat.reset_index()), ""]
    report += ["## Sensitivity to the drop scenario", "", _df_to_md(sens), ""]
    report += ["## Out of sample (fit on Phase 1 joins, score Phase 2 joins)", "", f"train rows {oos['train_rows']}, test rows {oos['test_rows']}, concordance {oos['concordance']:.3f}, Brier(14 d) {oos['brier_14d']:.3f} on {oos['brier_rows']} rows", "", _df_to_md(oos["calibration"]), ""]
    if head:
        report += ["## Headline", ""]
        for key, value in head.items():
            if isinstance(value, pd.DataFrame):
                report += [f"### {key}", "", _df_to_md(value), ""]
            elif isinstance(value, pd.Series):
                report += [f"### {key}", "", _df_to_md(value.reset_index()), ""]
            else:
                report.append(f"- {key}: `{json.dumps(value)}`")
        report.append("")
    if figures:
        report += ["## Figures", ""] + [f"- {p.relative_to(out_dir)}" for p in figures] + [""]
    (out_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    logger.info("wrote %s", out_dir / "report.md")
    return AnalysisResult(
        out_dir=out_dir,
        flows_summary=fsum,
        cohort_rows=cohort_rows,
        km_tables=km_tables,
        logrank=logrank,
        cox_summary=cox_summary,
        ph=ph,
        cox_stratified_summary=cox_strat,
        sensitivity=sens,
        out_of_sample=oos,
        headline=head,
        site_files=site_files,
        figures=figures,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Reproduce every table, figure and site file from the data branch.")
    p.add_argument("--data-root", type=Path, default=Path("./data-branch"))
    p.add_argument("--term-id", required=True)
    p.add_argument("--out", type=Path, default=Path("analysis/out"))
    p.add_argument("--site-dir", type=Path, default=Path("site/data"))
    p.add_argument("--data-log", type=Path, default=Path("docs/DATA_LOG.md"))
    p.add_argument("--max-interval-min", type=float, default=None)
    p.add_argument("--join-every-min", type=float, default=240)
    p.add_argument("--no-site", action="store_true", help="do not write site/data")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    calendar = calendar_for(args.term_id)
    panel = load_panel(args.data_root, args.term_id)
    identity = section_identity(args.data_root, args.term_id)
    outages = parse_data_log(args.data_log) if args.data_log.exists() else []
    result = run_analysis(
        panel,
        identity,
        calendar,
        args.out,
        outages=outages,
        max_interval_min=args.max_interval_min,
        join_every_min=args.join_every_min,
        site_dir=None if args.no_site else args.site_dir,
    )
    print(json.dumps({"out": str(result.out_dir), "flows": result.flows_summary, "cohort_rows": result.cohort_rows, "notes": result.notes, "figures": [str(f) for f in result.figures]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

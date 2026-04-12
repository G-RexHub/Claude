import sys
from pathlib import Path

import click

from . import tracker
from . import config as cfg


@click.group()
@click.option(
    "--state-file",
    default=None,
    metavar="PATH",
    help="Override the path to tracker_state.json.",
)
@click.option(
    "--config-file",
    default=None,
    metavar="PATH",
    help="Override the path to orchestrations.json.",
)
@click.option(
    "--sr-registry",
    default=None,
    metavar="PATH",
    help="Override the path to service_requests.json.",
)
@click.pass_context
def cli(ctx, state_file, config_file, sr_registry):
    """DCC Service Request Tracker — anomaly threshold calculator.

    Tracks service requests sent per smart orchestration and calculates
    Anomaly Detection Threshold values over an 8-month period.
    """
    ctx.ensure_object(dict)
    ctx.obj["state_path"] = Path(state_file) if state_file else cfg.get_state_path()
    ctx.obj["config_path"] = Path(config_file) if config_file else cfg.get_config_path()
    ctx.obj["sr_registry_path"] = Path(sr_registry) if sr_registry else cfg.get_sr_registry_path()


def _load(ctx) -> tuple[dict, dict, dict, dict, Path]:
    """Helper: load state + orchestrations + SR registry.

    Returns (state, all_orchs, sr_registry, state_path).
    """
    state_path: Path = ctx.obj["state_path"]
    config_path: Path = ctx.obj["config_path"]
    sr_registry_path: Path = ctx.obj["sr_registry_path"]

    try:
        config_orchs = tracker.load_orchestrations(config_path)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    state = tracker.load_state(state_path)
    all_orchs = tracker.merge_orchestrations(config_orchs, state["orchestration_overrides"])
    sr_registry = tracker.load_sr_registry(sr_registry_path)
    return state, all_orchs, sr_registry, state_path


@cli.command()
@click.argument("orchestration_name")
@click.option(
    "--count",
    default=1,
    show_default=True,
    type=int,
    help="Number of runs to log.",
)
@click.pass_context
def log(ctx, orchestration_name, count):
    """Log that ORCHESTRATION_NAME ran (increments actual run count)."""
    state, all_orchs, _, state_path = _load(ctx)
    try:
        tracker.log_run(state, orchestration_name, all_orchs, count=count)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    tracker.save_state(state, state_path)
    total = state["actual_counts"][orchestration_name]
    click.echo(
        f"Logged {count} run(s) for '{orchestration_name}'. "
        f"Total actual runs: {total}"
    )


@cli.command("set-estimate")
@click.argument("orchestration_name")
@click.argument("estimated_runs", type=int)
@click.pass_context
def set_estimate(ctx, orchestration_name, estimated_runs):
    """Set the estimated total runs for ORCHESTRATION_NAME over 8 months."""
    state, all_orchs, _, state_path = _load(ctx)
    try:
        tracker.set_estimate(state, orchestration_name, estimated_runs, all_orchs)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    tracker.save_state(state, state_path)
    click.echo(
        f"Estimate for '{orchestration_name}' set to {estimated_runs:,} runs over 8 months."
    )


@cli.command("list")
@click.pass_context
def list_cmd(ctx):
    """Display all orchestrations with SR counts, estimates, and actual runs."""
    state, all_orchs, _, _ = _load(ctx)
    table = tracker.format_list_table(
        all_orchs,
        state["estimates"],
        state["actual_counts"],
    )
    click.echo(table)


@cli.command()
@click.option(
    "--output-dir",
    default=None,
    metavar="PATH",
    help="Override the reports output directory.",
)
@click.pass_context
def report(ctx, output_dir):
    """Calculate anomaly detection thresholds and write a CSV report.

    \b
    All known DCC service request types are included in the report.
    SR types not assigned to any orchestration appear with 0 threshold.

    \b
    Threshold levels per service request type:
      Base             = total_requests / 243.5 days
      Adapter Warning  = base x 1.50  (+50%)
      Adapter Quarant. = base x 1.75  (+75%)
      DCC Warning      = base x 2.00  (+100%)
      DCC Quarantine   = base x 2.25  (+125%)
    """
    state, all_orchs, sr_registry, _ = _load(ctx)
    reports_dir = Path(output_dir) if output_dir else cfg.get_reports_dir()

    sr_totals = tracker.calculate_sr_totals(all_orchs, state["estimates"], sr_registry)
    thresholds = tracker.calculate_thresholds(sr_totals)
    rows = tracker.build_report_rows(sr_totals, thresholds, sr_registry)

    report_path = tracker.write_csv_report(rows, reports_dir)
    click.echo(f"Report written to: {report_path}\n")

    # Print summary table to stdout
    code_w = max(len(r["Service Request Code"]) for r in rows)
    name_w = min(max(len(r["Service Request Name"]) for r in rows), 50)
    header = (
        f"{'Code':<{code_w}}  {'Service Request Name':<{name_w}}  "
        f"{'Total Reqs':>12}  {'Base/day':>10}  "
        f"{'Adap.Warn':>10}  {'Adap.Quar':>10}  "
        f"{'DCC Warn':>10}  {'DCC Quar':>10}"
    )
    divider = "-" * len(header)
    click.echo(header)
    click.echo(divider)
    for row in rows:
        name = row["Service Request Name"][:name_w]
        click.echo(
            f"{row['Service Request Code']:<{code_w}}  {name:<{name_w}}  "
            f"{row['Total Estimated Requests']:>12,}  "
            f"{row['Daily Threshold (Base)']:>10.2f}  "
            f"{row['DCC Adapter Warning']:>10.2f}  "
            f"{row['DCC Adapter Quarantine']:>10.2f}  "
            f"{row['DCC Warning']:>10.2f}  "
            f"{row['DCC Quarantine']:>10.2f}"
        )


@cli.command("delete-orchestration")
@click.argument("orchestration_name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def delete_orchestration(ctx, orchestration_name, yes):
    """Delete a custom orchestration by name."""
    state, _, _, state_path = _load(ctx)
    if not yes:
        click.confirm(
            f"Delete custom orchestration '{orchestration_name}'?", abort=True
        )
    try:
        tracker.delete_orchestration(state, orchestration_name)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    tracker.save_state(state, state_path)
    click.echo(f"Orchestration '{orchestration_name}' deleted.")


@cli.command("add-orchestration")
@click.argument("orchestration_name")
@click.option(
    "--sr",
    "sr_pairs",
    multiple=True,
    type=(str, int),
    metavar="SR_CODE COUNT",
    required=True,
    help="Service request code and count per run. Repeatable.",
)
@click.pass_context
def add_orchestration(ctx, orchestration_name, sr_pairs):
    """Add or update a custom orchestration definition.

    \b
    Example:
      dcc-tracker add-orchestration My_Orch \\
        --sr ECS17b 2 \\
        --sr CS10a 1
    """
    state, all_orchs, _, state_path = _load(ctx)
    sr_counts = dict(sr_pairs)
    try:
        tracker.add_orchestration(state, orchestration_name, sr_counts)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    tracker.save_state(state, state_path)
    sr_summary = ", ".join(f"{k}\xd7{v}" for k, v in sorted(sr_counts.items()))
    click.echo(f"Orchestration '{orchestration_name}' saved with: {sr_summary}")

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import (
    EIGHT_MONTH_DAYS,
    ADAPTER_WARNING_MULT,
    ADAPTER_QUARANTINE_MULT,
    DCC_WARNING_MULT,
    DCC_QUARANTINE_MULT,
)

# CSV column names for the threshold report
REPORT_FIELDNAMES = [
    "Service Request Code",
    "Service Request Name",
    "Total Estimated Requests",
    "Daily Threshold (Base)",
    "DCC Adapter Warning",
    "DCC Adapter Quarantine",
    "DCC Warning",
    "DCC Quarantine",
]

_EMPTY_STATE: dict[str, Any] = {
    "estimates": {},
    "actual_counts": {},
    "orchestration_overrides": {},
}


# ── State I/O ─────────────────────────────────────────────────────────────────

def load_state(state_path: Path) -> dict:
    """Load tracker_state.json. Returns an empty skeleton if the file is absent."""
    if not state_path.exists():
        return {k: dict(v) for k, v in _EMPTY_STATE.items()}
    with state_path.open() as f:
        state = json.load(f)
    # Ensure all expected keys are present (forward-compat with older state files)
    for key in _EMPTY_STATE:
        state.setdefault(key, {})
    return state


def save_state(state: dict, state_path: Path) -> None:
    """Atomically write state to JSON (write .tmp then os.replace)."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, state_path)


def load_orchestrations(config_path: Path) -> dict[str, dict[str, int]]:
    """Load orchestrations.json. Raises FileNotFoundError with a clear message if absent."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Orchestrations config not found at: {config_path}\n"
            "Ensure orchestrations.json is present in the project root."
        )
    with config_path.open() as f:
        return json.load(f)


def load_sr_registry(sr_registry_path: Path) -> dict[str, str]:
    """Load service_requests.json — a mapping of SR code to display name.

    Returns an empty dict if the file is absent (graceful degradation).
    """
    if not sr_registry_path.exists():
        return {}
    with sr_registry_path.open() as f:
        return json.load(f)


def merge_orchestrations(
    config_orchs: dict[str, dict[str, int]],
    overrides: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    """Return config_orchs updated with overrides (overrides win on name collision)."""
    merged = dict(config_orchs)
    merged.update(overrides)
    return merged


# ── Core Commands ─────────────────────────────────────────────────────────────

def log_run(
    state: dict,
    orch_name: str,
    all_orchestrations: dict[str, dict[str, int]],
    count: int = 1,
) -> dict:
    """Increment actual_counts[orch_name] by count.

    Raises ValueError if orch_name is not in all_orchestrations.
    Returns the mutated state (caller must save).
    """
    if orch_name not in all_orchestrations:
        raise ValueError(
            f"Unknown orchestration: '{orch_name}'. "
            f"Available: {', '.join(sorted(all_orchestrations))}"
        )
    current = state["actual_counts"].get(orch_name, 0)
    state["actual_counts"][orch_name] = current + count
    return state


def set_estimate(
    state: dict,
    orch_name: str,
    estimated_runs: int,
    all_orchestrations: dict[str, dict[str, int]],
) -> dict:
    """Set estimates[orch_name] = estimated_runs.

    Raises ValueError if orch_name is unknown or estimated_runs is negative.
    Returns the mutated state (caller must save).
    """
    if orch_name not in all_orchestrations:
        raise ValueError(
            f"Unknown orchestration: '{orch_name}'. "
            f"Available: {', '.join(sorted(all_orchestrations))}"
        )
    if estimated_runs < 0:
        raise ValueError("Estimated runs must be a non-negative integer.")
    state["estimates"][orch_name] = estimated_runs
    return state


def add_orchestration(
    state: dict,
    orch_name: str,
    sr_counts: dict[str, int],
) -> dict:
    """Add or replace an orchestration in state['orchestration_overrides'].

    Validates that all sr_counts values are positive integers.
    Returns the mutated state (caller must save).
    """
    for sr_type, count in sr_counts.items():
        if not isinstance(count, int) or count < 1:
            raise ValueError(
                f"Service request count for '{sr_type}' must be a positive integer, got {count!r}."
            )
    state["orchestration_overrides"][orch_name] = dict(sr_counts)
    return state


def delete_orchestration(state: dict, orch_name: str) -> dict:
    """Remove a custom orchestration from state['orchestration_overrides'].

    Also removes associated estimates and actual_counts entries.
    Raises ValueError if orch_name is not a custom orchestration.
    Returns the mutated state (caller must save).
    """
    if orch_name not in state["orchestration_overrides"]:
        raise ValueError(
            f"'{orch_name}' is not a custom orchestration and cannot be deleted."
        )
    del state["orchestration_overrides"][orch_name]
    state["estimates"].pop(orch_name, None)
    state["actual_counts"].pop(orch_name, None)
    return state


# ── Threshold Calculation ─────────────────────────────────────────────────────

def calculate_sr_totals(
    all_orchestrations: dict[str, dict[str, int]],
    estimates: dict[str, int],
    sr_registry: dict[str, str] | None = None,
) -> dict[str, int]:
    """Compute total estimated requests per SR type over the 8-month period.

    All SR types from sr_registry are included in the output (with 0 for those
    not referenced by any orchestration), ensuring the full ADT report always
    covers every known service request type.

    Orchestrations with no estimate contribute 0.
    """
    # Pre-seed with every known SR type at 0
    totals: dict[str, int] = {sr: 0 for sr in (sr_registry or {})}

    for orch_name, sr_map in all_orchestrations.items():
        est = estimates.get(orch_name, 0)
        for sr_type, count_per_run in sr_map.items():
            totals[sr_type] = totals.get(sr_type, 0) + (count_per_run * est)
    return totals


def calculate_thresholds(
    sr_totals: dict[str, int],
    period_days: float = EIGHT_MONTH_DAYS,
) -> dict[str, float]:
    """Divide each SR total by period_days to get the base daily threshold."""
    return {sr_type: total / period_days for sr_type, total in sr_totals.items()}


def build_report_rows(
    sr_totals: dict[str, int],
    thresholds: dict[str, float],
    sr_registry: dict[str, str] | None = None,
) -> list[dict]:
    """Return a list of row dicts for the CSV writer, sorted by SR code.

    Each row contains the SR code, human-readable name (from sr_registry),
    the base daily threshold, and the 4 anomaly level thresholds,
    all rounded to 2 decimal places.
    """
    registry = sr_registry or {}
    rows = []
    for sr_code in sorted(sr_totals):
        base = thresholds[sr_code]
        rows.append({
            "Service Request Code": sr_code,
            "Service Request Name": registry.get(sr_code, ""),
            "Total Estimated Requests": sr_totals[sr_code],
            "Daily Threshold (Base)": round(base, 2),
            "DCC Adapter Warning": round(base * ADAPTER_WARNING_MULT, 2),
            "DCC Adapter Quarantine": round(base * ADAPTER_QUARANTINE_MULT, 2),
            "DCC Warning": round(base * DCC_WARNING_MULT, 2),
            "DCC Quarantine": round(base * DCC_QUARANTINE_MULT, 2),
        })
    return rows


# ── Report I/O ────────────────────────────────────────────────────────────────

def write_csv_report(rows: list[dict], reports_dir: Path) -> Path:
    """Write a threshold CSV report to reports_dir and return the file path."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"threshold_report_{timestamp}.csv"
    with report_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return report_path


# ── Display Helpers ───────────────────────────────────────────────────────────

def format_list_table(
    all_orchestrations: dict[str, dict[str, int]],
    estimates: dict[str, int],
    actual_counts: dict[str, int],
) -> str:
    """Return a column-aligned table string for the `list` command."""
    headers = ("Orchestration", "Service Requests", "Est. Runs", "Actual Runs")

    rows = []
    for orch_name in sorted(all_orchestrations):
        sr_map = all_orchestrations[orch_name]
        sr_summary = ", ".join(
            f"{sr}\xd7{n}" for sr, n in sorted(sr_map.items())
        )
        est = estimates.get(orch_name, 0)
        actual = actual_counts.get(orch_name, 0)
        rows.append((orch_name, sr_summary, f"{est:,}", str(actual)))

    # Compute column widths (two-pass)
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    sep = "  "
    header_line = sep.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider = sep.join("-" * w for w in col_widths)
    data_lines = [
        sep.join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        for row in rows
    ]

    return "\n".join([header_line, divider] + data_lines)

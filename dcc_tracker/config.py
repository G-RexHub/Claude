from pathlib import Path
import os

# 8 months expressed as average days (8 × 30.4375)
EIGHT_MONTH_DAYS = 243.5

# Anomaly threshold level multipliers (applied to the base daily threshold)
ADAPTER_WARNING_MULT = 1.50      # DCC Adapter Warning    (+50%)
ADAPTER_QUARANTINE_MULT = 1.75   # DCC Adapter Quarantine (+75%)
DCC_WARNING_MULT = 2.00          # DCC Warning            (+100%)
DCC_QUARANTINE_MULT = 2.25       # DCC Quarantine         (+125%)

DEFAULT_CONFIG_FILENAME = "orchestrations.json"
DEFAULT_STATE_FILENAME = "tracker_state.json"
DEFAULT_STATE_DIR = "data"
DEFAULT_REPORTS_DIR = "reports"


def get_project_root() -> Path:
    """Return the project root directory.

    Resolution order:
      1. DCCT_PROJECT_ROOT environment variable (useful for tests or CI)
      2. Parent of the dcc_tracker package directory (i.e. the repo root)
    """
    env_root = os.environ.get("DCCT_PROJECT_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).parent.parent


def get_config_path() -> Path:
    """Return the absolute path to orchestrations.json."""
    return get_project_root() / DEFAULT_CONFIG_FILENAME


def get_state_path() -> Path:
    """Return the absolute path to data/tracker_state.json."""
    return get_project_root() / DEFAULT_STATE_DIR / DEFAULT_STATE_FILENAME


def get_reports_dir() -> Path:
    """Return the absolute path to the reports directory."""
    return get_project_root() / DEFAULT_REPORTS_DIR

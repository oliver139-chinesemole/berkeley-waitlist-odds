"""Static configuration for the scraper. See docs/DESIGN_A2.md sections 4 and 6.

Everything here is a constant or a pure function of the process environment.
Nothing in this module performs I/O beyond reading environment variables, so
it is safe to import from tests and from every other scraper module.
"""
from __future__ import annotations

import os
from typing import Any, Final, Mapping

VERSION: Final[str] = "0.1.0"

# GitHub owner placeholder; replace once the public repository name is final.
REPO_OWNER: Final[str] = "oliver139-chinesemole"
REPO_URL: Final[str] = f"https://github.com/{REPO_OWNER}/berkeley-waitlist-odds"
CONTACT_EMAIL: Final[str] = "oliver139@berkeley.edu"

# Sent on every request (DESIGN_A2 section 4): honest identification with a
# contact address, never a browser impersonation.
USER_AGENT: Final[str] = f"berkeley-waitlist-odds/{VERSION} (+{REPO_URL}; mailto:{CONTACT_EMAIL})"

# Environment variable names.
ENV_SIS_APP_ID: Final[str] = "SIS_CLASS_APP_ID"
ENV_SIS_APP_KEY: Final[str] = "SIS_CLASS_APP_KEY"
ENV_LOG_LEVEL: Final[str] = "LOG_LEVEL"  # optional; defaults to INFO

# Endpoints observed in docs/PHASE0.md. The source modules own the request
# logic; these are here so probes and the CLI share one spelling.
CLASSES_BASE_URL: Final[str] = "https://classes.berkeley.edu"
SIS_SECTIONS_URL: Final[str] = "https://gateway.api.berkeley.edu/sis/v1/classes/sections"
BERKELEYTIME_GRAPHQL_URL: Final[str] = "https://berkeleytime.com/api/graphql"

SOURCE_CHOICES: Final[tuple[str, ...]] = ("auto", "sis_api", "classes_site", "berkeleytime")
PRIORITY_DISABLED: Final[str] = "none"  # value of --priority-file that disables the list
STATUS_FILENAME: Final[str] = "status.json"

# Defaults for every CLI flag of `python -m scraper.fetch` (DESIGN_A2 section 6).
# Keys are the argparse destinations. None means "computed at run time" or "unset".
DEFAULTS: Final[dict[str, Any]] = {
    "source": "auto",
    "data_root": "./data-branch",
    "priority_file": "config/priority_courses.txt",
    "n_shards": 8,
    "run_index": None,
    "time_budget_s": 1500.0,
    "min_interval_s": 1.0,
    "max_concurrency": 2,
    "force_baseline": False,
    "limit": None,
    "dry_run": False,
    "catalog_max_pages": None,
}


def sis_credentials(env: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    """Return ``(app_id, app_key)`` when both SIS variables are set and non-empty.

    Returns None otherwise, which the CLI's ``--source auto`` treats as "use
    classes_site". Whitespace-only values count as unset so an empty GitHub
    secret does not select the SIS route.
    """
    source = os.environ if env is None else env
    app_id = (source.get(ENV_SIS_APP_ID) or "").strip()
    app_key = (source.get(ENV_SIS_APP_KEY) or "").strip()
    if app_id and app_key:
        return app_id, app_key
    return None


def log_level(env: Mapping[str, str] | None = None) -> str:
    """Logging level name from ``LOG_LEVEL``; ``INFO`` when unset or blank."""
    source = os.environ if env is None else env
    return (source.get(ENV_LOG_LEVEL) or "INFO").strip().upper() or "INFO"

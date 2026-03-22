#!/usr/bin/env python3
"""
Periodic runner for the buscacursos scraper.

Reads configuration from environment variables (via .env when running with docker-compose)
and triggers the scraper at a fixed interval, persisting the SQLite database to the
configured location.
"""

import logging
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import List

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def build_command(periods: List[str]) -> List[str]:
    cmd = [sys.executable, "main.py", *periods]

    output_db = os.environ.get("SCRAPER_OUTPUT_DB", "/data/scraper_data.sqlite")
    if output_db:
        cmd.append(f"--output-db={output_db}")

    workers = os.environ.get("SCRAPER_WORKERS")
    if workers:
        cmd.append(f"--workers={workers}")

    if _bool_env("SCRAPER_STDOUT_JSON", False):
        cmd.append("--stdout-json")

    if _bool_env("SCRAPER_SKIP_PROGRAM", False):
        cmd.append("--skip-program")
    if _bool_env("SCRAPER_SKIP_REQUIREMENTS", False):
        cmd.append("--skip-requirements")
    if _bool_env("SCRAPER_SKIP_QUOTA", False):
        cmd.append("--skip-quota")
    if _bool_env("SCRAPER_DISABLE_CACHE", False):
        cmd.append("--disable-cache")

    extra_args = os.environ.get("SCRAPER_EXTRA_ARGS", "")
    if extra_args:
        cmd.extend(shlex.split(extra_args))

    return cmd


def run_once(periods: List[str]) -> int:
    cmd = build_command(periods)
    logger.info("Running scraper: %s", " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    if proc.returncode == 0:
        logger.info("Scraper finished successfully")
    else:
        logger.error("Scraper exited with code %s", proc.returncode)
    return proc.returncode


def main() -> None:
    raw_periods = os.environ.get("SCRAPER_PERIODS", "")
    periods = [p.strip() for p in raw_periods.split(",") if p.strip()]
    if not periods:
        logger.error("No periods configured. Set SCRAPER_PERIODS in your environment.")
        sys.exit(1)

    raw_interval = os.environ.get("SCRAPER_INTERVAL_MINUTES", "360")
    try:
        interval_minutes = int(raw_interval)
    except ValueError:
        logger.warning(
            "Invalid SCRAPER_INTERVAL_MINUTES value '%s', falling back to 360", raw_interval
        )
        interval_minutes = 360
    if interval_minutes <= 0:
        logger.warning("SCRAPER_INTERVAL_MINUTES must be positive, forcing to 1")
        interval_minutes = 1
    interval_seconds = interval_minutes * 60

    logger.info("Configured periods: %s", periods)
    logger.info(
        "Polling interval set to %s minutes (%s seconds)",
        interval_minutes,
        interval_seconds,
    )

    while True:
        start_time = datetime.now(timezone.utc).isoformat()
        logger.info("Starting scrape cycle at %s", start_time)
        run_once(periods)
        logger.info(
            "Sleeping for %s seconds before next scrape cycle", interval_seconds
        )
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()

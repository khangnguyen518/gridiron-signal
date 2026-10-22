"""Scheduled refresh: rebuild this repo's tables after sports_db's daily load.

    uv run nflm refresh            # check sports_db freshness, then dbt build
    uv run nflm refresh --force    # build even if sports_db did not build today

1. Freshness: sports_db must have a successful dbt build of the layer we read
   (SPORTS_DB_STAGING: staging is its prod target, dev_staging its dev target)
   within the last MAX_AGE_HOURS, in sports_db's raw_meta.load_runs. Otherwise
   we would rebuild on stale or half-built inputs.
2. dbt build with NFLM_DBT_TARGET into NFLM_DATASET.
3. Any failure posts to Discord (alerts.py) and exits non-zero for cron.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime

from google.cloud import bigquery

from nfl_model import alerts, config

MAX_AGE_HOURS = 30
STAGING_TO_TARGET = {"staging": "prod", "dev_staging": "dev"}
DBT_DIR = config.ROOT / "dbt"


def sports_db_last_build() -> datetime | None:
    """Finish time of sports_db's latest successful dbt build of the layer we read."""
    target = STAGING_TO_TARGET.get(config.SPORTS_DB_STAGING)
    if target is None:
        return None
    sql = f"""
        select max(finished_at) as finished_at
        from `{config.SPORTS_DB_PROJECT}.raw_meta.load_runs`
        where job = 'dbt.build' and status = 'success' and detail = @target
    """
    job = bigquery.Client(project=config.NFLM_GCP_PROJECT).query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("target", "STRING", target)]
        ),
    )
    row = next(iter(job.result()), None)
    return row.finished_at if row else None


def dbt_build() -> int:
    dbt = config.ROOT / ".venv" / "bin" / "dbt"
    cmd = [
        str(dbt) if dbt.exists() else "dbt",
        "build",
        "--profiles-dir",
        ".",
        "--target",
        config.NFLM_DBT_TARGET,
    ]
    env = {**os.environ}  # .env is already loaded into os.environ by config
    return subprocess.run(cmd, check=False, cwd=DBT_DIR, env=env).returncode  # exit code handled below


def main(force: bool = False) -> int:
    started = datetime.now(UTC)
    print(
        f"{started:%Y-%m-%d %H:%M} UTC refresh: target {config.NFLM_DBT_TARGET}, "
        f"dataset {config.NFLM_DATASET}, reading sports_db {config.SPORTS_DB_STAGING}"
    )

    last = sports_db_last_build()
    age = (started - last).total_seconds() / 3600 if last else None
    if age is None or age > MAX_AGE_HOURS:
        when = f"{age:.0f} hours ago" if age is not None else "never"
        msg = (
            f"gridiron-signal refresh: sports_db's last successful {config.SPORTS_DB_STAGING} build was "
            f"{when} (limit {MAX_AGE_HOURS})."
        )
        if not force:
            alerts.send(f"{msg} Skipped dbt build. Check sports_db's daily pipeline.")
            return 1
        print(f"{msg} Building anyway (--force).")
    else:
        print(f"sports_db built {age:.1f} hours ago")

    code = dbt_build()
    if code != 0:
        alerts.send(
            f"gridiron-signal refresh: dbt build --target {config.NFLM_DBT_TARGET} failed "
            f"(exit {code}). See logs/refresh.log on the VM."
        )
        return code
    print(f"refresh finished in {(datetime.now(UTC) - started).total_seconds():.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

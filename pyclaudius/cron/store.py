import json
import logging
from pathlib import Path

from pyclaudius.cron.models import ScheduledJob
from pyclaudius.timezone import get_zoneinfo

logger = logging.getLogger(__name__)


def load_cron_jobs(*, cron_file: Path) -> list[ScheduledJob]:
    """Load scheduled jobs from a JSON file. Returns [] on missing/invalid."""
    try:
        data = json.loads(cron_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def save_cron_jobs(*, cron_file: Path, jobs: list[ScheduledJob]) -> None:
    """Save scheduled jobs to a JSON file."""
    cron_file.write_text(json.dumps(jobs, indent=2), encoding="utf-8")


def _convert_once_expression(
    *, expression: str, original_timezone: str | None, display_timezone: str | None
) -> str:
    """Convert a once-job expression from original timezone to display timezone."""
    from pyclaudius.cron.scheduler import parse_schedule_datetime

    dt = parse_schedule_datetime(text=expression, timezone=original_timezone)
    if dt is None:
        return expression
    display_tz = get_zoneinfo(timezone=display_timezone)
    converted = dt.astimezone(display_tz)
    return converted.strftime("%Y-%m-%d %H:%M")


def format_cron_list(
    *, jobs: list[ScheduledJob], display_timezone: str | None = None
) -> str:
    """Format jobs as a numbered list with [CRON]/[ONCE] labels."""
    if not jobs:
        return "No scheduled jobs."
    lines = []
    for i, job in enumerate(jobs, start=1):
        label = "[CRON]" if job["job_type"] == "cron" else "[ONCE]"
        job_tz = job.get("timezone")

        if job["job_type"] == "once" and display_timezone is not None:
            display_expr = _convert_once_expression(
                expression=job["expression"],
                original_timezone=job_tz,
                display_timezone=display_timezone,
            )
        else:
            display_expr = job["expression"]

        tz_annotation = ""
        if job["job_type"] == "cron":
            tz_annotation = f" ({job_tz or 'UTC'})"

        lines.append(f"{i}. {label} {display_expr}{tz_annotation} — {job['prompt']}")
    return "\n".join(lines)

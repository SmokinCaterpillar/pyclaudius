import json
import logging
from pathlib import Path

from pyclaudius.cron.models import ScheduledJob

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


def format_cron_list(*, jobs: list[ScheduledJob]) -> str:
    """Format jobs as a numbered list with [CRON]/[ONCE] labels."""
    if not jobs:
        return "No scheduled jobs."
    lines = []
    for i, job in enumerate(jobs, start=1):
        label = "[CRON]" if job["job_type"] == "cron" else "[ONCE]"
        lines.append(f"{i}. {label} {job['expression']} — {job['prompt']}")
    return "\n".join(lines)

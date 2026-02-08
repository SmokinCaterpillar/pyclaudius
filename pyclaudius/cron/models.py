from typing import Literal, TypedDict


class ScheduledJob(TypedDict):
    id: str
    job_type: Literal["cron", "once"]
    expression: str
    prompt: str
    created_at: str

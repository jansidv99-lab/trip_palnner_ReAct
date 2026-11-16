# Phase 12 – Step 6: traveler feedback on a plan – the versioned record and where it's written.
"""A `FeedbackRecord` (schema "feedback.v1") is B5's input: it joins with the run by `run_id`.

The UI writes records through the `FeedbackSink` protocol. Locally that's `JsonlFeedbackSink`
(`logs/feedback.jsonl`, git-ignored); Phase 13/14 add a Cloud Logging sink without changing the UI.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from agentsville.agent import AgentRun

FEEDBACK_SCHEMA_VERSION = "feedback.v1"
MAX_COMMENT_CHARS = 1000
FEEDBACK_LOG_ENV = "AGENTSVILLE_FEEDBACK_LOG"
DEFAULT_FEEDBACK_PATH = Path(__file__).resolve().parents[2] / "logs" / "feedback.jsonl"

Rating = Literal["up", "down"]


# Phase 12 – Step 6: one traveler's verdict on one run
class FeedbackRecord(BaseModel):
    schema_version: Literal["feedback.v1"] = FEEDBACK_SCHEMA_VERSION
    run_id: str  # joins with AgentRun and the production signals
    rating: Rating
    comment: str = Field(default="", max_length=MAX_COMMENT_CHARS)
    model: str
    prompt_version: str
    created_at: datetime

    # Phase 12 – Step 6: surrounding whitespace is never meaningful
    @field_validator("comment", mode="before")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


# Phase 12 – Step 6: anything that can store a feedback record
class FeedbackSink(Protocol):
    def write(self, record: FeedbackRecord) -> None: ...


# Phase 12 – Step 6: append records as JSON lines (same format as the run log)
class JsonlFeedbackSink:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, record: FeedbackRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")


# Phase 12 – Step 6: the record for a run (comment is cut to the limit rather than rejected)
def make_feedback(
    run: AgentRun, rating: Rating, comment: str = "", now: datetime | None = None
) -> FeedbackRecord:
    return FeedbackRecord(
        run_id=run.run_id,
        rating=rating,
        comment=comment.strip()[:MAX_COMMENT_CHARS],
        model=run.model,
        prompt_version=run.prompt_version,
        created_at=now or datetime.now(UTC),
    )


# Phase 12 – Step 6: the sink from the environment (unset → logs/feedback.jsonl; "off" → None)
def feedback_sink(environ: dict[str, str] | None = None) -> FeedbackSink | None:
    value = (os.environ if environ is None else environ).get(FEEDBACK_LOG_ENV)
    if value is None:
        return JsonlFeedbackSink(DEFAULT_FEEDBACK_PATH)
    if value.strip().casefold() in ("", "off", "none", "false", "0"):
        return None
    return JsonlFeedbackSink(Path(value.strip()))

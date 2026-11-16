# Phase 12 – Step 6: unit tests for feedback records and sinks (no Streamlit, no network).
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentsville.samples import sample_vacation_info
from agentsville.ui.feedback import (
    DEFAULT_FEEDBACK_PATH,
    MAX_COMMENT_CHARS,
    FeedbackRecord,
    JsonlFeedbackSink,
    feedback_sink,
    make_feedback,
)
from agentsville.ui.form import RunOptions
from agentsville.ui.run import AgentBackend, run_agent
from tests.test_agent import HAPPY_SCRIPT, ScriptedLLM

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def run():
    backend = AgentBackend(llm=ScriptedLLM(*HAPPY_SCRIPT), prompt_version="v1", log_path=None)
    return run_agent(sample_vacation_info(), RunOptions(), backend)


def test_make_feedback_fields(run):
    record = make_feedback(run, "up", "  Great plan!  ", now=NOW)
    assert record.schema_version == "feedback.v1"
    assert record.run_id == run.run_id
    assert (record.rating, record.comment) == ("up", "Great plan!")
    assert (record.model, record.prompt_version) == (run.model, "v1")
    assert record.created_at == NOW


def test_long_comment_is_cut_to_the_limit(run):
    record = make_feedback(run, "down", "x" * (MAX_COMMENT_CHARS + 50))
    assert len(record.comment) == MAX_COMMENT_CHARS


def test_record_rejects_bad_rating_and_overlong_comment():
    base = {"run_id": "r", "model": "m", "prompt_version": "v1", "created_at": NOW}
    with pytest.raises(ValidationError):
        FeedbackRecord(rating="meh", **base)
    with pytest.raises(ValidationError):
        FeedbackRecord(rating="up", comment="x" * (MAX_COMMENT_CHARS + 1), **base)


def test_jsonl_sink_appends_one_line_per_record(run, tmp_path):
    sink = JsonlFeedbackSink(tmp_path / "sub" / "feedback.jsonl")
    sink.write(make_feedback(run, "up", now=NOW))
    sink.write(make_feedback(run, "down", "too much walking", now=NOW))
    lines = sink.path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["rating"] for line in lines] == ["up", "down"]
    assert FeedbackRecord.model_validate_json(lines[1]).comment == "too much walking"


def test_feedback_sink_from_environment(tmp_path):
    assert feedback_sink({}).path == DEFAULT_FEEDBACK_PATH
    assert feedback_sink({"AGENTSVILLE_FEEDBACK_LOG": "off"}) is None
    custom = feedback_sink({"AGENTSVILLE_FEEDBACK_LOG": str(tmp_path / "f.jsonl")})
    assert custom.path == Path(tmp_path / "f.jsonl")


# Phase 13 – Step 2: stdout sink for Cloud Run (Cloud Logging reads JSON lines from stdout)
def test_stdout_sink_prints_one_structured_json_line(run):
    import io

    from agentsville.ui.feedback import StdoutFeedbackSink

    stream = io.StringIO()
    StdoutFeedbackSink(stream).write(make_feedback(run, "down", "Too much walking", now=NOW))
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["severity"] == "INFO" and entry["event"] == "feedback"
    assert entry["schema_version"] == "feedback.v1"
    assert (entry["rating"], entry["comment"], entry["run_id"]) == (
        "down", "Too much walking", run.run_id,
    )
    assert FeedbackRecord.model_validate(
        {k: v for k, v in entry.items() if k not in ("severity", "message", "event")}
    ).created_at == NOW


def test_feedback_sink_stdout_from_environment():
    from agentsville.ui.feedback import StdoutFeedbackSink

    assert isinstance(feedback_sink({"AGENTSVILLE_FEEDBACK_LOG": "stdout"}), StdoutFeedbackSink)

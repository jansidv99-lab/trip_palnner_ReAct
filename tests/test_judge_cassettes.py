# Phase 10 – Step 1: per-judge grading cassettes and --record-graders.

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentsville.graders import B1_GRADERS
from agentsville.harness.grading import GradingContext, RunGrader, outcome
from agentsville.harness.recording import CassetteMissError
from agentsville.harness.runner import (
    grade_with_cassette,
    judge_cassette,
    update_expected,
    validate_record_graders,
)
from agentsville.harness.schema import ExperimentConfig
from agentsville.llm import LLMResponse
from tests.harness_fakes import ConversationFake
from tests.test_grounding import golden_run

FAKE_JUDGE_PROMPT = "FAKE JUDGE"


def fake_judge(run, ctx: GradingContext):
    reply = ctx.llm.chat([{"role": "system", "content": FAKE_JUDGE_PROMPT},
                          {"role": "user", "content": run.run_id}], model="gpt-4.1")
    return outcome("fake_judge", "llm", 1, [] if reply.text == "ok" else ["not ok"])


GRADERS = [*B1_GRADERS, RunGrader("fake_judge", "llm", fake_judge)]


class CountingLLM:
    """Answers the fake judge itself; the B1 reasons judge goes to ConversationFake."""

    def __init__(self, reply="ok"):
        self.reply, self.fake_calls, self.inner = reply, 0, ConversationFake([])

    @property
    def reasons_calls(self):
        return self.inner.calls

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        if messages[0]["content"] == FAKE_JUDGE_PROMPT:
            self.fake_calls += 1
            return LLMResponse(text=self.reply, model="judge", latency_ms=1)
        return self.inner.chat(messages, model=model, temperature=temperature, json_mode=json_mode)


@pytest.fixture
def recorded(tmp_path):
    run, cassette = golden_run(), tmp_path / "g01" / "r1.grading.jsonl"
    cassette.parent.mkdir()
    llm = CountingLLM()
    outcomes = grade_with_cassette(run, "record", cassette, llm, True, graders=GRADERS)
    return run, cassette, llm, outcomes


def test_judge_cassette_names():
    base = Path("x/r2.grading.jsonl")
    assert judge_cassette(base, "reasons_grounded") == base  # B1 keeps its file name
    assert judge_cassette(base, "traveler_relevancy").name == "r2.grading.traveler_relevancy.jsonl"


def test_each_judge_records_to_its_own_file(recorded):
    _, cassette, llm, outcomes = recorded
    assert sorted(p.name for p in cassette.parent.iterdir()) == [
        "r1.grading.fake_judge.jsonl", "r1.grading.jsonl"]
    assert llm.fake_calls == 1 and llm.reasons_calls == 6  # one reasons call per activity
    assert list(outcomes) == [g.name for g in GRADERS]  # graders' order kept


def test_record_graders_records_only_the_named_judge(recorded):
    run, cassette, _, first = recorded
    b1_bytes = cassette.read_bytes()
    llm = CountingLLM(reply="changed")
    outcomes = grade_with_cassette(run, "replay", cassette, llm, True, graders=GRADERS,
                                   record_graders=["fake_judge"])
    assert llm.fake_calls == 1 and llm.reasons_calls == 0  # the B1 judge replayed
    assert cassette.read_bytes() == b1_bytes  # byte-identical B1 cassette
    assert outcomes["reasons_grounded"] == first["reasons_grounded"]
    assert not outcomes["fake_judge"].passed  # the new recording was used


def test_full_replay_needs_no_llm(recorded):
    run, cassette, _, first = recorded
    assert grade_with_cassette(run, "replay", cassette, None, True, graders=GRADERS) == first


def test_replay_of_an_unrecorded_judge_fails_loudly(recorded):
    run, cassette, _, _ = recorded
    (cassette.parent / "r1.grading.fake_judge.jsonl").unlink()
    with pytest.raises(CassetteMissError):
        grade_with_cassette(run, "replay", cassette, None, True, graders=GRADERS)


def test_validate_record_graders():
    validate_record_graders(["fake_judge"], GRADERS)
    validate_record_graders(None, GRADERS)
    with pytest.raises(ValueError, match="unknown LLM judge"):
        validate_record_graders(["nope"], GRADERS)
    with pytest.raises(ValueError, match="activity_grounding"):  # code graders never record
        validate_record_graders(["activity_grounding"], GRADERS)


@pytest.mark.parametrize("overrides", [{"grade_mode": "record"}, {"mode": "live"}])
def test_record_graders_rejects_conflicting_modes(overrides):
    with pytest.raises(ValidationError):
        ExperimentConfig(record_graders=["reasons_grounded"], **overrides)


def test_record_graders_needs_llm_and_blocks_update_expected(tmp_path):
    config = ExperimentConfig(record_graders=["reasons_grounded"])
    assert config.needs_llm and not ExperimentConfig().needs_llm
    with pytest.raises(ValueError):
        update_expected(config, [], cassette_root=tmp_path)

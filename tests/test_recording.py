# Phase 7 – Step 9: record/replay cassettes.

import json

import pytest

from agentsville.harness.recording import CassetteLLM, CassetteMissError, request_key
from agentsville.llm import LLMError, LLMResponse

MSGS = [{"role": "user", "content": "hello"}]


class CountingLLM:
    default_model = "fake"

    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResponse(text=f"reply {self.calls}", model=model, latency_ms=5.0,
                           prompt_tokens=3, completion_tokens=2, cost_usd=0.0001)


def test_record_then_replay_is_identical(tmp_path):
    cassette = tmp_path / "c.jsonl"
    recorder = CassetteLLM("record", cassette, llm=CountingLLM())
    recorded = [recorder.chat(MSGS), recorder.chat(MSGS, json_mode=True)]

    player = CassetteLLM("replay", cassette, default_model="fake")  # no real LLM at all
    assert [player.chat(MSGS), player.chat(MSGS, json_mode=True)] == recorded


def test_same_request_twice_replays_in_order(tmp_path):
    cassette = tmp_path / "c.jsonl"
    recorder = CassetteLLM("record", cassette, llm=CountingLLM())
    first, second = recorder.chat(MSGS), recorder.chat(MSGS)
    player = CassetteLLM("replay", cassette, default_model="fake")
    assert (player.chat(MSGS).text, player.chat(MSGS).text) == (first.text, second.text)
    with pytest.raises(CassetteMissError, match="request #3"):
        player.chat(MSGS)


def test_replay_miss_names_the_request(tmp_path):
    cassette = tmp_path / "c.jsonl"
    CassetteLLM("record", cassette, llm=CountingLLM()).chat(MSGS)
    player = CassetteLLM("replay", cassette, default_model="fake")
    with pytest.raises(CassetteMissError, match="re-record") as exc:
        player.chat([{"role": "user", "content": "a changed prompt"}])
    assert "a changed prompt" in str(exc.value)


def test_missing_cassette_file(tmp_path):
    with pytest.raises(CassetteMissError, match="no cassette"):
        CassetteLLM("replay", tmp_path / "missing.jsonl", default_model="fake")


def test_recorded_errors_replay_as_llm_errors(tmp_path):
    cassette = tmp_path / "c.jsonl"
    recorder = CassetteLLM("record", cassette, llm=CountingLLM(error=LLMError("rate limited")))
    with pytest.raises(LLMError):
        recorder.chat(MSGS)
    with pytest.raises(LLMError, match="rate limited"):
        CassetteLLM("replay", cassette, default_model="fake").chat(MSGS)


def test_live_mode_writes_nothing(tmp_path):
    cassette = tmp_path / "c.jsonl"
    CassetteLLM("live", cassette, llm=CountingLLM()).chat(MSGS)
    assert not cassette.exists()


def test_record_needs_a_real_llm(tmp_path):
    with pytest.raises(ValueError, match="needs a real LLMClient"):
        CassetteLLM("record", tmp_path / "c.jsonl")


def test_rerecording_replaces_old_cassette(tmp_path):
    cassette = tmp_path / "c.jsonl"
    CassetteLLM("record", cassette, llm=CountingLLM()).chat(MSGS)
    CassetteLLM("record", cassette, llm=CountingLLM()).chat(MSGS)
    assert len(cassette.read_text(encoding="utf-8").splitlines()) == 1


def test_key_ignores_line_endings_but_not_content():
    lf = [{"role": "system", "content": "a\nb"}]
    crlf = [{"role": "system", "content": "a\r\nb"}]
    assert request_key("m", lf, 0.0, False) == request_key("m", crlf, 0.0, False)
    assert request_key("m", lf, 0.0, False) != request_key("m", lf, 0.0, True)
    assert request_key("m", lf, 0.0, False) != request_key("other", lf, 0.0, False)


def test_cassette_lines_are_summarized_json(tmp_path):
    cassette = tmp_path / "c.jsonl"
    CassetteLLM("record", cassette, llm=CountingLLM()).chat(MSGS, model="m1")
    entry = json.loads(cassette.read_text(encoding="utf-8"))
    assert entry["request"]["model"] == "m1" and entry["request"]["last_message"] == "hello"
    assert entry["response"]["text"] == "reply 1" and entry["occurrence"] == 0


def test_replay_needs_default_model(tmp_path):
    with pytest.raises(ValueError, match="needs default_model"):
        CassetteLLM("replay", tmp_path / "c.jsonl")

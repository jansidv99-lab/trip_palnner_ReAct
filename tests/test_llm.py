# Phase 0 – Step 7: LLM wrapper behaviour using a fake SDK client (no network, no cost).

import httpx
import openai
import pytest

from agentsville.llm import LLMClient, LLMError, estimate_cost


def test_estimate_cost_known_model():
    # gpt-4o-mini: $0.15 / 1M input, $0.60 / 1M output
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_estimate_cost_unknown_model_is_none():
    assert estimate_cost("some-new-model", 100, 100) is None


def test_estimate_cost_missing_usage_is_none():
    assert estimate_cost("gpt-4o-mini", None, 5) is None


def test_chat_returns_text_and_metrics(settings, fake_openai):
    fake = fake_openai(text="OK", prompt_tokens=10, completion_tokens=2)
    reply = LLMClient(settings, client=fake).chat([{"role": "user", "content": "hi"}])

    assert reply.text == "OK"
    assert reply.model == "gpt-4o-mini"  # default from settings
    assert (reply.prompt_tokens, reply.completion_tokens) == (10, 2)
    assert reply.cost_usd == pytest.approx(estimate_cost("gpt-4o-mini", 10, 2))
    assert reply.latency_ms >= 0


def test_chat_model_override_is_sent(settings, fake_openai):
    fake = fake_openai()
    LLMClient(settings, client=fake).chat([{"role": "user", "content": "hi"}], model="gpt-4.1")
    assert fake.calls[0]["model"] == "gpt-4.1"


def test_chat_wraps_sdk_errors(settings, fake_openai):
    error = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    fake = fake_openai(error=error)
    with pytest.raises(LLMError, match="APIConnectionError"):
        LLMClient(settings, client=fake).chat([{"role": "user", "content": "hi"}])


# Phase 4 – Step 4: JSON mode adds response_format; default calls don't send it
def test_json_mode_sets_response_format(settings, fake_openai):
    fake = fake_openai(text='{"ok": true}')
    LLMClient(settings, client=fake).chat([{"role": "user", "content": "hi"}], json_mode=True)
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_default_call_has_no_response_format(settings, fake_openai):
    fake = fake_openai()
    LLMClient(settings, client=fake).chat([{"role": "user", "content": "hi"}])
    assert "response_format" not in fake.calls[0]

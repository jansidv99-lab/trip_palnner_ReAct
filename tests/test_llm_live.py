# Phase 0 – Step 7: one real LLM call. Skipped by default; run with `pytest -m llm`.

import pytest

from agentsville.config import get_settings
from agentsville.llm import LLMClient


@pytest.mark.llm
def test_live_chat_returns_text_and_usage():
    reply = LLMClient(get_settings()).chat([{"role": "user", "content": "Reply with exactly: OK"}])
    assert reply.text.strip()
    assert reply.prompt_tokens and reply.completion_tokens

# Phase 0 – Step 7: shared test fixtures (fake settings and a fake OpenAI client – no network).

from types import SimpleNamespace

import pytest

from agentsville.config import load_settings


# Phase 0 – Step 7: settings built from a fake environment, never from the real .env
@pytest.fixture
def settings():
    return load_settings({"OPENAI_API_KEY": "sk-test-123", "MODEL": "gpt-4o-mini"})


# Phase 0 – Step 7: mimics `client.chat.completions.create(...)` from the OpenAI SDK
class FakeOpenAIClient:
    def __init__(self, text="OK", prompt_tokens=10, completion_tokens=2, error=None):
        self.calls = []
        self._text = text
        self._usage = SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        message = SimpleNamespace(content=self._text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=self._usage)


@pytest.fixture
def fake_openai():
    return FakeOpenAIClient

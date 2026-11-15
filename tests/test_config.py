# Phase 0 – Step 7: configuration loading and validation (pure function, no real .env).

import pytest

from agentsville.config import DEFAULT_MODEL, DEFAULT_PROMPT_VERSION, ConfigError, load_settings


def test_valid_environment():
    s = load_settings({"OPENAI_API_KEY": "sk-abc", "MODEL": "gpt-4.1-mini"})
    assert s.openai_api_key.get_secret_value() == "sk-abc"
    assert s.model == "gpt-4.1-mini"


def test_defaults_when_optional_missing():
    s = load_settings({"OPENAI_API_KEY": "sk-abc"})
    assert s.model == DEFAULT_MODEL
    assert s.prompt_version == DEFAULT_PROMPT_VERSION
    assert s.openai_base_url is None


@pytest.mark.parametrize("env", [{}, {"OPENAI_API_KEY": ""}, {"OPENAI_API_KEY": "  "}])
def test_missing_api_key_raises(env):
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        load_settings(env)


def test_prompt_version_lowercased():
    assert load_settings({"OPENAI_API_KEY": "k", "PROMPT_VERSION": "V1"}).prompt_version == "v1"


def test_stray_quotes_and_backticks_stripped():
    s = load_settings({"OPENAI_API_KEY": "k", "REGION": "`asia-south1`", "MODEL": '"gpt-4.1"'})
    assert s.region == "asia-south1"
    assert s.model == "gpt-4.1"


def test_api_key_masked_in_repr():
    s = load_settings({"OPENAI_API_KEY": "sk-super-secret"})
    assert "sk-super-secret" not in repr(s)

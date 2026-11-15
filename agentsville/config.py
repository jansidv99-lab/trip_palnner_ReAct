# Phase 0 – Step 4: load and validate configuration once, fail fast with a clear message.
"""Application settings.

Values come from environment variables. Locally, `.env` is loaded first (python-dotenv);
real environment variables win, which is how Cloud Run will inject secrets later (Phase 9).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr, field_validator

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PROMPT_VERSION = "v1"

REQUIRED_VARS = ("OPENAI_API_KEY",)


# Phase 0 – Step 4: one error type for every configuration problem
class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


# Phase 0 – Step 4: typed, validated settings used across the app
class Settings(BaseModel):
    openai_api_key: SecretStr  # masked in repr/logs
    openai_base_url: str | None = None  # OpenAI-compatible proxy; None → SDK default
    model: str = DEFAULT_MODEL
    prompt_version: str = DEFAULT_PROMPT_VERSION
    gcp_project_id: str | None = None  # required later by CD (Phase 9)
    gcp_project_number: str | None = None
    region: str | None = None

    model_config = {"frozen": True}

    # Phase 0 – Step 4: prompt files are lowercase (prompts/itinerary/v1.md)
    @field_validator("prompt_version")
    @classmethod
    def _lowercase(cls, value: str) -> str:
        return value.lower()


# Phase 0 – Step 4: strip whitespace and stray quotes/backticks; treat empty as missing
def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip("\"'`").strip()
    return cleaned or None


# Phase 0 – Step 4: build Settings from any mapping (pure function, easy to test)
def load_settings(environ: Mapping[str, str]) -> Settings:
    values = {key: _clean(environ.get(key)) for key in (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL", "PROMPT_VERSION",
        "GCP_PROJECT_ID", "GCP_PROJECT_NUMBER", "REGION",
    )}

    missing = [name for name in REQUIRED_VARS if not values[name]]
    if missing:
        raise ConfigError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in."
        )

    return Settings(
        openai_api_key=values["OPENAI_API_KEY"],
        openai_base_url=values["OPENAI_BASE_URL"],
        model=values["MODEL"] or DEFAULT_MODEL,
        prompt_version=values["PROMPT_VERSION"] or DEFAULT_PROMPT_VERSION,
        gcp_project_id=values["GCP_PROJECT_ID"],
        gcp_project_number=values["GCP_PROJECT_NUMBER"],
        region=values["REGION"],
    )


# Phase 0 – Step 4: app entry point – read .env once and cache the result
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(override=False)  # real env vars take precedence over .env
    return load_settings(os.environ)

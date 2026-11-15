# Phase 6 – Step 7: one real agent run. Skipped by default; run with `pytest -m llm` (~1–2 cents).
# Quality is measured statistically in Phase 7; here we only check the run completes sensibly.

import pytest

from agentsville.agent import ItineraryAgent
from agentsville.config import get_settings
from agentsville.llm import LLMClient
from agentsville.samples import sample_vacation_info

pytestmark = pytest.mark.llm


def test_real_agent_produces_a_plan(tmp_path):
    settings = get_settings()
    agent = ItineraryAgent(
        LLMClient(settings),
        prompt_version=settings.prompt_version,
        log_path=tmp_path / "runs.jsonl",
    )
    run = agent.run(sample_vacation_info())

    assert run.stop_reason == "final_answer", [s.observation[:200] for s in run.steps[-3:]]
    assert run.travel_plan is not None
    results = {r.name: r for r in run.final_eval_report.results}
    assert results["city_and_dates"].passed, results["city_and_dates"].details
    assert (tmp_path / "runs.jsonl").exists()

# Phase 4 – Step 6: calibrate the real weather judge on hand-labeled cases (data review §3).
# Skipped by default; run with `pytest -m llm` (uses gpt-4.1, ~2–3 cents).

from pathlib import Path

import pytest

from agentsville.config import get_settings
from agentsville.data_api import get_activity_by_id, get_weather
from agentsville.evals import judge_activity_weather, run_all_evals
from agentsville.llm import LLMClient
from agentsville.models import TravelPlan
from agentsville.samples import sample_vacation_info

pytestmark = pytest.mark.llm

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def llm() -> LLMClient:
    return LLMClient(get_settings())


@pytest.mark.parametrize(
    "activity_id, expected",
    [
        ("event-2025-06-13-1", False),  # outdoor hike, rainy, no fallback
        ("event-2025-06-12-1", True),  # outdoor picnic with indoor rain fallback, thunderstorm
        ("event-2025-06-14-3", True),  # held indoors (keyword hint wrongly says outdoor), rainy
        ("event-2025-06-12-3", True),  # indoor tech & film night, thunderstorm
    ],
)
def test_judge_calibration(llm, activity_id, expected):
    activity = get_activity_by_id(activity_id)
    verdict = judge_activity_weather(llm, activity, get_weather(activity.start_time.date()))
    assert verdict.suitable is expected, verdict.reason


def test_golden_plan_passes_with_real_judge(llm):
    plan = TravelPlan.model_validate_json(
        (REPO_ROOT / "sample_plan.json").read_text(encoding="utf-8")
    )
    report = run_all_evals(sample_vacation_info(), plan, llm=llm)
    assert report.passed, report.summary()

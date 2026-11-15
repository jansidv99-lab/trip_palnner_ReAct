# Phase 4 – Step 6: each eval passes the golden plan and catches its own failure (no network).

import datetime
from pathlib import Path

import pytest

from agentsville.evals import (
    EvalReport,
    eval_activities_per_day,
    eval_city_and_dates,
    eval_interest_coverage,
    eval_no_hallucinated_activities,
    eval_no_overlapping_activities,
    eval_total_cost_accurate,
    eval_weather_matches_forecast,
    eval_weather_suitability,
    eval_within_budget,
    run_all_evals,
)
from agentsville.llm import LLMError, LLMResponse
from agentsville.models import Interest, Traveler, TravelPlan, VacationInfo
from agentsville.samples import sample_vacation_info, tight_budget_vacation_info

REPO_ROOT = Path(__file__).resolve().parent.parent
D = datetime.date


# Phase 4 – Step 6: scripted stand-in for LLMClient – returns queued replies, records calls
class FakeLLM:
    def __init__(self, *replies: str, error: Exception | None = None):
        self.replies = list(replies)
        self.error = error
        self.calls = []

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        self.calls.append({"messages": messages, "model": model, "json_mode": json_mode})
        if self.error:
            raise self.error
        text = self.replies.pop(0) if self.replies else '{"suitable": true, "reason": "ok"}'
        return LLMResponse(text=text, model=model or "fake", latency_ms=1.0)


@pytest.fixture
def golden_plan() -> TravelPlan:
    return TravelPlan.model_validate_json(
        (REPO_ROOT / "sample_plan.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def request_() -> VacationInfo:
    return sample_vacation_info()


def first_activity(plan: TravelPlan):
    return plan.itinerary_days[0].activity_recommendations[0].activity


# --- golden plan ------------------------------------------------------------------


def test_golden_plan_passes_all_deterministic_evals(request_, golden_plan):
    report = run_all_evals(request_, golden_plan, include_llm=False)
    assert report.passed, report.summary()
    assert all(r.passed for r in report.results)


def test_include_llm_false_skips_judge(request_, golden_plan):
    names = [r.name for r in run_all_evals(request_, golden_plan, include_llm=False).results]
    assert "weather_suitability" not in names


def test_include_llm_without_client_raises(request_, golden_plan):
    with pytest.raises(ValueError, match="LLMClient is required"):
        run_all_evals(request_, golden_plan)


# --- E1 city and dates --------------------------------------------------------------


def test_wrong_city_fails(request_, golden_plan):
    golden_plan.city = "Paris"
    result = eval_city_and_dates(request_, golden_plan)
    assert not result.passed and "city is 'Paris'" in result.details[0]


def test_city_casing_ignored(request_, golden_plan):
    golden_plan.city = "agentsville"
    assert eval_city_and_dates(request_, golden_plan).passed


def test_wrong_end_date_fails(request_, golden_plan):
    golden_plan.end_date = D(2025, 6, 13)
    assert any("end_date" in d for d in eval_city_and_dates(request_, golden_plan).details)


def test_missing_day_fails(request_, golden_plan):
    golden_plan.itinerary_days.pop(1)
    assert "missing days: 2025-06-11" in eval_city_and_dates(request_, golden_plan).details


def test_days_out_of_order_fail(request_, golden_plan):
    golden_plan.itinerary_days.reverse()
    assert eval_city_and_dates(request_, golden_plan).details == ["itinerary days are out of order"]


def test_duplicate_day_fails(request_, golden_plan):
    golden_plan.itinerary_days.append(golden_plan.itinerary_days[0].model_copy(deep=True))
    details = eval_city_and_dates(request_, golden_plan).details
    assert any("more than once: 2025-06-10" in d for d in details)


# --- E2 cost accuracy / E3 budget ----------------------------------------------------


def test_wrong_total_fails_cost_but_not_budget(request_, golden_plan):
    golden_plan.total_cost = 120
    cost = eval_total_cost_accurate(request_, golden_plan)
    assert not cost.passed and "activities sum to 108" in cost.details[0]
    assert eval_within_budget(request_, golden_plan).passed  # real sum 108 <= 130


def test_over_budget_fails(golden_plan):
    result = eval_within_budget(tight_budget_vacation_info(), golden_plan)
    assert not result.passed and "over by 68" in result.details[0]


def test_understated_total_cannot_hide_overspend(golden_plan):
    golden_plan.total_cost = 30  # lies: real sum is 108
    assert not eval_within_budget(tight_budget_vacation_info(), golden_plan).passed


# --- E4 hallucinated activities --------------------------------------------------------


def test_unknown_activity_fails(request_, golden_plan):
    first_activity(golden_plan).activity_id = "event-2025-06-10-9"
    result = eval_no_hallucinated_activities(request_, golden_plan)
    assert not result.passed and "does not exist" in result.details[0]


def test_changed_price_fails(request_, golden_plan):
    first_activity(golden_plan).price = 5
    result = eval_no_hallucinated_activities(request_, golden_plan)
    assert "fields differ from the source data: price" in result.details[0]


def test_activity_on_wrong_day_fails(request_, golden_plan):
    rec = golden_plan.itinerary_days[0].activity_recommendations.pop(0)
    golden_plan.itinerary_days[1].activity_recommendations.append(rec)
    result = eval_no_hallucinated_activities(request_, golden_plan)
    assert any("listed on 2025-06-11 but takes place on 2025-06-10" in d for d in result.details)


# --- X1 weather matches forecast --------------------------------------------------------


def test_wrong_weather_fails(request_, golden_plan):
    golden_plan.itinerary_days[0].weather.condition = "rainy"
    result = eval_weather_matches_forecast(request_, golden_plan)
    assert not result.passed and "forecast is clear" in result.details[0]


# --- X2 overlaps and duplicates ---------------------------------------------------------


def test_duplicate_activity_fails(request_, golden_plan):
    day = golden_plan.itinerary_days[0]
    day.activity_recommendations.append(day.activity_recommendations[0].model_copy(deep=True))
    result = eval_no_overlapping_activities(request_, golden_plan)
    assert "event-2025-06-10-0 appears 2 times" in result.details


def test_time_overlap_fails(request_, golden_plan):
    second = golden_plan.itinerary_days[0].activity_recommendations[1].activity
    second.start_time = datetime.datetime(2025, 6, 10, 10, 0)  # first runs 09:00-11:00
    result = eval_no_overlapping_activities(request_, golden_plan)
    assert any("overlaps" in d for d in result.details)


# --- X3 interest coverage / X4 activities per day (warnings) ----------------------------


def test_uncovered_interest_is_warning_only(golden_plan):
    request = VacationInfo(
        travelers=[
            Traveler(name="Yuri", age=30, interests=[Interest.TECHNOLOGY]),
            Traveler(name="Tess", age=40, interests=[Interest.THEATRE]),
        ],
        destination="AgentsVille",
        date_of_arrival=D(2025, 6, 10),
        date_of_departure=D(2025, 6, 12),
        budget=130,
    )
    result = eval_interest_coverage(request, golden_plan)
    assert not result.passed and result.severity == "warning" and result.score == 0.5
    assert "Tess" in result.details[0]
    assert run_all_evals(request, golden_plan, include_llm=False).passed  # warnings don't fail


def test_empty_day_is_warning(request_, golden_plan):
    golden_plan.itinerary_days[2].activity_recommendations.clear()
    result = eval_activities_per_day(request_, golden_plan)
    assert not result.passed and result.severity == "warning"
    assert eval_activities_per_day(request_, golden_plan, minimum=0).passed


# --- E5 weather suitability with a fake judge -------------------------------------------


def test_judge_called_only_for_inclement_days(request_, golden_plan):
    llm = FakeLLM()
    result = eval_weather_suitability(request_, golden_plan, llm)
    assert result.passed and result.kind == "llm"
    assert len(llm.calls) == 1  # only 06-12 (thunderstorm) has an activity: event-2025-06-12-3
    assert llm.calls[0]["json_mode"] is True
    assert "Tech & Film Fusion Night" in llm.calls[0]["messages"][1]["content"]
    assert "thunderstorm" in llm.calls[0]["messages"][1]["content"].lower()


def test_unsuitable_verdict_fails_with_reason(request_, golden_plan):
    llm = FakeLLM('{"suitable": false, "reason": "outdoor event during a storm"}')
    result = eval_weather_suitability(request_, golden_plan, llm)
    assert not result.passed
    assert "event-2025-06-12-3 on 2025-06-12 (thunderstorm): outdoor event" in result.details[0]


def test_unparseable_reply_fails_closed(request_, golden_plan):
    result = eval_weather_suitability(request_, golden_plan, FakeLLM("not json at all"))
    assert not result.passed and "judge reply unparseable" in result.details[0]


def test_llm_error_fails_closed(request_, golden_plan):
    result = eval_weather_suitability(request_, golden_plan, FakeLLM(error=LLMError("timeout")))
    assert not result.passed and "judge call failed" in result.details[0]


# --- report -------------------------------------------------------------------------------


def test_report_summary_lists_failures(request_, golden_plan):
    golden_plan.total_cost = 120
    report = run_all_evals(request_, golden_plan, llm=FakeLLM())
    assert isinstance(report, EvalReport) and not report.passed
    text = report.summary()
    assert text.startswith("EVALS FAILED")
    assert "✗ total_cost_accurate" in text and "activities sum to 108" in text
    assert "✓ weather_suitability" in text


def test_report_serializes_passed_flag(request_, golden_plan):
    data = run_all_evals(request_, golden_plan, include_llm=False).model_dump()
    assert data["passed"] is True

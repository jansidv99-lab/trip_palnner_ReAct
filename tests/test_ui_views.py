# Phase 12 – Step 4: unit tests for the results display data (no Streamlit, no network).
import datetime

from agentsville.evals import EvalReport, EvalResult
from agentsville.models import TravelPlan
from agentsville.samples import sample_vacation_info
from agentsville.ui.form import RunOptions
from agentsville.ui.run import AgentBackend, run_agent
from agentsville.ui.views import (
    CostSummary,
    cost_note,
    cost_summary,
    day_cards,
    eval_label,
    eval_rows,
    is_empty_plan,
    summary_metrics,
)
from tests.test_agent import GOLDEN, HAPPY_SCRIPT, ScriptedLLM


def _plan(**overrides) -> TravelPlan:
    return TravelPlan.model_validate({**GOLDEN, **overrides})


def test_cost_summary_uses_actual_prices():
    cost = cost_summary(_plan(total_cost=999), sample_vacation_info())
    assert (cost.actual_total, cost.reported_total, cost.budget) == (108, 999, 130)
    assert cost.within_budget and not cost.total_matches
    assert cost.remaining == 22


def test_cost_note():
    assert cost_note(CostSummary(108, 108, 130)) is None
    assert cost_note(CostSummary(108, 120, 130)) == (
        "The agent reported a total of 120, but the prices add up to 108."
    )
    assert cost_note(CostSummary(150, 150, 130)) == "This is 20 over your budget of 130."


def test_day_cards_from_sample_plan():
    cards = day_cards(_plan())
    assert [c.title for c in cards] == ["Tue, Jun 10", "Wed, Jun 11", "Thu, Jun 12"]
    first = cards[0]
    assert first.weather == "clear · 31 °C"
    assert first.activities[0].time == "09:00–11:00"
    assert first.activities[0].name == "FutureTech Breakfast Meet-Up"
    assert first.activities[0].interests == "technology"
    assert first.activities[0].reasons[0] == "Matches Yuri's interest in technology"
    assert sum(c.day_cost for c in cards) == 108


def test_inclement_badge_follows_the_real_forecast():
    cards = day_cards(_plan())
    assert [c.inclement for c in cards] == [False, False, True]  # 06-12 is a thunderstorm


def test_day_cards_sorted_by_date_and_activities_by_time():
    plan = _plan()
    plan.itinerary_days.reverse()
    for day in plan.itinerary_days:
        day.activity_recommendations.reverse()
    cards = day_cards(plan)
    assert [c.date for c in cards] == sorted(c.date for c in cards)
    for card in cards:
        times = [a.time for a in card.activities]
        assert times == sorted(times)


def test_empty_plan():
    days = [
        {**day, "activity_recommendations": []} for day in GOLDEN["itinerary_days"]
    ]
    plan = _plan(itinerary_days=days, total_cost=0)
    assert is_empty_plan(plan)
    assert all(not c.activities and c.day_cost == 0 for c in day_cards(plan))
    assert not is_empty_plan(_plan())


def test_eval_rows_failed_first_with_labels():
    report = EvalReport(
        results=[
            EvalResult(name="city_and_dates", passed=True),
            EvalResult(name="activities_per_day", passed=False, severity="warning"),
            EvalResult(name="total_cost_accurate", passed=False, details=["reported 120"]),
        ]
    )
    rows = eval_rows(report)
    assert [(r.icon, r.label) for r in rows] == [
        ("✗", "total cost calculation"),
        ("!", "activities per day"),
        ("✓", "city and dates"),
    ]
    assert rows[0].details == ["reported 120"]


def test_eval_label_fallback():
    assert eval_label("brand_new_check") == "brand new check"


def test_summary_metrics_with_and_without_plan():
    llm = ScriptedLLM(*HAPPY_SCRIPT)
    backend = AgentBackend(llm=llm, prompt_version="v1", log_path=None)
    run = run_agent(sample_vacation_info(), RunOptions(), backend)
    labels = {label: value for label, value, _ in summary_metrics(run)}
    assert labels["Total cost"] == "108 / 130"
    assert labels["Days"] == "3" and labels["Activities"] == "6"
    assert labels["Agent steps"] == "4"

    run.travel_plan = None
    assert [m[0] for m in summary_metrics(run)] == ["Agent steps", "Run cost", "Time"]


def test_golden_dates_are_the_sample_trip():
    # guards the fixtures above: GOLDEN must stay the sample trip's plan
    assert _plan().start_date == datetime.date(2025, 6, 10)


# ---------------------------------------------------------------------------
# Phase 12 – Step 5: quality panel
# ---------------------------------------------------------------------------
from agentsville.graders import ALL_GRADERS  # noqa: E402
from agentsville.ui.views import GRADER_LABELS, quality_panel, skipped_judges  # noqa: E402


def _happy_run():
    backend = AgentBackend(llm=ScriptedLLM(*HAPPY_SCRIPT), prompt_version="v1", log_path=None)
    return run_agent(sample_vacation_info(), RunOptions(), backend)


def _rows(run) -> dict:
    return {row.name: row for group in quality_panel(run) for row in group.rows}


def test_every_code_grader_has_a_label():
    code = {g.name for g in ALL_GRADERS if g.kind == "deterministic"}
    assert code <= set(GRADER_LABELS)


def test_quality_panel_has_three_groups_with_only_code_graders():
    groups = quality_panel(_happy_run())
    assert [g.title.split(" –")[0] for g in groups] == [
        "Grounding", "Constraints", "Relevancy & reasoning",
    ]
    llm_names = {g.name for g in ALL_GRADERS if g.kind == "llm"}
    assert not llm_names & set(_rows(_happy_run()))


def test_quality_panel_on_the_golden_plan():
    rows = _rows(_happy_run())
    assert rows["activity_grounding"].status == "pass"
    assert rows["activity_grounding"].summary == "6/6 ok"
    assert rows["budget_respected"].status == "pass"
    assert rows["verified_before_final"].status == "pass"
    # the scripted run only looked up 06-10 and never used the calculator
    assert rows["calculator_total"].status == "fail"
    assert rows["calculator_total"].details == ["calculator_tool was never used"]
    assert rows["weather_lookup_coverage"].summary == "2 of 3 failed"


def test_label_graders_need_a_golden_case():
    rows = _rows(_happy_run())
    for name in ("weather_label_compliance", "infeasible_handling", "interest_coverage_labeled"):
        assert rows[name].status == "n/a"
        assert rows[name].summary == "needs a golden test case"


def test_altered_activity_fails_grounding_with_detail():
    run = _happy_run()
    run.travel_plan.itinerary_days[0].activity_recommendations[0].activity.price = 1
    row = _rows(run)["activity_grounding"]
    assert row.status == "fail" and row.summary == "1 of 6 failed"
    assert row.details


def test_run_without_plan():
    run = _happy_run()
    run.travel_plan = None
    rows = _rows(run)
    assert rows["activity_grounding"].status == "n/a"
    assert rows["activity_grounding"].summary == "no plan to check"
    assert rows["tool_efficiency"].status in ("pass", "fail")  # judges plan-less runs itself


def test_skipped_judges():
    assert skipped_judges() == [
        "reasons grounded", "traveler relevancy", "thought action consistency",
    ]

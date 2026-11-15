# Phase 10 – Step 2: B3 relevancy code graders (label-aware interest coverage, interest match).
# Phase 10 – Step 4: traveler-relevancy judge, ordinal agreement, relevancy calibration.

import copy
import json
from datetime import date

import pytest

from agentsville.graders.relevancy import (
    DayFact,
    interest_coverage_labeled,
    interest_match,
    relevancy_judge_input,
    relevancy_judge_prompt,
    score_from_days,
    served_days,
    traveler_relevancy,
    trip_days,
    verify_possible,
)
from agentsville.harness.calibration import (
    calibrate_relevancy_judge,
    ordinal_agreement,
    quadratic_weighted_kappa,
)
from agentsville.harness.dataset import (
    GoldenCase,
    GoldenLabels,
    RelevancyCalibrationItem,
    load_relevancy_calibration,
    write_calibration,
)
from agentsville.harness.grading import GradingContext
from agentsville.llm import LLMError, LLMResponse
from agentsville.models import TravelPlan
from tests.harness_fakes import GOLDEN_PLAN
from tests.test_constraints import empty_plan, run_with

# sample_vacation_info(): Yuri (technology, tennis, cooking), Hiro (reading, art, music).
# GOLDEN_PLAN covers both; event-2025-06-12-3 is technology + movies.


def case(**labels) -> GradingContext:
    return GradingContext(case=GoldenCase(
        case_id="g99-test", tags=["test"], description="test",
        vacation_info=run_with(None).vacation_info,
        labels=GoldenLabels(expected_behavior="test", **labels)))


def only_activity(activity_id: str) -> dict:
    """GOLDEN_PLAN reduced to the one activity with this id."""
    plan = copy.deepcopy(GOLDEN_PLAN)
    for day in plan["itinerary_days"]:
        day["activity_recommendations"] = [r for r in day["activity_recommendations"]
                                           if r["activity"]["activity_id"] == activity_id]
    return plan


# --- interest_coverage_labeled --------------------------------------------------------------------


def test_coverage_all_travelers_covered():
    o = interest_coverage_labeled(run_with(GOLDEN_PLAN), case())
    assert o.passed and (o.units, o.failed_units) == (2, 0)


def test_coverage_flags_coverable_traveler_left_out():
    o = interest_coverage_labeled(run_with(only_activity("event-2025-06-12-3")), case())
    assert not o.passed and (o.units, o.failed_units) == (2, 1)
    assert o.counts == {"uncovered": 1} and o.details[0].startswith("Hiro:")


def test_coverage_excludes_uncoverable_traveler():
    o = interest_coverage_labeled(run_with(only_activity("event-2025-06-12-3")),
                                  case(uncoverable_travelers=["Hiro"]))
    assert o.passed and (o.units, o.failed_units) == (1, 0)


def test_coverage_not_applicable_without_case_or_when_nothing_affordable():
    assert interest_coverage_labeled(run_with(GOLDEN_PLAN), GradingContext()).units == 0
    o = interest_coverage_labeled(run_with(empty_plan()), case(max_affordable_activities=0))
    assert o.passed and o.details == ["not applicable: nothing affordable – coverage impossible"]


# --- interest_match -------------------------------------------------------------------------------


def test_interest_match_all_activities_match():
    o = interest_match(run_with(GOLDEN_PLAN))
    assert o.passed and o.units == 6


def test_interest_match_counts_outside_interest_activity():
    plan = only_activity("event-2025-06-12-3")
    plan["itinerary_days"][2]["activity_recommendations"][0]["activity"]["related_interests"] = [
        "movies"]
    o = interest_match(run_with(plan))
    assert not o.passed and (o.units, o.failed_units) == (1, 1)
    assert o.counts == {"no_matching_interest": 1} and "movies match no traveler" in o.details[0]


def test_interest_match_empty_plan_has_no_units():
    o = interest_match(run_with(empty_plan()))
    assert o.passed and o.units == 0


# --- traveler_relevancy judge (Phase 10 – Step 4) -------------------------------------------------


class ScoreJudge:
    """Fake relevancy judge: fixed reply text, or raises."""

    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls, self.messages = text, error, 0, None

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        self.calls, self.messages = self.calls + 1, messages
        if self.error:
            raise self.error
        return LLMResponse(text=self.text, model="judge", latency_ms=1)


DATES = ("2025-06-10", "2025-06-11", "2025-06-12")


# real options that pass code verification (match, unplanned, affordable, no overlap)
OPTIONS = {"Yuri": ["event-2025-06-10-0", "event-2025-06-11-1", "event-2025-06-12-3"],
           "Hiro": ["event-2025-06-10-3", "event-2025-06-11-2", "event-2025-06-12-1"]}


def reply(*possible, dates=DATES, options=None) -> str:
    """Judge v2 reply: one list of per-day `possible` facts per traveler (Yuri, Hiro, …)."""
    names = ["Yuri", "Hiro"]
    return json.dumps({"travelers": [
        {"name": n, "days": [{"date": d, "possible": p, "why": "w",
                              "option": (options or OPTIONS)[n][i]}
                             for i, (d, p) in enumerate(zip(dates, days, strict=True))]}
        for n, days in zip(names, possible, strict=False)]})


ALL = (True, True, True)


# Phase 10 – Step 4: the labeling rule in code
@pytest.mark.parametrize(
    "possible, served, score",
    [((1, 1, 1), (1, 1, 1), 5), ((0, 0, 0), (0, 0, 0), 5), ((1, 1, 1), (1, 1, 0), 4),
     ((1, 1, 1), (1, 0, 0), 3), ((0, 1, 1, 1, 1), (0, 0, 1, 0, 0), 2), ((1, 1, 1), (0, 0, 0), 1),
     ((1, 0), (0, 0), 1), ((0, 1), (1, 1), 5), ((0, 1), (1, 0), 4)],
    ids=["all-served", "nothing-possible", "one-miss", "1-of-3-served", "1-of-5-served",
         "all-missed", "only-possible-day-missed", "served-on-impossible-day",
         "served-day-counts-as-possible"],  # g09 r1 Ben: every match already planned on 06-11
)
def test_score_from_days(possible, served, score):
    assert score_from_days([bool(p) for p in possible], [bool(s) for s in served]) == score


def test_served_days_is_computed_from_interests():
    hiro = run_with(None).vacation_info.travelers[1]  # reading, art, music
    days = trip_days(run_with(None).vacation_info)
    assert served_days(hiro, TravelPlan.model_validate(GOLDEN_PLAN), days) == [True, True, False]


def test_served_days_and_input_cover_days_missing_from_the_plan():
    plan = copy.deepcopy(GOLDEN_PLAN)
    del plan["itinerary_days"][1]  # the plan forgets 06-11
    info, travel_plan = run_with(None).vacation_info, TravelPlan.model_validate(plan)
    yuri = info.travelers[0]
    assert served_days(yuri, travel_plan, trip_days(info)) == [True, False, True]
    text = relevancy_judge_input(info, travel_plan)
    assert "DAY 2025-06-11" in text
    assert text.split("DAY 2025-06-11", 1)[1].split("AVAILABLE", 1)[0].strip().endswith(
        "- (nothing)")


# Phase 10 – Step 4: code rejects every "possible" claim it can disprove
@pytest.mark.parametrize(
    "option, budget, why",
    [("event-2025-06-12-9", 130, "is not an activity on 2025-06-12"),
     ("event-2025-06-12-3", 130, "is already planned"),
     ("event-2025-06-12-2", 130, "doesn't match the interests of Hiro"),  # writing/hiking
     ("event-2025-06-12-1", 110, "doesn't fit the budget (108 + 15 > 110)")],
)
def test_verify_possible_rejects(option, budget, why):
    hiro = run_with(None).vacation_info.travelers[1]
    fact = DayFact(date="2025-06-12", possible=True, option=option)
    plan = TravelPlan.model_validate(GOLDEN_PLAN)
    assert why in verify_possible(fact, hiro, plan, budget, date(2025, 6, 12))


def test_verify_possible_rejects_overlap_and_accepts_a_valid_option():
    hiro = run_with(None).vacation_info.travelers[1]
    plan = TravelPlan.model_validate(GOLDEN_PLAN)
    # 06-11: 11-2 (art/music, 15:00) is planned; 11-3 (art/cooking, 18:30, price 25) is free
    ok = DayFact(date="2025-06-11", possible=True, option="event-2025-06-11-3")
    assert verify_possible(ok, hiro, plan, 200, date(2025, 6, 11)) is None
    shifted = copy.deepcopy(GOLDEN_PLAN)
    shifted["itinerary_days"][1]["activity_recommendations"][1]["activity"]["end_time"] = (
        "2025-06-11T19:00:00")  # the planned 11-2 now runs into 11-3's start
    clash = verify_possible(ok, hiro, TravelPlan.model_validate(shifted), 200, date(2025, 6, 11))
    assert "overlaps a planned activity" in clash


def test_relevancy_input_shows_plan_forecast_and_every_available_activity():
    info = run_with(None).vacation_info
    text = relevancy_judge_input(info, TravelPlan.model_validate(GOLDEN_PLAN))
    assert "- Yuri (age 30): technology, tennis, cooking" in text
    assert "BUDGET: 130 (plan total_cost: 108)" in text
    assert "FORECAST: thunderstorm" in text
    # 06-12 has 4 activities in the data; all are offered as alternatives, with descriptions
    day = text.split("DAY 2025-06-12", 1)[1]
    available = day.split("AVAILABLE THAT DAY:", 1)[1]
    assert sum(line.startswith("- event-2025-06-12-") for line in available.splitlines()) == 4


def test_traveler_relevancy_scores_and_counts():
    # GOLDEN_PLAN serves Yuri every day; Hiro is not served on 06-12 (tech/movies only)
    judge = ScoreJudge(reply(ALL, ALL))
    o = traveler_relevancy(run_with(GOLDEN_PLAN), GradingContext(llm=judge))
    assert judge.calls == 1 and judge.messages[0]["content"] == relevancy_judge_prompt()
    assert o.passed and o.units == 2 and o.counts == {"score_4": 1, "score_5": 1}


def test_traveler_relevancy_fails_ignored_traveler():
    # only 06-12's tech/movies activity: Hiro never served (1), Yuri served 1 of 3 days (3)
    plan = only_activity("event-2025-06-12-3")
    o = traveler_relevancy(run_with(plan), GradingContext(llm=ScoreJudge(reply(ALL, ALL))))
    assert (o.units, o.failed_units) == (2, 1) and o.counts == {"score_1": 1, "score_3": 1}
    assert o.details[0].startswith("Hiro: score 1 – missed 2025-06-10: event-2025-06-10-3 – w")


def test_traveler_relevancy_ignores_a_claim_code_disproves():
    # the judge claims Hiro could have had 12-2 (writing/hiking) – not his interest → no miss
    bad = {"Yuri": OPTIONS["Yuri"], "Hiro": [*OPTIONS["Hiro"][:2], "event-2025-06-12-2"]}
    judge = ScoreJudge(reply(ALL, ALL, options=bad))
    o = traveler_relevancy(run_with(GOLDEN_PLAN), GradingContext(llm=judge))
    assert o.counts == {"score_5": 2}


@pytest.mark.parametrize(
    "judge, message",
    [(ScoreJudge(text="not json"), "unparseable"),
     (ScoreJudge(error=LLMError("timeout")), "judge call failed"),
     (ScoreJudge(text=reply(ALL)), "judge returned 1 travelers, expected 2"),
     (ScoreJudge(text=reply((True,), (True,), dates=("2025-06-10",))), "match the trip's days"),
     (ScoreJudge(text=reply(ALL, ALL).replace("true", '"maybe"', 1)), "unparseable")],
)
def test_traveler_relevancy_fails_closed(judge, message):
    o = traveler_relevancy(run_with(GOLDEN_PLAN), GradingContext(llm=judge))
    assert o.failed_units == o.units == 2 and o.counts == {"score_1": 2}
    assert message in o.details[0]


def test_traveler_relevancy_not_applicable_for_infeasible_case():
    judge = ScoreJudge(reply(ALL, ALL))
    o = traveler_relevancy(run_with(empty_plan()), case(max_affordable_activities=0))
    assert o.passed and o.units == 0 and judge.calls == 0


# --- ordinal agreement + calibration (Phase 10 – Step 4) ------------------------------------------


@pytest.mark.parametrize(
    "human, judge, qwk",
    [([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], 1.0), ([1, 2, 3, 4, 5], [5, 4, 3, 2, 1], -1.0),
     ([5, 5, 4, 3], [5, 4, 4, 2], 0.7647), ([4, 4, 4], [4, 4, 4], 1.0), ([4, 4], [4, 5], 0.0)],
)
def test_quadratic_weighted_kappa_known_values(human, judge, qwk):
    assert quadratic_weighted_kappa(human, judge) == pytest.approx(qwk, abs=1e-4)


def test_ordinal_agreement():
    assert ordinal_agreement([5, 5, 4, 3], [5, 4, 4, 1]) == pytest.approx(
        {"exact": 0.5, "within_1": 0.75, "mae": 0.75,
         "qwk": quadratic_weighted_kappa([5, 5, 4, 3], [5, 4, 4, 1])})


def calibration_set(tmp_path):
    info = run_with(None).vacation_info
    items = [RelevancyCalibrationItem(item_id="r01-golden", source="test", vacation_info=info,
                                      travel_plan=TravelPlan.model_validate(GOLDEN_PLAN),
                                      scores=[5, 4], justifications=["a", "b"])]
    write_calibration("relevancy", "v0.0.1", items, created=date(2026, 1, 1), root=tmp_path)
    return load_relevancy_calibration("v0.0.1", root=tmp_path)


def test_calibrate_relevancy_judge(tmp_path):
    # human: Yuri 5, Hiro 4. Judge facts: Hiro could have been served on 06-12 → 4 (agrees);
    # Yuri: no possible day → 5 (agrees)
    dataset = calibration_set(tmp_path)  # written once – versions are immutable
    agree = calibrate_relevancy_judge(dataset, ScoreJudge(reply((False,) * 3, ALL)))
    assert agree.n == 2 and agree.exact == 1.0 and agree.disagreements == []
    # judge says Hiro had nothing possible on 06-12 → 5, human said 4
    differ = calibrate_relevancy_judge(dataset, ScoreJudge(reply(ALL, (True, True, False))))
    assert differ.exact == 0.5 and differ.within_1 == 1.0 and differ.mae == 0.5
    assert differ.disagreements == ["r01-golden Hiro: human 4, judge 5 – no missed day"]
    assert agree.judge_prompt_version == "v2"


def test_relevancy_calibration_item_needs_one_score_per_traveler():
    info = run_with(None).vacation_info
    with pytest.raises(ValueError, match="one score"):
        RelevancyCalibrationItem(item_id="r01-x", source="t", vacation_info=info,
                                 travel_plan=TravelPlan.model_validate(GOLDEN_PLAN),
                                 scores=[5], justifications=["a"])

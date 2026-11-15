# Phase 8 – Step 11: calibration datasets, judge-vs-human math, and threshold checks.

from datetime import date

import pytest

from agentsville.harness.calibration import calibrate_reasons_judge, confusion, scores
from agentsville.harness.dataset import (
    CalibrationItem,
    DatasetError,
    load_calibration,
    write_calibration,
)
from agentsville.harness.metrics import GroundingMetrics, RateStat
from agentsville.harness.thresholds import check_thresholds, thresholds_passed
from agentsville.samples import sample_vacation_info
from tests.harness_fakes import ConversationFake

YURI_HIRO = sample_vacation_info().travelers


def item(item_id="c01-x", reasons=("ok", "UNGROUNDED claim"), grounded=(True, False)):
    return CalibrationItem(item_id=item_id, activity_id="event-2025-06-10-0",
                           travelers=YURI_HIRO, reasons=list(reasons), grounded=list(grounded))


# --- dataset ---------------------------------------------------------------------------------


def test_calibration_round_trip_and_immutability(tmp_path):
    write_calibration("reasons", "v0.0.1", [item()], date(2026, 1, 1), root=tmp_path)
    data = load_calibration("reasons", "v0.0.1", root=tmp_path)
    assert data.items[0].grounded == [True, False]
    with pytest.raises(DatasetError, match="already exists"):
        write_calibration("reasons", "v0.0.1", [item()], date(2026, 1, 1), root=tmp_path)


def test_calibration_tamper_and_unknown_activity(tmp_path):
    write_calibration("reasons", "v0.0.1", [item()], date(2026, 1, 1), root=tmp_path)
    path = tmp_path / "reasons" / "v0.0.1" / "items.jsonl"
    path.write_text(path.read_text("utf-8").replace("UNGROUNDED", "Ungrounded"), "utf-8")
    with pytest.raises(DatasetError, match="hash mismatch"):
        load_calibration("reasons", "v0.0.1", root=tmp_path)
    bad = item().model_copy(update={"activity_id": "event-x"})
    write_calibration("reasons", "v0.0.2", [bad], date(2026, 1, 1), root=tmp_path)
    with pytest.raises(DatasetError, match="unknown activity event-x"):
        load_calibration("reasons", "v0.0.2", root=tmp_path)


def test_one_label_per_reason_enforced():
    with pytest.raises(ValueError, match="one grounded label per reason"):
        item(reasons=("a", "b"), grounded=(True,))


def test_released_calibration_v1():
    data = load_calibration("reasons", "v1.0.0")
    reasons = [g for i in data.items for g in i.grounded]
    assert len(data.items) == 14 and len(reasons) == 32
    assert reasons.count(False) == 12


# --- math --------------------------------------------------------------------------------------


def test_confusion_positive_class_is_ungrounded():
    human = [True, True, False, False]  # True = ungrounded
    judge = [True, False, True, False]
    assert confusion(human, judge) == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}


@pytest.mark.parametrize(
    "counts, expected",
    [
        ({"tp": 5, "fp": 0, "tn": 5, "fn": 0}, {"precision": 1.0, "recall": 1.0, "kappa": 1.0}),
        ({"tp": 3, "fp": 3, "tn": 3, "fn": 3}, {"precision": 0.5, "recall": 0.5, "kappa": 0.0}),
        ({"tp": 9, "fp": 1, "tn": 18, "fn": 2},
         {"precision": 0.9, "recall": 9 / 11, "kappa": pytest.approx(0.7805, abs=1e-4)}),
    ],
)
def test_scores(counts, expected):
    result = scores(**counts)
    for key, value in expected.items():
        assert result[key] == pytest.approx(value)


def test_calibrate_with_fake_judge(tmp_path):
    # the fake judge flags reasons containing "UNGROUNDED": c01 perfect; c02's hidden lie missed
    items = [item(), item("c02-y", reasons=("subtle lie",), grounded=(False,))]
    write_calibration("reasons", "v0.0.1", items, date(2026, 1, 1), root=tmp_path)
    report = calibrate_reasons_judge(load_calibration("reasons", "v0.0.1", root=tmp_path),
                                     ConversationFake([]))
    assert (report.tp, report.fp, report.tn, report.fn) == (1, 0, 1, 1)
    assert report.recall == 0.5 and report.precision == 1.0
    assert any("c02-y (missed)" in d for d in report.disagreements)


# --- thresholds ----------------------------------------------------------------------------------


class FakeSummary:
    def __init__(self, b1):
        self.b1 = b1


class FakeCalibration:
    recall, precision = 0.95, 0.75


def stat(k, n):
    return RateStat.of(k, n)


def test_thresholds(tmp_path):
    rules = tmp_path / "t.toml"
    rules.write_text(
        "[b1]\nmax_activity_hallucination_rate = 0.05\nmax_ungrounded_reason_rate = 0.1\n"
        "min_judge_recall = 0.9\nmin_judge_precision = 0.8\nmax_bogus_metric = 1\n",
        encoding="utf-8",
    )
    b1 = GroundingMetrics(activity_hallucination=stat(1, 100), plan_hallucination=stat(1, 30),
                          trajectory_ungrounded=stat(0, 10), reason_reference_errors=stat(0, 10),
                          ungrounded_reasons=None)
    results = {r.rule: r for r in check_thresholds(FakeSummary(b1), FakeCalibration(), rules)}
    assert results["max_activity_hallucination_rate"].passed is True
    assert results["max_ungrounded_reason_rate"].passed is None  # judge not run
    assert results["min_judge_recall"].passed is True
    assert results["min_judge_precision"].passed is False
    assert results["max_bogus_metric"].note == "unknown rule"
    assert not thresholds_passed(list(results.values()))


def test_thresholds_without_b1_or_calibration(tmp_path):
    rules = tmp_path / "t.toml"
    rules.write_text("[b1]\nmax_activity_hallucination_rate = 0.05\nmin_judge_recall = 0.9\n",
                     encoding="utf-8")
    results = check_thresholds(FakeSummary(None), None, rules)
    assert all(r.passed is None for r in results) and thresholds_passed(results)

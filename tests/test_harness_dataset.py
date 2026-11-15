# Phase 7 – Step 9: golden dataset loading, immutability checks and the released v1.0.0.

import json
from datetime import date

import pytest

from agentsville.harness import dataset as ds
from agentsville.harness.dataset import (
    DatasetError,
    GoldenCase,
    GoldenLabels,
    load_golden,
    write_golden,
)
from agentsville.samples import sample_vacation_info
from tests.harness_fakes import make_dataset

# --- format and immutability (temporary datasets) ------------------------------------------------


def test_round_trip(tmp_path):
    make_dataset(tmp_path)
    data = load_golden("v0.0.1", root=tmp_path)
    assert [c.case_id for c in data.cases] == ["g01-sample", "g02-rainy"]
    assert data.manifest.case_count == 2
    assert data.case("g02-rainy").vacation_info.travelers[0].name == "Mika"


def test_versions_are_immutable(tmp_path):
    make_dataset(tmp_path)
    with pytest.raises(DatasetError, match="already exists"):
        make_dataset(tmp_path)


def test_tampered_cases_detected(tmp_path):
    make_dataset(tmp_path)
    path = tmp_path / "v0.0.1" / "cases.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("Mika", "Mike"), encoding="utf-8")
    with pytest.raises(DatasetError, match="hash mismatch"):
        load_golden("v0.0.1", root=tmp_path)


def test_crlf_checkout_still_verifies(tmp_path):
    make_dataset(tmp_path)
    path = tmp_path / "v0.0.1" / "cases.jsonl"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))  # what autocrlf does on Windows
    assert len(load_golden("v0.0.1", root=tmp_path).cases) == 2


def test_changed_data_detected(tmp_path, monkeypatch):
    make_dataset(tmp_path)
    monkeypatch.setattr(ds, "data_fingerprint", lambda: "different")
    with pytest.raises(DatasetError, match="data fingerprint mismatch"):
        load_golden("v0.0.1", root=tmp_path)


def test_missing_version(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        load_golden("v9.9.9", root=tmp_path)


@pytest.mark.parametrize(
    "labels, message",
    [
        (GoldenLabels(must_avoid_activity_ids=["event-x"], expected_behavior="t"),
         "unknown activity"),
        (GoldenLabels(uncoverable_travelers=["Nobody"], expected_behavior="t"), "unknown traveler"),
    ],
)
def test_invalid_labels_rejected(tmp_path, labels, message):
    case = GoldenCase(case_id="g01-x", tags=["t"], description="d",
                      vacation_info=sample_vacation_info(), labels=labels)
    write_golden("v0.0.1", [case], date(2026, 1, 1), root=tmp_path)
    with pytest.raises(DatasetError, match=message):
        load_golden("v0.0.1", root=tmp_path)


def test_duplicate_case_ids_rejected(tmp_path):
    case = GoldenCase(case_id="g01-x", tags=["t"], description="d",
                      vacation_info=sample_vacation_info(),
                      labels=GoldenLabels(expected_behavior="t"))
    write_golden("v0.0.1", [case, case], date(2026, 1, 1), root=tmp_path)
    with pytest.raises(DatasetError, match="duplicate case_id g01-x"):
        load_golden("v0.0.1", root=tmp_path)


# --- the released golden v1.0.0 ------------------------------------------------------------------


def test_golden_v1_loads_and_is_complete():
    data = load_golden("v1.0.0")
    assert data.manifest.case_count == 12
    assert len({c.case_id for c in data.cases}) == 12
    tags = {t for c in data.cases for t in c.tags}
    assert {"baseline", "budget", "weather", "coverage", "edge"} <= tags


def test_golden_v1_key_labels():
    data = load_golden("v1.0.0")
    assert data.case("g07-infeasible-budget").labels.max_affordable_activities == 0
    assert data.case("g02-tight-budget").labels.max_affordable_activities == 2
    assert data.case("g04-theatre-uncoverable").labels.uncoverable_travelers == ["Tess"]
    assert data.case("g03-rainy-outdoor-lover").labels.uncoverable_travelers == ["Mika"]
    g11 = data.case("g11-storm-day-only").labels
    assert g11.must_avoid_activity_ids == ["event-2025-06-12-2"]
    assert g11.ambiguous_activity_ids == ["event-2025-06-12-0"]
    assert data.case("g10-outdoor-fair-weather").labels.must_avoid_activity_ids == []


def test_golden_v1_manifest_is_lf_json():
    raw = (ds.DATASETS_DIR / "v1.0.0" / "manifest.json").read_text(encoding="utf-8")
    assert json.loads(raw)["version"] == "v1.0.0"

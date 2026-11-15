# Phase 7 – Step 1: versioned, tamper-evident golden datasets.
"""Golden datasets live in evals/datasets/golden/<version>/:

    cases.jsonl    one GoldenCase per line
    manifest.json  version, case count, sha256 of cases.jsonl, fingerprint of data/data.py
    CHANGELOG.md   what the version contains and why

A released version is immutable: `load_golden` recomputes both hashes and refuses to load on any
mismatch. Hashes are computed on LF-normalized text, so Windows (CRLF checkout) and Linux CI agree.
"""

import hashlib
import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, model_validator

from agentsville.data_api import get_activity_by_id
from agentsville.models import Traveler, VacationInfo

ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = ROOT / "evals" / "datasets" / "golden"
DATA_FILE = ROOT / "data" / "data.py"


# Phase 7 – Step 1: any problem loading or writing a dataset
class DatasetError(RuntimeError):
    pass


# Phase 7 – Step 1: human judgments about what a good plan for this case must (not) do
class GoldenLabels(BaseModel):
    must_avoid_activity_ids: list[str] = []  # clearly unsuitable for the weather
    ambiguous_activity_ids: list[str] = []  # deliberately left unlabeled (e.g. before a storm)
    uncoverable_travelers: list[str] = []  # no weather-suitable activity matches their interests
    max_affordable_activities: int | None = None  # set for budget-pressure cases
    expected_behavior: str


# Phase 7 – Step 1: one exam question – a trip request plus its labels
class GoldenCase(BaseModel):
    case_id: str = Field(pattern=r"^g\d{2}-[a-z0-9-]+$")
    tags: list[str] = Field(min_length=1)
    description: str
    vacation_info: VacationInfo
    labels: GoldenLabels


# Phase 7 – Step 1: identity of a released dataset version
class DatasetManifest(BaseModel):
    name: str = "golden"
    version: str
    created: date
    case_count: int
    cases_sha256: str
    data_fingerprint: str


# Phase 7 – Step 1: a loaded, verified dataset
class GoldenDataset(BaseModel):
    manifest: DatasetManifest
    cases: list[GoldenCase]

    def case(self, case_id: str) -> GoldenCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(case_id)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# Phase 7 – Step 1: hash of the mock data the labels were written against
def data_fingerprint(path: Path = DATA_FILE) -> str:
    return _sha256_text(path.read_text(encoding="utf-8"))


def _check_labels(case: GoldenCase) -> list[str]:
    labeled = case.labels.must_avoid_activity_ids + case.labels.ambiguous_activity_ids
    problems = [f"{case.case_id}: unknown activity {aid}" for aid in labeled
                if get_activity_by_id(aid) is None]
    names = {t.name for t in case.vacation_info.travelers}
    problems += [f"{case.case_id}: unknown traveler {n}" for n in case.labels.uncoverable_travelers
                 if n not in names]
    return problems


# Phase 8 – Step 3: shared by all dataset kinds – read a version and verify both hashes
def _read_verified(
    folder: Path, records_file: str, label: str
) -> tuple[DatasetManifest, list[str]]:
    try:
        manifest = DatasetManifest.model_validate_json(
            (folder / "manifest.json").read_text(encoding="utf-8")
        )
        text = (folder / records_file).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DatasetError(f"dataset {label} not found in {folder.parent}") from exc
    if _sha256_text(text) != manifest.cases_sha256:
        raise DatasetError(f"dataset {label}: {records_file} was modified (hash mismatch)")
    if data_fingerprint() != manifest.data_fingerprint:
        raise DatasetError(
            f"dataset {label}: data/data.py changed since the labels were written "
            "(data fingerprint mismatch) – create a new dataset version"
        )
    return manifest, [line for line in text.splitlines() if line.strip()]


def _parse(lines: list[str], model: type[BaseModel], label: str) -> list:
    records = []
    for number, line in enumerate(lines, start=1):
        try:
            records.append(model.model_validate_json(line))
        except ValidationError as exc:
            raise DatasetError(f"dataset {label}, record {number}: {exc}") from exc
    return records


def _duplicates(ids: list[str], what: str) -> list[str]:
    return [f"duplicate {what} {d}" for d in sorted({i for i in ids if ids.count(i) > 1})]


# Phase 8 – Step 3: shared writer – a NEW version only (released versions are immutable)
def _write_versioned(
    folder: Path, records_file: str, records: list[BaseModel], name: str, version: str,
    created: date,
) -> DatasetManifest:
    if folder.exists():
        raise DatasetError(f"dataset {version} already exists – versions are immutable")
    folder.mkdir(parents=True)
    text = "".join(json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n"
                   for r in records)
    (folder / records_file).write_text(text, encoding="utf-8", newline="\n")
    manifest = DatasetManifest(
        name=name, version=version, created=created, case_count=len(records),
        cases_sha256=_sha256_text(text), data_fingerprint=data_fingerprint(),
    )
    (folder / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


# Phase 7 – Step 1: load a version and verify hash, data fingerprint, schema and labels
def load_golden(version: str = "v1.0.0", root: Path = DATASETS_DIR) -> GoldenDataset:
    manifest, lines = _read_verified(root / version, "cases.jsonl", version)
    cases = _parse(lines, GoldenCase, version)
    problems = _duplicates([c.case_id for c in cases], "case_id")
    if len(cases) != manifest.case_count:
        problems.append(f"manifest says {manifest.case_count} cases, found {len(cases)}")
    for case in cases:
        problems += _check_labels(case)
    if problems:
        raise DatasetError(f"dataset {version}: " + "; ".join(problems))
    return GoldenDataset(manifest=manifest, cases=cases)


# Phase 7 – Step 1: write a NEW version (never overwrites a released one)
def write_golden(
    version: str, cases: list[GoldenCase], created: date, root: Path = DATASETS_DIR
) -> DatasetManifest:
    return _write_versioned(root / version, "cases.jsonl", cases, "golden", version, created)


# ---------------------------------------------------------------------------
# Judge-calibration datasets (Phase 8)
# ---------------------------------------------------------------------------

CALIBRATION_DIR = ROOT / "evals" / "datasets" / "calibration"


# Phase 8 – Step 3: one judge call's worth of human-labeled reasons (one recommended activity)
class CalibrationItem(BaseModel):
    item_id: str = Field(pattern=r"^c\d{2}-[a-z0-9-]+$")
    activity_id: str
    travelers: list[Traveler] = Field(min_length=1)
    reasons: list[str] = Field(min_length=1)
    grounded: list[bool]  # human label per reason, same order
    notes: str = ""

    @model_validator(mode="after")
    def _one_label_per_reason(self) -> "CalibrationItem":
        if len(self.grounded) != len(self.reasons):
            raise ValueError("need exactly one grounded label per reason")
        return self


# Phase 8 – Step 3: a loaded, verified calibration set
class CalibrationDataset(BaseModel):
    manifest: DatasetManifest
    items: list[CalibrationItem]


# Phase 8 – Step 3: load evals/datasets/calibration/<name>/<version>/ with the golden checks
def load_calibration(
    name: str = "reasons", version: str = "v1.0.0", root: Path = CALIBRATION_DIR
) -> CalibrationDataset:
    label = f"calibration/{name} {version}"
    manifest, lines = _read_verified(root / name / version, "items.jsonl", label)
    items = _parse(lines, CalibrationItem, label)
    problems = _duplicates([i.item_id for i in items], "item_id")
    problems += [f"{i.item_id}: unknown activity {i.activity_id}" for i in items
                 if get_activity_by_id(i.activity_id) is None]
    if len(items) != manifest.case_count:
        problems.append(f"manifest says {manifest.case_count} items, found {len(items)}")
    if problems:
        raise DatasetError(f"dataset {label}: " + "; ".join(problems))
    return CalibrationDataset(manifest=manifest, items=items)


# Phase 8 – Step 3: write a NEW calibration version
def write_calibration(
    name: str, version: str, items: list[CalibrationItem], created: date,
    root: Path = CALIBRATION_DIR,
) -> DatasetManifest:
    return _write_versioned(root / name / version, "items.jsonl", items, f"calibration/{name}",
                            version, created)

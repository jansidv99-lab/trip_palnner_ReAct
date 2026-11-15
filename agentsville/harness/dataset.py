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

from pydantic import BaseModel, Field, ValidationError

from agentsville.data_api import get_activity_by_id
from agentsville.models import VacationInfo

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


# Phase 7 – Step 1: load a version and verify hash, data fingerprint, schema and labels
def load_golden(version: str = "v1.0.0", root: Path = DATASETS_DIR) -> GoldenDataset:
    folder = root / version
    try:
        manifest = DatasetManifest.model_validate_json(
            (folder / "manifest.json").read_text(encoding="utf-8")
        )
        cases_text = (folder / "cases.jsonl").read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DatasetError(f"dataset {version} not found in {root}") from exc

    if _sha256_text(cases_text) != manifest.cases_sha256:
        raise DatasetError(f"dataset {version}: cases.jsonl was modified (hash mismatch)")
    if data_fingerprint() != manifest.data_fingerprint:
        raise DatasetError(
            f"dataset {version}: data/data.py changed since the labels were written "
            "(data fingerprint mismatch) – create a new dataset version"
        )

    cases = []
    for number, line in enumerate(cases_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(GoldenCase.model_validate_json(line))
        except ValidationError as exc:
            raise DatasetError(f"dataset {version}, line {number}: {exc}") from exc

    ids = [c.case_id for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    problems = [f"duplicate case_id {d}" for d in duplicates]
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
    folder = root / version
    if folder.exists():
        raise DatasetError(f"dataset {version} already exists – versions are immutable")
    folder.mkdir(parents=True)
    cases_text = "".join(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n"
                         for c in cases)
    (folder / "cases.jsonl").write_text(cases_text, encoding="utf-8", newline="\n")
    manifest = DatasetManifest(
        version=version,
        created=created,
        case_count=len(cases),
        cases_sha256=_sha256_text(cases_text),
        data_fingerprint=data_fingerprint(),
    )
    (folder / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest

# Phase 7 – Step 3: record/replay of LLM calls ("cassettes") for deterministic, free re-runs.
"""CassetteLLM has the same chat() signature as LLMClient, so the agent and the evals can't tell
the difference.

    live    call the real LLM, store nothing
    record  call the real LLM and append every response (or error) to the cassette
    replay  answer only from the cassette; a request that isn't there raises CassetteMissError

Requests are keyed by sha256 of the canonical (model, messages, temperature, json_mode). The same
request may occur more than once in one run (e.g. the judge sees the same activity twice), so
responses are stored per key in order and replayed in that order. Message text is LF-normalized so
Windows and Linux produce identical keys.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from agentsville.llm import LLMClient, LLMError, LLMResponse

Mode = Literal["live", "record", "replay"]


# Phase 7 – Step 3: replay found no recorded response – the code or prompt changed; re-record
class CassetteMissError(RuntimeError):
    pass


def _normalize(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {key: value.replace("\r\n", "\n") if isinstance(value, str) else value
         for key, value in message.items()}
        for message in messages
    ]


# Phase 7 – Step 3: stable identity of one LLM request
def request_key(
    model: str, messages: list[dict[str, str]], temperature: float, json_mode: bool
) -> str:
    canonical = json.dumps(
        {"model": model, "messages": _normalize(messages), "temperature": temperature,
         "json_mode": json_mode},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _summary(model: str, messages: list[dict[str, str]], json_mode: bool) -> dict:
    last = messages[-1]["content"] if messages else ""
    return {"model": model, "json_mode": json_mode, "messages": len(messages),
            "last_message": last[:200]}


# Phase 7 – Step 3: drop-in LLM client that records to / replays from one cassette file
class CassetteLLM:
    def __init__(
        self,
        mode: Mode,
        cassette: Path,
        llm: LLMClient | None = None,
        default_model: str | None = None,
    ) -> None:
        if mode in ("live", "record") and llm is None:
            raise ValueError(f"mode '{mode}' needs a real LLMClient")
        if mode == "replay" and default_model is None:
            raise ValueError("replay mode needs default_model (the model used when recording)")
        self.mode = mode
        self.cassette = cassette
        self._llm = llm
        self.default_model = default_model or llm.default_model
        self._occurrences: dict[str, int] = defaultdict(int)
        self._recorded: dict[str, list[dict]] = defaultdict(list)

        if mode == "record":
            cassette.parent.mkdir(parents=True, exist_ok=True)
            cassette.write_text("", encoding="utf-8")  # re-recording replaces the old cassette
        elif mode == "replay":
            if not cassette.is_file():
                raise CassetteMissError(f"no cassette at {cassette} – record it first")
            for line in cassette.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self._recorded[entry["key"]].append(entry)

    # Phase 7 – Step 3: same contract as LLMClient.chat
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        model = model or self.default_model
        key = request_key(model, messages, temperature, json_mode)
        occurrence = self._occurrences[key]
        self._occurrences[key] += 1

        if self.mode == "replay":
            entries = self._recorded.get(key, [])
            if occurrence >= len(entries):
                summary = _summary(model, messages, json_mode)
                raise CassetteMissError(
                    f"no recorded response in {self.cassette.name} for request #{occurrence + 1} "
                    f"with key {key[:12]}… ({summary}). The prompt, code or data changed – "
                    "re-record with --mode record."
                )
            entry = entries[occurrence]
            if "error" in entry:
                raise LLMError(entry["error"])
            return LLMResponse(**entry["response"])

        try:
            response = self._llm.chat(messages, model=model, temperature=temperature,
                                      json_mode=json_mode)
        except LLMError as exc:
            self._append(key, occurrence, model, messages, json_mode, error=str(exc))
            raise
        self._append(key, occurrence, model, messages, json_mode, response=response)
        return response

    def _append(self, key, occurrence, model, messages, json_mode, response=None, error=None):
        if self.mode != "record":
            return
        entry = {"key": key, "occurrence": occurrence,
                 "request": _summary(model, messages, json_mode)}
        if error is not None:
            entry["error"] = error
        else:
            entry["response"] = response.model_dump()
        with self.cassette.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

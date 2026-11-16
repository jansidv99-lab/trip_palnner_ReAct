# Phase 12 – Step 1: AppTest smoke tests for the Streamlit UI (headless, no network).
"""`AppTest` runs app.py in-process like a browser session would, then lets us read the page.

Every test injects a fake `AgentBackend` into session state (or replaces `make_backend`), so the
app never builds a real LLM client from `.env` – these tests must stay free and offline.
"""

import pytest
from streamlit.testing.v1 import AppTest

from agentsville.config import ConfigError
from agentsville.models import Interest
from agentsville.ui import APP_TITLE, SECTIONS
from agentsville.ui.run import SETUP_HELP, AgentBackend
from tests.test_agent import HAPPY_SCRIPT, ScriptedLLM


# Phase 12 – Step 3: never let a test reach the real make_backend()
@pytest.fixture(autouse=True)
def _no_real_backend(monkeypatch):
    def refuse():
        raise AssertionError("test tried to build the real backend")

    monkeypatch.setattr("agentsville.ui.run.make_backend", refuse)


# Phase 12 – Step 1: run the script once and return the rendered app
# Phase 12 – Step 3: with a fake backend in session state
def _run_app(llm: ScriptedLLM | None = None) -> AppTest:
    at = AppTest.from_file("app.py", default_timeout=10)
    llm = llm or ScriptedLLM(*HAPPY_SCRIPT)
    at.session_state["backend"] = AgentBackend(llm=llm, prompt_version="v1", log_path=None)
    at.session_state["feedback_sink"] = ListSink()
    at.run()
    return at


# Phase 12 – Step 6: collects feedback records in memory instead of writing a file
class ListSink:
    def __init__(self) -> None:
        self.records = []

    def write(self, record) -> None:
        self.records.append(record)


# Phase 12 – Step 1: the page starts without errors and shows its title
def test_app_starts_without_exceptions():
    at = _run_app()
    assert not at.exception
    assert at.title[0].value == APP_TITLE


# Phase 12 – Step 1: every planned section is on the page, in order
def test_app_shows_all_sections_in_order():
    at = _run_app()
    assert [h.value for h in at.header] == list(SECTIONS)


# Phase 12 – Step 2: the form starts pre-filled with the sample trip
def test_form_is_prefilled_with_sample_trip():
    at = _run_app()
    assert [t.value for t in at.text_input] == ["Yuri", "Hiro"]


# Phase 12 – Step 2: invalid input shows readable errors and never calls the agent
def test_invalid_input_shows_errors_and_does_not_run_agent():
    llm = ScriptedLLM(*HAPPY_SCRIPT)
    at = _run_app(llm)
    at.text_input(key="traveler_1_name").set_value("")
    at.multiselect(key="traveler_0_interests").set_value([])
    at.number_input(key="budget").set_value(0)
    at.button(key="generate").click().run()
    message = at.error[0].value
    assert "Traveler 1 (Yuri) – interests: pick at least one interest" in message
    assert "Traveler 2 – name: is required" in message
    assert "Budget: must be greater than 0" in message
    assert llm.agent_calls == []
    assert "run" not in at.session_state


# Phase 12 – Step 2: add and remove traveler rows; the last one can't be removed
def test_add_and_remove_travelers():
    at = _run_app()
    at.button(key="add_traveler").click().run()
    assert len(at.text_input) == 3
    at.button(key="traveler_0_remove").click().run()
    at.button(key="traveler_1_remove").click().run()
    assert [t.value for t in at.text_input] == [""]
    assert at.button(key="traveler_2_remove").disabled


# Phase 12 – Step 2: choosing an interest no activity offers shows a hint
def test_unavailable_interest_hint():
    at = _run_app()
    at.multiselect(key="traveler_0_interests").set_value([Interest.THEATRE]).run()
    assert any("No activity for theatre" in c.value for c in at.caption)


# Phase 12 – Step 3: Generate runs the agent, stores the run and shows success
def test_generate_runs_agent_and_shows_success():
    llm = ScriptedLLM(*HAPPY_SCRIPT)
    at = _run_app(llm)
    at.button(key="generate").click().run()
    assert not at.exception
    assert len(llm.agent_calls) == len(HAPPY_SCRIPT)
    assert at.session_state["run"].stop_reason == "final_answer"
    assert "passed every plan check" in at.success[0].value
    assert not at.button(key="generate").disabled  # inputs enabled again after the run


# Phase 12 – Step 3: other interactions redraw the stored run without re-running the agent
def test_rerun_does_not_rerun_agent():
    llm = ScriptedLLM(*HAPPY_SCRIPT)
    at = _run_app(llm)
    at.button(key="generate").click().run()
    calls = len(llm.agent_calls)
    at.button(key="add_traveler").click().run()
    assert len(llm.agent_calls) == calls
    assert "passed every plan check" in at.success[0].value


# Phase 12 – Step 3: a run that hits max_steps is explained, not hidden
def test_max_steps_run_is_explained():
    llm = ScriptedLLM()  # no script: keeps calling the calculator
    at = _run_app(llm)
    at.number_input(key="max_steps").set_value(5)
    at.button(key="generate").click().run()
    assert "ran out of steps" in at.error[0].value


# Phase 12 – Step 4: after a run, the itinerary shows metrics, day cards and the eval report
def test_itinerary_is_shown_after_run():
    at = _run_app()
    at.button(key="generate").click().run()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Total cost"] == "108 / 130"
    subheaders = [s.value for s in at.subheader]
    assert {"Tue, Jun 10", "Wed, Jun 11", "Thu, Jun 12"} <= set(subheaders)
    assert any("bad weather" in c.value for c in at.caption)  # 06-12 thunderstorm
    labels = [e.label for e in at.expander]
    assert "Eval report – all checks passed" in labels
    assert "Trace inspector – every step in full" in labels


# Phase 12 – Step 4: a run without a plan shows the placeholder, not day cards
def test_no_plan_shows_placeholder():
    at = _run_app(ScriptedLLM())
    at.number_input(key="max_steps").set_value(5)
    at.button(key="generate").click().run()
    assert not at.metric or "Total cost" not in [m.label for m in at.metric]
    assert any(i.value == "Your itinerary will appear here." for i in at.info)


# Phase 12 – Step 5: the quality panel shows the three groups; failures open their group
def test_quality_panel_is_shown_after_run():
    at = _run_app()
    at.button(key="generate").click().run()
    labels = [e.label for e in at.expander]
    # the scripted run only looked up 06-10: trajectory grounding fails; constraints all pass
    assert "Grounding – is everything in the plan real? – 1 failed" in labels
    assert "Constraints – does it respect the hard limits? – all passed" in labels
    assert any(label.startswith("Relevancy & reasoning") and "failed" in label for label in labels)
    assert any("Not run here (LLM judges" in c.value for c in at.caption)


# Phase 12 – Step 6: one feedback record per run, with the comment; then a thank-you
def test_feedback_writes_one_record_per_run():
    at = _run_app()
    at.button(key="generate").click().run()
    run_id = at.session_state["run"].run_id
    at.text_area(key=f"feedback_comment_{run_id}").set_value("Loved the tennis lunch")
    at.button(key="feedback_down").click().run()
    sink = at.session_state["feedback_sink"]
    assert [(r.rating, r.comment, r.run_id) for r in sink.records] == [
        ("down", "Loved the tennis lunch", run_id)
    ]
    assert "Thanks for your feedback!" in at.success[-1].value
    assert not [b for b in at.button if b.key in ("feedback_up", "feedback_down")]


# Phase 12 – Step 6: no feedback buttons before a run
def test_no_feedback_before_run():
    at = _run_app()
    assert not [b for b in at.button if b.key in ("feedback_up", "feedback_down")]


# Phase 12 – Step 3: a missing API key shows setup help instead of crashing
def test_missing_api_key_shows_setup_help(monkeypatch):
    def missing():
        raise ConfigError("Missing required environment variable(s): OPENAI_API_KEY")

    monkeypatch.setattr("agentsville.ui.run.make_backend", missing)
    at = AppTest.from_file("app.py", default_timeout=10)
    at.run()
    at.button(key="generate").click().run()
    assert not at.exception
    assert at.error[0].value == SETUP_HELP

# Phase 12 – Step 1: Streamlit entry point (thin: page config, layout, wiring).
"""Run with `streamlit run app.py`.

Streamlit re-runs this whole script top to bottom on every widget interaction, so it only draws.
Logic lives in `agentsville/ui/`; anything that must survive a rerun goes in `st.session_state`.
"""

import streamlit as st

from agentsville.agent import AgentRun, AgentStep
from agentsville.config import ConfigError
from agentsville.models import TRIP_WINDOW_END, TRIP_WINDOW_START, Interest, OpenAIModel
from agentsville.ui import APP_TAGLINE, APP_TITLE, SECTIONS
from agentsville.ui.feedback import (
    MAX_COMMENT_CHARS,
    FeedbackSink,
    Rating,
    feedback_sink,
    make_feedback,
)
from agentsville.ui.form import (
    COST_RULE,
    DEFAULT_MAX_STEPS,
    FieldError,
    RunOptions,
    TravelerInput,
    TripForm,
    default_form,
    interest_hint,
    to_vacation_info,
    unavailable_interests,
)
from agentsville.ui.run import (
    SETUP_HELP,
    AgentBackend,
    make_backend,
    outcome,
    run_agent,
    run_stats,
    step_markdown,
)
from agentsville.ui.views import (
    DayCard,
    cost_note,
    cost_summary,
    day_cards,
    eval_rows,
    is_empty_plan,
    quality_panel,
    skipped_judges,
    summary_metrics,
)


# Phase 12 – Step 2: widget keys of one traveler row (rows are identified by a stable id)
def _traveler_key(row_id: int, part: str) -> str:
    return f"traveler_{row_id}_{part}"


# Phase 12 – Step 2: seed session state from the default form once per browser session.
# Widgets then read their value from their key, so we never also pass value= (Streamlit warns).
def _init_state() -> None:
    if "traveler_ids" in st.session_state:
        return
    form = default_form()
    st.session_state.traveler_ids = list(range(len(form.travelers)))
    st.session_state.next_traveler_id = len(form.travelers)
    for row_id, traveler in enumerate(form.travelers):
        _seed_traveler(row_id, traveler)
    st.session_state.date_of_arrival = form.date_of_arrival
    st.session_state.date_of_departure = form.date_of_departure
    st.session_state.budget = form.budget


# Phase 12 – Step 2: put one traveler's values into session state under its widget keys
def _seed_traveler(row_id: int, traveler: TravelerInput) -> None:
    st.session_state[_traveler_key(row_id, "name")] = traveler.name
    st.session_state[_traveler_key(row_id, "age")] = traveler.age
    st.session_state[_traveler_key(row_id, "interests")] = list(traveler.interests)


# Phase 12 – Step 2: button callbacks (run before the rerun, so the new row list is drawn)
def _add_traveler() -> None:
    row_id = st.session_state.next_traveler_id
    st.session_state.next_traveler_id += 1
    _seed_traveler(row_id, TravelerInput())
    st.session_state.traveler_ids.append(row_id)


def _remove_traveler(row_id: int) -> None:
    st.session_state.traveler_ids.remove(row_id)


# Phase 12 – Step 2: draw the trip form; returns the raw form values and the run options
# Phase 12 – Step 3: busy=True disables every input while the agent runs – any interaction would
# make Streamlit rerun the script and abort the (paid) run halfway.
def _draw_form(busy: bool = False) -> tuple[TripForm, RunOptions]:
    col_from, col_to, col_budget = st.columns(3)
    col_from.date_input(
        "Arrival",
        key="date_of_arrival",
        min_value=TRIP_WINDOW_START,
        max_value=TRIP_WINDOW_END,
        disabled=busy,
    )
    col_to.date_input(
        "Departure",
        key="date_of_departure",
        min_value=TRIP_WINDOW_START,
        max_value=TRIP_WINDOW_END,
        disabled=busy,
    )
    col_budget.number_input(
        "Budget (whole group)", key="budget", min_value=0, step=10, disabled=busy
    )
    st.caption(
        f"Destination: **AgentsVille** – data covers {TRIP_WINDOW_START:%b %d} to "
        f"{TRIP_WINDOW_END:%b %d, %Y}. {COST_RULE}"
    )

    unavailable = unavailable_interests(
        st.session_state.date_of_arrival, st.session_state.date_of_departure
    )
    st.subheader("Travelers")
    travelers = []
    only_one = len(st.session_state.traveler_ids) == 1
    for position, row_id in enumerate(st.session_state.traveler_ids, start=1):
        col_name, col_age, col_interests, col_remove = st.columns([3, 1, 6, 1])
        name = col_name.text_input(
            f"Name {position}", key=_traveler_key(row_id, "name"), disabled=busy
        )
        age = col_age.number_input(
            "Age",
            key=_traveler_key(row_id, "age"),
            min_value=0,
            max_value=120,
            step=1,
            disabled=busy,
        )
        interests = col_interests.multiselect(
            "Interests",
            options=list(Interest),
            key=_traveler_key(row_id, "interests"),
            disabled=busy,
        )
        col_remove.button(
            "✕",
            key=_traveler_key(row_id, "remove"),
            help="Remove this traveler",
            on_click=_remove_traveler,
            args=(row_id,),
            disabled=only_one or busy,
        )
        hint = interest_hint(interests, unavailable)
        if hint:
            col_interests.caption(f"⚠️ {hint}")
        travelers.append(TravelerInput(name=name, age=int(age), interests=interests))
    st.button("+ Add traveler", key="add_traveler", on_click=_add_traveler, disabled=busy)

    with st.expander("Advanced"):
        model = st.selectbox(
            "Model",
            options=list(OpenAIModel),
            format_func=lambda m: m.value,
            key="model",
            disabled=busy,
        )
        include_llm_evals = st.checkbox(
            "Weather judge (LLM check of activities on rainy days)",
            value=True,
            key="include_llm_evals",
            disabled=busy,
        )
        max_steps = st.number_input(
            "Max agent steps",
            min_value=5,
            max_value=40,
            value=DEFAULT_MAX_STEPS,
            key="max_steps",
            disabled=busy,
        )

    form = TripForm(
        travelers=travelers,
        date_of_arrival=st.session_state.date_of_arrival,
        date_of_departure=st.session_state.date_of_departure,
        budget=int(st.session_state.budget),
    )
    options = RunOptions(
        model=model, include_llm_evals=include_llm_evals, max_steps=int(max_steps)
    )
    return form, options


# Phase 12 – Step 3: the Generate button only raises a flag; the rerun it triggers draws the form
# disabled and then runs the agent.
def _request_run() -> None:
    st.session_state.run_requested = True


# Phase 12 – Step 3: the agent backend, built once per session (tests pre-set a fake one).
# Returns None and shows setup help when the API key is missing.
def _backend() -> AgentBackend | None:
    if "backend" not in st.session_state:
        try:
            st.session_state.backend = make_backend()
        except ConfigError:
            st.error(SETUP_HELP)
            return None
    return st.session_state.backend


# Phase 12 – Step 3: validate, run the agent with live progress, keep the run in session state
def _generate(form: TripForm, options: RunOptions) -> None:
    result = to_vacation_info(form)
    if isinstance(result, list):
        st.error("Please fix these first:\n\n" + _bullets(result))
        return
    backend = _backend()
    if backend is None:
        return
    st.session_state.pop("run", None)
    with st.status("Planning your trip… (usually 1–2 minutes)", expanded=True) as status:

        def show_step(step: AgentStep) -> None:
            status.markdown(step_markdown(step), unsafe_allow_html=True)

        run = run_agent(result, options, backend, on_step=show_step)
        status.update(label="Done", state="complete")
    st.session_state.run = run
    st.rerun()  # redraw with the inputs enabled and the stored result


# Phase 12 – Step 3: the stored run – outcome message and the steps it took (survives reruns)
def _draw_progress() -> None:
    run = st.session_state.get("run")
    if run is None:
        st.info("Fill in the trip details and click **Generate itinerary**.")
        return
    level, message = outcome(run)
    getattr(st, level)(message)
    state = "complete" if level == "success" else "error"
    with st.status(f"Agent run: {run_stats(run)}", state=state, expanded=False):
        for step in run.steps:
            st.markdown(step_markdown(step), unsafe_allow_html=True)
    _draw_trace(run)


# Phase 12 – Step 4: every step in full – thought, action arguments, complete observation
def _draw_trace(run: AgentRun) -> None:
    with st.expander("Trace inspector – every step in full"):
        for step in run.steps:
            st.markdown(f"**Step {step.step} – `{step.tool_name or 'unparseable reply'}`**")
            if step.thought:
                st.markdown(f"> {step.thought}")
            if step.arguments:
                st.json(step.arguments, expanded=False)
            st.code(step.observation, language=None, wrap_lines=True)


# Phase 12 – Step 4: the itinerary – summary bar, day cards, eval report
def _draw_itinerary() -> None:
    run = st.session_state.get("run")
    if run is None or run.travel_plan is None:
        st.info("Your itinerary will appear here.")
        return
    plan = run.travel_plan

    metrics = summary_metrics(run)
    for column, (label, value, help_text) in zip(st.columns(len(metrics)), metrics, strict=True):
        column.metric(label, value, help=help_text)
    note = cost_note(cost_summary(plan, run.vacation_info))
    if note:
        st.warning(note)

    if is_empty_plan(plan):
        st.info(
            "The agent planned no activities: nothing on these dates fit the budget and the "
            "weather. Try a larger budget or different dates."
        )
    for card in day_cards(plan):
        _draw_day(card)

    report = run.final_eval_report
    if report is not None:
        verdict = "all checks passed" if report.passed else "some checks failed"
        with st.expander(f"Eval report – {verdict}", expanded=not report.passed):
            for row in eval_rows(report):
                suffix = " (warning)" if row.severity == "warning" else ""
                st.markdown(f"{row.icon} **{row.label}**{suffix}")
                for detail in row.details:
                    st.caption(f"– {detail}")


# Phase 12 – Step 4: one day card
def _draw_day(card: DayCard) -> None:
    with st.container(border=True):
        badge = " · ⛈️ bad weather – indoor plans" if card.inclement else ""
        st.subheader(f"{card.title}")
        st.caption(f"{card.weather}{badge} · day total {card.day_cost}")
        if not card.activities:
            st.write("No activities planned this day.")
        for activity in card.activities:
            st.markdown(
                f"**{activity.time} · {activity.name}** – {activity.price}  \n"
                f"📍 {activity.location}  \n"
                f"<small>Interests: {activity.interests}</small>",
                unsafe_allow_html=True,
            )
            for reason in activity.reasons:
                st.markdown(f"- {reason}")


# Phase 12 – Step 5: the free B1–B3 code graders on this run, grouped by quality question
_STATUS_ICONS = {"pass": "✅", "fail": "❌", "n/a": "➖"}


def _draw_quality() -> None:
    run = st.session_state.get("run")
    if run is None:
        st.info("After a run, automatic quality checks on the plan appear here.")
        return
    st.caption(
        "The same rule-based checks the evaluation harness uses (B1–B3), run on this plan "
        "for free. ➖ means the check needs a hand-labelled golden test case or a plan."
    )
    for group in quality_panel(run):
        verdict = "all passed" if group.failed == 0 else f"{group.failed} failed"
        with st.expander(f"{group.title} – {verdict}", expanded=group.failed > 0):
            for row in group.rows:
                st.markdown(f"{_STATUS_ICONS[row.status]} **{row.label}** – {row.summary}")
                for detail in row.details:
                    st.caption(f"– {detail}")
    st.caption(
        "Not run here (LLM judges, they cost money per call): "
        + ", ".join(skipped_judges())
        + ". They run in offline experiments."
    )


# Phase 12 – Step 6: the feedback sink, built once per session (tests pre-set a fake one)
def _feedback_sink() -> FeedbackSink | None:
    if "feedback_sink" not in st.session_state:
        st.session_state.feedback_sink = feedback_sink()
    return st.session_state.feedback_sink


# Phase 12 – Step 6: button callback – write one record for the current run
def _submit_feedback(rating: Rating) -> None:
    run = st.session_state.run
    comment = st.session_state.get(f"feedback_comment_{run.run_id}", "")
    try:
        _feedback_sink().write(make_feedback(run, rating, comment))
    except OSError as exc:
        st.session_state.feedback_error = f"Couldn't save your feedback: {exc}"
        return
    st.session_state.feedback_given = run.run_id


# Phase 12 – Step 6: thumbs up/down + optional comment, one per run
def _draw_feedback() -> None:
    run = st.session_state.get("run")
    if run is None:
        st.info("After a run, tell us whether the plan works for you.")
        return
    if _feedback_sink() is None:
        st.caption("Feedback storage is turned off.")
        return
    error = st.session_state.pop("feedback_error", None)
    if error:
        st.error(error)
    if st.session_state.get("feedback_given") == run.run_id:
        st.success("Thanks for your feedback!")
        return
    st.text_area(
        "Anything we should know? (optional)",
        key=f"feedback_comment_{run.run_id}",  # a new run starts with an empty comment
        max_chars=MAX_COMMENT_CHARS,
    )
    col_up, col_down, _ = st.columns([1, 1, 6])
    col_up.button("👍 Works for me", key="feedback_up", on_click=_submit_feedback, args=("up",))
    col_down.button(
        "👎 Not quite", key="feedback_down", on_click=_submit_feedback, args=("down",)
    )


# Phase 12 – Step 1: draw the page skeleton; each section is a placeholder until its step lands.
# Phase 12 – Step 2: the "Trip details" section is the real form.
# Phase 12 – Step 3: Generate runs the agent; "Agent progress" shows the stored run.
# Phase 12 – Step 4: "Your itinerary" shows the plan.
# Phase 12 – Step 5: "Quality checks" shows the code graders.
# Phase 12 – Step 6: "Feedback" collects one rating per run.
def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🧭", layout="wide")
    st.title(APP_TITLE)
    st.caption(APP_TAGLINE)
    _init_state()
    busy = st.session_state.pop("run_requested", False)

    trip_section, progress_section, itinerary_section, quality_section, feedback_section = (
        SECTIONS
    )
    st.header(trip_section)
    form, options = _draw_form(busy)
    st.button(
        "Generate itinerary",
        key="generate",
        type="primary",
        on_click=_request_run,
        disabled=busy,
    )

    st.header(progress_section)
    if busy:
        _generate(form, options)
    _draw_progress()

    st.header(itinerary_section)
    _draw_itinerary()

    st.header(quality_section)
    _draw_quality()

    st.header(feedback_section)
    _draw_feedback()


# Phase 12 – Step 2: errors as a markdown bullet list
def _bullets(errors: list[FieldError]) -> str:
    return "\n".join(f"- {error}" for error in errors)


main()

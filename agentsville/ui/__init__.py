# Phase 12 – Step 1: the Streamlit UI's testable core.
"""Pure UI logic (form -> VacationInfo, plan -> display rows, feedback records).

`app.py` only draws widgets and calls into this package, so everything here can be unit-tested
without Streamlit running. Modules are added step by step: form (Step 2), run (Step 3),
views (Steps 4-5), feedback (Step 6).
"""

APP_TITLE = "AgentsVille Trip Planner"
APP_TAGLINE = (
    "Plan a day-by-day trip to AgentsVille. A ReAct agent checks the weather and the activity "
    "calendar, keeps to your budget, and verifies its own plan before answering."
)

# Phase 12 – Step 1: page sections, in display order. Later steps fill them in.
SECTIONS = (
    "Trip details",
    "Agent progress",
    "Your itinerary",
    "Quality checks",
    "Feedback",
)

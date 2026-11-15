# Phase 8 – Step 1: run-level graders, grouped by quality question (B1 grounding, later B2/B3).
# Phase 9 – Step 2: B2 constraint graders registered.
# Phase 10 – Step 2: B3 relevancy graders registered.
# Phase 10 – Step 3: B3 trajectory graders registered.
# Phase 10 – Step 7: B3 LLM judges registered (with their recorded cassettes).
"""Run-level graders for the evaluation harness."""

from agentsville.graders.constraints import B2_GRADERS
from agentsville.graders.grounding import B1_GRADERS
from agentsville.graders.relevancy import B3_RELEVANCY_GRADERS, TRAVELER_RELEVANCY_JUDGE
from agentsville.graders.trajectory import B3_TRAJECTORY_GRADERS, THOUGHT_ACTION_JUDGE

B3_GRADERS = [*B3_RELEVANCY_GRADERS, TRAVELER_RELEVANCY_JUDGE, *B3_TRAJECTORY_GRADERS,
              THOUGHT_ACTION_JUDGE]

ALL_GRADERS = [*B1_GRADERS, *B2_GRADERS, *B3_GRADERS]

__all__ = ["ALL_GRADERS", "B1_GRADERS", "B2_GRADERS", "B3_GRADERS"]

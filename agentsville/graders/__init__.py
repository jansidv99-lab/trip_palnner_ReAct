# Phase 8 – Step 1: run-level graders, grouped by quality question (B1 grounding, later B2/B3).
"""Run-level graders for the evaluation harness."""

from agentsville.graders.grounding import B1_GRADERS

ALL_GRADERS = [*B1_GRADERS]

__all__ = ["ALL_GRADERS", "B1_GRADERS"]

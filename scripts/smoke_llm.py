# Phase 0 – Step 6: manual smoke check – can we reach the LLM with the configured key/endpoint?
"""Run from the repo root:  python scripts/smoke_llm.py [model]

Not run in CI: it needs the real API key and costs a tiny amount.
"""

import sys
from pathlib import Path

# Make `agentsville` importable when the script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.config import ConfigError, get_settings  # noqa: E402
from agentsville.llm import LLMClient, LLMError  # noqa: E402


# Phase 0 – Step 6: send one tiny prompt and print the reply and metrics
def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        settings = get_settings()
        reply = LLMClient(settings).chat(
            [{"role": "user", "content": "Reply with exactly: OK"}], model=model
        )
    except (ConfigError, LLMError) as exc:
        print(f"SMOKE FAILED: {exc}")
        return 1

    cost = f"${reply.cost_usd:.6f}" if reply.cost_usd is not None else "unknown"
    print(f"reply      : {reply.text!r}")
    print(f"model      : {reply.model}")
    print(f"latency    : {reply.latency_ms:.0f} ms")
    print(f"tokens     : {reply.prompt_tokens} in / {reply.completion_tokens} out")
    print(f"est. cost  : {cost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

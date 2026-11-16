# Phase 13 – Step 3: passcode gate for the public Cloud Run URL (each run spends OpenAI credit).
"""If `APP_PASSCODE` is set, the app asks for it before showing anything else.

Unset (local development, tests) → no gate. On Cloud Run the value comes from Secret Manager.
The comparison is constant-time (`hmac.compare_digest`), and a browser session is locked out after
`MAX_ATTEMPTS` wrong codes, which makes guessing by hand pointless.
"""

import hmac
import os

PASSCODE_ENV = "APP_PASSCODE"
MAX_ATTEMPTS = 5


# Phase 13 – Step 3: the configured passcode, or None when the gate is off
def required_passcode(environ: dict[str, str] | None = None) -> str | None:
    value = (os.environ if environ is None else environ).get(PASSCODE_ENV, "").strip()
    return value or None


# Phase 13 – Step 3: constant-time check (surrounding spaces from copy-paste are ignored)
def passcode_ok(entered: str, expected: str) -> bool:
    return hmac.compare_digest(entered.strip().encode("utf-8"), expected.encode("utf-8"))

# Phase 13 – Step 3: unit tests for the passcode gate logic.
from agentsville.ui.access import passcode_ok, required_passcode


def test_required_passcode():
    assert required_passcode({}) is None
    assert required_passcode({"APP_PASSCODE": "   "}) is None
    assert required_passcode({"APP_PASSCODE": " abc "}) == "abc"


def test_passcode_ok():
    assert passcode_ok("abc", "abc")
    assert passcode_ok("  abc\n", "abc")  # copy-paste whitespace
    assert not passcode_ok("abd", "abc")
    assert not passcode_ok("", "abc")
    assert passcode_ok("café", "café")  # non-ASCII is fine (compared as UTF-8 bytes)

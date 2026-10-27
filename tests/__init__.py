"""Test package.

Hermetic by construction: a test that fakes a browser spawn must not write a
fact about *this machine*.

Why this file exists (2026-10-27). 0.13.7 made `ensure_chrome()` record who
started the browser on the debug port — that record (`~/.hand-cdp-owner.json`)
is the only thing standing between a close and killing someone else's browser,
because "whose is it" cannot be read back off the process table afterwards. It
is a production fact. Two tests that fake a spawn (a stub Popen with `pid=4242`)
were, as a side effect, writing that fake record into the real file: the machine
then claimed it had spawned a browser it never spawned, and any later close
read a lie ("recorded process is not alive") instead of the truth.

The fix is here rather than in each test, because the failure mode is "someone
writes a new test that fakes a spawn and forgets". Every entry point
(`python3 -m unittest tests.x`, `tests/run_tests.py`) imports this package
first, so the isolation cannot be skipped.
"""
import os
import tempfile

if not os.environ.get("HAND_CDP_OWNER_FILE"):
    os.environ["HAND_CDP_OWNER_FILE"] = os.path.join(
        tempfile.mkdtemp(prefix="hand-test-owner-"), "owner.json")

"""Test harness package.

Importing anything under `tests.harness` also isolates the CDP session-page
record: a test run gets its own file instead of reading (and overwriting) the
one this machine's operator is using. Without that, a unit test that mocks its
pages still answers to whatever tab the last real interaction left recorded —
it passes or fails for reasons that have nothing to do with the code under test.
"""

import os
import tempfile

os.environ.setdefault(
    "HAND_CDP_STATE_FILE",
    os.path.join(tempfile.gettempdir(), "hand_cdp_last_idx_tests"),
)

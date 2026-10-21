"""L2 integration suite package.

Importing it gives the suite its own CDP session-page record, and clears it:
these tests resolve "the current page" implicitly, so a record left behind by
another suite would point at a page that no longer exists. Since 0.13 that
case raises instead of silently falling back to pages[0] — which is what we
want in production and what makes cross-suite bleed loud here.
"""

import os
import tempfile

_PATH = os.path.join(tempfile.gettempdir(), "hand_cdp_last_idx_integration")
os.environ["HAND_CDP_STATE_FILE"] = _PATH
try:
    os.remove(_PATH)
except OSError:
    pass

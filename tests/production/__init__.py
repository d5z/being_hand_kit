"""Production-shaped suite package (L4/L5/L6).

Own CDP session-page record, cleared on import — see tests/integration for why
a stale record no longer degrades to pages[0].
"""

import os
import tempfile

_PATH = os.path.join(tempfile.gettempdir(), "hand_cdp_last_idx_production")
os.environ["HAND_CDP_STATE_FILE"] = _PATH
try:
    os.remove(_PATH)
except OSError:
    pass

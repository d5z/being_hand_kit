#!/usr/bin/env python3
"""Run one layer's unittest modules in an isolated process, emit JSON counts.

Used by tests/run_production.py so each layer starts from a clean interpreter —
layer state (session place, page tabs, mock patches) must not leak into the next
layer's results. Prints one line: __LAYER_RESULT__ {json}
"""

import io
import json
import sys
import time
import unittest

sys.path.insert(0, "/home/alice/Hand")


def main(modules):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    imported = []
    for name in modules:
        try:
            mod = __import__(name, fromlist=[name.rsplit(".", 1)[-1]])
        except Exception as e:
            print(f"SKIP import {name}: {type(e).__name__}: {e}")
            continue
        imported.append(name)
        suite.addTests(loader.loadTestsFromModule(mod))
    t0 = time.time()
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=1).run(suite)
    dt = time.time() - t0
    failed = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    payload = {
        "modules": imported,
        "tests": result.testsRun,
        "passed": result.testsRun - failed - errors - skipped,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "skips": [[str(t), r] for t, r in result.skipped],
        "failures": [[str(t), tb] for t, tb in result.failures + result.errors],
        "seconds": round(dt, 1),
    }
    print("__LAYER_RESULT__" + json.dumps(payload))


if __name__ == "__main__":
    main(sys.argv[1:])

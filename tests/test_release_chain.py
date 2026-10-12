"""L1 meta-test: the release-test chain must never break again.

Origin: tests/test_release_080.py shipped as a *current-version* assertion
(version == 0.8.0), so after 0.9.0 it could never be registered in
run_tests MODULES without failing. It sat unregistered — a zombie — from
early October until 2026-10-12, when 0.9.8 work fixed it into a
historical lock. Meanwhile 0.9.0–0.9.7 all shipped with no release test
file at all. Nobody noticed, because nothing enforced noticing.

Two chain rules (the "连环扣" — each link locks the next):
  1. Every tests/test_release_*.py file must be registered in
     run_tests.MODULES. An unregistered release test is a zombie by
     definition — it cannot fail, so it asserts nothing.
  2. The current package version (hand.__version__) must have its own
     test_release_{maj}{min}.py file. Bumping the version without
     writing the release test goes red here. (Registered-ness of that
     file is already covered by rule 1.)

Consequence for the release SOP: bump version → write the new release
test (current-version assertions go there) → register in MODULES → all
green. Forgetting any step fails this chain.
"""

import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _release_test_files():
    pattern = os.path.join(ROOT, "tests", "test_release_*.py")
    return {os.path.basename(p) for p in glob.glob(pattern)}


def _registered_modules():
    with open(os.path.join(ROOT, "tests", "run_tests.py"), encoding="utf-8") as f:
        body = f.read()
    m = re.search(r"MODULES\s*=\s*\[(.*?)\]", body, re.S)
    if not m:
        return set()
    return set(re.findall(r'"tests\.([a-z0-9_]+)"', m.group(1)))


class TestReleaseChain(unittest.TestCase):
    def test_every_release_file_is_registered(self):
        files = _release_test_files()
        self.assertTrue(files, "no release test files found at all")
        registered = _registered_modules()
        unregistered = {
            f for f in files
            if f[:-3] not in registered and f != "test_release_chain.py"
        }
        self.assertEqual(
            set(), unregistered,
            f"zombie release tests (exist but not in run_tests MODULES): "
            f"{sorted(unregistered)}")

    def test_current_version_has_its_release_test(self):
        import hand
        ver = hand.__version__
        m = re.match(r"(\d+)\.(\d+)\.(\d+)$", ver)
        self.assertIsNotNone(m, f"unparseable version {ver!r}")
        stem = f"test_release_{m.group(1)}{m.group(2)}{m.group(3)}.py"
        path = os.path.join(ROOT, "tests", stem)
        self.assertTrue(
            os.path.exists(path),
            f"hand.__version__ is {ver} but {stem} does not exist — "
            f"bump the version, write the release test, register it")


if __name__ == "__main__":
    unittest.main()

"""L1 tests for hand 0.7.0 S6 — F9-F13 quick-fix batch.

PRD docs/prd-ax-perception.md S6:
  F9  requirements.txt pins mcp<2 (mcp 2.x needs the 1.x API adaption we don't have)
  F10 requirements.txt declares websocket/requests
  F11 start.sh loads .env when present
  F12 README: python >= 3.10 prerequisite
  F13 README: cold start 2-3s expectation, 6s endpoint-probe cap
  + upgrade impact: profile dir created on first run, old chrome-wrapper.sh is
    redundant (may be deleted or kept)

The .env test is behavioral: a throw-away kit dir with a stub mcp_server.py is
executed through the real start.sh.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KIT = os.path.join(ROOT, "kit")


def _read(name):
    with open(os.path.join(KIT, name), encoding="utf-8") as f:
        return f.read()


class TestRequirements(unittest.TestCase):
    """F9 + F10: the bundle must declare what it imports, and pin the API it uses."""

    def setUp(self):
        self.lines = [l.strip() for l in _read("requirements.txt").splitlines()]
        self.reqs = [l for l in self.lines if l and not l.startswith("#")]

    def test_mcp_is_pinned_below_2(self):
        mcp = [r for r in self.reqs if r.split("=")[0].split(">")[0].split("<")[0] == "mcp"]
        self.assertEqual(len(mcp), 1, self.reqs)
        self.assertIn("<2", mcp[0].replace(" ", ""))

    def test_websocket_client_is_declared(self):
        self.assertTrue(any(r.startswith("websocket-client") for r in self.reqs), self.reqs)

    def test_requests_is_declared(self):
        self.assertTrue(any(r.startswith("requests") for r in self.reqs), self.reqs)

    def test_websocket_is_actually_imported_by_the_tree(self):
        """Declaring it is only right because the code imports it."""
        src = open(os.path.join(ROOT, "hand", "perception", "cdp_core.py")).read()
        self.assertIn("import json, os, time, urllib.request, websocket", src)


class TestStartShEnvLoading(unittest.TestCase):
    """F11: start.sh must load .env — and the vars must reach the MCP process."""

    STUB = "import os, sys; sys.stdout.write(os.environ.get('HAND_QUICKFIX_MARK', 'MISSING'))"

    def _run(self, env_content=None):
        tmp = tempfile.mkdtemp()
        try:
            shutil.copy(os.path.join(KIT, "start.sh"), os.path.join(tmp, "start.sh"))
            with open(os.path.join(tmp, "mcp_server.py"), "w") as f:
                f.write(self.STUB)
            if env_content is not None:
                with open(os.path.join(tmp, ".env"), "w") as f:
                    f.write(env_content)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("CHROME", "HAND_QUICKFIX_MARK")}
            r = subprocess.run(["bash", "start.sh"], cwd=tmp, capture_output=True,
                               text=True, env=env, timeout=60)
            return r
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_env_file_is_exported_to_the_mcp_process(self):
        r = self._run("HAND_QUICKFIX_MARK=42\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "42")

    def test_missing_env_file_is_not_an_error(self):
        r = self._run(None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "MISSING")

    def test_env_file_can_override_the_chrome_binary(self):
        r = self._run("CHROME=/opt/kit-chrome\n")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_start_sh_is_valid_bash(self):
        r = subprocess.run(["bash", "-n", os.path.join(KIT, "start.sh")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestReadmeDocs(unittest.TestCase):
    """F12/F13 + upgrade impact. The kit README is what a Grove install reads."""

    def setUp(self):
        self.kit_readme = _read("README.md")
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            self.root_readme = f.read()

    def test_python_prerequisite(self):
        self.assertIn("3.10", self.kit_readme)

    def test_cold_start_expectation_and_probe_cap(self):
        self.assertIn("2-3", self.kit_readme)
        self.assertIn("6", self.kit_readme)
        self.assertRegex(self.kit_readme, r"6\s*(s|秒)")

    def test_upgrade_impact_section(self):
        self.assertIn(".chrome-profile", self.kit_readme)
        self.assertIn("chrome-wrapper.sh", self.kit_readme)

    def test_kit_readme_documents_the_a11y_default(self):
        self.assertIn("a11y", self.kit_readme)
        self.assertIn("[idx]", self.kit_readme)

    def test_root_readme_mentions_the_prerequisite(self):
        self.assertIn("3.10", self.root_readme)


if __name__ == "__main__":
    unittest.main()

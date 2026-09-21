"""L5 compatibility — the 6.11 -> 0.7 upgrade path.

PRD L5: old call shapes must not break (route_see() with no kind still works,
kind=dom/interactive remain), the profile strategy change is explicit, and the
manifest version-line reset (6.11 -> 0.7) upgrades cleanly.

Offline assertions (manifest, profile, version sync) run everywhere; the
old-call-shape assertions need a live Chrome and SKIP without one.
"""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, "/home/alice/Hand")

from hand import router
from hand.session import reset_session

from tests.harness import judge as J
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

_ROOT = "/home/alice/Hand"
_FX = None
_CHROME = runner.chrome_available()
IDEMPOTENCY = {"idempotent", "append", "side_effect"}
EVIDENCE = {"verified", "claimed"}


def setUpModule():
    global _FX
    if _CHROME:
        _FX = FixtureServer()


def tearDownModule():
    if _FX:
        _FX.close()


class L5ManifestUpgrade(unittest.TestCase):
    """Manifest / version-line / grove-update compatibility — no browser needed."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_ROOT, "kit", "manifest.json")) as f:
            cls.manifest = json.load(f)

    def test_version_line_reset_is_clean(self):
        """0.7.0 reset the version line — never 6.x again.

        Version policy (dev cycle): the manifest carries the last PUBLISHED
        version while the package may run ahead as `<next>-dev`
        (0.8.0-dev vs a published 0.7.0). The invariants: both are well-formed,
        the manifest is never a dev version, and the package is never behind the
        published manifest.
        """
        import hand
        pattern = r"^\d+\.\d+\.\d+(-dev)?$"
        self.assertRegex(hand.__version__, pattern)
        self.assertRegex(self.manifest["version"], pattern)
        self.assertFalse(hand.__version__.startswith("6."),
                         "0.7.0 is an intentional version-line reset, not 6.x")
        self.assertFalse(self.manifest["version"].startswith("6."))
        self.assertNotIn("-dev", self.manifest["version"])

        def parts(v):
            return tuple(int(x) for x in v.split("-")[0].split("."))

        self.assertGreaterEqual(parts(hand.__version__),
                                parts(self.manifest["version"]))

    def test_manifest_tools_declare_idempotency_and_evidence(self):
        tools = self.manifest.get("tools") or []
        self.assertTrue(tools, "manifest has no tools")
        bad = []
        for t in tools:
            if t.get("idempotency") not in IDEMPOTENCY:
                bad.append(f"{t.get('name')}: idempotency={t.get('idempotency')!r}")
            if t.get("evidence") not in EVIDENCE:
                bad.append(f"{t.get('name')}: evidence={t.get('evidence')!r}")
        self.assertEqual(bad, [], "manifest tools[] missing S4 fields:\n" + "\n".join(bad))

    def test_manifest_description_declares_receipt_semantics(self):
        desc = self.manifest.get("description", "")
        self.assertIn("verified", desc)
        self.assertIn("idempotency", desc)

    def test_grove_update_path_is_wellformed(self):
        """Grove update: valid JSON, runnable command, sync.sh parses."""
        self.assertTrue(self.manifest.get("command"))
        self.assertIn("start.sh", self.manifest["command"])
        r = subprocess.run(["bash", "-n", os.path.join(_ROOT, "kit", "sync.sh")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"sync.sh syntax: {r.stderr}")

    def test_changelog_and_spec_record_the_reset(self):
        cl = open(os.path.join(_ROOT, "CHANGELOG.md")).read()
        self.assertIn("## [0.7.0]", cl)
        self.assertIn("版本线重置", cl)
        spec = open(os.path.join(_ROOT, "SPEC.md")).read()
        self.assertIn("V0.7.0", spec)

    def test_see_kind_enum_covers_the_documented_channels(self):
        see = next(t for t in self.manifest["tools"] if t["name"] == "cdp_see")
        enum = (see.get("params", {}).get("properties", {})
                .get("kind", {}).get("enum", []))
        for ch in ("a11y", "dom", "interactive"):
            self.assertIn(ch, enum, f"cdp_see manifest enum missing {ch!r}")
        # NOTE (report): route_see also accepts kind='vlm'; the manifest enum
        # omits it. Not a break — old callers never sent 'vlm'.


class L5ProfileStrategy(unittest.TestCase):
    """F7 profile opt-in: isolated is the default, overrides still work."""

    def _flags(self, **env):
        import hand.perception.cdp_launcher as cl
        from unittest import mock
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("HAND_PROFILE", "HAND_PROFILE_DIR", "HAND_HEADLESS", "CHROME")}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True):
            return cl._chrome_flags()

    def test_unset_profile_is_isolated_by_default(self):
        import hand.perception.cdp_launcher as cl
        with __import__("unittest").mock.patch.dict(
                os.environ, {"HAND_PROFILE": ""}, clear=False):
            os.environ.pop("HAND_PROFILE_DIR", None)
            self.assertEqual(cl.profile_mode(), "isolated")

    def test_explicit_persistent_opt_in_still_works(self):
        flags = self._flags(HAND_PROFILE="persistent", HAND_PROFILE_DIR="/tmp/x-prof")
        self.assertIn("--user-data-dir=/tmp/x-prof", flags)

    def test_old_isolated_user_is_not_silently_moved(self):
        """Default stays isolated; the dir is documented, not a surprise move."""
        readme = open(os.path.join(_ROOT, "README.md")).read()
        self.assertIn("HAND_PROFILE", readme)
        self.assertIn("isolated", readme.lower())


@unittest.skipIf(not _CHROME, "Chrome unavailable")
class L5OldCallShapes(unittest.TestCase):

    def test_route_see_no_kind_defaults_to_a11y(self):
        router.route_open(_FX.url("/basic"))
        r = router.route_see()          # pre-0.7 shape: no kind argument
        J.assert_verdict(self, J.judge_a11y(r, task="see() legacy shape"))
        self.assertIn("Fixture Basic", r["tree"])

    def test_route_see_no_kind_without_open_still_answers(self):
        """Old caller that never calls open() — live browser is enough."""
        reset_session()
        r = router.route_see()
        J.assert_verdict(self, J.judge_a11y(r, task="see() no-open legacy shape"))

    def test_kind_dom_still_works(self):
        router.route_open(_FX.url("/basic"))
        J.assert_verdict(self, J.judge_legacy_channel(
            router.route_see(kind="dom"), "cdp_snapshot", task="kind=dom"))

    def test_kind_interactive_still_works(self):
        router.route_open(_FX.url("/basic"))
        J.assert_verdict(self, J.judge_legacy_channel(
            router.route_see(kind="interactive"), "cdp_interactive",
            task="kind=interactive"))

    def test_unknown_kind_does_not_crash(self):
        """kind='screenshot' is documented in the manifest enum; route_see must
        degrade to a real receipt, not raise."""
        router.route_open(_FX.url("/basic"))
        r = router.route_see(kind="screenshot")
        self.assertIsInstance(r, dict)
        self.assertIn("verified", r)

    def test_old_selector_click_shape_still_works(self):
        """pre-0.7 callers pass a CSS selector, not an [idx] handle."""
        router.route_open(_FX.url("/basic"))
        J.assert_verdict(self, J.judge_click(router.route_do("#mark"),
                                             expect_name="Mark", task="legacy selector click"))


if __name__ == "__main__":
    unittest.main()

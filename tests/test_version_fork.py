"""L2-hermetic: a kit that reports one version and is installed as another says so.

The failure this locks: hand carries its version twice — a literal inside the
package (which health reports) and the manifest (which installers, routers and
the seed wall read). Nothing keeps them equal. A bump that touches one and not
the other parses, imports, runs and reports green, so the two answers drift
apart in silence and both remain individually "correct".

Behaviour asserted here:
  1. a manifest that disagrees with the package literal is named, not hidden
  2. the manifest is found in both kit (sibling) and package (parent) layouts
  3. no manifest at all is 'absent', not a fork — a source checkout is not broken
  4. an unreadable manifest does not raise (health must never die on this)
  5. this repo's two version strings agree (the discipline, made checkable)

Note on discovery: tests/run_tests.py drives an explicit module list. A new
test file that is not listed there never runs, and the count stays the same —
green with an unchanged count is the signature of "absent", not "passing".
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "kit"))


def _load():
    import mcp_server
    return mcp_server


class VersionFork(unittest.TestCase):

    def test_disagreeing_manifest_is_named(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "manifest.json").write_text(json.dumps({"version": "9.9.9"}))
            self.assertEqual(_load()._manifest_version(base=d), "9.9.9")
        # the package literal is untouched: health keeps reporting the code it runs
        self.assertRegex(_load()._version(), r"^\d+\.\d+\.\d+$")

    def test_parent_manifest_is_not_authoritative(self):
        """A manifest one level up is NOT this kit's. /tmp/manifest.json exists (2026-10-26)."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            nested = pathlib.Path(d) / "kit"
            nested.mkdir()
            (pathlib.Path(d) / "manifest.json").write_text(json.dumps({"version": "1.2.3"}))
            self.assertEqual(_load()._manifest_version(base=str(nested)), "absent")

    def test_absent_manifest_is_not_a_fork(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_load()._manifest_version(base=d), "absent")

    def test_unreadable_manifest_does_not_raise(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "manifest.json").write_text("{not json")
            self.assertEqual(_load()._manifest_version(base=d), "absent")

    def test_repo_manifest_matches_package_literal(self):
        """Today the two agree — by hand, every bump. This is the check, not the mechanism."""
        repo_manifest = pathlib.Path(__file__).resolve().parent.parent / "kit" / "manifest.json"
        if not repo_manifest.exists():
            self.skipTest("no kit/manifest.json in this checkout")
        self.assertEqual(_load()._manifest_version(base=str(repo_manifest.parent)),
                         _load()._version(),
                         "bump hand/__init__.py and kit/manifest.json in the same commit")

    def test_changelog_head_is_this_version(self):
        """Third written source (Neuromancer, 2026-10-26): the changelog's first
        section names the version too. Comments are not checkable; this is."""
        root = pathlib.Path(__file__).resolve().parent.parent
        body = (root / "CHANGELOG.md").read_text()
        head = "## [" + body.split("## [")[1]
        self.assertIn(_load()._version(), head,
                      "bump CHANGELOG.md in the same commit as the two version literals")


if __name__ == "__main__":
    unittest.main()

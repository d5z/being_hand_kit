"""Release test for 0.13.3 — 空不等于没有，也不等于没问。

0.13.3 只有一处改动，但它属于这个项目最贵的那一类：回执把**我们的没看**说成
**页面的没有**。

实测（2026-10-22）：整页内容都在 iframe 里时，`cdp_see(kind=dom)` 回

    error: "empty page (CSR?)"   hint: "try render-wait"
    evidence.reason: "cdp_dom returned neither url nor title"

url 和 title 明明读得到却被丢掉，原因被归给页面（CSR 未渲染），而同一页上
`kind=a11y` 把 frame 里的文字读得干干净净。判据：读到了什么就报什么，读不到
就说读不到，别把「我没往里看」写成「里面没有」。

行为证明在 tests/test_dom_no_text.py。本文件锁版本、记录与措辞契约。
"""

import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _manifest():
    with open(os.path.join(ROOT, "kit", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


class TestVersion0133(unittest.TestCase):
    """Current-version assertions — these move with the next bump."""

    def test_version_is_0133(self):
        import hand
        self.assertEqual(hand.__version__, "0.13.3")

    def test_manifest_version_is_0133(self):
        self.assertEqual(_manifest()["version"], "0.13.3")

    def test_changelog_has_0133_entry(self):
        self.assertIn("## [0.13.3]", _read("CHANGELOG.md"))


class TestNoBlankPageVerdict(unittest.TestCase):
    def test_the_misdiagnosis_is_no_longer_returned(self):
        # the phrase may live in a comment (history); what must be gone is the
        # JS literal that made it a verdict
        src = _read("hand/perception/cdp_snapshot.py")
        self.assertNotIn('error:"empty page (CSR?)",hint', src)
        self.assertNotIn("empty page (CSR?)\",hint", src)

    def test_snapshot_reports_url_and_title_when_text_is_empty(self):
        src = _read("hand/perception/cdp_snapshot.py")
        # one object built before the empty-text branch, so metadata survives it
        self.assertIn('meta={page_title:document.title||"(no title)",url:window.location.href}',
                      src)
        self.assertIn("meta.text_chars=0", src)

    def test_empty_text_names_the_frame_count(self):
        src = _read("hand/perception/cdp_snapshot.py")
        self.assertIn("_child_frame_count(ws)", src)
        self.assertIn("content may live in a frame", src)

    def test_no_text_is_a_reason_of_its_own(self):
        from hand.receipt import text_channel
        self.assertEqual(text_channel(None, reason="no_text")["reason"], "no_text")
        self.assertEqual(text_channel(None)["reason"], "not_requested")


if __name__ == "__main__":
    unittest.main()

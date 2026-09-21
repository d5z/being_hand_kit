"""L3 scenarios — end-to-end journeys through real Chrome.

PRD L3: beings.town + github.com journeys plus a form journey. Each step is
judged programmatically; the journey judge returns three states. Real-site
journeys tolerate drift (NEAR) and SKIP when the network is unreachable, so a
flaky site never turns the gate red by itself.
"""

import os
import sys
import unittest

sys.path.insert(0, "/home/alice/Hand")

from tests.harness import judge as J
from tests.harness import runner
from tests.harness import scenarios as S
from tests.harness.scenarios import FixtureServer, Journey

_FX = None
_CHROME = runner.chrome_available()

BEINGS = "https://beings.town"
GITHUB = "https://github.com/d5z/being_hand_kit"


def setUpModule():
    global _FX
    if _CHROME:
        _FX = FixtureServer()


def tearDownModule():
    if _FX:
        _FX.close()


def beings_journey():
    steps = [
        ("open", S.step_open(BEINGS)),
        ("see", S.step_see("a11y")),
        ("find", S.step_find_link(["Browse the Grove", "Grove", "Bonfire", "篝火"])),
        ("click", S.step_click_handle()),
        ("see-again", S.step_see("a11y", key="see_after", settle=1.5)),
    ]
    return Journey("beings.town", BEINGS, "beings.town", steps,
                   lambda ctx: (ctx.update({"expect_url": "/grove",
                                            "candidates": ["Browse the Grove"]}),
                                S.judge_navigation_journey(ctx))[1])


def github_journey():
    steps = [
        ("open", S.step_open(GITHUB)),
        ("see", S.step_see("a11y")),
        ("find", S.step_find_link(["Issues"])),
        ("click", S.step_click_handle()),
        ("see-again", S.step_see("a11y", key="see_after", settle=1.5)),
    ]
    return Journey("github", GITHUB, "github.com", steps,
                   lambda ctx: (ctx.update({"expect_url": "/issues",
                                            "candidates": ["Issues"]}),
                                S.judge_navigation_journey(ctx))[1])


def form_journey(base):
    steps = [
        ("open", S.step_open(base + "/form")),
        ("see", S.step_see("a11y")),
        ("find", S.step_find_role("textbox")),
        ("focus", S.step_click_handle()),
        ("type", S.step_type_focused("being-says-hello")),
        ("read_back", S.step_read_input("#q")),
    ]
    j = Journey("form", base + "/form", "127.0.0.1", steps, S.judge_form_journey, layer="L3")
    return j


def _run(self, journey, require_network=False):
    if require_network and not runner.host_reachable(journey.start_url):
        self.skipTest(f"network unreachable: {journey.start_url}")
    ctx = {"type_text": "being-says-hello"}
    trace = runner.run_journey(journey, ctx=ctx)
    verdict = J.Verdict(**trace["verdict"])
    if not verdict.ok():
        # failure is evidence: keep the full trace on disk for the report
        import json, tempfile
        path = os.path.join(tempfile.gettempdir(), f"hand_l3_fail_{journey.name}.json")
        with open(path, "w") as f:
            json.dump(trace, f, ensure_ascii=False, indent=1)
        self.fail(f"[{verdict.state.upper()}] {verdict.task}: {verdict.reason}\n"
                  f"trace saved to {path}")
    if verdict.state == J.NEAR:
        print(f"  ~ NEAR {journey.name}: {verdict.reason}")


@unittest.skipIf(not _CHROME, "Chrome unavailable")
class L3Scenarios(unittest.TestCase):

    def test_journey_beings_town(self):
        _run(self, beings_journey(), require_network=True)

    def test_journey_github(self):
        _run(self, github_journey(), require_network=True)

    def test_journey_form(self):
        _run(self, form_journey(_FX.url("")), require_network=False)


if __name__ == "__main__":
    unittest.main()

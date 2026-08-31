"""Real-browser tests for CDP perception contract v1 (require Chrome).

Run with: python3 tests/run_tests.py
Skipped automatically if Chrome is not on localhost:9222.
"""

import os
import sys
import unittest
import urllib.request
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hand.perception.cdp_snapshot import interactive_map
from hand.action.cdp_act import cdp_click_do
from hand.perception.cdp_core import (
    list_pages, cdp_connect, cdp_call, _init_domains, CDP_HOST
)

_SKIP_NO_CHROME = False
try:
    list_pages()
except Exception:
    _SKIP_NO_CHROME = True


@unittest.skipIf(_SKIP_NO_CHROME, "Chrome not available on localhost:9222")
class TestRealBrowserDPR2(unittest.TestCase):
    """DPR=2 fidelity: coordinates are physical pixels, xy click lands."""

    def setUp(self):
        # Open a fresh tab for each test to avoid cross-test contamination
        req = urllib.request.Request(
            f'{CDP_HOST}/json/new?about:blank', method='PUT')
        resp = urllib.request.urlopen(req, timeout=5)
        self.page = json.loads(resp.read().decode())
        self.ws_url = self.page['webSocketDebuggerUrl']

    def tearDown(self):
        try:
            req = urllib.request.Request(
                f'{CDP_HOST}/json/close/{self.page["id"]}', method='PUT')
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    def _open_ws(self):
        ws = cdp_connect(self.ws_url)
        _init_domains(ws, 'Page', 'Runtime')
        return ws

    def _page_index(self):
        pages = list_pages()
        for i, p in enumerate(pages):
            if p['id'] == self.page['id']:
                return i
        raise RuntimeError('Test page not found in page list')

    def test_dpr2_coordinates_and_click(self):
        """Spec §4.1: DPR=2 rect must be CSS×2; xy click must land."""
        ws = self._open_ws()
        try:
            # Force DPR=2 via CDP emulation
            cdp_call(ws, 'Emulation.setDeviceMetricsOverride', {
                'width': 800,
                'height': 600,
                'deviceScaleFactor': 2,
                'mobile': False,
            })

            # Navigate to a minimal test page with a known-position button
            html = (
                'data:text/html,'
                '<html><body>'
                '<button id="btn" onclick="window.clicked=true" '
                'style="position:absolute;left:100px;top:100px;'
                'width:80px;height:30px;">Click</button>'
                '</body></html>'
            )
            cdp_call(ws, 'Page.navigate', {'url': html}, msg_id=10)
            # Page.navigate returns immediately; allow load + paint
            time.sleep(0.5)

            # interactive_map on this specific page
            idx = self._page_index()
            result = interactive_map(page_sel=idx)
            self.assertEqual(result['coord']['dpr'], 2.0)

            # Find the button
            btn = next(
                (e for e in result['elems'] if e.get('tag') == 'BUTTON'),
                None)
            self.assertIsNotNone(btn, 'BUTTON not found in interactive_map')
            # CSS center = (100+40, 100+15) = (140, 115); physical = ×2
            self.assertEqual(btn['x'], 280)
            self.assertEqual(btn['y'], 230)
            self.assertEqual(btn['w'], 160)
            self.assertEqual(btn['h'], 60)
            self.assertTrue(btn.get('in_viewport'))
            self.assertFalse(btn.get('occluded'))
            self.assertTrue(btn.get('visible'))

            # Click at the reported physical coordinates
            click_res = cdp_click_do(f"xy:{btn['x']},{btn['y']}")
            self.assertEqual(click_res.get('result'), 'ok')

            # Verify the click actually hit the button
            raw = cdp_call(ws, 'Runtime.evaluate', {
                'expression': 'window.clicked',
                'returnByValue': True,
            }, msg_id=20)
            clicked = raw.get('result', {}).get('value')
            self.assertTrue(
                clicked,
                'Button onclick did not fire — coordinates may be wrong')
        finally:
            ws.close()


if __name__ == '__main__':
    unittest.main()

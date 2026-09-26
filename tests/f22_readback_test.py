#!/usr/bin/env python3
"""F22 red/green sample matrix: cdp_type post-flight read-back.

R1–R4 must go red at the named gate; G1–G5 must land and verify.
Launches an isolated headless Chrome (temp user-data-dir, dedicated CDP
port) via hand.perception.cdp_launcher.ensure_chrome — the same machinery
cdp_open uses. Does not touch the developer's real Chrome profile.

Do not import hand.* until HAND_* env is set: cdp_core / cdp_launcher
bind CDP_HOST at import time.
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.parse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

_PROFILE = tempfile.mkdtemp(prefix='hand-f22-chrome-')
_PORT = str(_free_port())
os.environ['HAND_PROFILE_DIR'] = _PROFILE
os.environ['HAND_CDP_PORT'] = _PORT
os.environ['HAND_HEADLESS'] = '1'
os.environ['HAND_PROFILE'] = 'isolated'

from hand.perception.cdp_launcher import (  # noqa: E402
    ensure_chrome, open_new_tab,
)
from hand.perception.cdp_core import (  # noqa: E402
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains,
)
from hand.perception.ax_tree import save_handle_map  # noqa: E402
import hand.action.cdp_act as cdp_act  # noqa: E402

_CHROME_PROC = None

def _cleanup():
    proc = _CHROME_PROC
    if proc is not None:
        try:
            proc.kill()
            proc.wait(timeout=8)
        except Exception:
            pass
    shutil.rmtree(_PROFILE, ignore_errors=True)

def _html_url(body):
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body>' + body + '</body></html>'
    )
    return 'data:text/html;charset=utf-8,' + urllib.parse.quote(html)

def _page_ws():
    pages = list_pages()
    if not pages:
        raise RuntimeError('no CDP pages after Chrome spawn')
    _, page = resolve_page(None, pages)
    return cdp_connect(page['webSocketDebuggerUrl'])

def navigate(url):
    pages = list_pages()
    if not pages:
        open_new_tab(url)
        time.sleep(0.4)
        pages = list_pages()
    if not pages:
        raise RuntimeError('no CDP pages after open_new_tab')
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Page')
        cdp_call(ws, 'Page.navigate', {'url': url})
        time.sleep(0.35)
    finally:
        ws.close()

def page_eval(expr):
    ws = _page_ws()
    try:
        raw = cdp_call(ws, 'Runtime.evaluate',
                       {'expression': expr, 'returnByValue': True})
        return raw.get('result', {}).get('value')
    finally:
        ws.close()

def make_handle(selector, role='textbox', name=''):
    """backendNodeId of `selector` → a synthetic [1] handle map entry."""
    ws = _page_ws()
    try:
        _init_domains(ws, 'Runtime')
        cdp_call(ws, 'DOM.getDocument', {'depth': 0}, msg_id=30)
        expr = 'document.querySelector(' + json.dumps(selector) + ')'
        raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr}, msg_id=2)
        oid = (raw.get('result') or {}).get('objectId')
        if not oid:
            raise RuntimeError(f'no objectId for {selector!r}')
        desc = cdp_call(ws, 'DOM.describeNode', {'objectId': oid}, msg_id=3)
        bid = (desc.get('node') or {}).get('backendNodeId')
        if not bid:
            raise RuntimeError(f'no backendNodeId for {selector!r}')
    finally:
        ws.close()
    save_handle_map({
        '1': {
            'role': role,
            'name': name,
            'backend_node_id': bid,
            'interactive': True,
            'contains_interactive': False,
            'x': 0, 'y': 0,
        }
    })
    return '[1]'

def _error(receipt):
    return ((receipt or {}).get('error')
            or ((receipt or {}).get('evidence') or {}).get('reason')
            or '')


def _rb(receipt):
    ev = (receipt or {}).get('evidence') or {}
    rb = ev.get('read_back')
    return rb if isinstance(rb, dict) else {}

def _red(receipt, needle):
    return receipt.get('verified') is False and needle in _error(receipt)

def _green(receipt):
    return (receipt.get('verified') is True
            and _rb(receipt).get('landed') is True)

def run_samples():
    rows = []

    def record(sample, expect, ok, detail):
        rows.append((sample, expect, 'PASS' if ok else 'FAIL', detail))

    # R1 — exp2: focused SELECT is not text-editable
    navigate(_html_url(
        '<select id="sel"><option>A</option><option>B</option></select>'))
    cdp_act.cdp_click('#sel')
    r = cdp_act.cdp_type_focused('Y2')
    record('R1', 'pre-flight not text-editable',
           _red(r, 'not text-editable') and 'SELECT' in _error(r),
           _error(r)[:120])

    # R2 — exp1 shape: refuse SELECT, do not drift into the sibling input
    navigate(_html_url(
        '<input id="q" value="BOM">'
        '<select id="sel"><option>A</option><option>B</option></select>'))
    cdp_act.cdp_click('#sel')
    r = cdp_act.cdp_type_focused('已修复')
    bom = page_eval('document.querySelector("#q").value')
    record('R2', 'pre-flight not text-editable + no drift',
           _red(r, 'not text-editable') and bom == 'BOM',
           f'error={_error(r)[:80]!r} input.value={bom!r}')

    # R3 — only shape pre-flight cannot catch: oninput wipes the field
    navigate(_html_url('<input id="q" oninput="this.value=\'\'">'))
    r = cdp_act.cdp_type('#q', 'wiped')
    record('R3', 'post-flight did not land, after==""',
           _red(r, 'did not land') and _rb(r).get('after') == '',
           f'error={_error(r)[:90]!r} rb={_rb(r)}')

    # R4 — readonly input
    navigate(_html_url('<input id="q" readonly value="locked">'))
    r = cdp_act.cdp_type('#q', 'x')
    record('R4', 'pre-flight readonly',
           _red(r, 'readonly'),
           _error(r)[:120])

    # G1 — handle path, empty input
    navigate(_html_url('<input id="q">'))
    handle = make_handle('#q', role='textbox', name='q')
    r = cdp_act.cdp_type_handle(handle, 'hello')
    record('G1', 'handle path landed+verified',
           _green(r),
           f'verified={r.get("verified")} rb={_rb(r)} err={_error(r)[:60]!r}')

    # G2 — append to existing value (caret at end, focused path)
    navigate(_html_url('<input id="q" value="old">'))
    page_eval(
        'var el=document.querySelector("#q");'
        'el.focus(); el.setSelectionRange(el.value.length, el.value.length); true')
    r = cdp_act.cdp_type_focused('more')
    after = _rb(r).get('after', '')
    record('G2', 'append "more" into "old"',
           _green(r) and 'more' in after and 'old' in after,
           f'rb={_rb(r)}')

    # G3 — textarea text-mode newline
    navigate(_html_url('<textarea id="t"></textarea>'))
    r = cdp_act.cdp_type('#t', 'l1\nl2')
    after = _rb(r).get('after', '')
    record('G3', 'textarea text-mode "l1\\nl2"',
           _green(r) and 'l1\nl2' in after,
           f'rb={_rb(r)}')

    # G4 — input "query\n": read-back before keyboard Enter
    navigate(_html_url(
        '<form onsubmit="event.preventDefault(); return false;">'
        '<input id="q" name="q"></form>'))
    r = cdp_act.cdp_type('#q', 'query\n')
    after = _rb(r).get('after', '')
    record('G4', 'keyboard Enter: read-back before dispatch',
           _green(r) and 'query' in after,
           f'rb={_rb(r)} enter_mode={((r.get("evidence") or {}).get("enter_mode"))}')

    # G5 — contenteditable
    navigate(_html_url(
        '<div id="ed" contenteditable="true" '
        'style="min-height:40px;min-width:200px;border:1px solid #000"></div>'))
    r = cdp_act.cdp_type('#ed', 'ce-ok')
    after = _rb(r).get('after', '')
    record('G5', 'contenteditable textContent',
           _green(r) and 'ce-ok' in after,
           f'rb={_rb(r)}')

    return rows

def _print_table(rows):
    print()
    print(f'{"SAMPLE":<8}{"EXPECT":<46}{"RESULT":<8}DETAIL')
    print('-' * 110)
    fails = 0
    for sample, expect, result, detail in rows:
        print(f'{sample:<8}{expect:<46}{result:<8}{detail}')
        if result != 'PASS':
            fails += 1
    print('-' * 110)
    print(f'{len(rows) - fails} passed, {fails} failed')
    return fails

def main():
    global _CHROME_PROC
    try:
        _CHROME_PROC = ensure_chrome('about:blank')
        if _CHROME_PROC is None:
            print('FAIL: ensure_chrome returned None '
                  f'(something already on port {_PORT})', file=sys.stderr)
            return 1
        rows = run_samples()
        fails = _print_table(rows)
        return 1 if fails else 0
    except Exception as e:
        print(f'FAIL: test harness error: {type(e).__name__}: {e}',
              file=sys.stderr)
        return 1
    finally:
        _cleanup()

if __name__ == '__main__':
    sys.exit(main())
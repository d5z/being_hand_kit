import ast, sys

checks = [
    ('hand.perception.cdp_snapshot', 'cdp_snapshot'),
    ('hand.perception.ax_app', 'ax_app_see'),
    ('hand.perception.ax_ui', 'ax_ui_see'),
    ('hand.perception.vision_ocr', 'vision_ocr_see'),
    ('hand.action.cdp_act', 'cdp_click'),
    ('hand.action.cdp_act', 'cdp_type'),
    ('hand.action.keystroke', 'keystroke_do'),
    ('hand.action.ax_click', 'ax_click_do'),
    ('hand.place.detect', 'open_place'),
    ('hand.place.detect', 'detect_place'),
    ('hand.session', 'get_session'),
    ('hand.router', 'route_see'),
    ('hand.router', 'route_do'),
]

ok = []
fail = []
for mod, fn in checks:
    try:
        m = __import__(mod, fromlist=[fn])
        getattr(m, fn)
        ok.append(f'{mod}.{fn}')
    except Exception as e:
        fail.append(f'{mod}.{fn}: {e}')

print(f'OK: {len(ok)}')
for i in ok: print(f'  + {i}')
if fail:
    print(f'FAIL: {len(fail)}')
    for f in fail: print(f'  X {f}')
else:
    print('ALL IMPORTS OK')
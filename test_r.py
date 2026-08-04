import sys,json,time
sys.path.insert(0,'/Users/alice/Hand')
from hand.perception.cdp_core import list_pages, cdp_connect, cdp_call
from hand.router import route_open, route_do

pages = list_pages()
ws = cdp_connect(pages[0]['webSocketDebuggerUrl'])
cdp_call(ws, 'Page.enable')
cdp_call(ws, 'Page.navigate', {'url': 'https://example.com'})
time.sleep(0.5)

html = '<div style=padding:20px;background:#f0f0f0;border-radius:8px><h2>Test Search</h2><input id=srch type=text placeholder=Search... style=padding:8px;width:300px;font-size:16px><button id=btn onclick=document.getElementById(chr(39)+'res'+chr(39)+').innerText=document.getElementById(chr(39)+'srch'+chr(39)+').value>Search</button><p id=res style=margin-top:16px;font-size:18px></p></div>'
expr = 'document.body.innerHTML += ' + json.dumps(html)
cdp_call(ws, 'Runtime.evaluate', {'expression': expr})
time.sleep(0.3)

print('OPEN:', json.dumps(route_open('https://example.com'), indent=2))
print()
print('TYPE:', json.dumps(route_do('type #srch|Hello World'), indent=2))
print()
v = cdp_call(ws, 'Runtime.evaluate', {'expression': 'document.getElementById(srch).value'})
print('VALUE:', v.get('result',{}).get('value'))
print()
print('CLICK:', json.dumps(route_do('click text=Search'), indent=2))
print()
v2 = cdp_call(ws, 'Runtime.evaluate', {'expression': 'document.getElementById(res).innerText'})
print('RESULT:', v2.get('result',{}).get('value'))
ws.close()
print('DONE')

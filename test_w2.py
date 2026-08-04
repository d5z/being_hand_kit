import sys,json,time
sys.path.insert(0,'/Users/alice/Hand')
from hand.perception.cdp_core import list_pages, cdp_connect, cdp_call
from hand.router import route_open, route_do

pages = list_pages()
ws = cdp_connect(pages[0]['webSocketDebuggerUrl'])
cdp_call(ws, 'Page.enable')
cdp_call(ws, 'Page.navigate', {'url': 'https://en.wikipedia.org/wiki/Main_Page'})
time.sleep(1.0)

print('OPEN:', json.dumps(route_open('https://en.wikipedia.org'), indent=2))
print()
print('TYPE:', json.dumps(route_do('type #searchInput|Alice the silicon being'), indent=2))
print()
v = cdp_call(ws, 'Runtime.evaluate', {'expression': 'document.getElementById(
import sys,json,time
sys.path.insert(0,'/Users/alice/Hand')
from hand.perception.cdp_core import cdp_connect, cdp_call
from hand.router import route_open, route_do, route_see

# Get CDP connection
pages = cdp_call(None, 'list')
page_ws = pages[0]['webSocketDebuggerUrl']
ws = cdp_connect(page_ws)

# Navigate
cdp_call(ws, 'Page.enable')
cdp_call(ws, 'Page.navigate', {'url': 'https://example.com'})
time.sleep(0.5)

# Inject search UI
html = '<div style="margin:20px;padding:20px;background:#f0f0f0;border-radius:8px;"><h2>Test Search</h2><input id="search" type="text" placeholder="Search..." style="padding:8px;width:300px;font-size:16px;"><button id="searchBtn" onclick="document.getElementById(\'result\').innerText=\'You searched: \'+document.getElementById(\'search\').value" style="padding:8px 16px;margin-left:8px;font-size:16px;background:#1a73e8;color:white;border:none;border-radius:4px;cursor:pointer;">Search</button><p id="result" style="margin-top:16px;font-size:18px;color:#333;"></p></div>'
js_expr = 

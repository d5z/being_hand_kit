"""Scenario definitions + a local fixture server (L2-L6).

Two kinds of scenarios, both driven through real Chrome:

  * deterministic fixtures — a throwaway HTTP server on 127.0.0.1 serving
    pages with known structure (form, clickable button, oversized tree,
    never-answering socket). No external network → no flake.
  * real sites — beings.town and github.com journeys. These tolerate site
    drift: judges return NEAR when the target moved, SKIP when the network is
    unreachable.

The fixture server runs in-process (ThreadingHTTPServer) so L2/L4 keep working
on an offline box.
"""

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── rendered pages ───────────────────────────────────────────────────

BASIC_HTML = """<!doctype html><html><head><title>Fixture Basic</title></head>
<body>
  <h1>Fixture Basic</h1>
  <p>Deterministic page for hand L2 integration.</p>
  <a id="to-form" href="/form">Go to form</a>
  <button id="mark" onclick="window.clicked=(window.clicked||0)+1">Mark</button>
</body></html>"""

FORM_HTML = """<!doctype html><html><head><title>Fixture Form</title></head>
<body>
  <h1>Fixture Form</h1>
  <label for="q">Query</label>
  <input id="q" type="text" name="q" aria-label="Query">
  <a id="back" href="/basic">Back</a>
</body></html>"""

BIG_HTML = ("<!doctype html><html><head><title>Fixture Big</title></head><body>"
            "<h1>Fixture Big</h1>"
            + "".join(f'<p>paragraph number {i} with some words to fill the tree</p>'
                      for i in range(900))
            + "</body></html>")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        pages = {"/basic": BASIC_HTML, "/form": FORM_HTML, "/big": BIG_HTML,
                 "/": BASIC_HTML}
        body = pages.get(path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>404</h1>")
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FixtureServer:
    """In-process HTTP server + a raw socket that accepts and never answers.

    Usage:  with FixtureServer() as fx: fx.url("/basic")
    """

    def __init__(self):
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._http.daemon_threads = True
        self._t = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._t.start()
        # Blackhole socket: TCP accept, then hold the connection open. Used for
        # the "slow page / timeout is honest" L4 scenario.
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._blackhole_port = self._sock.getsockname()[1]
        self._held = []
        self._stop = False
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
                self._held.append(conn)  # hold it open forever
            except OSError:
                return

    @property
    def port(self):
        return self._http.server_address[1]

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def blackhole_url(self, path="/slow"):
        return f"http://127.0.0.1:{self._blackhole_port}{path}"

    def close(self):
        self._stop = True
        try:
            self._http.shutdown()
            self._http.server_close()
        except Exception:
            pass
        for c in self._held:
            try:
                c.close()
            except Exception:
                pass
        try:
            self._sock.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ── L3 real-site journey definitions (data-driven) ───────────────────
# Each journey: a list of steps (name, callable) + a judge that returns a
# three-state verdict. `host` gates the whole journey: unreachable → SKIP.

class Journey:
    def __init__(self, name, start_url, host, steps, judge, layer="L3"):
        self.name = name
        self.start_url = start_url
        self.host = host
        self.steps = steps            # list[(step_name, callable(ctx) -> dict)]
        self.judge = judge            # callable(ctx) -> Verdict
        self.layer = layer


JOUNREYS_PLACEHOLDER = None

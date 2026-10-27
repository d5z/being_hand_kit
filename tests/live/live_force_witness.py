"""Live: is force_witness a real witness, or only a string comparison?

Two grids Neuromancer and I both left unverified on 2026-10-27:
  - his: "带别人的 profile 那格只做了字符串反例，没真造一台别人的浏览器"
  - mine: "force_witness 四格全是 mock，真机零样本"

So: spawn two real browsers with two real profiles and ask the witness which is
which. No mocks, no string counterexamples.

Run: python3 tests/live/live_force_witness.py
"""

import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hand.perception import cdp_launcher as L  # noqa: E402

SCRATCH = "/tmp/hand-force-witness"
A = os.path.join(SCRATCH, "prof-A")
B = os.path.join(SCRATCH, "prof-B")
PORT_A, PORT_B = 9551, 9552


def spawn(port, prof):
    chrome = L._find_chrome()
    return subprocess.Popen(
        [chrome, "--headless=old", f"--remote-debugging-port={port}",
         f"--user-data-dir={prof}", "--no-first-run",
         "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait(port, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=1).read()
            return True
        except Exception:
            time.sleep(0.25)
    return False


def ask(port, prof, mode="isolated"):
    os.environ["HAND_CDP_PORT"] = str(port)
    os.environ["HAND_PROFILE_DIR"] = prof
    os.environ.pop("HAND_PROFILE", None) if mode == "isolated" else os.environ.__setitem__("HAND_PROFILE", mode)
    return L.force_witness()


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    pa = spawn(PORT_A, A)
    pb = spawn(PORT_B, B)
    up = (wait(PORT_A), wait(PORT_B))
    print(f"two real browsers up: A={up[0]} B={up[1]}")
    if not all(up):
        raise SystemExit("could not bring two browsers up")

    grid = [
        ("A on argv + env A  (our browser)", PORT_A, A, "isolated", "profile"),
        ("A on argv + env B  (a real stranger)", PORT_A, B, "isolated", None),
        ("B on argv + env B  (our browser)", PORT_B, B, "isolated", "profile"),
        ("B on argv + env A  (a real stranger)", PORT_B, A, "isolated", None),
        ("persistent mode on A  (the human's own Chrome profile)", PORT_A, A, "persistent", None),
    ]
    bad = 0
    for label, port, prof, mode, want in grid:
        w = ask(port, prof, mode)
        got = w.get("witness")
        ok = got == want
        bad += 0 if ok else 1
        print(f"\n[{'ok' if ok else 'MISMATCH'}] {label}")
        print(f"    witness={got!r} (want {want!r}) port={w.get('port')} "
              f"listener_pid={w.get('listener_pid')}")
        print(f"    why={w.get('why')}")

    for p in (pa, pb):
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(1)
    for p in (pa, pb):
        try:
            p.kill()
        except Exception:
            pass
    leftovers = subprocess.run(
        ["sh", "-c",
         f"ss -lptnH 'sport = :{PORT_A} or sport = :{PORT_B}' | wc -l"],
        capture_output=True, text=True).stdout.strip()
    print(f"\nleftover listeners: {leftovers}")
    print(f"grid: {len(grid) - bad}/{len(grid)} as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

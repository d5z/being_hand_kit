"""Live acceptance for the listener claim (0.13.8) on Linux.

Chrome does not re-exec here the way Neuromancer measured on macOS, so the
re-exec *state* is produced at the record level: a record whose pid is dead but
whose profile directory is the one the listener carries. That is exactly the
state a re-exec leaves behind — and the state that used to make owner_status say
"not mine" about our own browser.

Steps: spawn (record must name the listener) → dead-pid record (must still be
mine, via listener) → wrong-profile record (must be stranger) → close.
Run with HAND_CDP_PORT=9444.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/alice/Hand")
from hand.perception import cdp_launcher as L


def ss_pid(port):
    try:
        out = subprocess.run(["ss", "-lptnH", f"sport = :{port}"],
                             capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            if "pid=" in line:
                return int(line.split("pid=")[1].split(",")[0])
    except Exception as e:
        return f"error: {e}"
    return None


def rewrite(**kw):
    path = L._owner_file()
    rec = json.load(open(path))
    rec.update(kw)
    json.dump(rec, open(path, "w"))


port = L.CDP_PORT
print("port:", port, " listener before spawn:", ss_pid(port))

proc = L.ensure_chrome()
rec = L.read_owner()
print("spawn pid:", proc.pid, " listener by ss:", ss_pid(port))
print("record: pid=%s pid_source=%s spawn_pid=%s via=%s match=%s" % (
    rec.get("pid"), rec.get("pid_source"), rec.get("spawn_pid"),
    rec.get("listener_via"), rec.get("listener_profile_match")))
st = L.owner_status()
print("owner_status #1:", st["owner"], "|", st.get("reason", "pid matches"))

# the re-exec shape: the pid we recorded is gone, the browser is not
rewrite(pid=999999, start_ticks=None)
st = L.owner_status()
print("owner_status #2 (dead recorded pid):", st["owner"],
      "| pid_source:", st.get("pid_source"), "|", st.get("reason"))

# a listener carrying someone else's profile must not be adopted
rewrite(pid=999999, start_ticks=None, profile="/tmp/not-our-profile")
st = L.owner_status()
print("owner_status #3 (wrong profile):", st["owner"], "|", st.get("reason"))

# restore and close through the real path
prof = L.profile_dir()
rewrite(pid=999999, start_ticks=None, profile=prof)
out = L.ensure_chrome()  # endpoint already up → attach path
print("close:", json.dumps({k: v for k, v in
                            __import__("hand.hand", fromlist=["x"]).close(
                                force=False).items()
                            if k in ("closed", "endpoint_gone", "verified")}))
print("record after close:", L.read_owner())
print("listener after close:", ss_pid(port))

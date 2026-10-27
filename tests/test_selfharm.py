"""Tests: the killer is inside its own match set.

2026-10-27b -- Neuromancer killed his own hand MCP server with
`pkill -f "mcp_server.py"`, and the mechanism is worth a test, not a note:

    `pkill -f` matches the whole command line, and when a script arrives through
    `sh -c "..."`, the *entire script text is that shell's argv*. So every word
    used to describe the target also sits in an ancestor's command line. The
    match set and the killer overlap by construction.

Excluding os.getpid() alone does not fix it: the process that dies is the parent
shell, not the process that called kill(). What fixes it is excluding the
ancestor chain.

The test is built to fail in both wrong directions:
  * exclude only self      -> the shell shows up in `killed`          (test fails)
  * drop the marker check  -> the bystander shows up in `killed`      (test fails)
so a pass means the two rules are both doing work, not one masking the other.
"""

import json
import os
import shlex
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = "/nonexistent-marker-selfharm-9f3a"
TOKEN = "remote-debugging-port"          # what pgrep -f enumerates candidates by


class AncestorExclusionTest(unittest.TestCase):
    def test_self_and_bystander(self):
        """One shell carrying the words of this call, one innocent bystander.

        The first must be excluded (self/ancestor), the second skipped (no marker).
        Neither may be killed.
        """
        inner = (
            "import json\n"
            "from hand.perception.cdp_launcher import kill_our_browsers\n"
            "r = kill_our_browsers(dry_run=True, marker=%r)\n"
            "print('RECEIPT ' + json.dumps(r))\n" % MARKER
        )
        # outer shell: its command line carries the marker AND the port token,
        # exactly like a cleanup script that names its target in its own text.
        # bystander: carries the port token only (a candidate, not ours).
        cmd = [
            "/bin/sh", "-c",
            'echo "SHELL_PID $$ %s %s" >&2; '
            "sh -c 'sleep 2' %s-%s & echo \"BYSTANDER_PID $!\" >&2; "
            "python3 -c %s"
            % (MARKER, TOKEN, TOKEN, os.getpid(), shlex.quote(inner)),
        ]
        env = dict(os.environ, PYTHONPATH=REPO)
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, env=env,
                           timeout=30)
        shell_pid = bystander = None
        for line in r.stderr.splitlines():
            if line.startswith("SHELL_PID "):
                shell_pid = int(line.split()[1])
            elif line.startswith("BYSTANDER_PID "):
                bystander = int(line.split()[1])
        self.assertIsNotNone(shell_pid, r.stderr)
        self.assertIsNotNone(bystander, r.stderr)
        receipt = json.loads(r.stdout.split("RECEIPT ", 1)[1])

        # the shell that carried this call: excluded, never judged
        self.assertIn(shell_pid, receipt["excluded"],
                      "the shell carrying this call must be excluded, not judged")
        self.assertNotIn(shell_pid, receipt["killed"])
        # the bystander: seen as a candidate, skipped for lack of our marker
        self.assertIn(bystander, receipt["skipped"],
                      "a candidate without our marker must be skipped, not killed")
        self.assertNotIn(bystander, receipt["killed"])
        # and the two rules must not have been satisfied by the same process
        self.assertNotIn(bystander, receipt["excluded"])
        try:                                  # our own spawn; leave nothing behind
            os.kill(bystander, 15)
        except OSError:
            pass

    def test_ancestors_are_the_real_chain(self):
        """Walk must include me and reach init without looping."""
        from hand.perception.cdp_launcher import _ancestor_pids
        chain = _ancestor_pids()
        self.assertEqual(chain[0], os.getpid())
        self.assertIn(1, chain)
        self.assertEqual(len(chain), len(set(chain)))

    def test_chain_reports_when_it_stopped_early(self):
        """A short chain and a complete chain are two different facts.

        0.13.8 -- the walk used to return a bare list, so "I read four levels and
        could not go further" looked identical to "I reached init". The receipt
        then printed a clean excluded_count for a weakened gate. The walk has to
        carry its own truncation: where it stopped, and why.
        """
        from hand.perception import cdp_launcher as L

        full = L._ancestor_chain()
        self.assertTrue(full["reached_init"])
        self.assertIsNone(full["truncated_at"])
        self.assertIsNone(full["truncated_why"])

        short = L._ancestor_chain(depth=1)          # self only, parent never read
        self.assertEqual(short["levels"], 1)
        self.assertFalse(short["reached_init"])
        self.assertEqual(short["truncated_at"], os.getppid())
        self.assertIn("depth limit", short["truncated_why"])

        orig = L._read_ppid
        def broken(pid):
            if pid == os.getppid():
                return 0, "simulated EACCES"
            return orig(pid)
        L._read_ppid = broken
        try:
            r = L.kill_our_browsers(dry_run=True, marker="/nonexistent-marker-xyz-000")
            degraded = L._ancestor_chain()
        finally:
            L._read_ppid = orig

        self.assertFalse(degraded["reached_init"])
        self.assertIn("simulated EACCES", degraded["truncated_why"])
        self.assertIs(r["ancestry_complete"], False,
                      "the receipt must say the gate was weak, not just print a count")
        self.assertIn("simulated EACCES", r["ancestry"]["truncated_why"])

    def test_a_stranger_without_the_marker_is_still_skipped_not_killed(self):
        """Ancestor exclusion must not become 'kill everything that is not me'."""
        from hand.perception.cdp_launcher import kill_our_browsers
        r = kill_our_browsers(dry_run=True, marker="/nonexistent-marker-xyz-000")
        self.assertEqual(r["killed"], [])
        self.assertEqual(r["excluded_count"], len(r["excluded"]))


if __name__ == "__main__":
    unittest.main()

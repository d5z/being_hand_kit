#!/usr/bin/env bash
# Live: the identity fn used by kit/sync.sh -- stable across locale/TZ, and empty
# when it cannot judge (the caller must then refuse to act).
# The function text is extracted from kit/sync.sh at run time so this test cannot
# drift from the script it is testing.
set -u
cd "$(dirname "$0")/../.." || exit 1
eval "$(sed -n '/# --- identity start ---/,/# --- identity end ---/p' kit/sync.sh)"

target=$$
a=$(proc_identity $target)
b=$(LC_ALL=zh_CN.UTF-8 proc_identity $target)
c=$(TZ=America/New_York proc_identity $target)
d=$(LC_ALL=C TZ=UTC proc_identity $target)
echo "self identity = $a"
echo "under zh_CN   = $b"
echo "under NY TZ   = $c"
echo "under C/UTC   = $d"
[ "$a" = "$b" ] && [ "$a" = "$c" ] && [ "$a" = "$d" ] && echo "[ok] stable across locale/TZ" || echo "[FAIL] drifted"
sleep 3 & p=$!; e=$(proc_identity $p); kill -9 $p 2>/dev/null; wait $p 2>/dev/null
f=$(proc_identity $p)
echo "live child = $e (non-empty: $([ -n "$e" ] && echo yes || echo no))"
echo "after kill  = '${f}' (empty = 判不了/不在，调用方不许动手: $([ -z "$f" ] && echo yes || echo NO))"
g=$(proc_identity 0); echo "pid 0        = '${g}'"
h=$(proc_identity 999999); echo "pid 999999   = '${h}'"

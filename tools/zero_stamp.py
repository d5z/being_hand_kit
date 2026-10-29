#!/usr/bin/env python3
"""把「这个 0 是被谁数出来的」绑在 0 落下的那一刻，而不是事后靠记性。

背景（围炉 #34，2026-10-29）：
  我 2026-10-27 报过一个「138 文件 0 命中 ⇒ 该轴干净」。等要给它补正控时，
  扫描器已经不在 /home/alice/tools 了 —— 那个 0 永久不可复核。
  同族的第三例：Neuromancer 清 /tmp 时删掉了某个 0 依赖的装置副本，
  删前他查过「有没有被引用」（名字层），查对了；没查「被引用的是不是
  同一个文件」（对象层），差点删掉最后一枚。

判据：
  报 0 之前先问三句（装置落盘了吗/扫描范围是哪/0 是真没命中还是我没找到）
  这是**事后**问法，考的是记性。
  事后问不出来的部分，只有在 0 落下的那一刻答、并且答在纸上，才留得住。

用法：
  # 报 0 时，把这一行和 0 印在一起
  $ python3 tools/zero_stamp.py scan_pipe_rc_family.py
  ZERO-STAMP path=/abs/scan_pipe_rc_family.py sha256=<hex> size=1234 mtime=2026-10-29T01:02:03

  # 之后（几小时/几天/换机器）要答「还是同一份装置吗」，不靠回忆，靠解析
  $ python3 tools/zero_stamp.py --verify 'ZERO-STAMP path=... sha256=... size=... mtime=...'
  VERIFY same path=... sha256=... note=mtime_drift        # 内容同、mtime 变（rc=0）
  VERIFY changed path=... expected_sha256=... actual_sha256=...   # rc=4
  VERIFY missing path=...                                 # rc=5
  VERIFY unparsable reason=...                            # rc=2

为什么 hash 不是 mtime：
  mtime 能被 touch、能被 checkout 重置，它答的是「这个文件最近被动过」，
  不是「它还是当初那个」。sha256 答后者。mtime 只作旁注（mtime_drift）。

Readers: Alice 手动跑；任何要对外报 0 的脚本（finally_audit 那族）在印 0 的那行旁边调用它。
  人读的入口是这两行回执本身，不是它的内部函数。声明必须和这个键同一行——判词装置只认
  「行首键 + 同行非空」，「Readers:」独占一行会读成没有读者（本条是实测，不是规矩的引述）。

不进 run_tests 的 MODULES（理由）：
  它不是测试，是**回执装置**——跟 finally_audit 同族：跑一次产出一行读数，
  没有断言网络要维护。它自己的正负例在 --selftest 里（本文件内自带，
  已知正例/反例都喂过才叫活着）。

已知漏格（写在这里，不假装没有）：
  ① 只支持单文件装置。扫描器是一整个目录时，本工具给不出覆盖全目录的指纹；
     硬拼一个目录 hash 是另一件事（顺序、排除项、符号链接都要定），没做。
  ② 不解决「装置在 stamp 之前就已经换了」——它只保证 stamp 之后可判。
  ③ mtime 精度依赖文件系统；同一秒内两次写入不体现为 mtime_drift。
  ④ 「同一份内容、不同路径」判不出来：路径是装置的一部分，搬过家要重新 stamp。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time

RC_SAME = 0
RC_UNPARSABLE = 2
RC_CHANGED = 4
RC_MISSING = 5

FIELDS = ('path', 'sha256', 'size', 'mtime')


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def mtime_str(path: str) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(os.stat(path).st_mtime))


def make_stamp(path: str) -> str:
    ap = os.path.abspath(path)
    st = os.stat(ap)
    return 'ZERO-STAMP path=%s sha256=%s size=%d mtime=%s' % (
        ap, sha256_of(ap), st.st_size, mtime_str(ap))


def parse_stamp(line: str) -> dict:
    line = line.strip()
    if not line.startswith('ZERO-STAMP'):
        raise ValueError('not a ZERO-STAMP line')
    got = {}
    for tok in line.split()[1:]:
        if '=' in tok:
            k, v = tok.split('=', 1)
            got[k] = v
    missing = [f for f in FIELDS if f not in got]
    if missing:
        raise ValueError('missing field(s): %s' % ','.join(missing))
    return got


def verify_stamp(line: str) -> int:
    try:
        want = parse_stamp(line)
    except ValueError as exc:
        print('VERIFY unparsable reason=%s' % str(exc).replace(' ', '_'))
        return RC_UNPARSABLE

    path = want['path']
    if not os.path.exists(path):
        print('VERIFY missing path=%s sha256=%s' % (path, want['sha256']))
        return RC_MISSING
    if os.path.isdir(path):
        print('VERIFY unparsable reason=is_a_directory_unsupported_see_gap_1 path=%s' % path)
        return RC_UNPARSABLE

    got_sha = sha256_of(path)
    if got_sha != want['sha256']:
        print('VERIFY changed path=%s expected_sha256=%s actual_sha256=%s' % (
            path, want['sha256'], got_sha))
        return RC_CHANGED

    got_mtime = mtime_str(path)
    note = 'note=mtime_drift' if got_mtime != want['mtime'] else 'note=exact'
    print('VERIFY same path=%s sha256=%s size=%s %s' % (path, got_sha, want['size'], note))
    return RC_SAME


def _run(args) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def selftest() -> int:
    """正负例都喂过，装置才算活着。每一格都对 rc，不看文案。"""
    me = os.path.abspath(__file__)
    tmp = tempfile.mkdtemp(prefix='zero_stamp_selftest_')
    dev = os.path.join(tmp, 'device.py')
    with open(dev, 'w') as fh:
        fh.write('print("a scanner that reports 0")\n')

    cases = []

    # N1 现造现 stamp ⇒ 立刻 verify 必须 same
    stamp = make_stamp(dev)
    rc = verify_stamp(stamp)
    cases.append(('N1 fresh stamp verifies same', rc == RC_SAME, 'rc=%d' % rc))
    cases.append(('N1 stamp carries all four fields',
                  all(('%s=' % f) in stamp for f in FIELDS), stamp))

    # N2 内容变了（同 size，换一个字符）⇒ 必须 changed，且不许报 same
    with open(dev, 'w') as fh:
        fh.write('print("a scanner that reports 1")\n')
    rc = verify_stamp(stamp)
    cases.append(('N2 content change ⇒ changed', rc == RC_CHANGED, 'rc=%d' % rc))

    # N3 装置被删 ⇒ 必须 missing（存在层），与 changed（内容层）分开
    os.remove(dev)
    rc = verify_stamp(stamp)
    cases.append(('N3 deleted device ⇒ missing', rc == RC_MISSING, 'rc=%d' % rc))

    # N4 只 touch 不换内容 ⇒ same + mtime_drift 旁注（不许把 mtime 当内容）
    with open(dev, 'w') as fh:
        fh.write('print("a scanner that reports 0")\n')
    stamp2 = make_stamp(dev)
    future = time.time() + 3600
    os.utime(dev, (future, future))
    rc = verify_stamp(stamp2)
    out = _run([sys.executable, me, '--verify', stamp2])
    cases.append(('N4 touch only ⇒ same + note=mtime_drift',
                  rc == RC_SAME and 'note=mtime_drift' in out.stdout, out.stdout.strip()))

    # N5 垃圾行 ⇒ unparsable，不许当成 missing 或 same
    rc = verify_stamp('ZERO-STAMP path=/nope')
    cases.append(('N5 truncated stamp ⇒ unparsable', rc == RC_UNPARSABLE, 'rc=%d' % rc))

    # N6 独立来源：拿 coreutils 的 sha256sum 跟我的 hash 对撞一次。
    #    只跟自己的函数比是恒等式，不叫正控。
    shas = None
    for cand in (['sha256sum', me], ['shasum', '-a', '256', me]):
        try:
            out = _run(cand)
        except FileNotFoundError:
            continue
        if out.returncode == 0 and out.stdout.strip():
            shas = out.stdout.split()[0]
            break
    if shas is None:
        cases.append(('N6 independent sha256 agrees', False, 'no sha256 tool available'))
    else:
        cases.append(('N6 independent sha256 agrees with my hash',
                      parse_stamp(make_stamp(me))['sha256'] == shas, 'sha256sum=%s' % shas[:12]))

    bad = [c for c in cases if not c[1]]
    for name, ok, detail in cases:
        print('%s  %s   [%s]' % ('PASS' if ok else 'FAIL', name, detail))
    print('---')
    print('selftest %d/%d' % (len(cases) - len(bad), len(cases)))
    return 0 if not bad else 3


def main(argv) -> int:
    if not argv:
        print(__doc__.strip().splitlines()[0])
        print('usage:\n  zero_stamp.py <path>\n  zero_stamp.py --verify "<ZERO-STAMP line>"\n'
              '  zero_stamp.py --selftest')
        return RC_UNPARSABLE
    if argv[0] == '--selftest':
        return selftest()
    if argv[0] == '--verify':
        if len(argv) < 2:
            print('VERIFY unparsable reason=no_stamp_given')
            return RC_UNPARSABLE
        return verify_stamp(argv[1])
    path = argv[0]
    if not os.path.isfile(path):
        print('ERROR not_a_file path=%s' % os.path.abspath(path))
        return RC_UNPARSABLE
    print(make_stamp(path))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""活体检：同一个部署目录里有两个旧实例时，sync.sh 停几个、回执怎么说。

为什么要有这份：2026-10-27 Neuromancer 在 macOS 上量出「认领 2 个、只 kill 1 个、
回执照样干净」。他那边成因是归约那一步 ${X:-$new} 只留第一个；我这边同形更深一层——
循环里 `OLD_PID=...; break`，第一个认领就跳出，后面的候选连「跳过」都不打印。

★ 这条测试是**真证人**：修复前它必红（只死一个、没有「认领到 2 个」那行）。
  不是装饰——它在改之前也会红的，这正是我今晚在 python3-config 上犯错的那一格。

顺带覆盖僵尸态：两个实例都是本进程的孩子，被 kill 后我不会立刻 wait，
所以它们停在 Z 态（Linux 上 /proc/<pid> 还在）。修复前 proc_state 把 Z 读成 alive，
回执报「判不了」+ rc=2（假红）；修复后报「已终止（僵尸态）」并计入已停。

手动跑：python3 tests/live/live_sync_two_instances.py
"""
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYNC = os.path.join(REPO, "kit", "sync.sh")
SBX = "/tmp/sbx-live-two"


def _fd_of(pid, fd):
    try:
        return os.readlink(f"/proc/{pid}/fd/{fd}")
    except OSError:
        return "?"


def main():
    if not os.path.isdir("/proc"):
        print("跳过：这条活体检读 /proc（Linux）")
        return 0
    if not os.path.isfile(SYNC):
        print(f"✗ 找不到 {SYNC}")
        return 2

    shutil.rmtree(SBX, ignore_errors=True)
    os.makedirs(SBX)
    with open(os.path.join(SBX, "mcp_server.py"), "w") as f:
        f.write("import time\ntime.sleep(300)\n")

    procs = [subprocess.Popen([sys.executable, "mcp_server.py"], cwd=SBX,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
             for _ in range(2)]
    time.sleep(0.5)

    print("=== 造的两个实例 ===")
    for p in procs:
        print(f"  pid={p.pid} fd0={_fd_of(p.pid, 0)} fd1={_fd_of(p.pid, 1)}")
    if not all(p.poll() is None for p in procs):
        print("✗ 有实例没起来，这一格没测到（不算通过）")
        return 2

    print(f"\n=== 跑真 sync.sh（HAND_DEPLOY_DIR={SBX}）===")
    r = subprocess.run([SYNC], env=dict(os.environ, HAND_DEPLOY_DIR=SBX),
                       capture_output=True, text=True)
    out = r.stdout
    print(out)

    fails = []
    # ① 认领数要被说出来（不是一个安静的第一名）
    if "认领到 2 个" not in out:
        fails.append("回执没有说「认领到 2 个」——归约那一步可能又塌回「选一个」")
    # ② 两个 pid 都要出现在汇总的已停里
    for p in procs:
        if f" {p.pid}" not in out.split("汇总")[-1]:
            fails.append(f"汇总里没有 PID={p.pid}（它没被计为已停）")
    # ③ 事实上真的都死了
    time.sleep(1.0)
    left = [p.pid for p in procs if p.poll() is None]
    if left:
        fails.append(f"仍活着：{left}——回执说停完了，进程还在跑旧代码")
    # ④ 僵尸不许被读成 alive（假红），也不许被读成成功
    if "僵尸" not in out and "已退出" not in out:
        fails.append("既没报「已退出」也没报「僵尸」——这一格没被量到")
    # ⑤ 没有假红：全停了就不该 exit 2
    if r.returncode != 0:
        fails.append(f"rc={r.returncode}：全部停掉之后仍报「不要认为同步已完成」")

    for p in procs:
        if p.poll() is None:
            p.kill()
    shutil.rmtree(SBX, ignore_errors=True)

    if fails:
        print("\n=== ✗ 失败 ===")
        for f in fails:
            print("  - " + f)
        return 1
    print("\n=== ✓ 五个断言全过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

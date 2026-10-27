#!/bin/bash
# sync.sh — 把开发目录的 Hand 同步到 Portal 部署目录并停掉旧进程。
# 单一事实来源：/home/alice/Hand（开发仓库）
# 部署目标：/home/alice/.heart-portal/kits/hand
#
# 注意：Portal 的 kit 是 lazy spawn（按需启动），不是守护式重启。
# 所以 sync 只负责「替换文件 + 停旧进程」；新代码会在下一次
# hand_* 工具调用时由 Portal 自动加载（uptime 归零即为新进程）。
# 用法：cd /home/alice/Hand && ./kit/sync.sh
set -euo pipefail

DEV="/home/alice/Hand"
DEPLOY="/home/alice/.heart-portal/kits/hand"


# 进程身份：不用 `ps -o lstart=`。
# 2026-10-27 Neuromancer 实测三条：①lstart 只有秒精度，同一秒起 6 个进程归并成
# 1 个值；②随 LC_ALL 变（zh_CN 下是「二 10月/27 …」）；③随 TZ 变。用它判「是同
# 一个进程」，撞键时会放行误杀、locale/TZ 不一致时会永远判「不符」而该杀不杀。
# Linux 上用 /proc/<pid>/stat 第 22 字段（starttime，开机以来的时钟滴答）+ boot_id：
# 数字、内核所有、进程自己改不了（argv 能改，这个不能）、不随 locale/TZ 变。
# 取不到就返回空 —— 空表示「我判不了」，调用方必须当成不能动手，不是「不在」。
proc_identity() {
  pid=$1
  st=$(cat /proc/$pid/stat 2>/dev/null) || return 0
  # comm 里可能有空格/括号，从最后一个 ')' 之后切
  after=${st##*)}
  # after 以 " S 1 2 ..." 开头；starttime 是 stat 的第 22 字段 => after 里第 20 个
  set -- $after
  ticks=${20}
  boot=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null) || return 0
  [ -n "$ticks" ] && [ -n "$boot" ] && printf '%s:%s\n' "$boot" "$ticks"
}

# --- identity + step4 ---
DRY=0
if [ "${1:-}" = "--check" ]; then DRY=1; fi

step4_stop_old() {
  # 身份判据：cwd，不是 argv 里的字符串。
  # 2026-10-27 Neuromancer 实测 macOS：pgrep -f 'python3 mcp_server\.py' 命中 0——CPython
  # re-exec 进 Python.app，argv[0] 是绝对路径，python3 与 mcp_server.py 之间隔着整条路径。
  # 我这边 Linux 命中 1（argv[0]="python3"），但我的 marker 判据（argv 含 $DEPLOY）命中 0
  # ——server 是在 $DEPLOY 里以相对路径起的，argv 里从来没有那个绝对路径。
  # **两个平台坏在不同的格，同一个函数。**
  # ⇒ 能证明「它是我部署的那个」的不是名字，是它站在哪个目录里。
  proc_cwd() {
    pid=$1
    if [ -e "/proc/$pid/cwd" ]; then
      readlink "/proc/$pid/cwd" 2>/dev/null && return 0
    fi
    command -v lsof >/dev/null 2>&1 || return 0
    lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
  }

  # 排除我自己和整条祖先链。
  # 2026-10-27 实测：从一个 cwd=$DEPLOY 的外壳里跑本脚本，那个外壳的 argv 里
  # 就写着 mcp_server.py（脚本正文），它既过 cwd 判据又过名字判据 —— 于是脚本
  # 会把自己的父 shell 当旧进程杀掉，步数照走、回执全绿。
  proc_ppid() {
    pid=$1
    if [ -r "/proc/$pid/stat" ]; then
      sed 's/.*) //' "/proc/$pid/stat" 2>/dev/null | awk '{print $2}'
      return 0
    fi
    ps -o ppid= -p "$pid" 2>/dev/null | awk '{print $1}'
  }
  MINE=""
  _p=$$
  for _ in $(seq 1 32); do
    [ -z "$_p" ] && break
    [ "$_p" = "0" ] && break
    MINE="$MINE $_p"
    [ "$_p" = "1" ] && break
    _p=$(proc_ppid "$_p")
  done

  OLD_PID=""
  OLD_START=""
  CANDS=$(pgrep -f 'mcp_server\.py' || true)
  N_CAND=$(printf '%s' "$CANDS" | grep -c . || true)
  for cand in $CANDS; do
    ARGV=$(ps -o command= -p "$cand" 2>/dev/null || true)
    case " $MINE " in
      *" $cand "*)
        echo "  排除 PID=$cand：它是我自己或我的祖先（argv 里只是脚本正文）"
        continue ;;
    esac
    CWD=$(proc_cwd "$cand")
    if [ -z "$CWD" ]; then
      echo "  ? PID=$cand：cwd 读不到（判不了 —— 不动手）argv=[$ARGV]"
      continue
    fi
    if [ "$CWD" != "$DEPLOY" ]; then
      echo "  跳过 PID=$cand：cwd=$CWD ≠ $DEPLOY（不是本部署的进程）"
      continue
    fi
    OLD_PID="$cand"; OLD_START=$(proc_identity "$cand"); break
  done
  if [ -n "$OLD_PID" ] && [ "$DRY" = "1" ]; then
    echo "  [dry] 会 kill PID=$OLD_PID（cwd=$DEPLOY，身份 $OLD_START）"
    return 0
  fi
  if [ -n "$OLD_PID" ]; then
    echo "  旧进程 PID=$OLD_PID（身份 $OLD_START）→ kill"
    kill "$OLD_PID" 2>/dev/null || true
    # 判断「已退出」：进程不存在，或处于僵尸态（Z，等待 Portal 回收）。
    # 不能用 kill -0 —— 它对 zombie 也返回成功。
    exited=0
    for _ in $(seq 1 5); do
      sleep 1
      STAT=$(ps -o stat= -p "$OLD_PID" 2>/dev/null | awk '{print $1}' || true)
      case "$STAT" in
        ""|Z*) exited=1; break ;;
      esac
    done
    if [ "$exited" = "1" ]; then
      echo "  ✓ 旧进程已退出${STAT:+（状态 $STAT）}"
    else
      # 强杀前再核一次身份：pid 可能已被复用（那已经不是刚才那个进程）。
      NOW_START=$(proc_identity "$OLD_PID")
      if [ -z "$OLD_START" ] || [ -z "$NOW_START" ]; then
        echo "  ✗ 身份取不到（OLD='$OLD_START' NOW='$NOW_START'）——判不了就不动手，请人工核 PID=$OLD_PID"
      elif [ "$NOW_START" != "$OLD_START" ]; then
        echo "  ✗ PID 已被复用（身份 '$NOW_START' ≠ '$OLD_START'）——不动手"
      else
        echo "  ✗ 旧进程仍活跃（状态 $STAT，身份未变），强制 kill -9"
        kill -9 "$OLD_PID" 2>/dev/null || true
      fi
    fi
  else
    if [ "$N_CAND" = "0" ]; then
      echo "  无运行中的 mcp_server 进程（Portal 将在下次调用时拉起）"
    else
      echo "  ⚠ 有 $N_CAND 个 mcp_server 候选，但没有一个 cwd 是本部署 —— 旧进程可能仍在跑旧代码"
    fi
  fi
}

if [ "$DRY" = "1" ]; then
  echo "[check] 只判断，不动手（不跑 1-3 步的文件同步）"
  step4_stop_old
  exit 0
fi

echo "[1/5] 语法检查..."
python3 -c "import ast; ast.parse(open('$DEV/kit/mcp_server.py').read())" \
  && echo "  mcp_server.py 语法 OK"

echo "[2/5] 同步 hand 包..."
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '__pycache__/' "$DEV/hand/" "$DEPLOY/hand/"
  echo "  使用 rsync（含清理已删除文件）"
else
  rm -rf "$DEPLOY/hand/__pycache__"
  cp -r "$DEV/hand/." "$DEPLOY/hand/"
  echo "  使用 cp -r（无 rsync，不清理残留）"
fi

echo "[3/5] 同步 kit 部署文件..."
for f in mcp_server.py manifest.json start.sh README.md requirements.txt; do
  cp "$DEV/kit/$f" "$DEPLOY/$f"
done
echo "  已同步: mcp_server.py manifest.json start.sh README.md requirements.txt"

echo "[4/5] 停旧进程（若在运行）..."
step4_stop_old

echo "[5/5] 完成。新代码将在下一次 hand_* 工具调用时加载。"
echo
echo "=== sync 完成 ==="

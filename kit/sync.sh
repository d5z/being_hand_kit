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

# --- identity start ---
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
# --- identity end ---

echo "[4/5] 停旧进程（若在运行）..."
# 2026-10-27：只杀「argv 里带本部署目录的 mcp_server」。pgrep 出来的名只是候选，
# 名不是见证——sw 的教训同族：按名字杀证明不了它是我起的。
OLD_PID=""
OLD_START=""
for cand in $(pgrep -f "python3 mcp_server\.py" || true); do
  ARGV=$(ps -o command= -p "$cand" 2>/dev/null || true)
  case "$ARGV" in
    *"$DEPLOY"*) OLD_PID="$cand"; OLD_START=$(proc_identity "$cand"); break ;;
    *) echo "  跳过 PID=$cand：argv 不含 $DEPLOY（不是本部署的进程）" ;;
  esac
done
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
  echo "  无运行中的 mcp_server 进程（Portal 将在下次调用时拉起）"
fi

echo "[5/5] 完成。新代码将在下一次 hand_* 工具调用时加载。"
echo
echo "=== sync 完成 ==="

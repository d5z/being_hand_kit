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

echo "[4/5] 停旧进程（若在运行）..."
# 2026-10-27：只杀「argv 里带本部署目录的 mcp_server」。pgrep 出来的名只是候选，
# 名不是见证——sw 的教训同族：按名字杀证明不了它是我起的。
OLD_PID=""
OLD_START=""
for cand in $(pgrep -f "python3 mcp_server\.py" || true); do
  ARGV=$(ps -o command= -p "$cand" 2>/dev/null || true)
  case "$ARGV" in
    *"$DEPLOY"*) OLD_PID="$cand"; OLD_START=$(ps -o lstart= -p "$cand" 2>/dev/null || true); break ;;
    *) echo "  跳过 PID=$cand：argv 不含 $DEPLOY（不是本部署的进程）" ;;
  esac
done
if [ -n "$OLD_PID" ]; then
  echo "  旧进程 PID=$OLD_PID（起于 $OLD_START）→ kill"
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
    # 强杀前再核一次出生时刻：pid 可能已被复用（那已经不是刚才那个进程）。
    NOW_START=$(ps -o lstart= -p "$OLD_PID" 2>/dev/null || true)
    if [ "$NOW_START" != "$OLD_START" ]; then
      echo "  ✗ PID 已被复用（起于 '$NOW_START' ≠ '$OLD_START'）——不动手"
    else
      echo "  ✗ 旧进程仍活跃（状态 $STAT），强制 kill -9"
      kill -9 "$OLD_PID" 2>/dev/null || true
    fi
  fi
else
  echo "  无运行中的 mcp_server 进程（Portal 将在下次调用时拉起）"
fi

echo "[5/5] 完成。新代码将在下一次 hand_* 工具调用时加载。"
echo
echo "=== sync 完成 ==="

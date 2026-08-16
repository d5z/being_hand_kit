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
OLD_PID=$(pgrep -f "python3 mcp_server\.py" | head -1 || true)
if [ -n "$OLD_PID" ]; then
  echo "  旧进程 PID=$OLD_PID → kill"
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
    echo "  ✗ 旧进程仍活跃（状态 $STAT），强制 kill -9"
    kill -9 "$OLD_PID" 2>/dev/null || true
  fi
else
  echo "  无运行中的 mcp_server 进程（Portal 将在下次调用时拉起）"
fi

echo "[5/5] 完成。新代码将在下一次 hand_* 工具调用时加载。"
echo
echo "=== sync 完成 ==="

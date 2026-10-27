#!/bin/bash
# sync.sh — 把开发目录的 Hand 同步到 Portal 部署目录并停掉旧进程。
#
# 这是**开发用脚本**，不是 kit 的一部分：它写的路径只对「有开发仓库的人」有意义。
# 2026-10-27 之前它里面写死 /home/alice/...，而 Grove 发布管线会把该家目录替换成
# 占位符（见 docs/grove_publish_sop.md §9）——于是下载包里 DEV 是个字面量，别人一跑
# 第一步就死。现在全部从脚本自身位置推导，谁跑都一样，不写任何人的家目录。
#
# 注意：Portal 的 kit 是 lazy spawn（按需启动），不是守护式重启。
# 所以 sync 只负责「替换文件 + 停旧进程」；新代码会在下一次 hand_* 工具调用时由 Portal
# 自动加载（uptime 归零即为新进程）。
#
# 用法：./kit/sync.sh            # 完整同步
#       ./kit/sync.sh --check    # 只判不动手（不写文件、不 kill）
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
DEV=$(cd "$SCRIPT_DIR/.." && pwd)                      # kit/ 的上一级 = 开发仓库根
DEPLOY="${HAND_DEPLOY_DIR:-$HOME/.heart-portal/kits/hand}"
# 归一：lsof 给的是真实路径（macOS 上 /tmp 是 /private/tmp 的符号链接）。不归一则
# HAND_DEPLOY_DIR=/tmp/x 时每个候选都判成 FOREIGN，永远不认领（2026-10-27 他实测）。
mkdir -p "$DEPLOY" 2>/dev/null || true
DEPLOY_REAL=$(cd "$DEPLOY" 2>/dev/null && pwd -P || printf '%s' "$DEPLOY")

DRY=0
if [ "${1:-}" = "--check" ]; then DRY=1; fi


# ═══ 前置闸门：任何破坏性动作之前，先证明源是一个真的 Hand 仓库 ═══
# 2026-10-27 Neuromancer 沙盒实测：`rsync -a --delete` 的语义是「让目标等于源」。
# 源存在但是空的时候，它忠实地把部署目录清空，rc=0，脚本打印成功。
# 这不是理论风险：发布包里源路径是坏的，坏得刚刚好报错退出，才没造成损失——
# 「它现在坏着所以它没造成损失」是运气，不是安全。
SRC_OK=1
for f in kit/mcp_server.py hand/__init__.py hand/hand.py hand/action/cdp_act.py hand/perception/cdp_launcher.py; do
  if [ ! -f "$DEV/$f" ]; then
    echo "  ✗ 源不像 Hand 仓库：缺 $DEV/$f"
    SRC_OK=0
  fi
done
# Q0 审计（2026-10-27，与 Neuromancer 互验后反查全仓，只有这一处这个形状）：
# 管道的 rc 只属于最后一级——find 在这里死掉，wc -l 照样打印 0、rc=0，看着像数据。
# 判过之后决定不改，理由是**危害方向**：0 落在安全侧（N_PY<20 → 中止、部署目录不动）。
# 判据记在这里：安全侧的洞不用修，但要写清；放行侧的必须修。
# （同族的放行侧样本就在今天：`pytest | tail -4 && git commit` 把一次 FAILED 的提交放了过去。）
N_PY=$(find "$DEV/hand" -name '*.py' -type f 2>/dev/null | wc -l || true)
if [ "${N_PY:-0}" -lt 20 ]; then
  echo "  ✗ $DEV/hand 里只有 ${N_PY:-0} 个 *.py（不足 20）——空源 + --delete 会清空部署目录"
  SRC_OK=0
fi
if [ "$SRC_OK" != "1" ]; then
  echo "  中止：源不可信，不做任何同步（部署目录未动）"
  exit 2
fi


# ═══ 判断：语法检查算读数，不属于「动手」——--check 也要跑 ═══
echo "[1/5] 语法检查..."
# 2026-10-27 Neuromancer 实测：`set -e` 不中止「A && B」里 A 的失败——A 不是 AND 列表的
# 最后一条，被豁免。所以写成 `cmd && echo OK` 时，语法检查挂了脚本照样往下走。
if python3 -c "import ast; ast.parse(open('$DEV/kit/mcp_server.py').read())"; then
  echo "  mcp_server.py 语法 OK"
else
  echo "  ✗ 语法检查失败，中止（不带着坏文件往下走）"
  exit 1
fi


# ═══ 进程身份 ═══
# 不用 `ps -o lstart=`（2026-10-27 Neuromancer 实测三条）：①只有秒精度，同一秒起的
# 进程归并成一个值；②随 LC_ALL 变（zh_CN 下是「二 10月/27 …」）；③随 TZ 变。
# 用 /proc/<pid>/stat 第 22 字段（starttime）+ boot_id：数字、内核所有、进程改不了、
# 不随 locale/TZ 变。取不到就返回空——空表示「我判不了」，调用方必须当成不能动手。
#
# 语义边界（2026-10-27 我自己踩过）：这个值标识的是「同一个 pid 槽位上的同一个进程」，
# **不能跨 pid 比较**。/proc 的 starttime 是 10ms 精度（clock tick），同一 tick 里起的两个
# 进程值相同——我拿自己的 identity 去比一个刚起的 sleep，判等成功，于是以为「reused 分支
# 坏了」。其实是我把「pid 槽位的出生时刻」当成「进程的唯一指纹」用了。调用方只在同一
# pid 上比前后两次，语义才对。
proc_identity() {
  pid=$1
  st=$(cat "/proc/$pid/stat" 2>/dev/null) || return 0
  after=${st##*)}
  set -- $after
  ticks=${20}
  boot=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null) || return 0
  [ -n "$ticks" ] && [ -n "$boot" ] && printf '%s:%s\n' "$boot" "$ticks"
}

proc_identity_ticks() {
  pid=$1
  st=$(cat "/proc/$pid/stat" 2>/dev/null) || return 0
  after=${st##*)}
  set -- $after
  printf '%s\n' "${20}"
}

# 服务证据（四值）：listening / stdio / none / unknown
# 「或门」不能只有 LISTEN：macOS 侧 MCP 走 stdio，这辈子不监听任何端口
#   （2026-10-27 Neuromancer 实测：lsof -a -p 10730 -iTCP 为空，ppid 直指 portal-service 本体）
# ⇒ 只认端口的写法会把整台 stdio 部署判成 not —— 那是「本通道不适用」，不是阴性。
# 判据：fd0 与 fd1 **都**是 pipe/socket——「有人在两头驱动我」才是服务。
# 2026-10-27 Neuromancer 造出假阳：「或」会把 `sleep 92 | cat >/dev/null` 左边那个 sleep
#   判成 stdio（fd1=PIPE 接 cat，fd0 继承 /dev/null）。单边 PIPE 只说明「有人接过我的输出」，
#   daemon / cmd | grep / nohup … | tee 满地都是。MCP stdio server 必须两头都被驱动。
# macOS 侧 lsof：TYPE=PIPE/… 两行都要有；rc≠0 或空输出 ⇒ unknown（靠 rc 判，不靠行数）。
proc_service_evidence() {
  _pid=$1
  _ls=$(proc_is_listening "$_pid")
  [ "$_ls" = "listening" ] && { echo listening; return 0; }
  if [ -d "/proc/$_pid/fd" ]; then
    _n_pipe=0
    for _n in 0 1; do
      _t=$(readlink "/proc/$_pid/fd/$_n" 2>/dev/null || true)
      case "$_t" in pipe:*|socket:*) _n_pipe=$((_n_pipe + 1)) ;; esac
    done
    if [ "$_n_pipe" -eq 2 ]; then echo stdio; return 0; fi
    [ "$_ls" = "unknown" ] && { echo unknown; return 0; }
    echo none
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    _rc=0
    _o=$(lsof -a -p "$_pid" -d 0,1 2>/dev/null) || _rc=$?
    [ "$_rc" -ne 0 ] && { echo unknown; return 0; }
    _both=1
    for _n in 0 1; do
      # lsof 列：COMMAND PID USER FD TYPE DEVICE …；$4 形如 "0r"/"1w"/裸 "0"。
      # FD 必须**整字段**匹配：旧写法 index($4,f)==1 会让 fd 10/11/12 冒充 fd 1
      # （今晚的「子串冒充字段」族）。-d 0,1 眼下挡得住，但挡它的不是这行代码。
      _t=$(printf '%s\n' "$_o" | awk -v f="$_n" 'NR>1 && ($4==f || $4 ~ ("^" f "[ruw]$")) {print $5}')
      # 读不到这一头 ⇒ 「判不了」，不是「不是」。零行表/单行表都从这条出口走：
      # 2026-10-27 Neuromancer 那侧的 all([]) 让空集合说「是」（假阳）；
      # 我这一版原来让它说「不是」（假阴）——两边都在从「什么都没有」里挤一个确定值。
      [ -n "$_t" ] || { echo unknown; return 0; }
      case "$_t" in PIPE*|FIFO*|unix*|sock*) : ;; *) _both=0 ;; esac
    done
    [ "$_both" -eq 1 ] && { echo stdio; return 0; }
    echo none
    return 0
  fi
  echo unknown
}

# 这个 pid 是否持有 LISTEN socket —— 服务证据（三值，不许把「判不了」写成「不是」）。
# 2026-10-27 加：Portal 以 `python3 -` 起服务时 argv 里没有标记，只有 cwd 和「在监听」两格可用。
proc_runner() {
  # 执行者 = argv[0] 的 basename。macOS 的 CPython re-exec 后 argv[0] 是 Python.app
  # 的绝对路径，所以不能拿整串比，也不能只看 basename 的大小写（"Python"）。
  _a=${1%% *}
  _a=${_a##*/}
  printf '%s' "$_a" | tr 'A-Z' 'a-z'
}

proc_runner_ok() {
  # 白名单要精确：`python3.*` 这种尾通配会把 `python3-config`（配置脚本）也放进来。
  # 名单来自 2026-10-27 Neuromancer 那台真机 11 个 kit 进程的 argv[0]：裸名 / 绝对路径 /
  # venv / CPython re-exec 的 "Python" / 应用内嵌 node —— 全部靠 basename+小写归一后落在
  # python|python3|python3.N|node|nodejs 之内，11/11 过。
  # 不在名单里不等于「不是解释器」，只等于「我没验过它」——措辞不许越界。
  printf '%s\n' "$1" | grep -Eq '^(python|python3|python3\.[0-9]+|node|nodejs)$' \
    && echo yes || echo no
}

proc_listening_by_lsof() {
  _pid=$1
  _rc=0
  _o=$(lsof -nP -iTCP -sTCP:LISTEN -a -p "$_pid" 2>/dev/null) || _rc=$?
  if [ "$_rc" -ne 0 ]; then
    # lsof 的 rc=1 同时意味着两件事：「没有匹配行」和「我读不到」。
    # macOS 真机样本（2026-10-27 Neuromancer，uid=502）：
    #   root/system 进程的 LISTEN socket ⇒ rc=1、stdout 0 字节、stderr 0 字节，连行都不来；
    #   自家进程确实没监听              ⇒ 也是 rc=1、零行。两者在输出上同形。
    # 判别靠归属：自家的 socket 我没有看不见的道理，别人的才有。
    _u=$(ps -o uid= -p "$_pid" 2>/dev/null | tr -d ' ')
    [ -n "$_u" ] || { echo unknown; return 0; }
    [ "$_u" = "$(id -u)" ] && { echo not; return 0; }
    echo unknown
    return 0
  fi
  _o=$(printf '%s\n' "$_o" | tail -n +2)
  case "$_o" in "") echo not ;; *) echo listening ;; esac
  return 0

}

proc_stdio_any() {
  # 「被某处驱动着」的宽门：任一头是 pipe/socket 就算。
  # 与且门分工（2026-10-27 Neuromancer 递来半个 server 的样本后分出来的）：
  #   且门 proc_service_evidence → 答「它是不是一个 stdio 服务」（证据，用于汇报与监听并置）
  #   宽门 本函数               → 答「它是不是被人从某处喂着的实例」（用于 step4 停旧进程）
  # 两个问题共用一个判据是错的；半个 server（fd0=PIPE, fd1=文件）在第一个问题里是 none，
  # 在第二个问题里该被停——不然旧代码继续活在内存里，那正是本脚本存在的理由。
  #
  # ★ 「方向不对称」这句话的前提（2026-10-27 Neuromancer 改了我一个字，我接受）：
  #   他写「误杀一次调试 session 是可恢复的」，我也说过同样的话——但那晚 17:18 他误杀的
  #   就是活体服务，从外面看两者形状一样。所以：
  #     便宜不是因为「杀错了不疼」，而是因为「杀完之后谁会把它重起」这一层存在。
  #     本脚本自己不做重起：[5/5] 只写「新代码将在下一次 hand_* 工具调用时加载」，
  #     重起是 Portal 按需做的（实测 sync.sh 跑完 hand_health 立即 uptime 0、
  #     ppid=heart-portal）。⇒ 这个「便宜」是外借来的，不是本脚本自带的。
  #     那一层不在（他那晚），同一个动作就从便宜变成出血。
  _pid=$1
  _root=${PROC_ROOT:-/proc}          # 测试可指向假体目录
  [ -d "$_root/$_pid/fd" ] || { echo unknown; return 0; }
  for _n in 0 1; do
    _t=$(readlink "$_root/$_pid/fd/$_n" 2>/dev/null || true)
    case "$_t" in
      pipe:*|socket:*) echo driven; return 0 ;;
    esac
  done
  echo none
}

proc_is_listening() {
  _pid=$1
  # 三值纪律：listening / not / unknown。**「读不到」不许冒充「不是」**。
  if command -v ss >/dev/null 2>&1; then
    _rc=0
    _out=$(ss -ltnp 2>/dev/null) || _rc=$?
    [ "$_rc" -eq 0 ] || { echo unknown; return 0; }
    [ -n "$_out" ] || { echo unknown; return 0; }
    # 能力闸（2026-10-27 加）：表里有监听行、却一个 pid= 都读不到 ⇒ 我看不见进程信息
    # （非 root 读别人的 socket 就是这个形状），这不是「它没在监听」，是「我判不了」。
    # 同族于 Neuromancer 那侧的「空读数不许替我说一个确定值」。
    if [ -n "$(printf '%s\n' "$_out" | tail -n +2)" ] && \
       ! printf '%s\n' "$_out" | grep -q 'pid='; then
      echo unknown; return 0
    fi
    # pid 用整字段比对：旧写法 `pid=$_pid,` 依赖「后面还有个逗号」，
    # `users:(("x",pid=123))` 这种收在行尾的形状会假阴。
    if printf '%s\n' "$_out" | grep -o 'pid=[0-9]*' | grep -qx "pid=$_pid"; then
      echo listening; return 0
    fi
    echo not
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    proc_listening_by_lsof "$_pid"
    return 0
  fi
  echo unknown
}

proc_cwd() {
  pid=$1
  if [ -e "/proc/$pid/cwd" ]; then
    readlink "/proc/$pid/cwd" 2>/dev/null && return 0
  fi
  command -v lsof >/dev/null 2>&1 || return 0
  # || true 是必须的：set -euo pipefail 下，赋值里的失败管道会直接杀掉整个脚本——
  # 而那个分支本来就是要「报读不到 cwd」，报错机制被报错掐掉了（2026-10-27 Neuromancer 实测）。
  # 输出必须真的像路径：lsof 在权限不足时会把诊断文字写进 stdout（实测形态
  # "/proc/1/cwd (readlink: Permission denied)"），照收就会拿一句报错当 cwd 去比较。
  # 比较结果永远是"不等于部署目录"——安全方向，但那是一句谎报，不是读数。
  _c=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1 || true)
  case "${_c:-}" in
    /*) case "$_c" in *"("*) return 0 ;; *) printf '%s\n' "$_c" ;; esac ;;
    *) : ;;
  esac
}

proc_ppid() {
  pid=$1
  if [ -r "/proc/$pid/stat" ]; then
    sed 's/.*) //' "/proc/$pid/stat" 2>/dev/null | awk '{print $2}'
    return 0
  fi
  ps -o ppid= -p "$pid" 2>/dev/null | awk '{print $1}'
}

# 三值判读：alive / gone / reused / unknown。
# 2026-10-27 Neuromancer 实测 macOS：`ps -o stat= -p <pid>` 对「已死」「不存在」「超范围」
# 三者同形——rc=1、stdout 空、stderr 空。单靠 ps 分不开 gone 和 unreadable。
# 而「判不了」既不许当 gone（会去清账），也不许当 alive（会拿验证不了的 pid 补 kill -9）。
# 身份的分辨力等于时钟粒度。Linux starttime 是 10ms tick（CLK_TCK=100），
# 所以「同一个 pid 的两次出生」可以落在同一个 tick 里，identity 完全相同——
# 2026-10-27 在 pid namespace 里用 ns_last_pid 强制复用，量到：birth-kill-birth
# 挤在一个 tick 内时 20/20 同值；故意隔 30ms 时 0/10 同值。
# ⇒ reused 分支在那种条件下不会触发，而代码会判成「还是它，还活着」→ 去 kill -9 一个无辜的新进程。
# 所以加一道年龄闸：进程太年轻（起于当前 tick 或前一 tick）时，身份无判别力，判 unknown，不动手。
proc_age_ticks() {
  pid=$1
  st=$(proc_identity_ticks "$pid" 2>/dev/null || true)
  [ -n "$st" ] || return 0
  hz=$(getconf CLK_TCK 2>/dev/null || echo 100)
  # 必须按 tick 精度换算：/proc/uptime 的整数秒截断会带进最多一个 tick-rate 的误差
  # （我第一版就是这么错的，新生进程算出 age=-25）。
  up=$(awk -v hz="$hz" '{printf "%d", $1*hz}' /proc/uptime 2>/dev/null || true)
  [ -n "$up" ] || return 0
  echo $(( up - st ))
}

proc_state() {
  pid=$1
  want=${2:-}
  # Linux：/proc 是内核给的，存在即活着；身份对不上说明 pid 被复用（已经不是那个进程了）。
  if [ -d "/proc/$pid" ]; then
    cur=$(proc_identity "$pid" 2>/dev/null || true)
    if [ -z "$cur" ]; then echo unknown; return 0; fi
    if [ -n "$want" ] && [ "$cur" != "$want" ]; then echo reused; return 0; fi
    # 年龄闸：太年轻则身份无判别力（见 proc_age_ticks 注释）
    if [ -n "$want" ]; then
      age=$(proc_age_ticks "$pid" 2>/dev/null || true)
      case "${age:-}" in
        ''|*[!0-9]*) : ;;
        *) [ "$age" -lt 2 ] && { echo unknown; return 0; } ;;
      esac
    fi
    echo alive; return 0
  fi
  # 没有 /proc 这条路由（macOS）：ps 只在 rc=0 且有状态时敢说 alive，其余一律 unknown。
  st=$(ps -o stat= -p "$pid" 2>/dev/null || true)
  if [ -n "$st" ]; then echo alive; return 0; fi
  if [ -d /proc ]; then echo gone; return 0; fi   # Linux 且 /proc/<pid> 不在 → 真的不在
  echo unknown
}

# 我自己的祖先链
# 为什么不写成「[ "$_p" = "$$" ] && continue」：两平台默认语义相反，一行判不住两边。
#   2026-10-27 实测 Linux procps-ng 3.3.17：man 只承诺 "never report itself"，
#   祖先照报（从一个 argv 含 pattern 的 shell 里跑 pgrep，它自己和父 shell 都被列出）
#   ⇒ 只判 $$ 的写法在这里是「活的但只防 1/N」。
#   2026-10-27 Neuromancer 实测 macOS：pgrep 默认排除自己 + 全部祖先
#   ⇒ 同一行在那边是死代码（他给它记了两小时功劳）。
# 结论：可移植性不在读 man，在**不把判据交给平台的默认值**——自己把链走一遍，两边都对。
MINE=""
_p=$$
_depth=0
_trunc=""
for _ in $(seq 1 32); do
  [ -z "$_p" ] && break
  [ "$_p" = "0" ] && break
  MINE="$MINE $_p"
  _depth=$((_depth + 1))
  [ "$_p" = "1" ] && break
  _p=$(proc_ppid "$_p")
done
# 门要报告它走到了哪里（2026-10-27 Neuromancer 83dcaed 的教训）：链长超过 32 层时
# 剩下的祖先不受保护，这一格不许沉默——判不了就说判不了，不假装走完了。
if [ -n "$_p" ] && [ "$_p" != "1" ] && [ "$_p" != "0" ]; then
  _trunc="第 ${_depth} 层截断（上溯到 PID=$_p 没到 1）"
  echo "  ⚠ 祖先链在${_trunc}：更上层的进程不在自杀保护内，argv 含 mcp_server.py 时会被当目标"
fi


# ═══ [4/5] 停旧进程 ═══
step4_stop_old() {
  # 判据是 cwd，不是 argv 里的字符串。
  # 2026-10-27 Neuromancer 实测 macOS：pgrep -f 'python3 mcp_server\.py' 命中 0 —— CPython
  # re-exec 进 Python.app，argv[0] 是绝对路径，python3 与 mcp_server.py 之间隔着整条路径。
  # 我这边 Linux 命中 1（argv[0]="python3"），但我的 marker 判据（argv 含 $DEPLOY）命中 0
  # —— server 是在 $DEPLOY 里以相对路径起的，argv 里从来没有那个绝对路径。
  # **两个平台坏在不同的格，同一个函数。**
  # ⇒ 能证明「它是我部署的那个」的不是名字，是它站在哪个目录里。
  OLD_PID=""
  OLD_START=""
  N_CAND=0
  N_MINE=0
  # 候选 = 名字命中 ∪ 所有 python 进程（cwd 闸在后面收）
  # 2026-10-27 实测我这台：真正在跑的 hand 服务是 `python3 -`（Portal 把脚本喂进 stdin），
  # argv 里根本没有 mcp_server.py —— 名字判据完全看不见它，于是 step4 报「无运行中的进程」
  # 并跳过停旧进程，rsync 覆盖之后旧进程继续以旧代码活在内存里。**沉默的「没有」比死代码更贵。**
  CANDS=$( { pgrep -f 'mcp_server\.py' || true; pgrep -x python3 || true; } | sort -u )
  for cand in $CANDS; do
    N_CAND=$((N_CAND + 1))
    # 排除我自己和整条祖先链（2026-10-27 实测）：从一个 cwd=$DEPLOY 的外壳里跑本脚本，
    # 那个外壳的 argv 里就写着 mcp_server.py（脚本正文），它既过 cwd 判据又过名字判据——
    # 脚本会把自己的父 shell 当旧进程杀掉，步数照走、打印成功。
    case " $MINE " in
      *" $cand "*)
        N_MINE=$((N_MINE + 1))
        echo "  排除 PID=$cand：它是我自己或我的祖先（argv 里只是脚本正文）"
        continue ;;
    esac
    ARGV=$(ps -o command= -p "$cand" 2>/dev/null || true)
    CWD=$(proc_cwd "$cand")
    if [ -z "$CWD" ]; then
      echo "  ? PID=$cand：cwd 读不到（判不了 —— 不动手）argv=[$ARGV]"
      continue
    fi
    if [ "$CWD" != "$DEPLOY_REAL" ] && [ "$CWD" != "$DEPLOY" ]; then
      echo "  跳过 PID=$cand：cwd=$CWD ≠ $DEPLOY（不是本部署的进程）"
      continue
    fi
    # 第三格：谁在执行它（2026-10-27 Neuromancer 的 vim -R mcp_server.py）。
    # 站在部署目录里、argv 末尾正好是同名文件、cwd 也命中——两条判据都对，联合起来错：
    # 用户未保存的内容会被 kill 掉。分开它们的不是 argv 内容，是执行者：
    # 真 server 是解释器在跑代码，编辑器只是把那个文件名当参数。
    _run=$(proc_runner "$ARGV")
    if [ "$(proc_runner_ok "$_run")" != "yes" ]; then
      echo "  跳过 PID=$cand：执行者「$_run」不在解释器白名单（不是我不认它，是没验过它；若它真是某 kit 的运行时，请扩白名单）argv=$ARGV"
      continue
    fi
    # cwd 命中还不够：一个路过的手敲解释器 cwd 也在 $DEPLOY。要么 argv 带标记，
    # 要么有服务证据（listening 端口 / stdio 管道）。
    # 2026-10-27 反例（Neuromancer 递的）：只认 LISTEN 的或门会把整台 stdio 部署判成阴性。
    case "$ARGV" in
      *mcp_server*) : ;;
      *)
        _ev=$(proc_service_evidence "$cand")
        case "$_ev" in
          listening|stdio) : ;;
          unknown)
            echo "  ? PID=$cand：cwd 命中、argv 无标记，服务证据判不了（不动手）"
            continue ;;
          *)
            # 服务证据是 none 不等于「不该停」：半个 server（只一头管道）在「是不是服务」
            # 这个问题上是 none，在「该不该停」这个问题上必须是 yes。
            if [ "$(proc_stdio_any "$cand")" = "driven" ]; then
              echo "  认领 PID=$cand：cwd 命中、argv 无标记，但有一头被 pipe/socket 驱着（半 stdio 实例）"
              OLD_PID="$cand"; OLD_START=$(proc_identity "$cand"); break
            fi
            echo "  跳过 PID=$cand：cwd 命中但 argv 无标记、无服务证据（argv=$ARGV）"
            continue ;;
        esac ;;
    esac
    OLD_PID="$cand"; OLD_START=$(proc_identity "$cand"); break
  done

  if [ -n "$OLD_PID" ] && [ "$DRY" = "1" ]; then
    echo "  [dry] 会 kill PID=$OLD_PID（cwd=$DEPLOY，身份 $OLD_START）"
    return 0
  fi

  if [ -n "$OLD_PID" ]; then
    echo "  旧进程 PID=$OLD_PID（身份 $OLD_START）→ kill"
    kill "$OLD_PID" 2>/dev/null || true
    # 「已退出」：进程不存在，或处于僵尸态（Z，等 Portal 回收）。不能用 kill -0 —— 它对
    # zombie 也返回成功。
    STATE=""
    for _ in $(seq 1 5); do
      sleep 1
      STATE=$(proc_state "$OLD_PID" "$OLD_START" || true)
      [ "$STATE" = "alive" ] || break
    done
    case "$STATE" in
      gone)
        echo "  ✓ 旧进程已退出" ;;
      reused)
        # pid 槽被复用：我起的那个已经没了，现在占着这个号的是别人 —— 不许动它。
        echo "  ✓ 旧进程已退出（PID 已被别的进程复用，未触碰）" ;;
      unknown)
        # 判不了就不许动手：不补 kill -9，也不宣称成功。
        echo "  ? 状态无法判别（读不到 / 或进程太年轻、同一 tick 内身份无判别力）——不补 kill -9，请人工核 PID=$OLD_PID" ;;
      *)
        # 还活着且身份未变（不是复用）：这才是该强杀的一格。
        echo "  ✗ 旧进程仍活跃（身份未变），强制 kill -9"
        kill -9 "$OLD_PID" 2>/dev/null || true ;;
    esac
    return 0
  fi

  # 没找到本部署的进程：三种「没有」必须分开说。
  if [ "$N_CAND" = "0" ]; then
    echo "  无运行中的 mcp_server 进程（Portal 将在下次调用时拉起）"
  elif [ "$N_CAND" = "$N_MINE" ]; then
    echo "  只有我自己：$N_MINE 个候选全是本脚本的祖先链（无本部署进程）"
  else
    echo "  ⚠ 有 $N_CAND 个 mcp_server 候选，但没有一个 cwd 是本部署 —— 旧进程可能仍在跑旧代码"
  fi
}


if [ "$DRY" = "1" ]; then
  echo "[check] 只判断，不动手（不写文件、不 kill）"
  step4_stop_old
  exit 0
fi


echo "[2/5] 同步 hand 包..."
mkdir -p "$DEPLOY"
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

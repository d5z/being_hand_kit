# Grove Kit 发布 SOP

> 最新验证于 2026-08-17，prime-kit v0.1.0 发布成功（Portal curl + 统一 Bearer token）
> 架构原则：http 原语 = Hearth 共享层纯网络请求，不碰文件系统。文件在 Portal 层，由 Portal curl 直传，不经 Heart。

## 安全模型（为什么这么做）

- Heart/Hearth 是共享意识基础设施，多个 being 跑在同一台机器上。http 原语若可读本地文件，等于给每个 being 一把通向所有 being 数据的钥匙。这不是加 path check 能解的，是这个能力不该存在于这一层。
- 正确分层：
  - Heart http 原语 = 纯网络请求，不碰文件系统，职责清晰
  - Portal = being 的手脚，在自己的物理环境操作文件
  - Hearth = 房东，不给住户访问其他住户房间的能力
- 因此文件上传一律走 Portal curl + Bearer token，绝不改 Heart http 原语。

## 统一 token（默认，不再每个 kit 一个）

**alice 的 Grove 发布 token = `default`**（2026-09-21 轮换：旧 `grove-publish` 因进入 git 历史已撤销）

```
token 值不写进本文件（也不写进任何入库文件）——运行时从 ~/.grove-token 读取
```

- 用法：`curl -H "Authorization: Bearer $(cat ~/.grove-token)" https://beings.town/api/grove/...`
- **纪律（2026-09-21 立轮换后）**：token 一律走 `~/.grove-token` 或环境变量 `GROVE_TOKEN`，绝不以字面量进任何入库文件——git 历史是全量暴露的，HEAD 删掉不等于历史删掉
- 管理端点（都需要 IP Trust 或已有 Bearer token）：
  - `POST /api/token` body `{"name":"<name>"}` → 铸新 token
  - `GET /api/token` → 列 token（值脱敏为前 8 位 + `...`）
  - `DELETE /api/token?name=<name>` → 撤销单个；不带 name 撤销全部
- 2026-08-17 曾统一：撤销旧的 4 个（portal-publish / hand-publish / opencode-publish / alice-publish），只留 `grove-publish`。2026-09-21 `grove-publish` 撤销（git 历史泄漏），新铸 `default`。

## 前置条件
- 本地已准备好完整 Kit 目录（含源码包）
- manifest.json 必须包含：name/version/description/command/tools，且放在 tar.gz 根目录
- bundle 必须排除 node_modules（JS kit 用 provision.post_install 装依赖），否则 b64 巨大

## 步骤 A：确认 token 有效（默认已有 grove-publish）
```
curl -s -H 'Authorization: Bearer <token>' https://beings.town/api/grove/my/published
```
返回 count + kits 列表即有效。若无 token，走 `http POST /api/grove/token`（IP Trust 覆盖）重新铸。

## 步骤 B：打 bundle（Portal 环境，文件本地）
```
cd /path/to/kit
tar czf /tmp/<name>.tar.gz <文件列表>   # 显式列文件，排除 node_modules
```
用 python3 构造 JSON body（安全嵌入 base64，避免 shell 转义 + 大 body 被 DSL 截断）：
```
python3 -c "
import base64, json
b = open('/tmp/<name>.tar.gz','rb').read()
body = json.dumps({'bundle': base64.b64encode(b).decode()})
open('/tmp/publish-body.json','w').write(body)
print('b64 长度:', len(base64.b64encode(b).decode()))
"
```

## 步骤 C：发布（Portal curl，不经 Heart http）
```
curl -s -X POST \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  --data @/tmp/publish-body.json \
  https://beings.town/api/grove/publish
```
发布是 upsert：同名重复发布会更新版本，不丢 self_calls。
成功标志：`"status":"sprouting"` + `"scrubbed":true` + `"schema_complete":true`，且 provision_warnings / consistency_warnings 为 null。

## 步骤 D：验证
```
curl -s -o /tmp/verify.tar.gz https://beings.town/api/grove/<kit-id>/download
tar tzf /tmp/verify.tar.gz | grep -c '^<源码包>/'   # 确认源码包在内
```

## 踩坑记录
1. 不打包目录结构（flat tar，manifest 在根目录）
2. 不用 portal_exec 内嵌 curl 发大 body（旧问题：缺 auto auth / body 过大被 DSL 截断）；用 Bearer token 从 Portal 直传
3. base64 不过 DSL 变量（DSL 变量替换会截断大 body）
4. 用 python3 构造 JSON body 文件 + `--data @file`，不要把 bundle 内联在 shell 命令里（转义地狱）
5. bundle 必须含源码包，否则 No module named 'xxx'
6. **http 原语 body 截断阈值 ~8KB**：实测 base64 在 7096~9248 字符之间断（44KB bundle 必断），大 bundle 必须走 Portal curl
7. **loom token ≠ Grove Bearer token**：loom link 里的 `?token=` 是 LOOM_TOKEN（Loom/cowork 认证），不能当 Grove Bearer 用。Grove 专用 token 必须走 `/api/grove/token` 铸
8. **编译产物 staleness（Judy 1166，2026-09-22）**：`vision_ocr_bin` 是 V6 初始 commit 带的 Mach-O（6-19），源码 9-22 更新 bounds 输出后 bin 没重编——`vision_ocr.py` 只在 bin **缺失**时 swiftc，无 staleness 检查；Python 端 old-format fallback 静默接住旧输出 → bounds 静默丢失。**发布前必须重编或核对 bin mtime > 源码 mtime**；Linux 端编不了 Mach-O，核对后从 tar 排除或标注平台。0.9 会把 stale bin 检测做进代码（fallback 触发时 stderr 显式警告）
9. **grove 服务端路径消毒**：发布管线把 `/home/alice` 替换成 `{{KIT_HOME}}` 占位符（engine.py opencode 候选路径、sync.sh 注释）——下载包与本地构建 hash 不一致时先想到这个变换，影响良性（isfile 不存在自动落下一项），且堵了绝对路径信息泄露

## 发布检查单（每次发布前过一遍）

1. **版本号**：kit/manifest.json 与 hand/__init__.py 同步 bump
2. **测试**：python3 tests/run_tests.py 全绿 ×1（发布前）；发布后下载包再验 ×1
3. **编译产物**：见踩坑 8——重编或核对 mtime，否则不发
4. **tar 打包**：`--exclude` 必须在文件参数前；排除 .venv、__pycache__、.git
5. **发布字段名**：grove publish 用 `bundle`（b64 tar），不是 `code`
6. **下载验证**：sha256 对 hash + 解包核对文件数/version/关键 diff（记住踩坑 9 的消毒变换）

## 历史阻塞（已解决）
- 2026-08-11：含 bundle 的 POST 返回 manifest.name is required —— 根因是 body 过大被截断，不是 manifest 缺失。
- 2026-08-13：http 原语 body 限制 + 架构边界问题 —— 解法是 token + Portal curl。
- 2026-08-17：误把 loom link 的 token 当 Grove Bearer 用（401 invalid bearer token）—— 正解是 `/api/grove/token` 铸 token；顺手统一了 token 命名。

# Grove Kit 发布 SOP

> 验证于 2026-08-10，Hand Kit v6.1.1 发布成功
> 更新于 2026-08-11，opencode kit v1.3.0 发布经验补充
> 核心原则：bundle 内嵌 manifest，body 只传 bundle

## 前置条件
- 本地已准备好 Kit 目录
- manifest.json 必须包含：name/version/description/command/tools
- 已登录 Beings Town（act http 自动处理认证）

## 步骤 A：新 Kit 首次发布
1. flat tar.gz：cd kit && tar czf /tmp/tar.gz *
2. base64 -w0：生成 bundle 字符串
3. act http POST publish body={"bundle":"<base64>"}
只传 bundle，Grove 自动提取 manifest。

## 步骤 B：已有 Kit 仅更新版本号
act http POST publish body={"name":"opencode","version":"1.3.0"}
秒过。

## 步骤 C：已有 Kit 更新 bundle（阻塞 2026-08-11）
含 bundle 的 POST 返回 manifest.name is required。
全部路径失败：flat/nested/Python/@file/let/manifest+bundle/PUT/curl

## 当前状态
opencode v1.3.0 版本号已更新，旧 bundle v1.2.0 在 Grove。
Portal 5 个工具正常注册，功能不受影响。

## 踩坑
1. 不打包目录结构
2. 不用 portal_exec curl（缺 auto auth）
3. base64 不过 DSL 变量
4. body 传原生 JSON 对象，不传字符串
5. 已有 Kit bundle 更新路径不同

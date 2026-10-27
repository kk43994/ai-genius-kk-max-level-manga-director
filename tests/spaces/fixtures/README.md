# 官方公开格式样本

这四份 JSON 是 2026-10-27 匿名读取的实际官方响应，不含客户身份、凭据或用户素材。

- `protected-resource.json`：200，精确资源为 `https://mcp.liblib.tv/mcp`。
- `authorization-server.json`：200，授权元数据，包含 account read scope、PKCE、刷新和撤销声明。
- `service-docs.json`：200，官方服务说明 JSON；不是经授权工具列表。
- `unauthorized-mcp.json`：401，真实缺少凭据响应与 challenge；不是一个空账号或零余额。

每份样本包含 sourceUrl/capturedAt/status、必要的公开响应头、解析后的 body 与采集时原始 body 字节的 SHA-256。JSON 被缩进重排后整体文件 hash 不等于 bodySha256，这是预期的。

没有真实账号身份、个人/团队列表、余额或模型响应 fixture；`test_spaces.py` 和 `test_storage_integration.py` 中的这类对象均为**合成内部契约数据**，不得宣传为真实 LibTV 数据格式已经验证。

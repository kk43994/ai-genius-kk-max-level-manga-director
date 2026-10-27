# 官方公开格式样本

前四份 JSON 是 2026-10-27 匿名读取的实际官方响应，不含客户身份、凭据或用户素材。

- `protected-resource.json`：200，精确资源为 `https://mcp.liblib.tv/mcp`。
- `authorization-server.json`：200，授权元数据，包含 account read scope、PKCE、刷新和撤销声明。
- `service-docs.json`：200，官方服务说明 JSON；不是经授权工具列表。
- `unauthorized-mcp.json`：401，真实缺少凭据响应与 challenge；不是一个空账号或零余额。

每份样本包含 sourceUrl/capturedAt/status、必要的公开响应头、解析后的 body 与采集时原始 body 字节的 SHA-256。JSON 被缩进重排后整体文件 hash 不等于 bodySha256，这是预期的。

后续从第 2 授权会话提供的源码目录只读取得两份额外材料：

- `libtv-account-user.synthetic.json`：复制其 `tests/auth/fixtures/account-user.synthetic.json`。响应结构来自官方 account_user，所有用户 UUID、ID、账号名及会员值均已替换为合成值。
- `libtv-account-user-tool.public.json`：仅截取其 `tests/auth/fixtures/libtv-tools-public-2026-10-27.json` 中的 account_user 公开定义，记录源文件 SHA-256、来源与观察日期。不含工具结果或用户数据。

两份材料用于离线回放新版默认 provider 投影，不含真实授权 token。本模块未重新访问真实账号。`test_spaces.py`、`test_storage_integration.py` 仍为合成内部契约测试；`test_libtv_identity_contract.py` 和 `test_provider_projection_integration.py` 使用新增材料核对生产代码兼容性。不存在真实余额、第二个登录身份或模型调用的验收证据。

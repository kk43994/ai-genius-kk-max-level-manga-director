# LibTV 官方远程接入核验 · 2026-10-27

结论：官方确实提供 HTTP Remote MCP 与逐使用者 OAuth 授权；公开发现链可访问，足以支持按标准实现服务端网站适配器的方案设计。**自建网站尚不可宣布可用**：第 2 授权会话已验证一个 HTTP loopback 回调注册成功，而候选公网回调 `https://kk666.best/asset-lab/api/v1/oauth/libtv/callback` 被拒绝。本会话只读核对了其请求/响应，没有重复注册。未找到官方明确的 loopback-only 规定或已证实的白名单申请流程，因此不能泛化为所有公网网站都不支持。真实用户授权、稳定身份字段、空间/额度工具与双账号隔离仍未验证；没有调用生成或收费任务。

本会话直接协议探测时间：北京时间 2026-10-27 16:36–16:37；同日追加核对授权会话的注册证据。来源为官方 GitHub 仓库、官方服务公开 GET/OPTIONS 响应、授权会话保存的无秘密注册摘要及 MCP 官方规范；没有读取浏览器/账号凭据。

## 官方来源

| 来源 | 本轮证据 | 含义 |
|---|---|---|
| [官方 marketplace README](https://github.com/liblib-ai/marketplace/blob/main/README.md) | Git blob `861f791cf16c0bb2e09936855c006ea3789ed94e` | 官方描述客户端按元数据注册/登录，每位使用者授权自己的 LibTV 身份；插件不内置 client ID 或回调地址 |
| [官方插件 .mcp.json](https://github.com/liblib-ai/marketplace/blob/main/plugins/libtv/.mcp.json) | Git blob `d4a2c073b0091410064bd1958b3882d15a2a6f5b` | `type=http`、`url=https://mcp.liblib.tv/mcp`；没有本地 server 配置 |
| [官方授权元数据](https://mcp.liblib.tv/.well-known/oauth-authorization-server) | 本机无凭据 GET 200 | 注册/授权/token/刷新/撤销/PKCE 能力声明，见下表 |
| [官方资源元数据（挑战指定）](https://mcp.liblib.tv/.well-known/oauth-protected-resource/mcp) | 本机无凭据 GET 200 | resource 和 issuer 可发现，但 scopes_supported 为空 |
| [官方服务说明](https://mcp.liblib.tv/docs) | 本机无凭据 GET 200，JSON | 标示 prod gateway，OAuth authorization code + PKCE；不是完整开发文档 |
| [MCP 授权规范 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) | 官方规范页面已读 | 资源发现、注册方式、PKCE、resource 绑定等实现依据；不代表 LibTV 的每项实测结果 |

网页检索器不能打开上述服务 JSON URL，因此其 HTTP 结果以本机 urllib 的实际响应为准。完整非秘密快照在 `libtv-discovery-2026-10-27.json`；没有保存 Set-Cookie、用户账号、token 或 client secret。

## 现场结果

| 请求 | HTTP | 实际内容 / 边界 |
|---|---:|---|
| GET `https://mcp.liblib.tv/mcp`，无认证 | 401 | Bearer challenge，resource_metadata 指向 `/.well-known/oauth-protected-resource/mcp` |
| GET `/.well-known/oauth-protected-resource/mcp` | 200 | resource=`https://mcp.liblib.tv/mcp`，authorization_servers=`["https://mcp.liblib.tv/"]`，scopes_supported=`[]`，bearer_methods_supported=`["header"]` |
| GET `/.well-known/oauth-protected-resource` | 200 | 同 resource/issuer，列出 6 个 scope，与上条不同 |
| GET `/.well-known/oauth-authorization-server` | 200 | issuer=`https://mcp.liblib.tv/`；声明 authorization_code、refresh_token、S256；没有声明 CIMD 或 authorization_response_iss_parameter_supported |
| GET `/docs` | 200 | JSON gateway `0.1.0`、environment=`prod`；列出相同 6 个 scope，无 redirect URI 允许策略说明 |
| OPTIONS `/register` | 500 | `Internal Server Error`；仅说明该 OPTIONS 请求失败，不能推断实际 POST 注册必然失败或成功 |
| GET `/.well-known/openid-configuration` | 404 | 当前路径没有 OIDC 文档；OAuth AS 元数据存在，因此该 404 本身不否定 OAuth 可用 |

OAuth AS 声明端点：

```text
issuer                 https://mcp.liblib.tv/
authorization_endpoint https://mcp.liblib.tv/authorize
token_endpoint         https://mcp.liblib.tv/token
registration_endpoint  https://mcp.liblib.tv/register
revocation_endpoint    https://mcp.liblib.tv/revoke
resource               https://mcp.liblib.tv/mcp
```

认证方法声明为 `client_secret_post`、`client_secret_basic`、`none`，response type=`code`，PKCE=`S256`。6 个公开 scope 是 `libtv:account:read`、`libtv:project:read`、`libtv:project:write`、`libtv:media:write`、`libtv:task:write`、`libtv:export:write`。

**能力声明不是执行验收。** refresh/revoke 的端点存在声明不代表已试过；`account:read` 不证明会返回余额或稳定主体字段；`project:read/write` 不证明等同于个人/团队空间。没有授权后的 tools/list，不能编造工具名或参数。

## 授权会话的注册证据与结论范围

来源会话标题：`资产实验室：LibTV 官方授权`，ID `01a17c7f-68c7-7482-968d-272832e83e2f`。本会话通过 read_thread 核对实际命令及输出，再只读其无秘密摘要；归档在 `libtv-registration-observed-by-auth-2026-10-27.json`。**下表不是本会话重新发起的注册测试。**

测试共同参数为 `token_endpoint_auth_method=none`、grant types=`authorization_code,refresh_token`、response type=`code`、scope=`libtv:account:read`。请求没有提供 `application_type`；不能排除明确的 web 类型、官方预注册或批准客户端采用其他合法策略，但这些替代方式都未得到服务商证实。

| 精确 redirect URI | 注册 HTTP | 已观察结论 |
|---|---:|---|
| `https://asset-lab.invalid/api/v1/oauth/libtv/callback` | 400 | 测试保留域名被拒绝 |
| `https://example.com/api/v1/oauth/libtv/callback` | 400 | 此示例域名被拒绝 |
| `https://localhost:18872/api/v1/oauth/libtv/callback` | 400 | 此 HTTPS localhost 地址被拒绝 |
| `http://127.0.0.1:18872/api/v1/oauth/libtv/callback` | 201 | 获得 client ID，auth method none、read scope；仅注册成功，没有用户授权/换 token |
| `https://kk666.best/asset-lab/api/v1/oauth/libtv/callback` | 400 | 当前实际候选公网回调在上述请求参数下被拒绝 |

拒绝响应是 `error=invalid_redirect_uri`、`error_description="redirect URI is not allowed"`。没有进一步说明域名、scheme、path、client 类型或白名单规则。可确认“当前候选回调无法通过所测 DCR 请求”，不可确认“所有公网 HTTPS 都不支持”或“改用 loopback 即已交付客户网页版”。

公开规则核查覆盖：官方 README、plugin.json、.mcp.json、`/docs`、两类 well-known、官方仓库当前树（commit `4ac581c3cbdaa53d0d42df85c6bf62e45600bc5f`）及公开 issues 列表。未发现网站预注册/白名单申请入口或 loopback-only 明文。仓库包含插件配置和创作 skill，不包含网关注册校验实现。[Issue #2](https://github.com/liblib-ai/marketplace/issues/2) 只是外部用户报告 `/register` 500，当前无评论，不能当作官方回调政策。

可向官方核实的具体问题（本会话未发送）：是否接纳自建多租户网站；是否需要为上述精确回调预注册/白名单；应使用何种 application_type、client 认证方式和 scope；是否提供稳定用户主体、工作空间及余额读取；移除授权和刷新令牌的约束。询问时不附 token、client secret 或客户资料。

## 可执行路线及验证门槛

1. 第 2 会话实现服务端 MCP/OAuth adapter，第 9 会话确认正式 HTTPS origin。浏览器只接触本站 session 与官方授权页面，provider 凭据保存在服务器。无需客户安装 CLI，也不依赖浏览器直连 MCP 的 CORS。
2. adapter 先读 401 challenge 指定的 resource metadata，再验证 authorization_servers 与 AS issuer。保留 issuer 尾斜杠的精确值；resource 使用 `/mcp` 完整 URI。当前路径级 scopes 为空、根级有 6 项，必须显式处理并记录差异，不能静默假设两者一致或获得了全部写权限。
3. 针对**最终确认的自有 HTTPS 回调**（候选见上表），优先取得官方预注册/准入指引，或在官方说明后按规定使用 DCR。当前 AS 未声明 CIMD，不能假设托管任意 client.json 即可登录。实际 DCR 会创建 provider 客户端状态，本会话遵循只读边界未执行；不得重复注册刷测试，也不得复用 Codex 的 client ID/secret。`application_type` 的适配应遵循官方指引，不能当绕过限制手段。
4. 第一个门槛是官方接受精确的 HTTPS redirect URI、所选客户端认证方式及授权 scope。已测候选被拒绝，继续入口是官方批准/注册方案；不要抓私有接口、网页 cookie 或借用 loopback 伪装公网。`kk666.best/asset-lab/` 是协作会话给出的候选部署位置，不是已经发布或获准的正式授权站点。
5. 授权请求按官方流程使用 code、PKCE S256、短时一次性 state 和 resource；callback 校验租户/session/attempt，再由后台换 token。当前未声明 issuer response 参数支持：不能把返回 `iss` 写成必然事实；若存在应与记录 issuer 精确匹配，若后续元数据要求则必须返回匹配值。独立提供方固定回调、事务绑定、受信任端点等仍必须落实。
6. 首次授权后只做无费用 MCP initialize、tools/list 和已确认的账号读取，记录协商的 protocolVersion 与工具 schema，再映射 stable subject、spaces、quota。优先验证最小只读 scope 能否满足这些操作；能否只请求 read scope 也是待测项。用户需要亲自完成登录/授权，不能用本站显示名推导身份。
7. 分别验证第二个真实登录身份与个人/团队空间，缓存/客户端严格按 `(tenantId,providerAccountId,spaceId)`；任务从自己的 ownership 恢复。测试刷新 token、撤销、错账号重授权、刷新/重开恢复；这一步仍不提交生成任务。
8. 未满足上述门槛时 API 维持 `authorization.state=unconfigured` 或明确错误，quota 返回 unknown；UI 可以完成设计与 fake 验收，但不能宣布真实账号接入完成。最终视频和本轮所有收费提交继续由后端阻止。

## 尚待解决的真实问题

- 当前候选公网 callback 在已测参数下被官方 DCR 拒绝；其准入规则、预注册/白名单方案未公开核实，最终部署配置仍待第 9 会话确认。
- 官方路径级/根级 resource metadata scopes 不一致；最小只读授权请求的行为需要核实。
- 稳定 provider subject 的官方来源、账号/空间/积分工具 schema 均需授权后 tools/list/读取或官方额外文档。
- refresh/revoke、多真实账号隔离与空间切换需要真实无费用授权测试；元数据不足以代替。
- `ssh kelao` 仅是指定发布目标；本会话未登录、未修改、未发布服务器，域名/TLS/运行身份/持久化目录由第 9 会话核验。

这里列的是继续实施所需证据，不是确认服务不支持网站。已知协议方向成立，网站回调和账号操作能否完整跑通仍待验证。

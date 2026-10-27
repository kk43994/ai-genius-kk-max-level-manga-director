# LibTV 官方网站授权模块

本模块负责标准 OAuth、账号绑定/重授权/移除和授权风险控制。客户通过浏览器打开官方授权页；服务器不读取 CLI 默认登录、浏览器 cookie、密码库或旧工程凭据。正式视频及本轮付费生成未接入。

**状态（2026-10-27）**：协议与合成故障测试通过；本机真实浏览器已到官方只读授权确认页，尚未取得用户当次确认，尚无真实 token/身份读取结果。指定公网回调注册被拒绝。`customerReady` 保持 false。

## 集成方式

以下代码由集成会话放到公共入口，本模块未修改 `backend/app.py`、存储模块或前端。

```python
from backend.auth import ProviderService, register_routes
from backend.auth.secrets import AesGcmSecretCodec
from backend.auth.storage_adapter import StorageAuthRepository
from backend.providers.libtv_oauth import LibTVOAuth, OAuthConfig, ClientRegistration

config = OAuthConfig(
    redirect_uri=confirmed_exact_callback_uri,
    return_paths=("/", "/asset-lab/"),
    scopes=("libtv:account:read",),
    application_type="web",  # 可配置；这不意味着官方已批准公网 web client。
)
codec = AesGcmSecretCodec({"primary": externally_loaded_32_byte_key}, "primary")
providers = ProviderService(
    StorageAuthRepository(storage), codec, LibTVOAuth(config),
    identity_verifier=verified_official_identity_reader,
    # 正式预注册客户端由部署 secret 配置提供；不要借用 Codex 的客户端。
    # registration=ClientRegistration(client_id, confirmed_exact_callback_uri,
    #                                 "client_secret_basic", client_secret),
)
services.providers = providers
register_routes(router, services)
```

安装模块依赖 `python -m pip install -r backend/auth/requirements.txt`。密钥必须由独立部署 secret 配置提供并跨发布保留；不能随进程启动随机生成。支持多个解密 key ID 和一个当前加密 key ID。不要把密钥和数据库/备份一起存放。正式 HTTPS callback 必须预先得到官方准入；配置不能从请求 Host、Forwarded header、body 或 returnPath 拼接。

`StorageAuthRepository` 对接第 3 模块 schema v1。`provider_accounts` 是空间/选择服务读取的权威账号表；`provider-grants` encrypted secret 中存 `authBundleCiphertext` 与 refresh claim，`libtv-oauth/state` encrypted secret 存授权尝试与注册资料。不存在第二份可独立复活账号的授权账号表。状态提交、账号投影和加密凭据由同一个 Store 事务提交。为衔接当前存储接口，桥接层使用 `tx._conn` 做限定 tenant 的账号投影；未修改存储实现。若存储提供正式 transaction-level account API，应在此桥接层替换。

所有 provider 授权操作通过 `ProviderService`；不要让其他模块把 `AccountRepository.credentials()` 的内部内容送到浏览器或直接使用旧 CLI。

## 路由与框架责任

`register_routes(router, services)` 注册 v1 账号/授权路由，`Response` 包含 status/body/headers，JSON 带 v1 envelope。额外提供取消端点 `POST /api/v1/authorization-attempts/{id}/cancel`，body `{}`；取消映射为 attempt `status=failed`、error `AUTHORIZATION_CANCELLED`，兼容现有 pending/completed/failed/expired 状态集。

`PUBLIC_ROUTES` 只声明 OAuth callback 无普通 CSRF 校验。**公开 callback 仍必须恢复并传递原本站 cookie 的 ctx，不得给无 cookie 的 callback 新建租户，不得仅凭 state 查到 tenant 后跳过会话核对。** callback 只接受原租户+原 session 的一次性 state，PKCE verifier 仅在服务器解密。回调 query 必须保留重复参数（例如 `parse_qs` 的 list）；预先压成单值会丢失重复参数防护。

公共 adapter 必须：

- 对普通 cookie 写请求执行真实 Origin + CSRF 校验，再设置服务端 `ctx.csrfVerified=True`；该值不是请求 JSON 字段。
- 把 `tenantId`、`siteSessionId` 从已恢复本站 session 注入，不从请求 body 取。
- 禁止 access log 记录 callback query、Cookie、Authorization、POST body；反向代理也应只记录 callback path。HTTP 303 的 Location 没有 code/state/token。
- callback 响应 `Cache-Control: no-store`、`Referrer-Policy: no-referrer`；本站静态页面应使用合适的同源策略，避免给普通 POST 表单造成 `Origin: null`。
- 使用明确挂载前缀配置。内部注册路径仍为 `/api/v1/...`；可将外部 `/asset-lab/api/v1/...` 精确映射到它，并在 OAuthConfig 中保留完整外部 callback。
- 不因本机回调成功或 mock 通过就启用公网 `features.providerAuthorization`；真实身份读取和正式 HTTPS callback 都验收后再启用。

已注册的 client secret、provider tokens 只在服务端。开始授权的响应只有 attemptId、官方 HTTPS authorizationUrl、expiresAt；attempt 查询不返回 state/verifier/code。错误只有固定中文原因，忽略上游 error_description/error_uri。

## 账号和空间的边界

`begin_authorization(ctx, providerAccountId=None, returnPath="/", expectedVersion=None)`；指定 account 表示重授权，必须带原 version，回调 issuer+subject 必须一致。新添加的同 subject 恢复相同内部 account ID。移除期间已开始的回调不能悄悄复活账号。移除先销毁本地可用授权并保留 tombstone，后尝试官方撤销；remoteRevocation 分开报告 confirmed/unsupported/failed。官方尚未实测真实 revoke。

`account_client_for(ctx, ownership)` 供第 4 模块在尚未选择空间时调用；ownership 要求 `tenantId,provider="libtv",providerAccountId,providerSubject`。对象只暴露 `identity()` 和 `list_spaces()`，不提供配额、模型、生成或下载方法。

`client_for(ctx, ownership)` 额外要求真实 `spaceId`，返回绑定不可变 owner 的客户端；不会读取当前 UI selection。每次操作前重新检查账号未移除和授权可用。`list_spaces/quota/list_models/prepare/submit/lookup/download` 未核实真实官方工具时抛 `PROVIDER_CAPABILITY_UNAVAILABLE`；不能返回伪造空间、零余额或偷偷走 CLI。

后台任务没有浏览器会话时，从**持久化任务归属**构造 `ProviderWorkerContext(tenantId)` 并调用 client_for；普通 dict 缺 siteSessionId 仍被拒绝。HTTP adapter 不得从请求 body 构造这个类型。工作区恢复的 connect/recover 新契约由第 3 模块提供后再接入，不能从浏览器传入 subject 恢复 tenant。

## 官方身份读取

默认 `UnavailableIdentityVerifier` 使真实 callback 在身份无法核验时失败并尝试撤销新 grant，不生成 connected 假账号。授权元数据未提供可直接使用的 OIDC subject 来源，不能解码 access token 的 JWT payload 当已验证身份。

`ReadOnlyMCPIdentityVerifier(http, IdentityReadContract(...))` 支持在正式确认后配置官方只读工具：明确 tool name、稳定 subject path、display-name path、证据说明。它先 initialize / tools/list，要求工具明确标注 readOnlyHint=true、destructiveHint=false、无需猜测必填账号/空间参数，再读取 identity；不会自动挑名称相似的工具或执行写操作。当前没有预置猜测的工具名。未经授权的工具 schema、subject、空间和额度形状仍待真实只读验证。

访问令牌过期时原子领取刷新权，刷新并重新核对同 subject 后才保存新 grant。刷新超时/崩溃可能已在上游轮换，因此本模块要求重新授权，禁止跨重启重放旧 refresh token。旧账号和任务 owner 保留。

## 检查与本机人工验证入口

```sh
python -m unittest discover -s tests/auth -p 'test_*.py' -v
```

本模块 55 项独立测试；在第 3 模块可导入时另跑 4 项真实 SQLite Store 桥接测试，共 59 项。独立克隆缺第 3 模块时桥接测试明确 skip。测试包含并发、跨重启、跨租户/会话、错误身份、取消竞争、移除竞争、PKCE 标准向量、恶意元数据/重定向、SSE 不等待 EOF、token 刷新、AEAD 绑定、数据库回滚与秘密不落明文。

`tests/auth/manual_preview.py` 是开发者诊断入口，不是交给客户安装的工具。仅绑定 127.0.0.1，拒绝原 8768 和基线 8870；需要仓库外的隔离 data dir 与独立 0600 密钥文件。默认端口 18872。服务端从官方 DCR 发起只读 OAuth，并只读取 tools/list；token 全部进入隔离加密文件。页面只会显示“身份未核验”，不伪装为客户版已连通。官方用户信息的后续只读命令只输出字段类型，原始字段值保存在同一个加密文件中。

当前运行入口：`http://127.0.0.1:18872/`。浏览器授权 state 有 10 分钟有效期；确认超时应回入口重新发起，不能复用旧回调或扩大权限。没有实际真人批准前，不能把测试脚本返回/页面跳转当真实账号接入成功。

## 实时公网准入证据

依据官方 [marketplace](https://github.com/liblib-ai/marketplace)、[授权元数据](https://mcp.liblib.tv/.well-known/oauth-authorization-server)、[资源元数据](https://mcp.liblib.tv/.well-known/oauth-protected-resource/mcp) 与本会话直接 POST 注册响应：

- 公开官方端点声明 code + S256、refresh_token、撤销、DCR；本模块固定官方 resource 和 issuer，先验证 401 challenge，再读取其资源元数据及 AS 元数据。
- 当前路径级 resource metadata 的 scopes_supported 为空，AS metadata 列出六个 scope；默认只申请 `libtv:account:read`，不将空列表误写成已获全部权限。
- `http://127.0.0.1:18872/api/v1/oauth/libtv/callback`：DCR 201，none 方法，只读 scope。只说明注册被接受。
- `https://kk666.best/asset-lab/api/v1/oauth/libtv/callback`：未传 application_type 时 DCR 400 `invalid_redirect_uri`；补充标准 `application_type=web` 后仍为相同拒绝。没有通过改成 native 或 loopback 伪装公网。
- `https://example.com/...`、`https://asset-lab.invalid/...`、HTTPS localhost 的所测回调也被拒绝，但这**不能泛化**为所有 HTTPS 或所有预注册客户端均不支持。
- 官方公开 README、服务说明和元数据未写明允许列表，也未找到已核实的预注册/白名单申请流程；不猜私有注册接口，不借用其他产品 client ID。正式下一步是获得该精确 HTTPS callback 的官方准入/预注册方案。

公网域名发布、两个真实账号、subject 与空间/余额读取、真实 refresh/revoke、付费功能均未由此模块验收；本模块没有操作 kelao。

# LibTV 官方网站授权模块

本模块负责标准 OAuth、账号绑定/重授权/移除和授权风险控制。客户通过浏览器打开官方授权页；服务器不读取 CLI 默认登录、浏览器 cookie、密码库或旧工程凭据。正式视频及本轮付费生成未接入。

**状态（2026-10-27）**：用户批准本机只读授权后，真实浏览器确认、callback、token exchange、工具目录和两次一致的官方身份读取均已完成。实际 grant 仅为 `libtv:account:read`。默认身份来源已接入 `account_user.user.uuid`，账号级空间投影使用 `accounts.accounts`。指定公网 callback 注册仍被拒绝，`customerReady` 保持 false；未追加 scope、上传或付费生成。详见 [实时证据](OFFICIAL_READ_EVIDENCE.md)。

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
    # 默认已使用核实过的 account_user.user.uuid / user.nickname。
    workspace_recovery=services.workspace_recovery,  # 第 3 模块实例；不启用可省略。
    # operation_adapter_factory=verified_image_adapter_factory,  # 独立交付，默认关闭。
    # 正式预注册客户端由部署 secret 配置提供；不要借用 Codex 的客户端。
    # registration=ClientRegistration(client_id, confirmed_exact_callback_uri,
    #                                 "client_secret_basic", client_secret),
)
services.providers = providers
register_routes(router, services)
```

安装模块依赖 `python -m pip install -r backend/auth/requirements.txt`。密钥必须由独立部署 secret 配置提供并跨发布保留；不能随进程启动随机生成。支持多个解密 key ID 和一个当前加密 key ID。不要把密钥和数据库/备份一起存放。正式 HTTPS callback 必须预先得到官方准入；配置不能从请求 Host、Forwarded header、body 或 returnPath 拼接。

`StorageAuthRepository` 对接第 3 模块稳定的账号投影接口，已用 **schema v2** Store 验证；工作区恢复依赖第 3 模块 `60fdd4b0baddff687cd78594d1818129e84aaadc` 或后续兼容版本。集成环境 manifest/readiness 应报告 schema 2，不要与本模块内部 OAuth 状态的 `schemaVersion=1` 混淆。`provider_accounts` 是空间/选择服务读取的权威账号表；`provider-grants` encrypted secret 中存 `authBundleCiphertext` 与 refresh claim，`libtv-oauth/state` encrypted secret 存授权尝试与注册资料。不存在第二份可独立复活账号的授权账号表。状态提交、账号投影和加密凭据由同一个 Store 事务提交。为衔接当前存储接口，桥接层使用 `tx._conn` 做限定 tenant 的账号投影；未修改存储实现。若存储提供正式 transaction-level account API，应在此桥接层替换。

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

已注册的 client secret、provider tokens 只在服务端。开始授权的基础响应只有 attemptId、官方 HTTPS authorizationUrl、expiresAt；owner 流程另含公开 workspaceIntent，不含恢复 nonce。attempt 查询不返回 state/verifier/code。错误只有固定中文原因，忽略上游 error_description/error_uri。

## 账号和空间的边界

`begin_authorization(ctx, providerAccountId=None, returnPath="/", expectedVersion=None)`；指定 account 表示重授权，必须带原 version，回调 issuer+subject 必须一致。新添加的同 subject 恢复相同内部 account ID。移除期间已开始的回调不能悄悄复活账号。移除先销毁本地可用授权并保留 tombstone，后尝试官方撤销；remoteRevocation 分开报告 confirmed/unsupported/failed。官方尚未实测真实 revoke。

`account_client_for(ctx, ownership)` 供第 4 模块在尚未选择空间时调用；ownership 要求 `tenantId,provider="libtv",providerAccountId,providerSubject`。对象只暴露 `identity()` 和 `list_spaces()`，不提供配额、模型、生成或下载方法。

`client_for(ctx, ownership)` 额外要求真实 `spaceId`，返回绑定不可变 owner 的客户端；不会读取当前 UI selection。`list_spaces` 实时调用 `account_user`，核对同一 subject，再把官方 `accountId` 投影为空间 ID、`accountType=1/2` 投影为 personal/team。读取后再次检查账号是否被移除。所有成员记录均展示，不把 `isActive=false` 当权限撤销；会员等级、effective 与余额无关。

`quota/list_models/prepare/submit/lookup/download` 默认仍抛 `PROVIDER_CAPABILITY_UNAVAILABLE`。后续可注入经过验证的 server-side adapter；该入口核对固定归属、实时空间成员关系和所需 scope，再提供不返回令牌的工具接口。当前只读 grant 不能调用模型/生成等操作。详见 [adapter 契约](ADAPTER_CONTRACT.md)，不能根据工具目录就假定项目归属或付费生成已经验证。

后台任务没有浏览器会话时，从**持久化任务归属**构造 `ProviderWorkerContext(tenantId)` 并调用 client_for；普通 dict 缺 siteSessionId 仍被拒绝。HTTP adapter 不得从请求 body 构造这个类型。

## 网站工作区绑定与找回

`POST /api/v1/provider-accounts/authorize` 可传 `purpose=provider_account | bind_owner | recover_workspace`，或兼容 `intent=connect | bind_owner | recover`。不允许冲突目的、浏览器传入 subject/tenant/proof、或在 owner 流程指定生成账号 ID。owner 请求可携带 `hasUnsavedChanges: bool | null`、`workspaceLabel`；必须将第 3 模块的同一个 `WorkspaceRecoveryService` 同时注入 `services.workspace_recovery` 与 `ProviderService(workspace_recovery=...)`。

发起时先创建恢复 intent，nonce 只进授权尝试的加密私有资料。callback 在 state、原 session、PKCE、新 code exchange、权威身份读取全部通过后构造 `FreshOwnerProof`。先提交 OAuth 尝试，再在事务外调用 `accept_verified_authorization`；调用后不再操作旧 ctx。响应必须保留 hook 返回的 `Set-Cookie`，即使后续官方 revoke 暂时失败也不能丢掉已轮换的 cookie。

普通添加创作账号不会绑定网站 owner。绑定/找回仅证明网站身份，不自动保存创作账号 grant，临时 token 会尝试撤销。`authorizationStatus=completed` 表示身份流程完成，`workspaceStatus` 单独表示 bound/recovered/awaiting_confirmation/blocked/not_found/failed；不能把它们混成一个“已找回”。有新工作区内容、未确认的草稿或多个候选时由第 3 模块继续确认，不静默覆盖或合并。

这部分已用真实 schema v2 SQLite Store / Session / Recovery 服务联调，OAuth 身份证据使用合成 fixture。本次真人只读诊断没有替用户绑定或找回工作区。

## 官方身份读取

默认使用已核实的 `LIBTV_ACCOUNT_IDENTITY`：官方 `account_user`、subject 路径 `user.uuid`、展示名路径 `user.nickname`。`UnavailableIdentityVerifier` 仍可显式关闭身份接入。身份无法核验时 callback 失败并尝试撤销新 grant，不生成 connected 假账号。授权元数据未提供可直接使用的 OIDC subject 来源，不能解码 access token 的 JWT payload 当已验证身份。

`ReadOnlyMCPIdentityVerifier(http, IdentityReadContract(...))` 支持经审计的其他官方只读工具：明确 tool name、稳定 subject path、display-name path、证据说明。它先 initialize / tools/list，要求工具明确标注 readOnlyHint=true、destructiveHint=false、无需猜测必填账号/空间参数，再读取 identity；不会自动挑名称相似的工具或执行写操作。本次账号成员结构与个人/团队枚举已经核实，额度及模型响应形状尚未核实。

访问令牌过期时原子领取刷新权，刷新并重新核对同 subject 后才保存新 grant。刷新超时/崩溃可能已在上游轮换，因此本模块要求重新授权，禁止跨重启重放旧 refresh token。旧账号和任务 owner 保留。

## 检查与本机人工验证入口

```sh
python -m unittest discover -s tests/auth -p 'test_*.py' -v
```

本模块 67 项独立测试；第 3 模块可导入时另跑 4 项真实 SQLite Store 桥接和 12 项 owner recovery 测试；第 3、4 模块均可导入时另跑 1 项真实 SpaceService / 持久化选择联调；第 1 模块 generation types 可导入时另跑 1 项 AuthorizedMCP 接口联调，共 85 项。独立克隆缺其他模块时对应测试明确 skip。测试包含并发、跨重启、跨租户/会话、错误身份、取消竞争、移除竞争、PKCE 标准向量、恶意元数据/重定向、SSE 不等待 EOF、token 刷新、AEAD 绑定、数据库回滚、秘密不落明文、owner cookie 轮换与 scope 拦截。

`tests/auth/manual_preview.py` 是开发者诊断入口，不是交给客户安装的工具。仅绑定 127.0.0.1，拒绝原 8768 和基线 8870；需要仓库外的隔离 data dir 与独立 0600 密钥文件。默认端口 18872。callback 完成后先显示身份未核验；官方身份审查完成并记录后入口显示“本机身份已验证”，仍明确公网 callback 未获准。只读命令只输出字段类型，原始字段值与 token 保存在加密文件中。

当前运行入口：`http://127.0.0.1:18872/`。浏览器授权 state 有 10 分钟有效期；确认超时应回入口重新发起，不能复用旧回调或扩大权限。没有实际真人批准前，不能把测试脚本返回/页面跳转当真实账号接入成功。

## 实时公网准入证据

依据官方 [marketplace](https://github.com/liblib-ai/marketplace)、[授权元数据](https://mcp.liblib.tv/.well-known/oauth-authorization-server)、[资源元数据](https://mcp.liblib.tv/.well-known/oauth-protected-resource/mcp) 与本会话直接 POST 注册响应：

- 公开官方端点声明 code + S256、refresh_token、撤销、DCR；本模块固定官方 resource 和 issuer，先验证 401 challenge，再读取其资源元数据及 AS 元数据。
- 当前路径级 resource metadata 的 scopes_supported 为空，AS metadata 列出六个 scope；默认只申请 `libtv:account:read`，不将空列表误写成已获全部权限。
- `http://127.0.0.1:18872/api/v1/oauth/libtv/callback`：DCR 201，none 方法，只读 scope。只说明注册被接受。
- `https://kk666.best/asset-lab/api/v1/oauth/libtv/callback`：未传 application_type 时 DCR 400 `invalid_redirect_uri`；补充标准 `application_type=web` 后仍为相同拒绝。没有通过改成 native 或 loopback 伪装公网。
- `https://example.com/...`、`https://asset-lab.invalid/...`、HTTPS localhost 的所测回调也被拒绝，但这**不能泛化**为所有 HTTPS 或所有预注册客户端均不支持。
- 官方公开 README、服务说明和元数据未写明允许列表，也未找到已核实的预注册/白名单申请流程；不猜私有注册接口，不借用其他产品 client ID。正式下一步是获得该精确 HTTPS callback 的官方准入/预注册方案。

公网域名发布、两个真实登录用户的账号隔离、官方余额、模型响应、远端团队/项目执行归属、真实 refresh/revoke、付费功能均未由此模块验收；本模块没有操作 kelao。已验证的是一个真实用户的身份及其两个账号成员记录，不能写成“两账号生成隔离已验证”。

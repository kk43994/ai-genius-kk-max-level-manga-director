# 本站会话与公共入口装配

`SessionService` 维护独立于 LibTV 登录身份的匿名本站租户；切换个人/团队空间或 LibTV 账号不会切换 tenant。

## HTTP adapter（会话 10）

1. 启动时装配 `Store` 与 `SessionService`，配置真实 `public_origin`。见 `../storage/README.md`。
2. 注册 `backend.sessions.register_routes(router, services)`，其中 `services.sessions` 为 SessionService。
3. `PUBLIC_ROUTES` 只含 `GET /api/v1/session`。该 endpoint 没有 Cookie 时创建隔离匿名 tenant；有 Cookie 时恢复它。其余业务路由默认必须认证；OAuth callback 的例外与绑定由会话 2 单独注册。
4. 其他请求先 `token = sessions.token_from_cookie(headers.get("Cookie"))`，再 `result = sessions.restore(token, request_id=request_id)`；从 `result.context` 设置 ctx.tenantId/siteSessionId，绝不从 query/body 设置。没有 token 就返回 401，不自动替业务请求创建匿名 tenant。
5. 将 `result.set_cookie` 作为响应的 Set-Cookie，延续 30 天闲置期限；会话绝对期限默认 90 天。浏览器关闭再打开仍依赖该持久 Cookie。若不打算延长期限可用 `restore(..., touch=False)`。
6. 所有 Cookie 写请求调用 `sessions.verify_mutation(ctx, origin=header_origin, csrf_token=header_csrf)`；必须同时满足同来源和 session 绑定 CSRF。不要以请求中的 csrfVerified 字段为依据。
7. `StorageError` 转成 `error.public()` 和 `.status`，加标准 meta；日志仅记录稳定错误码与 requestId，不包含 Cookie、Set-Cookie、授权头、返回 grant、OAuth query 或原始异常 traceback。

`Response` 是带 `status/body/headers` 的 dataclass；session 路由已经生成 v1 `{data,meta}` envelope，adapter 不要再套第二层 data。会话响应带 Cache-Control: no-store。生产安全头、JSON 体积限制、请求 ID、CORS 与错误 envelope 仍由集成入口负责。

`GET /session` 的 data 为 `{session:{id,expiresAt},tenant:{id},csrfToken,selection,features}`。session id 是公开随机 ID，不能当 bearer 使用。只有 Cookie 中的 256 位随机 token 能恢复会话，服务端仅保存 SHA-256。CSRF token 通过独立派生 key 与 session id 绑定，轮换后改变。

features 默认全 false；SessionService 接受显式的 `features` 参数，由集成根据已验证能力设置。`videoGeneration` 在本轮始终强制 false。

## 注销与恢复边界

本模块对 v1 契约增加 `POST /api/v1/session/logout`，body `{}`、带 Origin 和 X-CSRF-Token；返回 `{loggedOut:true}`，服务端撤销当前 session，Cookie 清空。它与“移除 LibTV 账号”不同：不删除项目、素材或 provider grant，也不宣称撤销 LibTV 登录。

已补充独立的主所有者绑定与找回服务：用户先明确绑定主所有者，清 Cookie、本站注销或 Cookie 到期后，可以通过**新的官方 OAuth + 权威身份读取**恢复原工作区。普通生成账号不是主所有者。精确的 callback、确认与草稿保留接线见 `OWNER_RECOVERY.md`；只有完成授权模块接线和官方验证后才能对客户宣称可用。尚未绑定主所有者的旧匿名数据不会根据已有生成账号猜测归属或跨租户合并。

有无效、过期、重复、伪造的本站 Cookie 时 bootstrap 返回 SESSION_REQUIRED，不静默换成另一个客户。adapter 不要捕获 401 后偷偷创建新会话或返回空白项目成功。

`rotate(ctx)` 仅为未来本站身份验证或权限升级提供会话轮换：旧 token 即刻失效，tenant 保持不变，新 CSRF 产生。LibTV 账号切换不调用 rotate。`logout(ctx,all_sessions=True)` 供已验证的本站安全动作使用，当前公开注销路由不接受此选项。

本模块不控制 provider OAuth state/PKCE，不处理官方注销或 revocation。真实授权由会话 2 实现并验证。

`GET /session` 额外提供 `workspace` 概要；`services.workspace_recovery` 注入后注册工作区查询、待确认和取消接口。Schema 1 升级到 schema 2 为增量迁移，主所有者绑定不会修改历史 task ownership。

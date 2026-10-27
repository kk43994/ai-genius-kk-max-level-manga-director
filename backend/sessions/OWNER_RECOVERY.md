# 主所有者绑定与工作区找回：授权 / 存储 / HTTP 接线契约 v1

新增实现 `WorkspaceRecoveryService`、`FreshOwnerProof`、`WorkspaceRepository`；数据 schema 2，从 schema 1 在单事务内增量迁移。此文给会话 2 和 10 精确接线，不授权从浏览器构造 proof，不替代官方 OAuth 验证。

## 身份与权限

- `workspace_owners` 固定每个 tenant 的一个主所有者，锚点为官方 `provider=libtv, issuer=https://mcp.liblib.tv/, subject`。同一主所有者可在明确确认后拥有多个独立工作区。
- 生成用 `provider_accounts` 完全独立。添加、切换、删除、刷新 grant 不授予、删除或转移网站所有权。找回也不自动添加/恢复生成账号。
- 初次绑定必须由持有当前匿名会话的用户主动选择 `bind_owner` 并完成新的官方 OAuth。已绑定另一个主所有者的工作区不可转移。
- 重新打开且 Cookie 有效时仍走普通会话恢复。清 Cookie / 注销 / 到期后，先引导一个新匿名会话，再由用户明确选择 `recover_workspace`，执行新 OAuth，按新鲜验证的主所有者选择原 tenant。
- 没有主所有者绑定记录时不猜测恢复：v1 的旧 provider account 不会被迁移成主所有者。尚持有效匿名 Cookie 的客户需完成初次绑定。对已经丢失 Cookie 且从未绑定的旧匿名数据，本模块没有安全所有权证据，明确拒绝自动接管。

## 最小装配

```python
from backend.sessions import WorkspaceRecoveryService, FreshOwnerProof

workspace_recovery = WorkspaceRecoveryService(store, session_service)
services.workspace_recovery = workspace_recovery
# 必须在 sessions.register_routes() 之前注入。
```

`SessionHTTPAdapter` 可代理底层 SessionService；共享 Store 必须为同一个实例。已有 adapter 的 cookie 名称 / basePath 重写仍须用于新的 callback 和 confirmation 响应。

## 授权开始：普通添加与主所有者动作必须分支

会话 2 的外部授权开始 endpoint 可增加白名单 `purpose: provider_account | bind_owner | recover_workspace`；默认 `provider_account` 不调用主所有者接口。UI 必须分别呈现“绑定工作区主所有者”和“找回工作区”，不能把普通“添加生成账号”默认当所有者绑定。

对 owner purpose，禁止 `providerAccountId` / `expectedVersion` 作为恢复身份输入。body 只接受 purpose、hasUnsavedChanges、workspaceLabel、已允许的 returnPath；不要接收 tenantId、issuer、subject、proof 或 nonce。

在 auth `begin_authorization` 已生成 `attempt_id` 与随机 OAuth state、通过 CSRF 检查之后，**在已有 repository.transaction 之外**调用：

```python
ticket = workspace_recovery.begin(
    ctx, purpose="bind_owner",  # 或 recover_workspace；保存，不从 callback query 取值
    authorization_attempt_id=attempt_id,
    oauth_state_hash=sha256(oauth_state.encode()).hexdigest(),
    has_unsaved_changes=False,  # 必须由 UI 如实传递；遗漏/未知按需要确认处理
    workspace_label="我的工作区",
)
```

服务再次验证 Origin、X-CSRF-Token、活动本站 session，持久化 intent 与哈希挑战。`ticket.intent_id` 和 **`ticket.nonce`** 存进同次 OAuth attempt 的加密 private payload；将 intent_id/purpose 作为可查状态。`ticket.public()` 可作为返回 data 的附加 `workspaceIntent` 字段；**不要返回 nonce**。尝试表/授权 URL 存储失败时取消 intent，不继续显示可用授权。

这个 nonce 是本站工作区意图的一次性挑战，与 OAuth attempt 的 state hash、session ID 双重绑定，**不是 OIDC ID token nonce**。当前官方路径是 OAuth + 权威身份读取；若后续改用 OIDC，官方验证器还须按协议验证其 ID token nonce。不要把本挑战当作跳过标准 OAuth state/PKCE 的理由。

`ctx.headers` 必须保留真实 Origin 和 X-CSRF-Token。仅给 ctx.csrfVerified=True 不足以通过本模块开始/确认操作。

## 官方回调：顺序必须固定

只有官方正常授权码兑换得到的 grant + 新的权威身份读取可产生以下 proof。不能使用刷新 token、已有账号 projection、providerAccountId、浏览器 subject、解码未验证 token 或旧 identity cache。

1. 会话 2 按现有逻辑验证 callback state 单次消费、当前 session、issuer、PKCE、授权码兑换及受信官方 subject。仅能读取 attempt 加密载荷里的 intent/nonce，不能从 callback query 获取。
2. 记录本次 code exchange 完成时间与随后 identity read 验证时间；二者必须不早于 intent 创建，身份读取距接受时间最多 60 秒。
3. 对 owner purpose **不要执行 provider account 创建 / grant 保存分支**。在源匿名租户自己的 auth 事务中重新检查 attempt 仍 exchanging，然后结束该 OAuth attempt 并清除私密载荷。释放事务，之后再调用工作区 hook，避免嵌套 SQLite 写事务。
4. 构造只在服务器内部流转的类型：

```python
proof = FreshOwnerProof(
    authorization_attempt_id=saved_attempt["id"],
    oauth_state_hash=saved_attempt["stateHash"],
    site_session_id=ctx.siteSessionId,
    issuer=verified_official_identity.issuer,
    subject=verified_official_identity.subject,
    code_exchanged_at=exchange_completed_at,
    identity_verified_at=identity_read_completed_at,
    grant_type="authorization_code",
    state_verified=True,             # 只能在上述验证实际成功后设置
    pkce_verified=True,
    authoritative_identity_read=True,
)
result = workspace_recovery.accept_verified_authorization(
    ctx, intent_id=saved_private["workspaceIntentId"],
    nonce=saved_private["workspaceIntentNonce"], proof=proof,
)
```

proof 类型是受信代码间断言，不是独立数字签名；接口没有对应 HTTP endpoint，不能让 JSON 反序列化构造该类型。存储再检查 issuer 固定值、subject 格式、session、state hash、attempt、nonce、时间与一次性消费；这些检查不能替代会话 2 的密码学/官方验证。

5. `result.session is not None` 才表示已绑定/恢复并轮换 Cookie。将 `result.session.set_cookie` 放入 callback 响应；作为最后一个使用旧 ctx 的操作，因为旧 session 已撤销。回调仅跳回已白名单的 returnPath，附带非秘密结果状态。仍需 HTTP adapter 统一处理 basePath 和 Cookie Path。
6. `awaiting_confirmation`、`blocked`、`not_found` 没有新 session，绝不声称已恢复。pending 时跳回原匿名会话，在 UI 显示结果。OAuth attempt 结束只表示官方身份验证完成，与工作区恢复完成分开记录。
7. owner flow 的临时 grant 不进入生成账号。回调结束后按官方能力尝试撤销并销毁临时 grant；不能让撤销失败反向“恢复”普通账号，也不能在日志输出 grant。临时 grant 撤销结果不影响已经经过验证的网站身份；不能报告远程撤销成功，除非官方确认。

OAuth attempt 的消费与 owner hook 分两次持久事务，故若进程在二者之间崩溃会要求重新授权；没有已消耗 state 的静默重放，也没有未持久化即宣称成功。hook 内的主所有者绑定、intent 消费、源 session 撤销与新 session 创建为**同一事务**。

## 待确认与浏览器未保存内容

`awaiting_confirmation` 返回：

```json
{"id":"wi_example","purpose":"recover_workspace","status":"awaiting_confirmation",
 "version":2,"reasons":["current_workspace_has_content"],
 "sourceWorkspace":{"id":"tenant_current","content":{"revision":7,"hasContent":true}},
 "candidates":[{"id":"tenant_prior","label":"旧工作区"}],
 "proofExpiresAt":"..."}
```

所有 candidates 都来自刚刚验证的同一主所有者，不接受任意 workspace ID。默认 proof 确认窗口 5 分钟，并受最初 10 分钟授权窗口限制。

- `bind_owner` 发现已有同 owner 工作区，或当前未保存草稿状态未知/为 true：先等待确认。只允许 `action=bind_current`，明确将当前工作区也绑定到此 owner，不自动选择旧工作区。需要找回时取消并另发 recover intent。
- `recover_workspace` 有多个候选、当前有项目/素材/账号记录，或浏览器草稿未知/未保存：先等待确认。只有一个候选、当前无内容且 UI 显式确认无未保存草稿时可直接恢复。
- 当前有内容时，切换必须选 `recover_preserve_current`：把当前匿名工作区显式绑定给同一主所有者，再进入选定旧工作区。两边数据保持原 tenant、项目和 task ownership；不合并、不覆盖。之后可再次选择恢复保留下来的工作区。
- UI 若报告有未保存草稿，必须先通过原工作流保存到当前匿名 tenant，等待保存成功，然后携带 `savedDrafts:[{collection,id,version}]` 确认。服务核对这些记录属于源 tenant、当前版本、保存时间及内容 revision。仅勾“已保存”但没有持久记录会失败。服务端无法证明未发送到服务器的文本已完整保存，UI 仍必须将所有编辑内容保存后再提交，不能用一个无关记录代替。
- `draftDisposition=none` 是明确确认没有未保存浏览器草稿；开始时 hasUnsavedChanges=true 不允许绕过成 none。每次确认带最新 `sourceWorkspace.content.revision`，并发修改会报 WORKSPACE_CONTENT_CHANGED，不切换。

## 路由（会话 3 提供，均要求本站 session）

- `GET /api/v1/workspace`：当前工作区所有权与内容概要。
- `GET /api/v1/workspace-intents/{id}`：只有开始该意图的同 tenant、同 session 可读。
- `POST /api/v1/workspace-intents/{id}/confirm`：Origin+CSRF；body 白名单见下。
- `POST /api/v1/workspace-intents/{id}/cancel`：Origin+CSRF、空 body，保持原会话。

```json
{"action":"recover_preserve_current","workspaceId":"tenant_prior",
 "expectedVersion":2,"expectedContentRevision":8,
 "draftDisposition":"saved",
 "savedDrafts":[{"collection":"drafts","id":"obj_saved","version":3}]}
```

成功确认响应带新 Set-Cookie；客户端随后重新 GET /session 加载目标工作区，清理或重命名源 tenant 对应的前端状态，不能清 localStorage 全域。取消保持当前工作。被主动移除的生成账号仍为 removed，不因网站找回复活。

`GET /session` 新增 `workspace` 字段。授权模块尚未接上或官方新鲜 subject 不可验证时，前端不能启用找回按钮宣称可用。配置了 `services.workspace_recovery` 后才注册确认路由；没有普通 POST 可以直接设置 owner。

## 集成与发布必须同步

- `SCHEMA_VERSION` 已为 **2**，`Store.readiness()` 返回实际 dataSchemaVersion。当前集成入口曾硬编码 `schema == 1`；必须改用该常量/方法，避免把成功迁移误判为未就绪。
- release manifest 的 dataSchemaVersion 同步为 2。旧 schema 1 代码会拒绝写新库，回滚需包含兼容 schema 2 的代码或经过核验的备份恢复，不可覆盖真实数据。
- 工作区内容版本由 records/blobs/provider_accounts/provider_spaces/selections 的 SQLite triggers 跟踪，覆盖现有模块直接 SQL 更新。若后续新增独立数据表，需为其加入同样的内容版本与 hasContent 检查，不能把有客户数据的工作区误判为空。
- 数据 key、路径、凭据加密机制保持不变；迁移不读取生产凭据、不回填猜测的所有者、不改旧任务 owner。

当前测试覆盖实际 SQLite、私有 blob、新进程恢复、并发消费、工作区选择与草稿保存；官方 OAuth 回调只使用合成证据。真实官方 issuer/subject 读取、授权回调、浏览器交互和部署仍须分别验证，未接线时不得把本模块测试称为客户已可找回。

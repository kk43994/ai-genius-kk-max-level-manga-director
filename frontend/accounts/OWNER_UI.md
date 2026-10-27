# 工作区主账号与找回 UI 增量

本增量只修改账号模块及其测试，不修改后端、公共 shell 或部署入口。以第 3 模块已提交的 `60fdd4b0baddff687cd78594d1818129e84aaadc`（前置 `4ce81cfecb117a0281b3461d27db5814228b8c56`）中 `backend/sessions/OWNER_RECOVERY.md` 为工作区契约；授权 start 参数和返回值直接核对第 2 模块提交 `c56463a` 的 `backend/auth/routes.py`、`service.py` owner 分支实现。

## 接线与默认关闭

既有 `mount({root, api, events, session, publicBasePath})` 不变，新增可选 `workspaceRecovery` 配置。完整示意：

```js
const accounts = mount({
  root: accountRoot, api, events, session: sessionData, publicBasePath,
  workspaceRecovery: {
    enabled: verifiedOwnerRecoveryReady,
    inspectDrafts: async () => ({
      hasUnsavedChanges: false,  // true / false / null；来自真实编辑器
      items: [],                 // [{label:'资产清单中的未保存修改'}]，只传描述
    }),
    saveDrafts: async ({purpose, intentId, sourceWorkspaceId}) => {
      // 调用真实 workflow / 项目保存逻辑，保存全部编辑内容到当前 source tenant。
      // 等待服务器返回持久记录后再返回；不能用本地存储或无关记录冒充。
      return {savedDrafts: [{collection:'drafts', id: persisted.id, version: persisted.version}]};
    },
    beforeSessionRotation: async ({purpose, sourceWorkspaceId}) => {
      // 暂停/排空其他模块的旧上下文请求，并禁止它们继续编辑/写入。
      // 不要阻断账号模块自身即将发出的 confirm 请求，不清空任何输入。
      return async () => { /* 确认失败且仍是旧 session 时，恢复其他模块。 */ };
    },
    onSessionRotated: async ({session, previousSession, result, reason, preserveUnsavedInputs}) => {
      // session 是 Cookie 轮换后重新 GET /session 得到的完整 data。
      // 终止旧租户/旧 session 的模块请求，再用新 session 重挂载项目、任务、流程等模块。
      // 可同时重挂载账号模块。此时旧账号模块会停止发事件/写 DOM。
      // preserveUnsavedInputs=true：本页未保存输入必须留存待用户确认，不能清掉，
      // 也不能擅自把它们保存到另一个工作区。
      // result=null 只表示会话变化，不能声称本次找回成功。
    },
    bootstrapSession: async ({preserveUnsavedInputs}) => {
      // 可选：由第 10 的 HTTP/session adapter 处理过期 Cookie，建立新的临时 session。
      // 返回完整 session data；保持当前浏览器输入，绝不以生成账号或 subject 选择 tenant。
      return freshAnonymousSession;
    },
  },
});
```

必须明确 `enabled === true`，并提供 `inspectDrafts`、`beforeSessionRotation`、`onSessionRotated`，才能启用绑定/找回按钮。`session.workspace.id` 还必须等于服务端 `tenant.id`。已有生成账号、普通 `features.providerAuthorization` 或本地 storage marker 不会开启 owner 能力。官方新鲜 subject 验证、owner hook、Cookie/CSRF 与 schema 2 没有就绪时，集成层必须保持关闭。

`inspectDrafts` **只聚合项目/资产/流程编辑器的未保存内容**，不要把账号模块自身的“正在授权/待确认”状态作为草稿，否则永远无法确认。账号/空间选择本身尚未应用时，会先阻止进入 owner 流程。`saveDrafts` 必须覆盖本次所有未保存输入；缺少保存钩子时仍可取消，但不能绕过确认。

第 3 的基础 `GET /session` 对已过期的 Cookie 返回 `SESSION_REQUIRED`，不会自行换租户。因此“建立临时会话并继续找回”通过显式 `bootstrapSession` 接到第 10 的实际 adapter；本模块没有猜测 `/reset`、没有读写 HttpOnly Cookie，也没有调用普通注销接口冒充过期会话清理。钩子未提供时，此按钮不可用，并说明临时会话需要接入。`bootstrapSession` 只能创建新的空白工作区，找回仍需之后的新鲜官方 owner OAuth。

`beforeSessionRotation` 的返回函数只在确认失败且仍处于旧上下文时调用；若该钩子自己失败，应在抛错前恢复自身冻结。Cookie 已轮换后，交给 `onSessionRotated` 彻底替换旧模块上下文，不恢复旧请求。同步失败时账号模块保持锁定，提供“重新同步工作区”；重试只读取 session 和运行同步钩子，不重新 POST confirm。

## 实际 HTTP 契约

账号模块仍通过注入的 `api.request` 使用相对路径，`apiBase` 由集成层配置。需要 `api.setCsrfToken`（公共客户端已提供）接收轮换后的新 CSRF。

开始：`POST /provider-accounts/authorize`

```json
{"purpose":"recover_workspace","returnPath":"/asset-lab/","hasUnsavedChanges":null,"workspaceLabel":"当前工作区"}
```

绑定使用 `purpose=bind_owner`。不发送 `providerAccountId`、`expectedVersion`、`tenantId`、issuer、subject、proof 或 nonce。后端兼容 intent 命名，但本模块仅使用第 3 文档的 purpose 命名，不同时发送两个意图字段。

start 返回 `{attemptId,authorizationUrl,expiresAt,workspaceIntent:{intentId,purpose,expiresAt}}`；模块只读取这些公开字段。owner URL 必须是已经核实的 `https://mcp.liblib.tv/authorize`，且仅有一个 `scope=libtv:account:read` 参数；写入范围、多个 scope 参数或其他 URL 会被拒绝，并保留“取消”入口。前端不拼接 OAuth 参数，不保存生成 grant。

即使预检没有草稿，start 也发送 `hasUnsavedChanges:null`，因为官方登录期间编辑器可能产生新输入。这样走服务端已有的 `unsaved_or_unknown_browser_drafts` 确认分支，不会在后台回调中自动切换工作区；已有未保存内容则如实发送 true，后续不能降级为 none。

状态读取先 `GET /session` 核对同一站点 session，再 `GET /workspace-intents/{id}`；intent 仍 pending 时读取 `GET /authorization-attempts/{id}` 来显示失败/取消。状态请求未结束时不能并发保存、确认或取消。OAuth `completed` 且 `providerAccountId=null` 只表示完成身份验证，绝不会按生成账号 connected 或工作区 recovered 处理。

恢复确认：`POST /workspace-intents/{id}/confirm`

```json
{"action":"recover_preserve_current","workspaceId":"本次返回的候选ID",
 "expectedVersion":2,"expectedContentRevision":8,
 "draftDisposition":"saved","savedDrafts":[{"collection":"drafts","id":"实际保存ID","version":3}]}
```

用户必须选择候选并勾选确认；不默认选中唯一候选，也不接受任意输入的工作区 ID。所有恢复都明确保留当前工作区，两个 tenant 的项目/素材/任务不合并。确认前重新检查草稿，在其他模块冻结之后再检查一次；新内容会阻止确认。没有未保存内容时发送 `draftDisposition=none`。开始时为 true，必须有真实 `savedDrafts` 才能继续。保存后重新读取 intent 的最新 source content revision，CAS 冲突后保留用户输入并清除勾选，绝不自动重试确认。

绑定确认使用 `action=bind_current`，不发送 workspaceId；即使存在旧工作区候选也不会切到旧 tenant。进入旧工作区需先取消绑定意图，再发起找回。

取消先调用第 2 已实现的 `POST /authorization-attempts/{attemptId}/cancel`（空 body），再调用第 3 `POST /workspace-intents/{intentId}/cancel`（空 body）。这样既覆盖 OAuth pending，也覆盖身份已验证但 awaiting_confirmation 的阶段。仅服务端返回 cancelled 才显示取消完成；网络失败保留当前输入，不宣称取消成功。

## 会话轮换与草稿保护

- confirm 返回 bound/recovered 后，下一次请求必须是完整 `GET /session`；不再用旧 ctx 读 intent。
- 核对新 session ID、目标 workspaceId、ownerBound；符合才报告绑定/找回完成。callback URL query 或 localStorage 都不能证明完成。
- 更新公共 API 的 CSRF，调用 `onSessionRotated`，然后发 `session:changed`、`workspace:changed`、`selection:changed`、`provider-accounts:changed`、`tasks:changed`。hook 是跨模块同步的必要接线，事件只是后续通知。
- 在其他标签页轮换 session 时，停止旧 intent 请求，通知 `preserveUnsavedInputs=true`，不宣称当前流程已找回成功。
- 原生成账号模块现在也检测“同 tenant、不同 session ID”变化，丢弃旧请求与旧授权 attempt；恢复记录带 siteSessionId，旧会话记录不复用。
- 本模块只移除自己当前 intent 的 storage key。原工作区的账号/空间草稿保留，不清整个 localStorage。
- owner storage marker 只含 purpose、attemptId、intentId、源 session/工作区 ID、公开状态、到期时间和是否初始有草稿。nonce、proof、subject、OAuth URL、CSRF、草稿正文及保存记录不写入 storage。

## 检查

```sh
node --test tests/accounts-ui/state.test.mjs tests/accounts-ui/owner-state.test.mjs
python3 tests/accounts-ui/serve_fixture.py --port 8897
```

- 新 owner 套件：`/tests/accounts-ui/owner-fixture.html?suite=1`
- 子路径 owner 套件：`/asset-lab/tests/accounts-ui/owner-fixture.html?suite=1&base=/asset-lab/`
- 原账号回归：`/tests/accounts-ui/fixture.html?suite=1`
- 手动 owner 页面：移除 `suite=1`。所有账号、工作区、OAuth 结果和保存凭据都是合成，官方页面跳转被阻止。

这些测试验证前端状态和请求边界。真实官方登录、可信 subject 获取、持久化草稿保存、清 Cookie / 过期 Cookie adapter、生产 session 轮换、跨模块旧 ctx 清理与公网交付必须在集成后分别验收。schema 2 和 release manifest 的升级由第 10/发布模块负责，本增量不改后端 schema。

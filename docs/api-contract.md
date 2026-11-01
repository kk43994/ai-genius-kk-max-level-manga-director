# 客户网页版接入契约 v1

状态：客户集成候选版已装配本文业务接口、主账号找回与正式生成适配器；具体可用边界见 README 和 /ready。生产协议映射、创作授权、公网 callback、收费实测分别未通过，不能把接口存在视为真实生成可用。客户最终只需浏览器；正式视频暂停，本轮不产生收费任务。

## 1. 标识与安全边界

- `tenantId`：本站客户数据所有者，由站点服务端 session 解析，任何客户端 `tenantId` 都不得用来扩大访问范围。
- `siteSessionId`：本站会话，与 LibTV 登录无关。第 3 会话实现持久化会话；浏览器使用 HttpOnly、Secure（正式 HTTPS）、SameSite=Lax Cookie，服务端只存随机会话令牌的哈希。普通刷新/重开恢复同一租户。建议闲置期 30 天；过期、清 Cookie、跨设备恢复需后续明确站点账户/恢复方案，不能暗示 LibTV 账户天然等于本站租户。
- `providerAccountId`：本站一个绑定的 LibTV 登录身份，随机内部 ID。唯一性按 `(tenantId, provider, issuer, subject)`；`subject` 必须由官方认证证据得到，显示名、手机号掩码、套餐、空间 ID 都不是身份依据。官方暂未提供 subject 时记录 pending/unsupported，禁止猜测合并账号。
- `spaceId`：该登录身份可访问的个人/团队工作空间。`CLI account use` 若只切空间，不能实现第二个登录身份。
- `projectId`：本站租户内项目；`taskId`：独立任务；`assetId`/`revisionId`：素材及不可变版本。
- provider token、refresh token、client secret 仅服务端加密存储；不进 JSON 响应、HTML、localStorage、日志、Git、错误文本、下载清单。provider cookie/浏览器凭据不得抓取。
- 所有项目、任务、资产、下载、审核先做 tenant 校验，再检查 providerAccountId/spaceId 对应关系。别人的对象返回 404；cookie 写请求同时校验 Origin 与 CSRF token。OAuth callback 独立校验一次性 state、session 绑定、PKCE；禁止开放重定向。
- 所有后端网络/CLI/数据路径只能由受验证的服务对象决定，浏览器不能传 token、文件系统根路径、任意上游 URL 或任意 tenantId。

## 2. HTTP 与模块调用

最终公共接口统一 `/api/v1/`；JSON UTF-8、时间 UTC ISO-8601、内部 ID 为不透明字符串。GET 无写入业务副作用（首次站点 session 引导除外）。Cookie 会话的变更请求带 `X-CSRF-Token` 和发起编辑时的 `X-Asset-Lab-Session`，后者必须等于当前 Cookie 所属 session.id；缺少或不匹配返回 409 WORKSPACE_CONTEXT_CHANGED。该字段只做上下文比较，不能授予访问权或指定 tenant。创建/提交任务另带 `Idempotency-Key`。同键同正文返回同结果，同键不同正文返回 409；幂等记录在进程/发布重启后保留。

上面的路径相对站点安装前缀。若第 9 会话采用候选 `/asset-lab/`，配置 `ASSET_LAB_BASE_PATH=/asset-lab`，外部路径为 `/asset-lab/api/v1/...`，公共 adapter 去前缀后匹配本文路由。OAuth redirect URI 必须包含实际前缀并经官方准入；前端从统一 bootstrap 的 basePath 构造资源/API URL，不能硬写根目录。这是部署适配约定，不是已上线地址。

成功：`{"data": {...}, "meta": {"requestId":"...", "apiVersion":1}}`。列表 data 为 `{items, nextCursor}`。错误：`{"error":{"code":"...","message":"面向用户的简短原因","retryable":false,"details":{}},"meta":{"requestId":"...","apiVersion":1}}`。501 `NOT_IMPLEMENTED`、401 `SESSION_REQUIRED`、403 `FORBIDDEN`/`CSRF_FAILED`、404 `NOT_FOUND`、409 `VERSION_CONFLICT`/`SELECTION_CHANGED`/`OWNERSHIP_MISMATCH`、422 `VALIDATION_FAILED`、503 `PROVIDER_UNAVAILABLE`。不要把原始官方响应或签名 URL 作为 error details。

更新对象带整数 `expectedVersion`，成功原子递增 `version`。选择上下文使用 `expectedRevision`。请求 body 不接受 `tenantId`；所有 SQL/文件操作必须带服务端 `ctx.tenantId`。

框架无关的 Python 装配接口：

```python
# 契约示意，非已实现的代码。
register_routes(router, services)   # 各后端模块导出
router.add("GET", "/api/v1/tasks/{taskId}", handler)
# handler(ctx: RequestContext, params: dict) -> Response
# ctx: requestId, tenantId|None, siteSessionId|None, method, path,
#      headers, query, json, csrfVerified, origin
# Response: status:int, body:dict|bytes, headers:dict
# services: storage, sessions, providers, spaces, tasks, workflow, releases,
#           config, clock（依赖由第 10 会话装配，未实现显式 unavailable）
```

模块注册时声明公开路由（health、首次 session、OAuth callback）；默认所有路由要求站点 session。JSON 解析、体积上限、Origin/CSRF、requestId、错误 envelope 由公共 adapter 处理；对象归属和事务由业务模块再次验证。标准返回 JSON status/body；下载使用 bytes + MIME/Content-Disposition，仍必须鉴权。

前端 `api.request(path,{method,body,idempotencyKey})` 自动加 `/api/v1`、credentials 与 CSRF，解析成功为 `data`，失败抛带 `code/message/retryable` 的 Error；不静默 retry POST。所有组件经同一 `api` 请求，不复制 provider 状态。

## 3. 站点 session / 当前选择

`GET /session` → `{session:{id,expiresAt},tenant:{id},csrfToken,selection,features}`。首次匿名引导分配全新隔离 tenant；后续 Cookie 恢复。匿名会话不是已验证邮箱/手机号，产品如要求跨设备找回需另设站点身份验证。

当前响应还包含 workspace。主账号恢复使用 backend/sessions/OWNER_RECOVERY.md 与 frontend/accounts/OWNER_UI.md 的明确确认契约。workspaceOwnerAuthorization 默认 false，生成账号不授予工作区所有权。POST /session/anonymous 是唯一无旧 CSRF 的显式匿名创建入口：精确 Origin、X-Asset-Lab-Action:new-anonymous-workspace 和 body {confirmNewWorkspace:true} 缺一不可，且现有有效 Cookie 返回 409；不接受 tenant 或 provider 身份。只会建立新的空白工作区，进入旧工作区仍需新鲜 owner OAuth。

```json
{"providerAccountId":null,"spaceId":null,"revision":0}
```

`PUT /selection` body `{providerAccountId,spaceId,expectedRevision}` → 新 selection。服务端核对账户属于 tenant、未移除，空间属于该账户且可访问；切换只影响后续新任务，绝不批量修改历史 ownership。更换账号时必须同时提交该账号有效的 spaceId，或显式清空空间，不能保留上个账号的空间。读到过期/失权空间应禁用新提交，并保留旧任务的文字标识。

`features` 明示 `{providerAuthorization:false,imageGeneration:false,videoGeneration:false,scriptAnalysis:false,persistentProjects:false}` 的真实可用值；只有完成实现和验收才能置 true。

## 4. 账号 / OAuth

`GET /provider-accounts` 返回公开账号列表。公开实体示例：

```json
{"id":"pa_example","provider":"libtv","label":"我的账号","version":1,
 "identity":{"issuer":null,"subject":null,"displayName":null,"verified":false},
 "authorization":{"state":"unconfigured","expiresAt":null,"lastVerifiedAt":null,
                  "reason":"official_client_registration_unverified"},
 "capabilities":{"authorize":false,"spaces":false,"quota":false},"removedAt":null}
```

授权 state：`unconfigured | authorizing | connected | expired | revoked | error | removed`。`connected` 只在成功换取令牌、验证官方身份及最小读取后设置；跳到授权页不算 connected。过期与刷新失败可恢复，但不能悄悄改用另一账号。`authorization` 不返回 token。

| 方法/路径 | 输入 | 输出/约束 |
|---|---|---|
| POST `/provider-accounts/authorize` | `{provider:"libtv",returnPath:"/"}` | `{attemptId,authorizationUrl,expiresAt}`；仅官方 HTTPS 授权页，returnPath 本站白名单相对路径 |
| POST `/provider-accounts/{id}/reauthorize` | `{expectedVersion,returnPath}` | 同上；回调 subject 必须匹配旧身份，否则拒绝覆盖，可另走添加账号 |
| GET `/oauth/libtv/callback` | 官方 code/state 或 error | state 单次消费、短时过期、绑定租户与 PKCE；服务端换 token，不回传浏览器；303 回本站结果页 |
| GET `/authorization-attempts/{id}` | — | `{status:"pending|completed|failed|expired",providerAccountId:null,error:null}`；仅本人可读，不暴露 code/state |
| DELETE `/provider-accounts/{id}` | `{expectedVersion}` | `{removed:true,remoteRevocation:"confirmed|unsupported|failed",affectedTaskIds:[]}`；撤销本站可用凭据并 tombstone，保留项目、文件、任务归属 |

同租户重复添加相同 verified subject 采用同账号恢复，不能伪造第二真实登录。两个真实身份隔离必须另行实测；独立 CLI 目录空白测试不算该验收。第三方网站接入必须验证官方客户注册、HTTPS redirect URI、授权 scope、资源 audience、token 刷新/撤销，以及账号 subject 获取方式。未核实就 `unconfigured`，不可自行假造 OAuth URL。

ProviderService（第 2 会话）对其他模块提供：`begin_authorization(ctx, providerAccountId?, returnPath)`、`complete_authorization(ctx, callback)`、`get_account(ctx,id)`、`list_accounts(ctx)`、`remove_account(ctx,id,expectedVersion)`、`client_for(ctx, ownership)`。返回的 ProviderClient 绑定不可变账户/空间，提供 `identity()`、`list_spaces()`、`quota(spaceId)`、`list_models(spaceId)`、`prepare(spec)`、`submit(prepared,idempotencyKey)`、`lookup(receipt)`、`download(receipt)`；未支持的方法抛 `PROVIDER_CAPABILITY_UNAVAILABLE`，绝不退回全局 CLI 登录。

## 5. 空间与积分

`GET /provider-accounts/{id}/spaces` → `{items:[{id,kind:"personal|team",name,access:"available|revoked|unknown",checkedAt}],nextCursor:null}`。列表失败保持 unknown/错误，不伪造个人空间。provider 的 accountId 若实际表示团队，只能映射为 spaceId。

`GET /provider-accounts/{id}/spaces/{spaceId}/quota`：

```json
{"providerAccountId":"pa_example","spaceId":"space_example",
 "state":"unknown","remaining":null,"unit":"credits","buckets":[],
 "planName":null,"source":"official","observedAt":null,"expiresAt":null,
 "reason":"provider_did_not_return_balance", "checkedAt":"2026-11-01T06:00:00Z",
 "officialViewUrl":"https://www.liblib.tv/"}
```

state 为 `known | unknown | stale | unavailable`。`remaining:0` 只允许官方实际返回零；套餐名称/等级不推算积分；币种、积分与不同额度桶不相加。stale 允许显示带时间的上次值，但不得当实时可支付保证。空间切换后重读自己的 quota，不能复用上个账户缓存。缓存键至少 `(tenantId,providerAccountId,spaceId)`，明确 observedAt。未知余额不自行认定支付能力，收费提交需要真实参数/报价和用户明确确认；此开发轮统一禁止提交。

`checkedAt` 是本服务完成本次账号/空间余额查询的时间，`observedAt` 是官方数值的观测时间；前者不能证明后者存在。当前授权接口未提供数值时返回 `reason=provider_capability_unavailable`，保留 `remaining=null`。顶部“查询余额”和账号面板的重查都会调用此路由，不因静态 capability 标志而直接显示假查询结果。仅暂时失败且归属完全相同的历史数值可标为 stale；身份错误会清空。官方分项余额逐项显示，不拼成合计。

## 6. 项目与资产流程

模块 8 路由：`GET/POST /projects`，`GET/PATCH /projects/{id}`；`POST /projects/{id}/scripts` 接收 `{filename,contentBase64}`（TXT/MD/DOCX ≤8 MiB，解压后文本 ≤250000 字，拒绝路径、压缩炸弹、不可读格式）；`GET /projects/{id}/scripts/{scriptId}`；`GET/PUT /projects/{id}/plan` body 包含 expectedVersion、entities、stylePrompt；`GET /projects/{id}/assets`；`POST /assets/{id}/reviews` body `{revisionId,sha256,decision:"approved|changes_requested",note,expectedVersion}`；`GET /projects/{id}/export` 下载通过审核的资产和无秘密清单。资产读取/缩略图统一 `/assets/{id}/content` 或 `/assets/{id}/thumbnail`，服务端鉴权，不能暴露整个 dataRoot。

导入只表示文件保存。文本模型未验证时 analysis 为 unavailable，不得用导入成功替代拆解完成。手工清单无需先调用模型。Entity 至少 `{id,category:"character|scene|prop",name,description,origin:"script|manual",quote,version}`，可按需求扩展 effect，不能漏掉未生成实体档案。

阶段为 `style → asset → refine`，recipe 为 `mj_style | image2_asset | nano_refine | script_analysis`，展示名独立于官方实际 modelKey；模型/key/schema 从官方读取验证后绑定，不用名称猜测。每次输出均 `review=pending`，人工 approved 后才能成为下一阶段参考。阶段状态与任务 completed 分离；文件返回不等于定版。

素材 revision 记录 `{id,assetId,projectId,tenantId,ownership,stage,sourceRevisionIds,sha256,mime,width,height,review,status,createdAt}`。Nano 返修必须追到原始 Image2 revision，记录 `refineSourceRevisionId`，禁止以损失细节的 Nano 输出再次精修。改变参考或源版本将下游标记 stale。历史素材复用默认限定同租户且同 owner；跨账号/空间复用需要以后明确的复制/授权动作和来源记录，不能隐式混用。

## 7. 任务 ownership / 状态机

`POST /tasks/prepare` body `{projectId,recipe,entityId,prompt,sourceRevisionIds,settings,expectedSelectionRevision}`。服务端从 session 选择构造 ownership，在**准备任务时**一次固定，校验所有源文件属于租户，原子存储草稿与请求摘要。浏览器不能覆盖 ownership。返回 `{task,confirmation:{token,expiresAt,summary},cost}`；cost 不可确认时 `{state:"unknown",amount:null,unit:null}`，不能当免费。

```json
{"tenantId":"tenant_example","provider":"libtv","providerAccountId":"pa_example",
 "providerSubject":"official-subject-example","spaceId":"space_example",
 "spaceKind":"personal","boundAt":"2026-10-27T00:00:00Z",
 "accountLabelAtCreation":"我的账号","spaceNameAtCreation":"个人空间"}
```

`POST /tasks/{id}/submit` body `{expectedVersion,confirmationToken}`。confirmation 绑定任务版本、owner、prompt/schema/source 哈希、数量与报价。切换当前账户不能改写草稿 owner；若 selection 已变化，UI 明示任务仍使用原账号/空间并重新确认该任务，服务端校验确认摘要，绝不默认改绑。开发配置 `allowPaidSubmission=false`、`videoGeneration=false` 必须服务端强制拒绝提交，不能只禁用按钮。

`GET /tasks?projectId=&providerAccountId=&spaceId=&cursor=`、`GET /tasks/{id}`；`POST /tasks/{id}/recover` `{expectedVersion}` 只查原 provider receipt；`POST /tasks/{id}/cancel` 只表示本地停止/请求取消，官方未确认不可标成退款/远程停止。每条 task 记录 `version,ownership,recipe,status,providerReceipt,submissionAttempted,sourceRevisionIds,outputs,review,createdAt,updatedAt,error`。公开 receipt 不泄露 token/签名下载 URL。

状态：`draft → preparing → submitting → queued → running → downloading → completed`；异常 `failed | needs_attention | blocked_authorization | cancelled`。`completed` 表示结果已可靠入库存储并校验，review 独立仍可 pending。提交前持久化 idempotency 和 submissionAttempted，官方返回后持久化 receipt，再推进状态。网络超时且是否接受不明 → needs_attention，只查询原任务，不自动重发。进程重启扫描未完成任务，必须按 task.owner 恢复客户端，禁止使用当前 UI selection。

重授权仅允许同 subject，新 grant 可恢复旧任务；移除账号后保留 ownership、历史文件、review 和 receipt。待执行任务 blocked_authorization，远端已运行任务不谎称停止。服务器不能凭当前登录账号接管已移除账号任务。两个租户相同 provider 登录也不能互读数据。

TaskService（第 7 会话）：`prepare(ctx,spec,expectedSelectionRevision,idempotencyKey)`、`submit(ctx,id,expectedVersion,confirmationToken,idempotencyKey)`、`get/list/recover/cancel(ctx,...)`。WorkflowService（第 8 会话）生成 spec、管理 source 与 review，通过 TaskService 调度，不自行起第二套 worker 或调用全局 provider。

## 8. 存储与发布分离

`ASSET_LAB_DATA_DIR` 必须为 release 目录以外的绝对路径；第 3 会话配置/校验并集中管理。建议结构 `state.sqlite3`、`tenants/<tenantId>/projects/...`、`tenants/<tenantId>/blobs/...`、`private/`（加密授权/会话）、`backups/`。密钥单独位于服务器 secret 配置，禁止和备份明文混放。路径 ID 由服务端生成，resolve/归属校验，拒绝穿越和符号链接逃逸。

Store 边界：`transaction(ctx)`、带 ctx 的 CRUD/CAS、`idempotency(ctx,key,requestHash)`、`blob_put/get(ctx,...)`、`migrate()`；租户条件由仓储强制注入。必须原子持久化任务+ownership+幂等，不让内存队列决定是否已提交。多个 worker 需要租约/锁，单一 worker 也需要跨重启防重复。

部署采用独立 release 目录/切换 current 与外置 data，代码包不携客户数据。升级前备份与数据库迁移检查；回滚只能用于兼容 schema，不能简单覆盖真实数据。具体远端路径、域名、TLS、服务管理方式需第 9 会话读取 kelao 当前规约和端口后确定，本会话未部署。

## 9. 版本 manifest / 浏览器更新

第 9 会话实现 `GET /version`（当前运行构建）与 `GET /releases/latest?channel=stable`（服务器核验后的最新版本；前端不请求任意 URL）。manifest v1：

```json
{"schemaVersion":1,"product":"asset-lab-customer","channel":"stable",
 "version":"0.1.0","buildId":"git-commit-or-build-id",
 "publishedAt":"2026-10-27T00:00:00Z","apiVersion":1,
 "dataSchemaVersion":1,"minCompatibleClient":"0.1.0",
 "releaseNotes":["示例更新说明"],"reloadRequired":true,
 "entryUrl":"/","integrity":{"algorithm":"sha256","value":null}}
```

示例不是正式可发布 manifest；真实发布必须填真实 buildId/时间/checksum，确认来源为受信任 HTTPS 与允许的 origin。必须按语义版本比较，禁止字符串比较。静态资源内容哈希，HTML/版本接口合理 no-cache，避免代码和接口代际混用。

客户端状态 `idle | checking | up_to_date | update_available | offline | error | incompatible`，同时展示 currentVersion/latestVersion/checkedAt/releaseNotes。启动检查一次，建议 6 小时一次并抖动；页面不可见暂停轮询，重新可见且过期才查；提供手动检查（服务端短时限流/缓存）。离线不等于最新，未知最新版本显示 unknown，保留上次检查时间。

发现新版提示用户刷新；不强制刷新表单、下载或审核中页面。刷新前先将编辑草稿持久化并等待确认，有冲突时停止升级并保留内容。未完成任务由服务端持久化，刷新只重连；不注销 provider、不删项目/素材/授权、不清 localStorage 全域。旧 API 不兼容时进入保存/只读提示，禁止新的收费操作。生产代码发布、数据迁移与浏览器刷新是三个不同状态，分别验收。

## 10. 必需验收场景

第 10 会话使用合成数据和无费用 provider fake 验证：两个 tenant 无交叉访问；两个 provider 身份隔离；个人/团队切换；旧 task 永远保留原 owner；重授权错 subject 拒绝；重复提交/超时恢复不二次生成；移除账号保留历史；刷新/重开 session 与工作恢复；未知额度显示未知；更新提示、草稿保存、版本不兼容；每阶段人工审核；Nano 原始 Image2 来源；开发模式所有收费与视频提交都被后端拒绝。

真实官方 OAuth 和双账号验证需由用户实际授权配合；没有该证据时明确写“协议/模拟验收通过，真实身份接入未验收”。真实部署须以域名访问、服务、持久化与升级回滚证据为准，不以本地 200 代替上线。

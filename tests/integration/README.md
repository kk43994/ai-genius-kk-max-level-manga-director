# 公共装配与验收接口 · 检查点 1

业务 HTTP 契约仍以 `docs/api-contract.md` 为准。本文件补充第 10 会话已经实现的 Python adapter 细节，避免模块自行猜测。当前只验收公共骨架；合成测试不计入真实账号/项目/任务业务验收。

## 后端接线

公共类型来自 `backend.app`：`Config`、`RequestContext`、`Response`、`APIError`、`Router`、`Services`。用 `python -m backend.app` 启动也保持同一类型身份。

```python
from backend.app import APIError, Response

def create_service(services):
    # 可选工厂：返回本模块服务。不可在这里读取全局 CLI 或恢复原工程任务。
    # 配置 services.config，其他服务 services.storage / services['storage'] 等价。
    return MyService(services.storage, services.config)

def register_routes(router, services):
    def read(ctx, params):
        # tenantId / siteSessionId 仅由 sessions.resolve_request 得到。
        # 对象归属还须在本模块仓储中验证。
        return Response(200, services.tasks.get(ctx, params['taskId']))
    router.add('GET', '/api/v1/tasks/{taskId}', read)
```

路由参数名可为 `{id}` 或 `{taskId}`。同方法且形状相同的两个路由是启动错误，不能靠注册先后覆盖。静态片段优先于参数片段。HEAD 沿用 GET，只省略响应正文；GET 不得写入业务状态（契约允许的首次 session 引导除外）。公共路由须显式传 `public=True`；除此之外均先校验本站 session。

`create_service(services)` 按 `storage, sessions, providers, auth, spaces, tasks, workflow, releases` 顺序执行，返回值绑定到同名服务。随后统一 `register_routes(router,services)`。没有工厂的模块也可以在注册时向 services 写入已构造服务，但应避免依赖注册顺序。服务暂缺时拿到 `UnavailableService`，其 `available=False`，不能当成有效 provider；丢失内部依赖会阻止启动。

RequestContext 字段：`requestId, tenantId, siteSessionId, method, path, headers, query, json, csrfVerified, origin, cookies, session, publicPath`。`path` 是内部 `/api/v1/...`，`publicPath` 是浏览器实际挂载 URL；`headers.get()` 大小写不敏感；query 为字符串键值字典，重复键拒绝；json 为对象；cookies 是已解析的字符串字典。不要把 context/session 整体序列化进响应或日志。

返回 `Response(status, body, headers)`，或 `{status,body,headers}`，或作为成功数据的普通 dict。JSON 自动加 `{data,meta:{requestId,apiVersion}}`，已包好的 `{data,meta}` 不重复套层。`APIError(status,code,message,retryable=False,details={})` 生成规范 error；只使用面向客户的安全 message/details，不放上游原始响应。非预期异常只返回 `INTERNAL_ERROR`，日志仅含随机 requestId 和异常类型。二进制下载用 bytes 加 Content-Type/Content-Disposition；仍要求 session 与对象归属。只允许本站相对 Location，公开 OAuth URL 应通过 authorize JSON 返回给浏览器。

模块错误/成功响应不能覆盖公共安全头与 API no-store 缓存策略。所有 Cookie 写请求先检查配置 Origin，再调 sessions.verify_csrf。`tenantId` 作为顶层 body 参数会被拒绝。模块仍须验证字段白名单、ownership、事务、对象版本、任务来源和幂等摘要；公共层不代替这些检查。

## 站点 session 模块的最小适配

```python
sessions.resolve_request(ctx)
# 返回 None，或 {tenantId: str, siteSessionId: str, ...}，也可同名属性对象。
# 只能从安全 Cookie 查服务端会话；不信任 headers/query/body 的 tenant。

sessions.verify_csrf(ctx, presented_token) -> bool
# 必须返回 True 才允许写入；校验对应本站 session 的 token。
```

`GET /api/v1/session` 是公开注册路由，由 session 模块负责首次引导、持久化、设置 Cookie 与返回 csrfToken。公共 adapter 不提供内存 session fallback。Cookie Path 取 `services.config.publicBasePath`，正式 HTTPS 设置 Secure；刷新/重开、过期、重启恢复均由集成后的存储与 session 测试确认。

## 账号级空间发现

协调会话要求的最小补充接口是 `providers.account_client_for(ctx, ownership)`，在还未选空间时只读身份/空间列表。该入口必须校验 tenant、providerAccountId、official subject；只允许 `identity()` 与 `list_spaces()`，不能借此调用 quota/model/generation。选定有效空间后仍用原 `client_for(ctx, ownership)`。不传虚构 spaceId。实现由授权/空间模块各自提供，集成验收见矩阵 `P03`。

## 配置与就绪报告

任务/工作流联调还须保留服务端生成的不可变 workflow snapshot/context（清单与风格版本），贯穿准备、持久化、查询、恢复和结果回收。缺少快照或源已换版时，旧任务结果不得入库为当前版本；浏览器提交的任意 snapshot 不能成为可信来源，也不能透传给 provider。字段持久化归任务模块，来源校验与入库归工作流模块，集成验收见矩阵 `W05`。

服务可读取 snake_case 字段，也可读取以下契约属性：`dataDir`（Path）、`publicOrigin`、`publicBasePath`（尾斜杠）、`apiBase`（无尾斜杠）、`allowPaidSubmission=False`、`videoGeneration=False`。clock 是 `services.clock()`，返回 UTC aware datetime。不得从浏览器接收本地根目录或任意上游 URL。

服务可提供无副作用的 `readiness() -> {ready:bool,reason:'stable_machine_code'}`。缺少接口是 `readiness_not_reported`，异常为 `readiness_check_failed`。公开 reason 只允许短的小写机器码，防止泄露上游响应。`GET <apiBase>/health` 只报进程存活；`GET <apiBase>/ready` 对缺失或未就绪服务返回 503。真实 callback、subject/空间/模型、双账号和公网发布验收单列 false，不自动由 fake 测试或 factory 加载改为完成。

此检查点在所有 submit 上强制收费禁用。视频 prepare 或标注 `capability='videoGeneration'` 的路由同样拒绝。新收费路径须声明 `capability='paidSubmission'`，不得绕过公共提交入口。

## 前端与子路径

所有外部 URL 由 `publicBasePath`、`apiBase` 明确配置。路由注册仍写内部 `/api/v1/...`，adapter 在边界映射。静态文件相对 publicBasePath 提供；子路径实例不暴露根 `/api`。旧 `/dashixiong-scene-studio/...` URL 只在本挂载内做相对重定向，避免首页相对资源路径漂移。

页面可读取与入口同目录的 `app-config.json`（普通 JSON）或 `_app/config.js`（导出 `config`），已迁移 HTML 中另有 `script#asset-lab-config[type=application/json]`。集成 bootstrap 后续应读取这一个配置并以参数传入 `api` 和 `mount({root,api,events,session})`，不猜 window 全局，不给每个模块另建账户/session 状态。

尚未合并模块 5/6/7/8/9 的 JS，因此本检查点只提供空白集成页。不会创建账户/更新/任务组件的假实现，也不会修改它们的独占目录。

## 合并与最终验收顺序

1. 接收明确的模块克隆路径与 commit；记录来源，逐个 cherry-pick。公共入口冲突由第 10 会话处理，其他模块文件只做有证据的兼容修复。
2. 先接存储/session → provider/auth → spaces → tasks/workflow → releases，再接页面/API 客户端与账户、任务、流程、更新组件。每轮只运行相关模块测试与集成冒烟。
3. 用两个合成租户、两个 provider fake 和独立数据目录完成 `acceptance-matrix.json`。验证进程重启与切换上下文，不以当前选择重绑旧任务。
4. Chrome 在根路径与 `/asset-lab/` 跑完整客户流程、失败恢复、审核/返修/导出与更新保存；再做窄屏布局检查。把模拟证据与真人官方授权证据分开。
5. 真实 OAuth 与公网部署按独立门槛处理；付费生成和视频本轮保持禁用。打包前确认未把原工程数据、凭据、媒体或旧运行目录带入。

当前测试命令：`python3 scripts/check_integration.py --output /absolute/evidence.json`。Tests 里的 FixtureSessions 仅用于公共 HTTP 边界测试，不是任何可部署服务。对 fake 对象返回 404 只能证明 context 接线正确，不能替代实际 storage 的跨租户查询验收。

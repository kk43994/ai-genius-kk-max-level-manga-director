# 第 7 模块：任务归属、状态与安全恢复

本模块只实现任务业务、任务自己的路由注册及依赖适配，不启动 HTTP 服务、不启动第二套 worker、不读取 CLI 登录、不访问真实 LibTV、不修改公共入口或共享存储源码。默认 `allow_paid_submission=False`，所有新生成提交由服务端拒绝；视频 recipe 始终拒绝。测试中开放提交开关的实例只连接内存 fake。

## 接线

`TaskService` 从 `backend.tasks` 导入；`register_routes(router, services)` 使用 `services.tasks`。`Response` 提供 `status/body/headers`，公共 HTTP adapter 负责 requestId/meta、session、JSON 大小、Origin、CSRF；本模块变更路由还会检查 `ctx.csrfVerified is True`。`ctx.tenantId` 只能来自已验证的服务端会话。跨租户对象返回 404。

```python
from backend.tasks import TaskPolicy, TaskService, register_routes
from backend.tasks.adapters import (
    SelectionAdapter, SpaceAdapter, StoreOutputStore, StoreTaskRepository,
)
from backend.storage import SelectionRepository
from backend.workflow import WorkflowOutputStore

selection_repository = SelectionRepository(services.storage)
task_repository = StoreTaskRepository(
    services.storage,
    # 必须读传入事务；不能在此调用会另开事务的 selection_repository.get(ctx)。
    # 第 3 模块当前实现名称为 _get；集成层可换成相同语义的公开方法。
    selection_reader=SelectionRepository._get,
)
tasks = TaskService(
    repository=task_repository,
    providers=services.providers,
    selections=SelectionAdapter(selection_repository),
    spaces=SpaceAdapter(services.spaces),
    inputs=services.workflow,
    outputs=WorkflowOutputStore(services.workflow, task_repository),
    policy=TaskPolicy(
        confirmation_key=server_confirmation_key,  # 独立、持久的至少 32 字节服务端密钥
        allow_paid_submission=False,
        video_generation=False,
    ),
)
services.tasks = tasks
services.workflow.tasks = tasks
# ProviderService 的 on_account_removed 回调接 tasks.block_account。
register_routes(router, services)
```

`StoreTaskRepository` 仅通过共享 `Store.transaction`、CRUD/CAS 存储 `tasks` 和 `task_requests`。任务记录与幂等记录同事务提交；准备时的当前选择 revision 也在同一事务中核对。共享 Store 的 immutable_fields 还会拒绝修改 ownership、项目/实体、spec、inputs、inputHash、参考列表和创建时间。

`StoreOutputStore` 可单独验证公共 blob 存储，或供非工作流消费者使用；**完整资产流程应接 `WorkflowOutputStore`**，才能建立 revision、执行真实图片解码、保留 Nano 来源以及标记旧版本失效。原始 blob 适配器不代表资产审核流程已完成。文件先落盘再提交任务 metadata；崩溃可能留下未被引用的私有 blob，但不会生成完成任务或重复可见 revision。公共存储后续可以收集这些孤立 blob。

## 已实现 API

| 调用 | 行为 |
| --- | --- |
| `prepare(ctx, spec, expectedSelectionRevision, idempotencyKey)` | 校验项目与参考、固定 owner、原子登记请求，再做官方准备。返回 task/confirmation/cost。 |
| `submit(ctx, id, expectedVersion, confirmationToken, idempotencyKey)` | 默认禁用；启用时二次核验原身份、原空间、输入快照，持久化 attempted 后才可调用一次 provider.submit。 |
| `get(ctx, id)` / `list(ctx, projectId=..., providerAccountId=..., spaceId=..., cursor=..., limit=50)` | 只读；输出公开状态及安全的原任务引用，不触发生成或恢复。 |
| `recover(ctx, id, expectedVersion)` | 只查原 receipt；验证原身份后下载，校验文件及存储回读，再写 completed。 |
| `cancel(ctx, id, expectedVersion)` | 停止本站处理；返回 localOnly=true、remoteConfirmed=false、refundConfirmed=false。 |
| `confirm(ctx, id, expectedVersion)` | 对原归属显式重新确认，处理切换选择或过期的确认；从不重新绑定 owner。 |
| `block_account(ctx, providerAccountId)` | 账号移除/失权回调；保留所有历史字段、结果与官方引用。 |
| `reconcile_after_restart(ctx)` | 只处理已过期租约，不接触 provider；已尝试的提交转 needs_attention。 |
| `recover_pending(ctx, limit=50)` | 调度器的一次有界查回 tick；只调用 lookup/download，不会 submit。 |

对应路由遵循 `docs/api-contract.md`。额外的最小兼容扩展是 `POST /api/v1/tasks/{taskId}/confirm`，body `{expectedVersion}`，返回与 prepare 一致的 task/confirmation/cost。公共契约文档和入口未改；第 10 模块注册这些模块路由即可。

同幂等键同正文返回原任务当前状态；同键不同正文 409。换幂等键也不能重提已 attempted 的任务。幂等响应不会把状态倒退成旧的 queued，也不会因当前账号已切换而改写归属。未知 cost 固定为 `{state:"unknown",amount:null,unit:null}`，绝不当作免费或余额。

确认摘要绑定：task id/version、完整 ownership、prompt/settings/source hash、工作流 snapshot、官方 model/schema hash、数量、报价、当前选择 revision、到期时间。confirmation token 用持久服务端密钥签名；任务 JSON 只保存摘要，不保存可重用明文 token。密钥轮换会使旧确认失效，任务数据仍保留。

## 第 8 模块的快照与输出接口

`inputs.validate_task_inputs(ctx, spec, ownership)` 必须返回：

```python
{
    "projectTenantId": ctx.tenantId,
    "spec": canonical_spec,  # 与收到的 v1 spec 等价
    "sources": [{
        "revisionId": "rev_x", "sha256": "64 lowercase hex",
        "ownership": source_owner, "review": "approved", "stale": False,
    }],
    "workflowSnapshot": {
        "entityVersion": 1, "styleVersion": 2,
        "sourceHashes": {"rev_x": "64 lowercase hex"},
    },
}
```

`workflowSnapshot` 必须来自服务端项目/清单/参考读取；浏览器 spec 禁止包含此字段。任务把它保存在不可变 `task.inputs.workflowSnapshot` 中并纳入 `inputHash`；公开 task 也返回该安全快照，刷新、查回不会丢失。可兼容额外整数 `planVersion`，其他未知字段拒绝而非丢弃。

提交前、收图入库前后都会重新比较快照与源文件摘要。缺失快照 `WORKFLOW_SNAPSHOT_MISSING`；版本变化 `WORKFLOW_VERSION_CHANGED`；文件摘要变化 `SOURCE_CHANGED`，均保留原 owner/receipt 并停止推进。不会用当前版本补造旧任务快照。工作流在其自身提交事务中再次保护版本：如果恰在最后入库窗口发生修改，旧 revision 只能成为 stale 历史，任务再次核验后进入 needs_attention。

内部快照不进入 provider.prepare/submit 的模型参数。任务向 provider 传入的 `requestHash` 是不透明摘要，仍覆盖内部快照；模型 spec 仅为允许的 v1 字段。`WorkflowOutputStore.put` 会从 task_repository 重新读取持久任务，因此不接受浏览器伪造的 task。输出中的 assetId/revisionId 经格式校验后保留在 task.outputs，且 review 始终 pending。

## ProviderClient 的最小归一化协议

ProviderService 的 `get_account(ctx,id)` 和 `client_for(ctx,ownership)` 使用公共 v1 约定。所有调用都传 task 原 owner；没有当前账号兜底。`identity()` 至少返回已验证的 `{issuer,subject,verified:true}`；若带 providerAccountId/spaceId/spaceKind/provider，全部必须匹配原 owner。空间权限还会独立通过 `SpaceService.assert_space_access` 重新读取。

当前官方授权模块的 BoundProviderClient 尚未实现 prepare/submit/lookup/download；未支持时必须抛 `PROVIDER_CAPABILITY_UNAVAILABLE`，不能用 fake 或全局 CLI 填补。以下是**适配协议，非已核验的 LibTV 原始响应字段**：

```python
client.prepare({**spec, "ownership": owner, "requestHash": input_hash,
                "sources": source_snapshot, "localTaskId": task_id})
# => {modelKey, schemaHash: "sha256", requestHash: input_hash, count,
#     cost: {state,amount,unit,expiresAt?}, providerReceipt?}

client.submit({**prepared, "spec": spec, "sources": source_snapshot,
               "ownership": owner, "localTaskId": task_id}, server_idempotency_key)
# => {status:"queued|running|completed", providerReceipt?}

client.lookup(receipt)
# => {status:"queued|running|completed|failed|cancelled|not_found|unknown",
#     providerReceipt?}

client.download(receipt)
# => [DownloadArtifact(content=verified_bytes, mime="image/png", sha256=optional_official_sha)]
```

公开及持久 receipt 只接受 `taskId/projectId/nodeId/requestId` 的不透明 ID，拒绝 URL、签名参数或原始响应；新 receipt 只能补全，不能改变已有 ID。未知提交状态中的有效引用也会保留。typed provider exception 可带 `provider_receipt`；异常文本永远不写日志、状态或响应。官方 adapter 负责实际网络限时、授权有效性、模型/schema 回读和图片格式识别，任务再做数量/大小/SHA-256/落盘回读校验。

Provider 的 prepare 不得产生收费生成；如准备本身结果不明，任务停在 needs_attention，不自动再次 prepare。官方 submit 是否支持幂等尚未真实验证；即使不支持，本模块也不会因 timeout/crash 重新调用它。

## 状态、并发与恢复边界

- 草稿 ownership 固定客户、LibTV 内部账号 ID、官方 issuer/subject、个人或团队空间及创建时显示名。
- `preparing` 预检与 `submitting` 已尝试标记分开。后者必须提交到持久事务后才能发出生成调用。磁盘提交失败时生成调用数为 0。
- 每个任务有持久租约；陈旧预检 worker 失去租约后不能提交。即使租约超时，attempted 标记仍阻止第二次生成。
- 服务重启后保留官方 canvas/node/task 引用。缺少引用时给出 `ORIGINAL_RECEIPT_REQUIRED`，不会搜索当前账号、另建节点或盲重发。
- 授权失效为 blocked_authorization；恢复授权仍必须匹配原 issuer/subject/space。删除账号不是远端取消；晚到的提交回执在本地取消或移除后仍会被保留。
- completed 仅代表下载数量及 bytes 校验、持久存储回读成功；不代表人工审核、定版、退款或远程任务停止。
- `recover_pending` 由集成层调度并传可信 tenant context。不能在 GET 请求里恢复业务，也不能因为页面刷新新建任务。站点登录跨设备/清 Cookie 的找回机制仍由 session 模块负责。

## 验证

独立模块不需要第三方依赖：

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests/tasks -v
```

未合并第 3/8 模块时，共享模块联调测试明确 skip，不伪造通过。集成后安装其依赖再执行同一命令；也可以在本模块独立克隆中设置只读模块目录进行联调：

```sh
ASSET_LAB_STORAGE_MODULE_ROOT=/absolute/path/to/module3/repo \
ASSET_LAB_WORKFLOW_MODULE_ROOT=/absolute/path/to/module8/repo \
python -W error::ResourceWarning -m unittest discover -s tests/tasks -v
```

覆盖：两租户/两身份/个人团队隔离、重复请求与并发提交、磁盘故障、提交前后进程中断、全新 Python 进程恢复、租约 fencing、同身份重授权、过期/撤销、缺失或矛盾 receipt、收图校验失败、本地取消时的晚到回执、快照遗漏/换版以及任务与真实工作流入库适配。

所有测试使用临时空白 Store、合成身份、内存 provider、合成小图片，无收费请求、真实 token、客户剧本或生产素材。真实官方 OAuth、两个真实登录账号、真实团队权限、真实 provider 任务回执及公网部署/浏览器重开仍需要各模块集成后的独立验收；本模块不宣称这些已完成。

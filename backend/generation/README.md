# LibTV 图片操作适配器

2026-10-28 本地验收增量：显式本地启动参数 `--enable-image-generation` 可启用
`LiveGenerationAdapter`。已真实完成一次 MJ 四图生成、官方交付及待审入库；也验证了参考图上传和未运行 Image2 节点的连线。
Image2 / Nano 收费生成与最终审核下载尚待本轮选图确认，不能宣称全流程验收完成。
详见 [本地真实验收记录](LOCAL_REAL_RUN_2026-10-28.md)。下文记录默认关闭的通用适配器及其初始集成边界；不代表本地增量的当前状态。

这是可注入第 2 模块的真实协议实现增量：代码会调用官方 MCP 工具、校验模型 schema、上传参考图、创建/回读节点、提交生成、查询原任务并下载图片。默认禁止所有外部写入；**目前没有生产响应映射、经过目录核验的 MJ/Image2/Nano 模型配置及媒体域名清单，不能宣称客户已能真实生图。** 缺项逐一列于 `EVIDENCE.md`。本次没有读取真实令牌、调用上传或付费生成。

基于集成仓库提交 `9d49c05d4969707002f37ec2f849263b92757941`；授权接口依据第 2 模块正式提交 `c56463a2dc0138585b4831ff74e5880f4dca1fef`。改动仅在 `backend/generation/`、`tests/generation/`。

## 冻结的接法

沿用第 2 模块已经兼容的 `operation_adapter=`，不要同时设置 `operation_adapter_factory=`：

```python
from backend.generation import (
    GenerationAdapter, GenerationPolicy, OfficialProjectResolver, ReferenceNodeRoute,
    StoreGenerationJournal, TaskSubmissionBridge, WorkflowReferenceReader,
    SafeMediaTransfer, ResponseContracts,
)

adapter = GenerationAdapter(
    journal=StoreGenerationJournal(store, context_for_original_owner),
    submission_bridge=TaskSubmissionBridge(task_repository, context_for_original_owner),
    project_resolver=OfficialProjectResolver(read_saved_project_candidate),
    references=WorkflowReferenceReader(workflow, context_for_original_owner),
    media_transfer=SafeMediaTransfer(allowed_hosts=(), evidence=''),
    recipes={},
    responses=ResponseContracts(),
    reference_route=ReferenceNodeRoute(),
    policy=GenerationPolicy(),  # 外部写入关闭；合成响应契约关闭
)
# 在第 10 模块的组合入口中传给现有 ProviderService：
# ProviderService(repository, codec, oauth, ..., operation_adapter=adapter)
```

这段默认配置故意不填未核实数据。`context_for_original_owner(ownership)` 是本站可信后端回调，返回该租户的有效 context；不可从浏览器提交的 tenantId 创建 context，也不能固定为管理员会话。三个 Store/workflow 适配器也支持直接传单租户 context，并验证它与 owner 一致。`read_saved_project_candidate(owner, local_project_id)` 从本站租户仓库返回 `ProjectBinding` 候选；`OfficialProjectResolver` 再用官方 `project_info` 核对项目、空间及空间类型，拒绝当前默认空间回退。

第 2 模块调用的精确接口：

```python
bound = adapter.bind(ownership=owner_copy, authorize=authorize)

# 每次重新检查固定租户、issuer、subject、账号、空间成员关系和实际 scope：
permit = authorize(frozenset(required_scopes))
# permit 是 backend.generation.types.AuthorizedMCP
# permit.ownership: dict
# permit.granted_scopes: frozenset[str]
# permit.call_tool(name: str, arguments: dict) -> MCP CallToolResult envelope
# 例如 {"structuredContent": {...}, "isError": False}

bound.list_models(spaceId=None)              # 原样返回官方目录字典，不猜列表位置
bound.get_model(model)                      # 精确名称/标识，原样返回官方 schema
bound.prepare(payload)                     # 只读官方请求 + 本地持久化
bound.submit(prepared, idempotencyKey)      # 必须有 TaskService 已落盘的确认提交
bound.lookup(receipt)                       # 只查询原任务/专属原节点
bound.download(receipt)                     # list[backend.tasks.ports.DownloadArtifact]
```

无需也不得给本模块传 access token、refresh token、cookie、Authorization header、CLI 路径或全局登录会话。quota 没有在此模块实现；现有空间模块保留未知额度语义。

`prepare` 接收任务模块现有的 projectId、entityId、recipe、prompt、sourceRevisionIds、settings，加上 ownership、requestHash、sources、localTaskId。只返回 modelKey、schemaHash、requestHash、count、未知 cost、providerReceipt。canonical 参数及参考快照存入现有 Store 的 `generation.operations`，不是另建数据库。`submit` 接收上述准备结果，加任务模块保存的 spec、sources、ownership、localTaskId，与现有 TaskService 调用完全一致。

## 已实现的行为

- `ToolCatalog` 使用 14 项公开工具完整 schema；验证请求、MCP envelope、错误标志及 JSON 输出，禁止外部 `$ref`、无穷数、超大响应。授权 transport 还会按当前 tools/list 独立核对 scope。
- `RecipeBinding` 不预置任何猜测模型或创作参数。通过 `get_model` 的经核验响应契约取得模型和 parameterSchemas，逐字段验证；保留准确数量，默认 1，最多 4。拒绝凭空出现的参数及网关保留的 model/provider/媒体列表字段。模型 schema 在提交前再核对；成本未获报价就保持 unknown。
- MJ 风格不带参考；Image2 必须引用一个已人工通过的 style 版本；Nano 必须引用一个已人工通过的原始 asset 版本。每次读取检查原租户/issuer/subject/空间、版本、review、stale、SHA-256、真实图片解码。上传结束后、收费前再复核来源及模型。
- `prepare` 不上传、不建节点、不调用交付工具。`submit` 必须在任务仓库找到 `submitting`、`submissionAttempted=true`、原 requestHash 和原 submissionKey。收费前已缺少查询/交付映射、scope 或媒体域名时直接停止。
- 无参考路线使用公开 `generation_submit` 精确输入，保存公开说明明确的 `task_id`；`cop_` 画布操作号不视作 Task SOT。返回 `queued` 仅表示已取得任务引用，不把它说成图片已完成。
- 参考路线：`upload_ticket` → DNS 固定的 HTTPS 分片 PUT → `upload_complete` → `upload_media` 完成审核 → `create_node(run=false,left=[...])` → `read_node` 核对原节点、保存状态、参数、连线及 revision → 本地保存 nodeId → `update_node(run=true,expectedRevision=...)`。不把 URL/imageList 放入 params。
- 上传、建节点、收费、交付都有先落盘的尝试标记。遇到超时、服务错误、协议不明或进程中断，同一步不会自动重发。已保存节点的收费超时可只读 `read_node` 查回与原幂等键对应的 taskId，再查询 `task_status`。没有原节点或任务 ID 时明确停止，不能按新键重提。
- 下载先确认原任务 completed 和 nodeId；按每个输出调用一次 `prepare_project_delivery`，保留水印，不改变账号偏好。保存每项操作 ID；后续只用 `get_web_operation_status` 查询原操作。未知结果不重发交付。回执必须仍指向原项目、节点及输出索引；不绕过官方交付直接取未知原图 URL。
- `SafeMediaTransfer` 只允许有证据的精确 HTTPS 主机及 443 端口。拒绝凭据 URL、私有/回环/链路本地或混合 DNS、重定向；连接固定到已核验 IP，TLS 仍核验原主机。不传 cookie/auth。限制声明长度与实际流量，核验 MIME、PNG/JPEG/WebP 单帧解码、像素与摘要。签名 URL 不进任务、journal 或异常文本。
- 下载返回 bytes，由现有 WorkflowOutputStore 保存到租户私有库并建立 `review=pending` 版本。此模块不替用户做保留/重绘决定。

## 集成需要第 10 模块处理的事项

1. 安装本目录 `requirements.txt`；storage/workflow 的 cryptography 等依赖仍由对应模块管理。
2. 在组合入口绑定同一个 Store、task repository、workflow 与按原 owner 取 context 的回调；注入第 2 模块 `operation_adapter`。不要开放新路由绕过 TaskService 确认。
3. 只有 `EVIDENCE.md` 所列字段得到同一 MCP 协议证据后，才能提供 `ResponseContract(verified=True)`、RecipeBinding 和 allowed_hosts；测试的 `synthetic=True` 映射不能复制成生产配置。
4. TaskService 当前 `provider_failure()` 只识别一部分授权错误，其他错误会归并成 `PROVIDER_OPERATION_UNCONFIRMED` / `SUBMISSION_UNKNOWN`。接入时需要在任务模块受控映射本模块的 scope/缺少 schema/缺少项目映射等固定错误，避免客户页面把“未开始生成、资料缺项”显示成不明提交。本增量没有越界改任务错误映射。
5. 公网 OAuth callback、真实 scope 扩权及正式 paid policy 是独立事项。本模块没有完成公网发布或扩大用户授权。

## 验证与重跑

```sh
python -m pip install -r backend/generation/requirements.txt -r backend/storage/requirements.txt
ASSET_LAB_AUTH_MODULE_ROOT=/absolute/path/to/module-2/repo python -m unittest discover -s tests/generation -p 'test_*.py' -q
```

48 项针对性测试通过，无跳过（设置了上述第 2 模块路径）。其中使用真实 Store、TaskRepository、TaskService、WorkflowService、WorkflowOutputStore 和第 2 模块 BoundProviderClient/BoundMCPTools 代码；远端响应、身份、scope、图片都为明确标记的合成样本，网络被阻断。没有设置 auth 路径时 3 项兼容测试会明确跳过。

覆盖了未确认/默认关闭/缺 scope、owner 与 issuer 隔离、模型漂移、数量与参数、审核/来源哈希变化、Nano 原图、收费重复、重开 Store 后的超时禁止重发、节点查回、交付恢复、错项目/任务/文件、图片内容、SSRF/重定向/大小/MIME，以及真实任务到工作流的待审入库。测试通过不等于生产响应已验证或真实付费图片链路验收完成。

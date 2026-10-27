# 后续图片 adapter 的最小注入契约

ProviderService 保持授权/密钥/账号/租户归属职责。图片 adapter 由独立模块提供，以 server-side factory 注入，默认没有 adapter，所有生成相关方法关闭。注入仅提供代码入口，不意味着批准额外 scope、公开发布或付费测试。

```python
def image_adapter_factory(*, ownership, tools):
    return OfficialImageAdapter(ownership=ownership, tools=tools)

providers = ProviderService(
    repository, codec, oauth,
    operation_adapter_factory=image_adapter_factory,
)
```

factory 接收两个参数：

- `ownership`：tenantId/provider/providerAccountId/providerSubject/spaceId，以及调用方已保存的其他归属字段的深拷贝。修改这份副本不能切换授权 transport。
- `tools`：`BoundMCPTools`，不提供 access_token、refresh_token、cookie、HTTP header 或底层 HTTP 客户端。repr 不含凭据。只提供下面两个方法。

```python
catalogue = tools.list_tools()
result = tools.call_tool(
    "task_status",
    {"project_id": verified_project_id, "task_id": saved_provider_task_id},
    space_id=ownership["spaceId"],
)
```

`list_tools()` 返回官方工具元数据。`call_tool()` 返回成功工具响应的 structuredContent 字典，或单段 JSON text 中的字典；网络、协议或工具错误只抛安全的 AuthError，不透传原始上游文本。若 schema 的 outputSchema 只有宽泛 object，adapter 必须验证具体响应后才能标记任务提交/完成。

每次工具调用都会核对本站 tenant、固定 provider subject、账号未移除/令牌可用、传入 space_id 等于绑定空间、官方成员列表仍包含该空间及 kind 一致；再从本次 tools/list 读取该工具的 securitySchemes，要求其 OAuth scopes 被实际 token scope 覆盖。没有声明 scope 的工具和 read scope 下的写工具不能经此接口执行。读取完成后再次检查本地账号可用状态。

外层 BoundProviderClient 转发同名方法及参数：quota、list_models、get_model、prepare、submit、lookup、download。factory 每次外层调用重新创建，不应依赖内存保存任务状态；任务归属和 provider task ID 必须持久化。外层最低 scope：quota 为 account:read，submit 为 task:write，其余为 project:read（均带 libtv: 前缀）；真实工具如上传需要的 media:write 仍由 transport 逐次检查。

## GenerationAdapter.bind 兼容接法

上述 factory 接口已冻结，同时兼容第 1 模块已经约定的 bind/authorize 接口。使用 `ProviderService(..., operation_adapter=GenerationAdapter(...))`；不可同时指定 factory。服务调用 `adapter.bind(ownership=deepcopy(owner), authorize=callback)`，再转发同名方法。

`authorize(required_scopes)` 每次重新核对固定租户/用户/空间成员关系与实际 token scope，返回第 1 模块的 `backend.generation.types.AuthorizedMCP`。`ownership` 为副本，`granted_scopes` 为实际 scope 的 frozenset；`call_tool(name, arguments)` 自动绑定原空间，每次调用仍执行实时归属/scope 校验，不保存或返回 token。它返回 `{"structuredContent": parsed_dict, "isError": false}` 格式的规范化 MCP result envelope，以兼容第 1 模块的 ToolCatalog.response。失败只抛 AuthError，不能把错误包装成成功 envelope。

两种接法的唯一区别是传入对象和成功返回形式：factory 的 tools.call_tool 需要显式 space_id、返回结果字典；bind 的 AuthorizedMCP.call_tool 已绑定 space_id、返回 MCP result envelope。不要将两个返回形式重复解析。

## adapter 必须补齐的业务校验

本 transport 验证的是账号成员关系，不知道 project_id 是否属于该 space。所有按项目调用之前，adapter 必须用官方证据验证**项目 → 绑定账号/空间**，并把 provider project ID 固定在任务 owner 中。`generation_submit` 的官方输入没有 accountId/teamId 参数；不得注入猜测参数、读取 CLI 默认账号、改远端当前账号，或拿 activeAccountId 替代任务归属。项目归属响应结构尚未实测，未核实前应返回 capability unavailable。

准备/提交还须复核已锁定的模型参数、用户确认、准确数量和幂等键；超时后按原幂等键/持久 task_id 查结果，不能用新键重提。资源上传和下载必须验证当前 owner、明确 file_ref、允许的服务地址、响应长度/类型；不能根据宽泛 outputSchema 猜签名地址字段。此模块没有放宽已有生成政策或用户审查门禁。

参考 `tests/auth/fixtures/libtv-tools-public-2026-10-27.json` 和 `backend/auth/OFFICIAL_READ_EVIDENCE.md`。当前真实授权仅 account:read；其他 scope 和真实业务响应仍待明确授权及验证，相关 adapter 可先用合成协议样本测试。

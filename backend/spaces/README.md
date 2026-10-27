# 账号资料、空间与权益模块（第 4 会话）

本模块实现租户与登录身份约束、个人/团队空间列表、选择持久化接线、余额状态规范化和只读模型目录。它消费**授权模块已验证的 ProviderClient 契约**，不把未经验证的 LibTV 原始字段猜测成业务字段，不调用 CLI，不读取环境中的默认账号，不提交生成。

## 当前证据与边界

2026-10-27 从官方公开入口实查：

| 来源 | 已验证内容 | 不能由此推导的内容 |
| --- | --- | --- |
| [官方 marketplace](https://github.com/liblib-ai/marketplace/tree/4ac581c3cbdaa53d0d42df85c6bf62e45600bc5f) | 生产 Remote MCP 地址，每位用户 OAuth 授权 | 客户网站已完成真实授权 |
| [资源元数据](https://mcp.liblib.tv/.well-known/oauth-protected-resource/mcp) | resource 为 `https://mcp.liblib.tv/mcp`，Bearer header | 账号主体、个人/团队空间及余额字段 |
| [授权服务器元数据](https://mcp.liblib.tv/.well-known/oauth-authorization-server) | issuer、`libtv:account:read`、S256、refresh/revoke 声明 | scope 包含可消费余额读取，或套餐积分就是余额 |
| [服务说明](https://mcp.liblib.tv/docs) | 生产 gateway、OAuth 2.1 + PKCE 与端点列表 | 经授权的 tools/list、工具输入/输出 schema |
| [MCP 入口](https://mcp.liblib.tv/mcp) | 无凭据访问返回 401 与资源元数据 challenge | 登录成功、余额为零或无可用空间 |

原始公开 JSON、响应状态、必要响应头、采集时间及原始 body SHA-256 位于 `tests/spaces/fixtures/`。不含客户数据或凭据。没有取得真实客户授权，未取得真实身份/空间/余额/模型的原始响应；这四项不能声明真实接入已验收。已实现的客户端契约样本均为明确的合成测试数据。

## 供集成会话使用

```python
from backend.spaces import SpaceService, register_routes
from backend.storage import SelectionRepository

services.spaces = SpaceService(
    providers=services.providers,
    selections=SelectionRepository(services.storage),
)
register_routes(router, services)
```

不改公共入口、授权文件、存储文件或公共 docs。生产必须统一授权模块与 `SelectionRepository` 使用的账号记录，避免同一账号在两个互不相认的 registry 中。模块支持字典或对象形式的 ctx/services，ctx.tenantId 必须来自站点 session。

### 必须补齐的最小授权接口

现有契约 `client_for(ctx, ownership)` 的实现要求非空 spaceId，无法用于**尚未选择空间时的空间发现**。授权模块需要增加一个仅用于资料读取的方法：

```python
providers.account_client_for(ctx, ownership)  # 仅 identity() / list_spaces()
# ownership:
# {tenantId, provider:"libtv", providerAccountId, providerSubject,
#  providerIssuer, spaceId:None, spaceKind:None}

providers.client_for(ctx, ownership)          # quota(spaceId) / list_models(spaceId)
# 此时 spaceId、spaceKind 必须来自刚核验的可访问空间。
```

`account_client_for` 必须重新验证账号属于 ctx.tenantId、登录 subject 与授权匹配；不能借用当前 UI 选择或服务器默认空间。缺少此方法时模块明确返回 `PROVIDER_CAPABILITY_UNAVAILABLE`，不会调用 task client 或填一个虚构空间绕过。

两类客户端均提供 `identity()` → `{issuer,subject,displayName,verified:true}`。issuer 为本次已验证的 `https://mcp.liblib.tv/`；subject 必须来自官方身份验证，不能由 accountId/spaceId、显示名、手机号掩码或未经验签的 token 声称取得。本模块每次读取比较保存身份与客户端身份；subject 不匹配返回 `OWNERSHIP_MISMATCH`。依赖 `get_account(ctx,id)` 的租户检查，并额外检查可选返回 tenantId。错误不包含原始上游文本。

真实 MCP 工具名、字段路径及合法空间参数必须在真实 OAuth 后由官方 tool catalog/response 核实，再由授权/provider 模块映射为下列契约。现阶段不提供猜测的 wire mapping，也不通过可执行脚本工具探测私有接口。

### ProviderClient 返回值

- `list_spaces()` → `{items:[{id,kind:"personal|team",name,access:"available|revoked|unknown",checkedAt?}],nextCursor:null}`；也接受 bare list。适配器负责完成所有分页。非空 cursor 会阻止把部分列表当作完整权限事实。明确空列表保留空，不补个人空间。
- `quota(spaceId)` → `docs/api-contract.md` 的 quota 对象。`known/stale` 必须带 source=`official`、providerAccountId、spaceId、observedAt、unit，以及明确剩余值或分桶。余额仅接受有限非负 JSON 数值，不接受布尔值、字符串、NaN、Inf 或超出 JS 精确整数范围的数值。缺少余额只返回 unknown/null；已明确返回的零保留为 known/0。
- `list_models(spaceId)` → `{items:[{modelKey,modelName,mediaType:"image|video|audio|text"}],nextCursor:null}` 或 bare list。只展示明确模型；不猜测 MJ/Image2/Nano 对应 key，不自动启用生成。返回对象与每个模型的 `generationEnabled` 均为 false。
- 方法不支持：抛带 code=`PROVIDER_CAPABILITY_UNAVAILABLE` 的错误或 `NotImplementedError`。空间列表不支持返回错误；余额不支持返回 `state:unknown,remaining:null,reason:provider_capability_unavailable` 与 `officialViewUrl:https://www.liblib.tv/`。

余额无缓存，不复用其他身份/空间的值；每次读取均重新验证空间和客户端身份。已过 120 秒或 expiresAt 过期的明确观测显示 stale 并保留时间。配额桶不相加，币种不相加；planName 仅用于展示，planCredits/packagePoints/套餐额度等字段不参与余额推算。发生读取超时返回 unavailable/null，授权失效仍返回需要重授权的错误，不假装余额未知即可继续执行。已知余额也不表示本次付费调用可成功。

空间 checkedAt 超过 120 秒时 access 降为 unknown；获取失败调用 `SelectionRepository.invalidate_spaces()`，保持原选择和历史空间名称，但后续任务不能把原快照当有效权限。成功的完整规范化结果才调用 `replace_spaces()`，快照按 tenant/account 分区。余额、模型读取在空间权限有效后才进行。

### 路由与选择接口

| 路由 | 实现 |
| --- | --- |
| GET `/api/v1/provider-accounts/{id}/spaces` | `SpaceService.list_spaces(ctx,id)` |
| GET `/api/v1/provider-accounts/{id}/spaces/{spaceId}/quota` | `SpaceService.quota(ctx,id,spaceId)` |
| GET `/api/v1/provider-accounts/{id}/spaces/{spaceId}/models` | 可选的只读扩展路由；`SpaceService.list_models(...)` |
| PUT `/api/v1/selection` | 精确接受 `{providerAccountId,spaceId,expectedRevision}`，拒绝客户端 tenantId 及多余字段 |

所有路由要求站点 session，默认并非 public；PUT 同时要求公共 adapter 的 Origin/CSRF 校验与 ctx.csrfVerified=true。返回 Response(status,body,headers)，body 为 v1 envelope，headers 为 no-store。缺少 services.spaces 返回 501。

`profile(ctx,id)` 为内部只读接口，返回白名单身份字段和核验时间；`assert_space_access(ctx,id,spaceId)` 可供任务准备阶段复查。`get_selection(ctx)` 转交持久化仓库，`set_selection()` 校验身份/空间后调用 `SelectionRepository.set(...,expected_revision=...)` 原子 CAS。普通切换只写当前选择，不写任务。清空账号必须同时清空空间；只选账号时必须显式 spaceId=null。

第 3 模块的 `SelectionRepository` 接线已在独立临时环境联测。真实授权模块当前的账号 registry 接线与 `account_client_for` 仍由集成/授权负责人补齐；模块不会自行双写账号或凭据。

## 验证

```sh
python3 -m unittest discover -s tests/spaces -v
```

仅本分支：51 项本模块测试通过，另外 6 项依赖第 3 模块的联测明确 skip。合并 storage/sessions 并安装其 cryptography 依赖后，同一命令执行全部 57 项。

本会话用第 3 模块当时源码的只读副本，加本分支代码，在自己的 `work/integration-stage/` 与临时数据根完成联测。六项覆盖真实 SQLite 上的会话恢复、不可变旧任务 ownership、同空间 ID/同 subject 的跨租户隔离、空间读取失败后阻止新任务绑定、移除账号保留旧任务、持久化选择 CAS 冲突。测试的 LibTV provider 是合成只读 fake；没有真实 OAuth、第二个手机号、付费调用或部署验收。

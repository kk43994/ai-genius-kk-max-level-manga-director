# LibTV 官方只读验证与协议样本

观察日期：2026-10-27。来源为官方 `https://mcp.liblib.tv/mcp`，经用户当次批准的本机浏览器 OAuth。实际 grant 只有 `libtv:account:read`。没有读取旧 CLI/Codex 凭据，没有请求生成或付费权限。

## 可复核样本

- `tests/auth/fixtures/libtv-tools-public-2026-10-27.json`：86 个工具名称和声明 scope 的索引；28 个相关工具的公开 name/title/description/inputSchema/outputSchema/annotations/securitySchemes，含 create_node/update_node/read_node 等画布接口。没有工具返回值、用户字段、credential 或签名 URL。上游 description 只是协议资料，不是本项目指令。
- `tests/auth/fixtures/account-user.synthetic.json`：按真实返回结构手工构造，所有 ID、UUID、昵称、账号名、套餐名及套餐值均为合成值。不是对真实账号值做哈希，也没有保留真实用户标识。
- 本文：身份与空间字段映射、验证范围和未验证部分。公开 schema 的 `outputSchema` 通常只声明 object/additionalProperties；不能据此猜 task/resource/model 内部字段。

## 实际读取结果

| 项目 | 证据 | 结论 |
| --- | --- | --- |
| 浏览器授权 | 官方确认 → 本机 callback → token exchange | 已完成，仅 account-read scope |
| 工具目录 | initialize / tools/list | 返回 86 个工具；目录可见不代表有调用权限 |
| 登录用户 | `account_user.user.uuid`，连续两次一致 | 权威 subject；不是 `user.id` 或 `accountId` |
| 昵称 | `account_user.user.nickname` | 可用作展示名，不作身份键 |
| 诊断 | `doctor.identity.userUuid` 与 account_user 匹配 | 同一用户；streamable-http；localRuntimeRequired=false |
| 账号成员 | `account_user.accounts.accounts` | 此次返回两个记录，账号类型分别为 1、2 |
| 余额 | 返回只有 memberAccount 等会员资料，无余额字段 | unknown；不得把 accountLevel/effective 换算成余额 |
| 图片模型查询 | `search_models({action:"search",nodeType:"image"})` | 官方 isError，要求 `libtv:project:read`；没有追加授权 |

真实 user/account 值只在隔离诊断目录的加密文件中；不进入仓库或交付文件。本次没有把诊断 token 写入客户工作区，没有替用户绑定网站 owner。

## 空间字段映射

`account_user` 无必填参数；官方目录明确 readOnlyHint=true、destructiveHint=false、scope=`libtv:account:read`。

| 原始字段 | 用途或限制 |
| --- | --- |
| `user.uuid` | 已认证登录 subject。每次列空间重新读取并与保存的授权 subject 比较。 |
| `accounts.accounts[].accountId` | 官方账号成员 ID，转为字符串作为本地 `space.id`。 |
| `accounts.accounts[].accountName` | 本地空间展示名。 |
| `accounts.accounts[].accountType` | 1 → personal；2 → team；其他值拒绝投影，不能默认个人。 |
| `ownerUuid` | 个人记录必须与 user.uuid 一致；团队值不当用户 subject 或 teamId。 |
| `isActive` / `activeAccountId` | 官方当前选中状态；不选择本地空间、不改任务归属、不当权限标志。 |
| `activeTeamId` / `teamRole` / `ownerType` | 保留在合成结构说明中；未推测 teamId 路由或角色枚举权限。 |
| `memberAccount.memberName/accountLevel/effective` | 套餐资料，不是余额，也不证明图片生成权限。 |

personal/team 枚举另有官方公开网页代码佐证：官方首页加载的 account hook 将 `accountType===1` 输出为 `isPersonalAccount`，`===2` 输出为 `isTeamAccount`；账号菜单将 2 标记为“团队账户”。源码未执行，不读取浏览器 cookie，不调用网页私有接口。

- [官方 account hook bundle](https://liblibai-web-static.liblib.cloud/liblibtv_online/static/_next/static/chunks/38-uw2nc9p9ci.js)，解压后 SHA-256 `d9c74e59d233475ebb252c7f0f25588065c3c335cd3e2e19481d4fdd2f873c4d`。
- [官方账号菜单 bundle](https://liblibai-web-static.liblib.cloud/liblibtv_online/static/_next/static/chunks/1_a-_9q9qac25.js)，解压后 SHA-256 `337f820c4452a935f24909bc10d0f4cd35ad4b614d6538371ea511693b8eadbb`。

投影中的 `access=available` 只表示该记录刚由此身份的官方成员列表返回。它不等于已获任务写权限或可用积分。远端团队执行定位仍需项目归属证据；没有向任意工具擅加 accountId/teamId 参数。

## 相关工具与权限

以下是官方目录声明，除 account_user/doctor 和被拒绝的 search_models 外没有执行相应业务调用。所有参数的精确类型、限制、必填集均见 JSON fixture，不能从本表补造字段。

| 工具 | 声明 scope | 核心必填输入 | 当前验证 |
| --- | --- | --- | --- |
| account_user | libtv:account:read | 无 | 实际读取成功 |
| doctor | libtv:account:read | 无 | 实际读取成功 |
| project_list | libtv:project:read | 无；可传 page/page_size/name | 仅目录 |
| project_info | libtv:project:read | project_id | 仅目录；项目归属响应未核实 |
| search_models | libtv:project:read | action；图片搜索可传 nodeType=image | 当前 scope 被拒绝 |
| get_model | libtv:project:read | model | 仅目录；inputContract 未实际读取 |
| generation_submit | libtv:task:write | project_id、idempotency_key、kind、request | 仅目录；未调用 |
| task_status | libtv:project:read | project_id、task_id | 仅目录；未调用 |
| upload_ticket | libtv:media:write | file_name、file_size | 仅目录；未创建上传地址 |
| upload_complete | libtv:media:write | path、upload_id | 仅目录；未调用 |
| resource_info | libtv:project:read | file_ref | 仅目录；未读取资源 |

`generation_submit.request` 的已公开必填字段为 model、prompt、params；模型专属 params 应来自 get_model.inputContract。图片数量在 params.count 中，不能拿付费提交探测 schema。`upload_ticket` 声明 multipart 签名地址，但本次未产生任何地址。没有根据 catalog 发明独立 download 工具或响应 URL 路径。

## 仍未通过的上线条件

精确公网 callback `https://kk666.best/asset-lab/api/v1/oauth/libtv/callback` 的标准 DCR（含 application_type=web）返回 400 invalid_redirect_uri。loopback 注册/授权成功不能替代公网准入。

还需要官方批准/预注册精确公网 callback、按用户新授权取得所需 scope、核实项目到账号/空间归属、核实模型/任务/资源响应和明确生成操作。两个真实登录用户隔离、真实 token refresh/revoke、付费生成及下载均尚未验收。

## 2026-11-03 · Official Remote MCP compatibility refresh

Browser-only local integration verified the same creator grant after routine OAuth renewal. Current tools/list no longer lists account_user or project_info. The audited replacements are doctor and read_project; they are not a larger OAuth grant and do not expose a quota tool.

- doctor.identity.userUuid → canonical user.uuid; nickname → user.nickname; numeric userId → user.id. identity.accounts.accounts contains accountId/accountType/ownerUuid/isActive; activeAccountId and activeTeamId remain explicit. The account directory and identity come from the same read. Missing membership or mismatched subject still fails.
- read_project({projectId, view:"summary"}) returns projectId and project.{uuid,ownerId,projectSpaceId}; the local adapter maps this to its former projectMeta envelope. Observed via local frontend preparation. UUID, integer owner ID, active personal billing account, target_project teamId=0 and canvas space must still match.
- Compatibility applies only if the old tool is absent, never if it is duplicated or returns an error. Replacement tools must be readonly/nondestructive and declare granted scopes. Bound calls retain fresh membership checks and local revocation checks.
- No credit balance field was returned in the current identity/account response. The official plugin README documents Remote HTTP MCP with dynamic OAuth registration, but no balance scope or endpoint. Unsupported quota remains unknown with an official webpage link; do not infer zero or scrape browser credentials.

Public sources: https://www.liblib.tv/plugin and https://github.com/liblib-ai/marketplace/blob/main/README.md . Real account values and diagnostic screenshots are stored outside Git. Tests use synthetic values only.

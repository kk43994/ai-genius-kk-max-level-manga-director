# 持久化与身份存储（会话 3）

这是供公共入口、授权、空间和任务模块装配的服务端存储实现。它不安装 OAuth 回调、不修改公共服务器、不运行 CLI、不读取本机真实授权、不发送生成或付费请求。

数据 schema 为 `2`，新增主所有者与恢复意图表；从 schema 1 原子增量迁移。仅在真实服务安装本模块并完成相应功能验收之后才能启用产品 feature flag。存储单元测试通过不能将 `providerAuthorization` 或 `imageGeneration` 设为 true。

## 安装与数据边界

Python 3.10+，新增依赖见本目录 `requirements.txt`：`cryptography==50.0.2`（2026-10-27 核对 PyPI 的稳定版本）。集成会话负责合入根依赖清单，部署会话负责安装。

```python
from backend.storage import Store, AccountRepository, SelectionRepository
from backend.sessions import SessionService

storage = Store.from_env(release_root="/srv/asset-lab/releases/example")
sessions = SessionService(storage, public_origin="https://confirmed-domain.example")
accounts = AccountRepository(storage)
selections = SelectionRepository(storage)
```

配置要求：

- `ASSET_LAB_DATA_DIR`：绝对路径，与 release 目录完全分离，互不包含。默认不会猜路径，也不会读取原工作台数据。
- `ASSET_LAB_SECRET_KEY_FILE`：独立于 data 和 release 的绝对路径，普通文件，当前服务用户所有，权限 0600 或更严格，禁止符号链接或硬链接。内容是 **32 个随机字节的标准 Base64 编码**。运维生成一次并持久保管，升级不能重新生成；源代码、日志、备份数据包中不得包含该密钥。`Store` 不会自动生成生产密钥。
- 数据根、`private/`、`tenants/`、`backups/` 使用 0700；数据库和 blob 为 0600。主机与服务账户应受到保护，本模块不声称抵御已控制服务 UID 的攻击者。

生产 HTTPS Cookie 为 `__Host-asset_lab_session`，HttpOnly、Secure、SameSite=Lax、Path=/、无 Domain。仅显式 localhost/127.0.0.1/::1 的 HTTP 开发来源允许无 Secure Cookie，名称为 `asset_lab_session`。公开 HTTP 域名配置会报错。

密钥只在进程内使用。SQLite 内凭据采用 AES-256-GCM 加密，随机 96 位 nonce；AAD 绑定 schema、tenant、namespace 与对象 ID。密钥错误或密文被跨租户搬运时失败关闭，不重新创建空库掩盖错误。依据 [PyCA 的 AEAD 文档](https://cryptography.io/en/latest/hazmat/primitives/aead/) 使用其认证加密实现。

目录结构：

```text
external-data/
  state.sqlite3              # 租户、哈希会话、账号元数据、加密 grant、记录、幂等、租约
  tenants/<generated-id>/blobs/<generated-id>
  private/                   # 保留给私有附件；不存明文密钥
  backups/                   # 运维备份目的地；本模块不自动备份
```

不要在 release 内设 `data/`。测试示例使用独立临时目录、合成身份和随机测试密钥，不导入客户数据。

## Store / Transaction 接线

`ctx` 可是对象或 dict，必须来自服务端会话恢复，带 `tenantId`，HTTP 请求另带 `siteSessionId`。`TenantContext` 供服务端使用。客户端 body 中的 tenantId 不能用来构建 ctx。后台 worker 可使用可信任务 owner 的 tenantId 构建无 siteSessionId 的服务上下文，不能从 HTTP 参数接受此捷径。

`Store.transaction(ctx, readonly=False)`：打开单个 SQLite 事务，自动注入租户条件；写事务使用 `BEGIN IMMEDIATE`，提交后返回，异常自动回滚。提供了 siteSessionId 时，每次事务再次检查会话归属、注销及过期。

仓储返回记录：`{id,tenantId,collection,version,data,createdAt,updatedAt}`。记录 ID 与集合名受限，SQL 使用参数绑定。跨租户对象一律 `NOT_FOUND`，不暴露其他租户是否拥有它。

```python
with storage.transaction(ctx) as tx:
    # Record fields belong in data; envelope version is controlled by storage.
    project = tx.create("projects", {"name": "新项目"})
    project = tx.update("projects", project["id"], {"name": "更新名称"},
                        expected_version=project["version"])

record = storage.get(ctx, "projects", project["id"])
page = storage.list(ctx, "projects", limit=100, after=None)
```

`tx` 提供 `create/get/list/update/delete`。`Store` 提供便捷的 `create/get/list/update`，删除需要显式事务。CAS 参数为 Python `expected_version`。`create(..., record_id=..., immutable_fields=(...))` 支持服务端预先生成 ID；`ownership` 与 `tenantId` 始终不可修改，包括后补或删除，其他固定字段可添加到 immutable_fields。

通用 JSON 拒绝明显的 token、refresh token、client secret、password 等秘密字段；这不是任意内容过滤器。调用方仍须对白名单 provider 元数据建模，禁止保存或返回原始响应、签名下载 URL 和秘密文本。公开接口只返回业务字段，不原样返回 `Record` 或密文表。

加密存储仅在事务内调用：

```python
with storage.transaction(ctx) as tx:
    tx.secret_put("oauth-attempts", attempt_id, {"code_verifier": verifier})
    pending = tx.secret_get("oauth-attempts", attempt_id)  # 仅服务器内存使用
    tx.secret_delete("oauth-attempts", attempt_id)         # 可与 state 消费原子提交
```

命名空间与 ID 一并进入 AAD。OAuth state 的验证、过期、PKCE、单次消费和回调 session 绑定属于会话 2；可用同一事务的公开状态记录和 secret 实现，不要创建独立明文凭据文件。

幂等提交必须将 owner、任务和幂等结果放在同一事务：

```python
from backend.storage import request_hash

def prepare_locally(tx):
    owner = selections.bind_ownership(tx, expected_revision=expected_selection_revision)
    return tx.create("tasks", {"ownership": owner, "status": "draft"})

task = storage.idempotency(ctx, idempotency_key, request_hash(validated_spec),
                           prepare_locally, scope="tasks.prepare")
```

`operation(tx)` **只做本地操作**，不可在数据库事务中调用官方网络/CLI。相同租户、scope、key、请求 hash 重放原结果；同 key 不同正文报 `IDEMPOTENCY_CONFLICT`（HTTP 409，v1 错误码的兼容扩展）。不同租户或 endpoint scope 独立。`request_hash` 基于规范化 JSON。幂等结果永久保留，本版本不自动过期，以免重启后重复提交。

任务 provider submit 是外部副作用，仍需会话 7 持久化 `submissionAttempted` 和 receipt、遵守不明结果只查原任务的规则；存储不能将远端请求变成跨系统事务。

Worker 租约：事务内 `claim_lease(resource, holder, ttl=60)` 返回单调 fence；后续状态写事务先 `assert_lease(resource, holder, fence)`，定期 `renew_lease`，结束 `release_lease`。资源租约已过期或被新进程接管时旧 fence 失败。租约防本地并发，远端不支持幂等时仍不能保证远端 exactly once。

## 身份仓储给会话 2

`AccountRepository` 只负责存储：

```python
from backend.storage import VerifiedIdentity

# Values must come from official, verified authorization evidence, never browser JSON.
# At begin_authorization, save this with the persisted, session-bound OAuth attempt.
epoch_at_begin = accounts.authorization_epoch(ctx)

# At callback, use the SAVED epoch. Do not reread it to make an old callback pass.
account = accounts.complete_authorization(
    ctx, VerifiedIdentity(official_issuer, official_subject, display_name),
    server_grant,                    # dict; access_token required, never returned publicly
    expires_at=expires_epoch,        # None only if official grant has no expiry
    minimum_read_verified=True,     # official token + subject + minimum read must all pass
    expected_authorization_epoch=epoch_at_begin,
)
```

- 身份唯一性为 `(tenant, provider, issuer, subject)`，`provider` 当前仅 libtv。VerifiedIdentity 是服务层的受信断言，不替官方验证证据；此模块不支持从 displayName、掩码手机、空间 ID、套餐猜 subject。
- 官方身份未就绪时可 `create_unconfigured(ctx, label=...)`；不得把它置 connected。
- 同租户重复添加相同 subject 复用稳定 ID；另一租户相同 subject 独立分配 ID 与 grant。
- 重授权传 `account_id` 和 `expected_version`；旧 subject 不匹配、版本落后、账号已移除时拒绝。未绑定 subject 的待授权对象可完成第一次官方验证。
- 授权开始时必须把 `authorization_epoch(ctx)` 的结果与该次 OAuth attempt 一起持久化。回调传原始 `expected_authorization_epoch`；缺少时失败关闭。账号移除会递增本租户代次，使之前已打开的“添加账号”回调也无法复活 grant。回调时不能重新读新代次绕过检查；新一次添加可取得新代次。另一租户不受影响。
- `mark_authorization(ctx,id,state,expected_version=...,reason=...)` 支持 unconfigured/authorizing/expired/revoked/error。reason 必须来自代码内固定集合，不记录原始错误响应。revoked/error/unconfigured 删除 grant，expired 可保留 refresh token 给官方刷新适配器使用。
- `credentials(ctx,id)` 仅服务器使用，只允许 connected；`for_refresh=True` 额外允许 expired，不能被任务提交绕过。它不自动刷新、不选择其他身份、也不读取全局 CLI。
- `get/list` 返回安全公开账号，授权过期根据当前时钟计算。仓储能力 flags 恒 false；ProviderService 根据真实官方验证覆盖，存储不宣称能力。
- `remove_local(ctx,id,expected_version=...)` 原子 tombstone、删除本地 grant、撤销缓存空间、清空当前选择并递增 revision；返回 `removed/affectedTaskIds/account`。**不返回 remoteRevocation**，由 ProviderService 的真实官方撤销结果填 confirmed/unsupported/failed。任务模块按返回 ID 显示 blocked_authorization，但不能谎称远端已停止。
- 已运行中的外部请求可能在用户移除前就已发出；本地删除无法撤回该请求。每个外部操作前重新验证原 owner，真实远端撤销另由官方适配器执行。
- 已移除 subject 再走“添加”可以恢复原稳定 ID；默认不会恢复空间访问，需要新的官方空间读取。旧任务 owner 不改写。

## 选择仓储给会话 4 / 7

这里只提供持久化原语，不注册选择路由，也不实现积分或 provider 请求。会话 4 负责选择路由、官方查询和缓存策略：

- `replace_spaces(ctx,account_id,items)` 接受成功的官方结果；每项 `{id,kind,name,access}`，kind 仅 personal/team。不同登录身份可以具有相同 upstream spaceId，存储仍隔离。列表中移除的空间保留名称但标 revoked。
- 查询失败调用 `invalidate_spaces(ctx,account_id)` 将已有访问标 unknown；不要把失败当作空列表或个人空间。
- `list_spaces(ctx,account_id)` 返回带 `checkedAt` 的快照；`get(ctx)` 返回 selection。
- `set(ctx,provider_account_id,space_id,expected_revision=...)` 原子版本切换。账号必须属于当前 tenant；space 需属于该账号且 access=available。传 `space_id=None` 是显式清空，不能省略该参数。错误空间不会继承到另一个登录身份。
- `set_in_transaction(tx,...)` 供需要组合事务的调用者；`bind_ownership(tx,expected_revision=...)` 只允许 connected、verified、有效空间，并输出 v1 owner 快照。必须和 task.create 同一事务调用。
- `assert_ownership_available(ctx,ownership)` 用于恢复/提交原任务；只检查已存 owner，不看当前 UI 选择。旧授权失效或空间失权时拒绝，禁止切换到另一账号接管。

## 素材 / 升级与运维

`storage.blob_put(ctx,content:bytes,mime=...)` 返回 `{id,sha256,size,mime,createdAt}`，最大 64 MiB；`blob_get(ctx,id)` 返回 `(bytes,metadata)`。HTTP 下载路由仍由资产/任务模块鉴权并选择允许的 MIME/响应方式。

路径只由服务端生成 ID 构成，文件访问使用目录 FD + O_NOFOLLOW；拒绝路径穿越、符号链接和硬链接，读取核对长度与 SHA-256。文件先 fsync 后提交数据库，避免记录指向尚未落盘的内容。硬崩溃可能留下无记录的孤立 blob；它不会被公开读取，需后续维护工具清理，不能因此删除有记录素材。

`migrate()` 在单个写事务安装 schema 2 或从 schema 1 增量升级，并校验持久密钥；遇到更新的 schema 立即拒绝运行，不做降级、不删表。SQLite 当前使用默认 rollback journal、FULL 同步和跨进程数据库锁；没有不受管控的内存队列。`readiness()` 返回实际 dataSchemaVersion；部署/集成不得再硬编码 schema 1。

本模块不自动执行生产备份、schema 升级或轮换密钥。部署需使用 SQLite backup API 或暂停写入后做一致性备份，同时保留 tenant blob 文件；不要在写入时只复制一个 sqlite 文件，也不要只备份数据库就声称素材完整。数据库中的历史 grant 备份仍是密文，key 必须通过独立受控渠道备份。轮换密钥需单独设计重加密迁移，不可直接换文件。

## 验证范围

```sh
python -m unittest discover -s tests/storage -v
```

测试使用两个合成租户、多组合成身份、临时数据目录；涵盖重新启动恢复、跨租户拒绝、授权失效与重授权、8 路并发 CAS/幂等、删除保留历史、Origin/CSRF、cookie 哈希、凭据认证加密、路径攻击、迁移拒绝和 worker fence。没有真实官方授权、真实双登录身份、收费调用、Chrome UI 或服务器部署验收。

Schema 2 的主所有者、Cookie 丢失找回、显式保留匿名工作区和未保存草稿门禁，见 `../sessions/OWNER_RECOVERY.md`。网站所有权独立于 provider_accounts，账号移除不触碰主所有者，旧库不从生成账号推断主所有者。

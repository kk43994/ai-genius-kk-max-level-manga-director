# 账号管理前端模块（第 6 会话）

此模块独占 `frontend/accounts/` 与 `tests/accounts-ui/`。没有改公共 HTML、shell、公共 CSS、API 客户端或生产后端。所有演示账号、授权结果、额度均为合成数据，不能作为真实 OAuth 或两个真实身份隔离验收。

## 集成入口

加载 `accounts/accounts.css`，在视觉 shell 的 `#account-root` 上挂载 ESM 模块；资源 URL 相对部署目录解析。传入统一的 `api` 客户端与 EventTarget，不用 window 配置变量。

```js
import { mount as mountAccounts } from './accounts/index.js';

// api 已由 shell 按 apiBase 配置：本地 /api/v1，子路径 /asset-lab/api/v1。
// api.request('/session') 必须返回 envelope.data，并维护 Cookie/CSRF。
const accountModule = mountAccounts({
  root: document.querySelector('#account-root'),
  api,
  events,
  session: sessionData,      // GET /session 的完整 data，不是 data.session 子对象
  publicBasePath,           // '/' 或 '/asset-lab/'；只用于 OAuth returnPath
});
await accountModule.ready;

// 升级保存钩子：先检查 reason 展示给用户，再 await flush。
accountModule.getDirtyState(); // {dirty, reason}
await accountModule.flush();  // 正在进行写请求时抛 ACCOUNT_OPERATION_IN_PROGRESS
// 卸载页面区域时：accountModule.unmount();
```

`publicBasePath` 默认为 `/`，也接受 `/asset-lab` 并规范为 `/asset-lab/`。回调路径的服务端白名单必须同步配置。模块请求始终使用契约相对路径 `/session`、`/selection` 等，由注入的 api 加正确的 `apiBase`；这里不自行 fetch、不硬编码 `/api/v1` 或 `/dashixiong-scene-studio`。

挂载返回 `ready / refresh / getDirtyState / flush / unmount`。`ready` 完成首次读取，失败在页面内呈现并释放重试按钮；`refresh()` 重新读服务器 session 和账号列表。`unmount()` 清理计时器、事件及自己打开的授权窗口，不修改其他模块 DOM。

## 接入的契约

| 路由 | 模块行为 |
| --- | --- |
| GET `/session` | 恢复租户、功能开关和当前选择；会话切换清除旧租户状态；拒绝回退 selection revision |
| GET `/provider-accounts` | 读取所有分页，只显示 LibTV 非 removed 账号；connected 还需 identity.verified |
| POST `/provider-accounts/authorize` | `{provider:'libtv',returnPath}`，带唯一 `idempotencyKey`，不自动重试 |
| POST `/provider-accounts/{id}/reauthorize` | `{expectedVersion,returnPath}`，保留原身份，错误显示原账号不匹配提示 |
| GET `/authorization-attempts/{id}` | pending / completed / failed / expired；完成后重读账号，不自动切换归属 |
| DELETE `/provider-accounts/{id}` | `{expectedVersion}`，原生 dialog 确认；只有 confirmed 才称官方撤销成功 |
| GET `/provider-accounts/{id}/spaces` | 个人与团队 optgroup 分开；切换登录身份立即清空旧空间与额度 |
| GET `/provider-accounts/{id}/spaces/{spaceId}/quota` | 验证返回归属；未知显示“余额未知”，不把套餐、空值和失败当作 0 |
| PUT `/selection` | `{providerAccountId,spaceId,expectedRevision}`；显式“应用到新任务”，409 后保留草稿且不自动重试 |

状态和事件只反映服务器返回的公开实体。`features.providerAuthorization !== true` 时添加和重新授权关闭；单账号 `capabilities.authorize !== true` 时不能重授权，未接入不会伪装成可登录。余额、空间失败不会回退到其他账号或全局 CLI。

## 事件载荷

所有模块发出的事件都有 `detail.source`（每次挂载的随机标识），用于避免回环；消费者只读取，不原样重复派发。

- `session:changed` → `{session: sessionData, source}`。这里 sessionData 包含 `session, tenant, selection, features` 等完整 data。
- `provider-accounts:changed` → `{items: publicAccounts, source}`。
- `selection:changed` → `{selection: {providerAccountId, spaceId, revision}, source}`。
- `tasks:changed` → `{reason:'provider-account-removed', providerAccountId, source}`，仅用于触发任务重新读取。

模块监听以上前 3 个事件；外部发 `provider-accounts:changed` 表示需要刷新即可，不强制传 items。会话更新必须传完整 sessionData，选择更新必须传有效 revision。公共集成层应统一这些 detail 形状。

## 授权与取消边界

2026-10-27 只读核查官方公开元数据：

- [官方 marketplace](https://github.com/liblib-ai/marketplace)：每位用户自己的 OAuth 授权，HTTP Remote MCP。
- [官方授权服务元数据](https://mcp.liblib.tv/.well-known/oauth-authorization-server)：`authorization_endpoint` 为 `https://mcp.liblib.tv/authorize`。

模块只接受上述精确 HTTPS origin/path（拒绝 userinfo、其他端口、hash、伪造子域或重定向路径）。URL 必须来自本站后端的 begin API，前端不拼装 client_id / state / scope / PKCE。官方未来改变授权端点时，应先核实元数据再更新常量；不能放开任意地址。

用户点击时预开空窗口并清除 opener；后端返回有效链接后跳转官方。弹窗被拦截则显示带 `noopener noreferrer` 的官方链接。无需客户安装 CLI、复制 token 或敲命令。模块不依赖 postMessage 或 URL query 来认定完成，只查询本站授权 attempt。

现有 v1 契约 **没有取消 attempt 的写接口**。因此“取消等待”仅停止本页自动检查并关闭本页打开的授权窗口，不声称服务器授权被撤销。pending 尝试保留，避免用户误发第二次；可继续查询。只有后端 failed 的 `ACCESS_DENIED / access_denied / OAUTH_ACCESS_DENIED / AUTHORIZATION_CANCELLED / AUTHORIZATION_DENIED` 才显示“已在官方页面取消授权”。链接本地过期仍可核对之前是否已完成。

若产品需要“取消后旧官方回调绝不生效”，最小待补接口是租户绑定、原子消费 attempt state 的 `POST /authorization-attempts/{id}/cancel`，并补充 `cancelled` 终态；需由授权和契约负责人确认后实现。当前模块没有调用不存在的接口。

## 保留输入与竞态控制

- 只更新自己的挂载点；其他模块的 textarea、项目、素材、任务不改动。
- localStorage 只保存按租户分隔的未应用账号/空间 ID，以及 attemptId、expiresAt、公开状态、是否暂停检查；不保存授权 URL、OAuth state/code、provider token 或 CSRF token。
- 刷新恢复仍以服务端 Cookie session 为准；localStorage 只是草稿与查询线索，不是授权证明。站点会话丢失或跨设备恢复由 session 模块负责。
- 新授权、重授权、切换、移除在当前模块互斥；授权期间不允许再发起第二次。支持 Web Locks 时，同源多个页面竞争同一个授权锁；localStorage pending 标记进一步防重入。没有 Web Locks 或本地存储不可用时，跨标签页最终幂等需后端保障。
- 空间、余额、session 读取带租户 epoch 与请求序号；晚到的旧响应不回填。已知选择只缓存文字标签，不缓存不同账号余额。
- 每次应用都带服务端 revision，更新冲突后重新读取但保留用户选择；不自动提交第二次。POST 无自动重试。网络超时后不能由前端推断授权未创建，服务端幂等仍是最终边界。
- 页面更新钩子可把未应用选择持久化；进行中的写请求必须等到完成，`flush()` 会拒绝中途刷新。不要直接忽略拒绝后 reload。
- 原生 label/select/button/dialog、状态 live region、错误 alert、焦点恢复、移动端 44px 按钮与 reduced-motion 支持均已提供；CSS 全部限定在 `.al-accounts`。

## 验证

```sh
node --test tests/accounts-ui/state.test.mjs
python3 tests/accounts-ui/serve_fixture.py --port 8897
```

只在独立测试端口开放以下静态目录；不会启动原后端，也不会访问 provider：

- 根路径：`http://127.0.0.1:8897/tests/accounts-ui/fixture.html?suite=1`
- 子路径：`http://127.0.0.1:8897/asset-lab/tests/accounts-ui/fixture.html?suite=1&base=/asset-lab/`
- 手动操作：移除 `suite=1` 查询项。顶部控件用于合成授权完成/取消/过期/失败。真实官方链接点击被测试夹具拦截。

浏览器套件完成后设置 `document.documentElement.dataset.testStatus`、`testCount` 并显示逐项结果。验证覆盖账号与空间分离、迟到响应、409、双击防重、暂停恢复、授权各终态、移除确认、XSS 文本转义、归属校验、租户切换、草稿恢复、子路径、同源授权锁和升级操作保护。真实官方注册、登录、token 刷新/撤销、两个真实身份、生产 session 持久化、正式 shell 集成与公网发布需对应负责会话继续验收。

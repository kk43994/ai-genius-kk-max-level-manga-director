# 第 9 模块交接：发布与浏览器更新

本模块从基线 `f2069e3a9c460e6f6d9dcf9a5fc1f4e95999cccf` 的独立克隆实现，只新增 `deploy/`、`backend/releases/`、`frontend/updates/`、`tests/releases/` 和 manifest 示例；没有修改公共 `backend/app.py`、现有 HTML、共享 API 客户端或原工作台。

## 后端装配

```python
from backend.releases import ReleaseService, register_routes, PUBLIC_ROUTES
services.releases = ReleaseService(
    release_root='/srv/asset-lab-customer/runtime',
    running_manifest='/srv/asset-lab-customer/runtime/channels/preview/current/release.json',
    origin='https://kk666.best',
    base_path=config.publicBasePath,
)
register_routes(router, services)
```

- `running_manifest` 在进程启动时 resolve/read 一次，之后 `/version` 代表这个运行进程。不要在每次请求时重新读 current 并伪装成运行新版。
- `GET /api/v1/version` 返回当前运行 manifest；`GET /api/v1/releases/latest?channel=...` 读取对应 current 的已校验 manifest；两者都返回 v1 envelope，`ReleaseResponse.status/body/headers` 直接交 HTTP adapter，避免重复包 envelope。
- `router.add(method, path, handler)` 为三参数；`handler(ctx, params)` 返回 `ReleaseResponse`。`ctx` 可以是对象或 dict；query 支持字符串值或 `parse_qs` 单值列表。
- `PUBLIC_ROUTES` 明确列出两个不含任何用户信息的只读接口，由公共 adapter 决定公开注册。没有 releases service 时返回 503 `RELEASE_UNAVAILABLE`，绝不伪造可用版本。
- 版本响应都 `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`。后端只在同一实际 manifest 路径/mtime 上缓存 3 秒；current 切换立即使键变化，坏 JSON 返回 503。反代/Service Worker 也必须绕过缓存；不要将 JSON 错误回退为 SPA index.html。
- 真实数据库 schema 与任务恢复由存储/任务模块验证；发布模块不读取客户库。`apiVersion` 使用契约整数代际，`minCompatibleClient` 使用 SemVer。

## 前端装配

```js
import { mount as mountUpdates } from './updates/index.js';
const updates = mountUpdates({
  root: document.querySelector('#update-root'),
  api, events, session,
  publicBasePath: config.publicBasePath, // '/' 或 '/asset-lab/'
  // 一般从构建 HTML 的 #asset-lab-build 读取；开发模式也可明确传 currentBuild。
  currentBuild: compiledBuildIdentity,
  getSafetyState: () => workflow.getUpdateSafetyState(),
  saveDraft: () => workflow.saveDraftForUpdate(),
});
// 页面组件退出：updates.unmount()
```

`getSafetyState()` 必须返回真实 `{hasUnsavedChanges:boolean, activeTasks:nonnegativeInteger, activeDownloads?:nonnegativeInteger}`，包含导入、清单、prompt、审核备注及进行中的下载；缺失或错误会阻止刷新。`saveDraft()` 必须等待真实持久化 ACK，成功返回 `{saved:true}`；CAS 冲突/失败/未知状态抛错或返回非成功，组件保留页面。确认保存后再次检查 dirty/task/download。当前任务/下载未完成时仍阻止刷新，这是保守默认策略，不会取消任务。

`api` 是全站唯一请求客户端，本模块只发 `api.request('/version', options)` 和 `api.request('/releases/latest?...', options)`，不硬编码 `/api` 或旧 dashixiong 路径。API 客户端需接收明确的 `apiBase`，透传 `signal/cache: 'no-store'`，请求最大时长 8 秒；即使其忽略 abort，模块仍会超时并停止等待。正式 HTTPS cookie/CSRF/归属完全由共享 adapter 处理，本模块没有 provider 凭据。

每次状态变化发 `release:changed`：`{status,currentVersion,latestVersion,checkedAt,releaseNotes,current,latest,server,compatibleNow,compatibleLatest,canUpdate,reason,changeKind}`。消费 `compatibleNow === false` 时将制作界面置为保存/只读，并禁止新的收费操作；后端收费禁止仍应独立强制执行。更新组件本身不会提交任务，不能代替收费门禁。

状态名遵循契约：idle/checking/up_to_date/update_available/offline/error/incompatible。`changeKind:'rollback'` 和同 SemVer 不同 buildId 都会提示显式刷新。离线/错误保留上次查询时间，旧结果标记“上次查询”，不能显示成已确认最新。默认启动一次、6 小时加 0–10% 抖动、后台页面停止轮询、重新可见且过期再查；手动检查不改变工作内容。

当前构建 identity 为 `{schemaVersion,product,version,buildId,channel,apiVersion,dataSchemaVersion}`。不能用启动时从 `/version` 或 live `build-info.mjs` 读到的“当前服务器构建”替代这个标签页实际载入的 identity，否则旧页面会误报自己已升级。工具在 HTML 内嵌 stamp；旧版本资源永久指向原 immutable version URL。缺 stamp 时组件明确显示版本未就绪并保留工作，不默认假定已保存。

## publicBasePath / apiBase 两种挂载

| 配置 | 本机根路径 | 候选服务器子路径 |
|---|---|---|
| publicBasePath / 发布工具 --base-path | `/` | `/asset-lab/` |
| apiBase，由集成会话传给 api 客户端 | `/api/v1` | `/asset-lab/api/v1` |
| 入口 entryUrl | `/` | `/asset-lab/` |
| 版本化静态资源 | `/releases/<id>/...` | `/asset-lab/releases/<id>/...` |

发布构建 spec 的 `basePath` 与集成配置 `publicBasePath` 是同一值。更新模块显式参数叫 `publicBasePath`；内部 checker 的信任配置名为 `basePath`。候选 Nginx snippet 去掉请求的 `/asset-lab/` 前缀后转发给 root-mounted app；应用不能再去掉一次。集成服务也可以原生挂载子路径，但那时须同步去掉 `proxy_pass` 尾部 `/`，由集成负责人择一。

两个挂载方式已在真实 loopback HTTP 中验证 HTML、两个版本接口、旧静态资源缓存、版本切换、回退、坏 manifest 503、目录逃逸 404。`deploy/config/nginx-asset-lab.locations.example.conf` 仅是待安装示例：当前 kelao MIME 表没有 `.mjs`，示例局部补映射，避免模块被 nosniff 阻止。

## 仍需集成完成的事项

1. 合入模块，按公共 HTTP adapter 接线，确保只包一层 v1 envelope 并保留 headers；接入界面 `#update-root`。
2. 注入 build identity、publicBasePath、apiBase；接入真实 workflow 草稿保存、task/download 计数和不兼容只读控制。
3. 集成构建只产出批准的 public/server；构建与全业务无费用测试通过，生成真实版本与包摘要。
4. 实现五个生产 hooks：任务静止、候选/schema 检查、专属进程激活/首次失败停止、真实运行 buildId 探活。确认启动不会自动迁移不兼容数据库、不会恢复被暂停的收费/最终视频生成。
5. 确认正式访问入口与预览访问控制，完成独立用户/env/data/service 配置。现场重新核查端口和证书；此模块没有保留端口，也没有提前创建/改动公网路由。
6. 先独立预览验收，真实 session/双租户/授权/任务重启/数据保留和回退通过后再产出稳定验收记录。当前合成测试不代表真实授权或客户数据持久化已验收。

## 参考

- SemVer 2.0 的数值和预发布优先级：[官方规范](https://semver.org/)。实现覆盖 1.9→1.10、alpha/beta/rc、build metadata、巨大整数；没有用字符串大小比较版本。
- Nginx 缓存旁路配置：[官方 proxy 文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache_bypass)。远端的实际 Nginx 配置优先于模板；安装前必须备份、`nginx -t`、最小 include 与现场 HTTP 验证。

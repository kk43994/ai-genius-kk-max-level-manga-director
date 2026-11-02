# 并行模块责任边界 v1

详细接口见 `api-contract.md`。目录在模块实现时创建；不要为占位制造假实现。公共契约的修改须明确版本与兼容影响，由集成会话合并。

| 会话 | 主责 | 独占文件/目录 | 交付边界 |
|---|---|---|---|
| 1 基线与官方核验 | 初始源码、约定、证据 | `docs/api-contract.md`, `docs/module-ownership.md`, `docs/source-inventory.json`, `docs/libtv-official-evidence.md`, `examples/contracts/` | 不实现其他模块 |
| 2 授权 | 官方 OAuth/MCP、账号增删重授权 | `backend/auth/`, `backend/providers/`, `tests/auth/` | 不把 CLI 全局登录当网站 OAuth；未知能力显式未就绪 |
| 3 存储 | 站点会话、租户、事务、数据迁移 | `backend/storage/`, `backend/sessions/`, `tests/storage/` | 服务端 tenantId、独立数据根、版本/CAS、幂等记录 |
| 4 空间与积分 | 个人/团队空间、选择、额度 | `backend/spaces/`, `tests/spaces/` | 分离 provider 登录身份和工作空间；未知额度不显示 0 |
| 5 页面 | 页面结构与视觉、移动端、通用 API 客户端 | `frontend/asset-lab.html`, `frontend/asset-lab*.css`, `frontend/shell/`, `frontend/api-client.js`, `tests/ui/` | 在 HTML 中提供账户、更新、任务挂载点；不改流程主 JS |
| 6 账户 UI | 账号入口/切换/重授权/移除、空间与余额显示 | `frontend/accounts/`, `tests/accounts-ui/` | 仅消费规范 API，不读 CLI 或持久化 provider token |
| 7 任务 | 不可变 ownership、队列、恢复、下载 | `backend/tasks/`, `frontend/tasks/`, `tests/tasks/` | 固定发起账号与空间，不自动重提不明任务 |
| 8 资产流程 | 导入、清单、MJ→Image2→Nano、人工审核与导出 | `backend/workflow/`, `frontend/asset-lab.js`, `frontend/asset-lab-archives.js`, `frontend/workflow/`, `tests/workflow/` | 每阶段人工审核；禁止 Nano 失真结果继续精修 |
| 9 发布与更新 | kelao 发布、版本查询、保留数据、更新提示 | `deploy/`, `backend/releases/`, `frontend/updates/`, `tests/releases/`, `release-manifest.example.json` | 启动/适度轮询/手动检查，刷新前保存，不变成 CLI 安装产品 |
| 10 集成验收 | 服务组合、依赖、通用冒烟/隔离/E2E | `backend/app.py`, `backend/__init__.py`, `scripts/`, `tests/integration/`, 根依赖/构建文件、README | 汇总各模块，清除基线 501 后才能声明对应功能可用 |

早期 `backend/legacy/` 迁移参考已从工作目录移除；原始哈希仍见 `docs/source-inventory.json`，源码恢复方法见 [代码清理与运行负担](rag/code-cleanup.md)。当前服务使用各模块自己的实现，构建继续拒绝打包 legacy。各测试只改自己目录。各模块自有配置说明放本模块目录，不并发修改公共 README。

后端统一模块边界：模块导出 `register_routes(router, services)`，调用 `router.add(method, pattern, handler)`；handler 接收 `RequestContext` 与参数，返回 `Response`。由第 10 会话提供最终 HTTP adapter，第 3 会话提供持久化/站点 session，第 2 会话提供 provider service。框架可选，但不得改变线上的 v1 JSON 契约；没有接入的路由保持明确 NOT_IMPLEMENTED，严禁静默假成功。

前端模块导出 `mount({root, api, events, session})`，返回 `{unmount}`；动态状态通过 `events`（EventTarget）发 `session:changed`、`provider-accounts:changed`、`selection:changed`、`tasks:changed`、`release:changed`。第 5 会话提供 `#account-root`、`#task-root`、`#update-root` 容器，第 10 会话装配。第 8 会话将 legacy 调用集中迁到 api-client，不自行定义第二套账户状态。

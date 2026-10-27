# 资产实验室 · 客户网页版集成骨架

当前检查点为 `0.1.0-integration.1`。公共启动、HTTP 路由、安全边界、空白客户预览和验收工具已实现；各业务模块等待合并。**这不是已经完成授权、保存与制作的客户成品。** `health=200` 只代表进程存活，`ready=503` 列出未接入模块，`customerReady` 保持 `false`。

客户最终通过网址操作，无需安装 Codex 或 CLI。以下命令只给开发/部署人员使用。原工作台 8768 和基线 8870 不受本服务影响，也不能用作本副本端口。

## 本地运行

Python 3.10+；本检查点使用标准库，无需安装第三方依赖。从独立仓库或解压后的运行包目录执行：

```sh
python3 -m backend.app --port 8890 --data-dir /absolute/path/outside-release/customer-data
```

打开 `http://127.0.0.1:8890/`。当前页面是明确标注的空白集成预览，未连接任何真实账号；额度显示未知。首次 session 接口暂时返回 501，私有业务接口要求真实本站 session。缺少模块不会借用本机 LibTV 登录或调用旧引擎，也不会制造模拟客户状态。

独立子路径预览：

```sh
python3 -m backend.app --port 8891 --public-base-path /asset-lab/ --data-dir /absolute/path/outside-release/customer-subpath-data
```

打开 `http://127.0.0.1:8891/asset-lab/`。该实例的 `/` 和 `/api/v1/health` 返回 404，不占用其他应用根路径。API 位于 `/asset-lab/api/v1/`。也可通过 `--api-base /customer-api/v1` 显式指定同域 API 路径。

`ASSET_LAB_HOST`、`ASSET_LAB_PORT`、`ASSET_LAB_DATA_DIR`、`ASSET_LAB_PUBLIC_ORIGIN`、`ASSET_LAB_PUBLIC_BASE_PATH`、`ASSET_LAB_API_BASE` 对应同名命令行配置；命令行优先。服务不自动加载 `.env`。默认数据目录为代码目录旁的 `work/customer-data`，必须位于 release 之外。骨架只验证数据路径，尚不创建持久化客户业务数据。指定 `--check-config` 可只检查配置与模块加载情况。

`ASSET_LAB_ALLOW_PAID_SUBMISSION` 或 `ASSET_LAB_VIDEO_GENERATION` 设为真会直接拒绝启动。本开发版本不提供打开收费/正式视频开关的途径。服务端拦截任务 submit 和视频 prepare，不依赖按钮状态。

## 接线约定

公共业务协议与责任分工见 `docs/api-contract.md`、`docs/module-ownership.md`。具体 Python 适配接口、前端配置注入与合并步骤见 `tests/integration/README.md`；完整待验收项见 `tests/integration/acceptance-matrix.json`。

模块可提供 `create_service(services)`；按 storage → sessions → providers → auth → spaces → tasks → workflow → releases 的顺序装配。所有服务绑定完成后，调用各模块的 `register_routes(router, services)`。未实现的路由保留明确占位，模块内依赖损坏会阻止启动，避免静默当成“模块未安装”。不导入 `backend/legacy/`。

前端统一读取同挂载目录的 `app-config.json`，或显式导入 `_app/config.js` 的 `config`。已迁移 HTML 还会得到 `#asset-lab-config` 惰性 JSON。内容为 `{publicBasePath, apiBase, apiVersion, mode}`，不写入 window 全局，不含路径、账号、凭据。组件由后续装配入口以参数方式接收配置。尚未收到页面模块时显示 `scripts/templates/integration-shell.html`；当 `frontend/api-client.js` 存在后使用模块 5 的 `frontend/asset-lab.html`。本检查点不替换其他会话的前端源码。

## 验证与打包

```sh
python3 scripts/check_integration.py --output /absolute/path/to/evidence/http-tests.json
python3 scripts/build_bundle.py --output /absolute/path/to/asset-lab-customer-checkpoint.zip
```

HTTP 测试启动独立临时端口，用合成 session 验证公共边界；不会调用 LibTV，也不证明真实双账号、数据库持久化或完整业务已通过。覆盖根路径及子路径、会话上下文、跨租户请求隔离、Origin/CSRF、幂等标识、收费/视频禁用、错误脱敏、静态路径、JSON/体积限制和模块装配。

运行包从指定 Git commit 的白名单源码生成，排除 `backend/legacy`、运行数据、凭据、Git 元数据。ZIP 内含 `BUNDLE-MANIFEST.json`（每文件 SHA-256），外部附整包 SHA-256；同 commit 生成内容相同。构建不会自动收录未提交改动。解压后可直接按“本地运行”启动。后续合并新增依赖时要同步锁定并重验。

## 部署人员须知

本检查点没有连接 `ssh kelao` 或修改公网服务。发布由第 9 会话负责；`https://kk666.best/asset-lab/` 仍是候选位置。此 adapter 供联调使用，生产发布前还需完成并发/资源限制及反向代理验收。

反向代理应保留挂载前缀和原始 `Host`。本站设置 `ASSET_LAB_PUBLIC_ORIGIN=https://已确认域名`、`ASSET_LAB_PUBLIC_BASE_PATH=/asset-lab/`，API 自动为 `/asset-lab/api/v1`；本站 Origin/Host 按配置严格校验，不信任请求提供的 tenantId 或 Forwarded 头。生产 Cookie 的 Secure/HttpOnly/SameSite 和 Path 由 session 模块落实，Path 应对应 publicBasePath。TLS、服务用户、外置数据目录、备份迁移、原子发布及回滚由发布模块核验后再部署。

需要分开记录三种状态：服务进程能响应、业务模块就绪、真实客户流程验收。官方公网 callback 准入、稳定 subject 与空间/模型读取、真实双账号隔离、公网部署均尚未验收；ready 的 acceptance 项现在明确为 false，不得仅因本地 200 或 fake 测试改成 true。已有官方核查见 `docs/libtv-official-evidence.md`。正式视频保持暂停，本轮不提交付费生成。

# 创作流程候选版 0.3.0-preview.3

本分支当前范围与验收见 [版本记录](docs/versions/0.3.0-preview.5.md)，产品规则与检索入口见 [项目 RAG](docs/rag/README.md)，每批变化见 [CHANGELOG](CHANGELOG.md)。下面的旧运行与发布记录按其记录日期理解，不能作为本分支已经部署或更新安装包的证据。

# 资产实验室 · 本地 LibTV 连接预览

当前提供 Mac（Apple 芯片）与 Windows（x64）连接体验版：安装后创建桌面快捷方式，双击启动工作台，点击“授权 LibTV”，在官方页面确认后，由本机回调自动核验账号并读取个人／团队空间。仅申请 `libtv:account:read`；授权令牌由本地服务加密存储，不放入浏览器、源码包或程序包。生成和自动安装更新未开放。

下载入口：<https://kk666.best/asset-lab/>。Windows EXE 为中文向导，安装到当前用户的 Programs 目录，创建桌面和开始菜单快捷方式；Mac PKG 安装到“应用程序”并为当前登录用户创建桌面链接。均自带运行时，无需安装 Python、Codex 或 CLI。Windows 数据位于 `%LOCALAPPDATA%\\AssetLab`，Mac 数据位于 `~/Library/Application Support/AssetLab`，与程序分开。只绑定 `127.0.0.1:18874`；页面底部可停止本地服务。卸载保留独立的数据目录。

Windows 安装流程、快捷方式与本机权限保护仍需 Windows 实机验收；Mac 系统安装流程也需验收。Mac 独立应用的启动、重复打开和重启持久化须以打包后的应用核验。Windows 未代码签名，Mac 仅有本地 ad-hoc 签名，尚无 Developer ID 签名和 Apple 公证；当前为小范围试用包。不要建议用户关闭系统安全保护。

开发人员可运行：

```sh
.venv/bin/python local_client/launch.py --instance /absolute/path/outside-source/local-instance
```

构建 Windows 包前，下载固定版本的 Windows x64 wheels，再调用构建脚本。脚本从 Python 官方发布清单确定内嵌运行时并校验 SHA-256；只复制公共前端、服务器代码和依赖，不复制任何运行实例。

```sh
.venv/bin/python -m pip download --only-binary=:all: --platform win_amd64 --python-version 3.14 --implementation cp --abi cp314 --dest work/windows-wheels -r requirements.txt
.venv/bin/python scripts/build_windows_local.py --output /absolute/path/to/output
.venv/bin/python scripts/build_windows_installer.py --output /absolute/path/to/output
```

Windows 安装器需要 NSIS，使用命名互斥量避免覆盖正在运行的程序。ZIP 仅用于支持人员排查，公开下载页使用 EXE。Mac 需在 Apple 芯片电脑上，使用最低部署目标为 macOS 11 的 Python 3.14 构建环境：

```sh
python -m pip install -r local_client/macos-build-requirements.txt
python scripts/build_macos_local.py --output /absolute/path/to/output
```

已用 Astral python-build-standalone `20261026` 的 CPython 3.14.10 aarch64-apple-darwin 运行时构建；下载归档 SHA-256 为 `95eb8c87d16af37c54e9765e31d8c56c0d8ffa9968ea0f704f73a9b83f84e9f9`。不要用最低系统版本高于 macOS 11 的宿主 Python 构建并宣称兼容 macOS 11。打包后检查全部 Mach-O 的最低系统版本与应用签名，再在独立测试实例验证启动和持久化。

`scripts/build_download_site.py` 从两份安装包及校验文件生成黑白下载页。必须提供 `--installer`、`--mac-installer`、`--mac-verification`、`--output`；核验报告须包含匹配的 `version` 与 `packagedLaunchPassed: true`。公网页面只含静态文件、安装包及校验值，不能复制任何本地实例、密钥或数据库。

本分支基于集成版本 `46464071006fb3e734073b54c7d3d5684327ad81`，下面保留公共网页模式的开发说明。网页模式的正式授权门槛没有放开；只有明确启用且严格绑定本机的本地模式开放账号读取。

## 公共网页模式的集成状态

公共入口已装配 SQLite 存储、本站会话、LibTV 授权生命周期、账号与空间选择、项目工作流、任务归属与恢复、版本更新。前端只有一个 bootstrap，共享 API client 和事件通道。项目与草稿可以保存、刷新和重启恢复，角色、场景、道具分别保留制作与人工审核记录。

**当前是集成候选版，customerReady=false。** 正式 GenerationAdapter 已注入 ProviderService，并与同一 Store、TaskRepository、WorkflowService 接线；模型、准备、提交、查询、参考图和下载的协议流程已有实现。生产响应字段映射、准确模型绑定、项目到空间映射与媒体域名证据尚未补齐，不能开放真实生成。创作 scope、公网 callback 和收费实测是另外三个未通过的门槛。另一隔离实例已完成本机官方只读授权；该实例的凭据没有复制到本仓库或发布包。

客户最终通过网址操作，无需 Codex 或 CLI。以下命令只给开发和部署人员使用。8768 与 8870 是原工作台和基线端口，禁止此副本占用。

## 本地运行

运行环境已在 Python 3.14.7 验证。requirements.txt 固定凭据加密与图片完整性检查所需依赖。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/init_local_instance.py --directory /absolute/path/outside-release/local-instance
.venv/bin/python -m backend.app --port 8890 --data-dir /absolute/path/outside-release/local-instance/data --secret-key-file /absolute/path/outside-release/local-instance/secrets/storage.key
```

打开 http://127.0.0.1:8890/。初始化只为新实例生成密钥，绝不覆盖已有密钥。数据与密钥分别存放在代码发布目录之外；密钥须为当前服务用户独占的普通文件，不能软链接、随数据备份或进入发布包。更换密钥会影响已有加密授权，不能用重新初始化代替恢复。

子路径实例添加 --public-base-path /asset-lab/，使用独立端口与实例目录，访问 http://127.0.0.1:8891/asset-lab/。API 自动位于 /asset-lab/api/v1，根 /api 不被占用。--api-base 可显式指定另一个同源路径。Cookie 按根/子路径和本地实例隔离。

环境变量见 .env.example，命令行优先，程序不自动加载 .env。--check-config 只检查配置语法，不创建或迁移数据库。实际数据库 schema 为 **2**。指定发布清单时，先校验 schema 再初始化存储。回滚不能擅自把 schema 2 数据交给只支持 schema 1 的代码。

## 已装配行为

- tenantId/siteSessionId 仅从安全 Cookie 查服务端会话。项目、任务、文件下载、审核、草稿都校验工作区归属；浏览器不能指定其他租户。
- 写入验证 Origin、CSRF、发起时的 X-Asset-Lab-Session、字段白名单、对象版本、任务幂等。Cookie 轮换后即使拿到新 CSRF，旧页面发起的新项目创建或无 projectId 草稿仍返回 WORKSPACE_CONTEXT_CHANGED；已通过 HTTP 检查的请求在 Store 事务中再次验证 session，轮换竞态不会跨工作区落盘。
- 主所有者服务和 UI 已接入真实草稿检查、强制服务器保存凭据、旧上下文暂停与会话轮换。界面只在 workspaceOwnerAuthorization 明确为 true 时允许操作；当前为 false。外部会话改变时保留旧输入供用户核对，不把旧草稿保存到新工作区。真人 owner 绑定/找回尚未执行。
- 过期 Cookie 不静默生成新工作区。POST /session/anonymous 只接受同源显式新建动作与专用请求头，拒绝替换有效会话，不授予旧工作区访问权。
- 导入 TXT/MD/DOCX 或手工整理清单，导入不等于模型分析。MJ 风格、Image2 资产、Nano 精修逐阶段人工审核；返修追溯原始 Image2。
- 任务 owner 和工作流快照固定持久化。切换当前账号不改变历史任务，恢复只查询原回执，不重提生成。源换版时阻止旧结果混入当前资产。
- PUT /drafts/browser 保存新项目、计划、提示词、审核备注及待应用选择，采用 CAS。更新必须收到服务器保存确认，本机缓存不能代替确认。冲突保留双方副本并阻止自动覆盖。
- 版本模块使用页面构建时写入的标记，定期或手动提示。检查不会自动刷新；客户点击后再次检查草稿、任务、下载。页面与服务不兼容时拦截业务写入，仍可保存草稿。

health=200 只表示进程存活。ready 报告模块装配和官方授权、双真实账号、公网部署、生成门槛，未满足时保持 503。模块测试、合成 provider 或本地升级不代表客户成品完成。

官方只读证据见 backend/auth/OFFICIAL_READ_EVIDENCE.md。已确认 account_user.user.uuid 稳定、个人与团队空间投影；余额无字段，仍为 unknown。search_models 因缺 project:read 被拒绝。精确候选 callback 在标准 DCR 和 application_type=web 下都被拒绝；这不证明所有公网 OAuth 都不支持。生成缺项详见 backend/generation/EVIDENCE.md。

## 检查与打包

```sh
.venv/bin/python scripts/check_all.py --output /absolute/path/to/evidence/all-checks.json
.venv/bin/python scripts/check_integration.py --output /absolute/path/to/evidence/http-tests.json
.venv/bin/python scripts/build_bundle.py --output /absolute/path/to/asset-lab-customer-source.zip
```

源码包从指定 Git commit 白名单生成，ZIP 内含每文件 SHA-256，外附整包校验和，同 commit 可重复构建。排除旧引擎、客户数据、密钥、Git 元数据、本地测试实例、原工程媒体和未提交改动。

发布结构由 scripts/build_customer.py 生成 .build/public 和 .build/server，不带测试假服务。deploy/release.py 根据真实 build spec 生成清单、完整 SHA-256 inventory 和不可变版本资源基址。示例 buildId、时间、版本、说明须替换为实际值。

scripts/prepare_local_release.py 可完整构建、校验、解包到仓库外独立 loopback 实例，用于升级验收，不连接远程主机。发布包从 server 目录启动：

```sh
python -m backend.app --frontend-dir ../public --release-root /absolute/runtime-root --running-manifest ../release.json --public-base-path /asset-lab/ --port 8892 --data-dir /absolute/instance/data --secret-key-file /absolute/instance/secrets/storage.key
```

## 发布边界

未操作 ssh kelao，未修改公网路由。https://kk666.best/asset-lab/ 仅为候选路径，实际官方注册曾拒绝该候选 callback，不能推广为所有公网回调都不支持。

部署、回滚、SSH/Hub 流程保留在 deploy/，生产 hooks、反向代理、服务用户、备份迁移、公网验收还须配置执行。工具要求真实空闲检查、预检、激活、停用和探针 hooks；示例命令不是已安装的服务。

allowPaidSubmission 与 videoGeneration 目前不可开启。新增收费路径必须受同一提交门槛控制，最终视频继续暂停。

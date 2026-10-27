# 资产实验室 · 客户网页版集成预览

公共入口已装配 SQLite 存储、本站会话、LibTV 授权生命周期、账号与空间选择、项目工作流、任务归属与恢复、版本更新。前端只有一个 bootstrap，共享 API client 和事件通道。项目与草稿可以保存、刷新和重启恢复，角色、场景、道具分别保留制作与人工审核记录。

**当前仍是集成预览，customerReady=false。** 收费提交、正式视频和未验收的网页授权入口由服务器关闭。真实图片 provider 的模型、准备、提交、查询、上传、下载适配尚待后续模块提交；这与创作 scope 尚未取得、收费实测尚未进行是不同缺项。协调会话确认另一隔离实例已完成本机官方只读授权；该实例的凭据不复制到本仓库或发布包。公网回调准入、两个真实身份隔离和公网部署尚待独立验收。

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
- 写入验证 Origin、CSRF、字段白名单、对象版本、任务幂等。未知异常只记录随机请求号和异常类型，不记录 OAuth code/state、URL 或 Cookie。
- 主所有者恢复使用独立服务，与创作用账号分开。只有新鲜官方身份验证、意图校验和必要确认成功后才能轮换会话。授权 hook 和 UI 的后续提交完成前，不宣称客户已能找回。
- 导入 TXT/MD/DOCX 或手工整理清单，导入不等于模型分析。MJ 风格、Image2 资产、Nano 精修逐阶段人工审核；返修追溯原始 Image2。
- 任务 owner 和工作流快照固定持久化。切换当前账号不改变历史任务，恢复只查询原回执，不重提生成。源换版时阻止旧结果混入当前资产。
- PUT /drafts/browser 保存新项目、计划、提示词、审核备注及待应用选择，采用 CAS。更新必须收到服务器保存确认，本机缓存不能代替确认。冲突保留双方副本并阻止自动覆盖。
- 版本模块使用页面构建时写入的标记，定期或手动提示。检查不会自动刷新；客户点击后再次检查草稿、任务、下载。页面与服务不兼容时拦截业务写入，仍可保存草稿。

health=200 只表示进程存活。ready 报告模块装配和官方授权、双真实账号、公网部署、生成门槛，未满足时保持 503。模块测试、合成 provider 或本地升级不代表客户成品完成。

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

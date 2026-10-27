# 资产实验室：版本检测与发布工具

交付状态：模块已实现并在本机隔离环境验收；没有发布到 kelao，没有修改其 Nginx、服务或客户库。此目录只负责版本与发布，不能把模块测试通过当作客户产品/官方授权验收通过。集成接线见 [INTEGRATION.md](docs/INTEGRATION.md)，现场核查见 [KELAO.md](docs/KELAO.md)。

## 可运行验证

在客户版仓库根目录执行（Python 3.11+，Node 22+，不安装第三方依赖）：

```sh
python3 deploy/verify.py
```

它运行前端版本逻辑、Python 发布/回退、真实 loopback HTTP 测试，并写 `deploy/evidence/verification.json` 和两份日志。测试不调用 provider、不提交生成、不通过 SSH 写服务器。

浏览器演示使用合成代码包：

```sh
python3 deploy/demo.py --directory /tmp/asset-lab-release-demo --public-base-path /asset-lab/
python3 deploy/preview.py --root /tmp/asset-lab-release-demo/runtime --channel preview --public-base-path /asset-lab/ --port 0
```

服务始终只监听 `127.0.0.1`，打印实际端口，不抢 8768/8870。先打开页面，再用下述 install 命令安装 `demo-second.tar.gz`；老页面手动检查将显示新版。`demo-first.tar.gz`/`demo-second.tar.gz.sha256` 均由真实打包器生成。演示页面明确标明合成验收；演示保存使用当前标签页的 sessionStorage，正式草稿保存必须接上集成服务。`preview.py` 不是客户鉴权服务，不用于公网部署。

## 代码包与目录

构建输入必须是经过审阅的 `.build/public` 和可选 `.build/server`。不要将原工作台、整个用户目录、运行库、授权目录或旧实验 outputs 作为输入。`config/build-spec.example.json` 是集成构建配置模板，里面的 `scripts/build_customer.py` 由集成会话提供；它并不是已经存在的构建入口。`deploy/demo.py` 是现在即可运行的完整示例。

```text
/srv/asset-lab-customer/
  tools/<tool-sha256>/release.py        # 已校验工具快照
  incoming/                            # 传输中的包，成功后清理
  runtime/
    releases/<version>--<buildId>/      # 发布后只读，不覆盖同名版本
      public/                          # 唯一允许静态公开的目录
      server/                          # 可选，仅服务进程读取
      release.json                     # manifest v1
      files.json                       # 文件长度和逐文件 SHA-256
      build-evidence.json              # 构建/测试成功状态
    channels/<preview|stable>/current  # 原子替换的链接
    channels/<preview|stable>/previous # 成功切换前的版本
    channels/<preview|stable>/pending.json # 只有未结束事务才存在
    audit/                             # 不含凭据的发布审计
/var/lib/asset-lab-customer/<preview|stable>/ # 独立持久化，由应用管理
/etc/asset-lab-customer/               # 受保护服务配置，不进入代码包
```

稳定/预览必须使用各自数据目录。发布工具不复制、不迁移、不删除、不恢复客户数据库/素材，也不注销授权。历史版本默认保留，不自动清理；旧页面的延迟加载资源仍可访问。日后清理须保证没有仍需引用的版本并保留回退版本。

构建器执行 JSON 参数数组形式的 build/test 命令，两者都成功才打包；只复制 include 指定目录，拒绝链接、隐藏/运行数据路径、数据库和已知凭据模式。它保留合法的 `backend/sessions`、`auth/tokens.py` 源码模块，但拒绝同位置的授权 JSON/数据库。白名单和模式检测不能代替对应用特定配置/JSON 的审阅。产物中的 `files.json` 为每个文件记录 SHA-256；其字节摘要写入 manifest.integrity.value，包本身另有 `.sha256`。摘要经本机与 SSH 两端核对，不把自带摘要当作发布者数字签名。

构建器会把 build stamp 嵌入 `public/index.html`，并为 HTML 设置不可变版本资源基址：`<publicBasePath>releases/<version>--<buildId>/`。页面读嵌入的当前构建，不查询 live API 来猜当前标签页版本。每个静态资源均有内容 SHA-256；不可变版本 URL 保证缓存隔离，集成构建器也可输出本身带内容 hash 的资源文件名。相对资源引用留在对应版本目录，切换 current 不会让旧 JS 再加载新版本依赖。版本身份不得复用。

## 本地构建、安装和回退

```sh
python3 deploy/release.py build --spec /absolute/reviewed-build-spec.json --output /absolute/output/asset-lab-preview.tar.gz
python3 deploy/release.py install --bundle /absolute/output/asset-lab-preview.tar.gz --sha256 '<本机已核包摘要>' --root /absolute/isolated/runtime --data-root /absolute/isolated-data --channel preview --origin http://127.0.0.1 --base-path /asset-lab/
python3 deploy/release.py status --root /absolute/isolated/runtime
python3 deploy/release.py rollback --root /absolute/isolated/runtime --data-root /absolute/isolated-data --channel preview --origin http://127.0.0.1 --base-path /asset-lab/
```

`install` 拒绝坏摘要、坏清单、不同渠道、路径穿越、链接、额外文件、同版本不同内容；成功时先校验并冻结新目录，再写事务日志，原子切 current，探活通过后记录 previous。已有根目录必须带本工具标记，防止误用已有业务目录。文件锁防止并发发布。稳定安装额外需要 `--allow-stable`。

含 `server/` 的包必须提供 `--hooks /absolute/reviewed-hooks.json`，五个 hook 都是参数数组：

- `quiescenceCommand`：实际检查运行任务/下载/worker 租约；未安全完成或隔离时非零退出，不能简单把页面任务数当后台状态。
- `preflightCommand`：在候选 release 检查依赖、当前真实数据库 schema、配置、备份与启动条件；不得提交收费任务或迁移真实数据。
- `activateCommand`：仅切换资产实验室进程。脚本读取 `ASSET_LAB_RELEASE_DIR`，采用已审阅的服务管理方式。
- `deactivateCommand`：仅在首次发布失败、原本没有旧进程时关闭新服务。
- `probeCommand`：确认真实 HTTP 健康、运行 buildId/API/schema 与候选匹配；非零退出触发回退。

这些 hook 通过 `ASSET_LAB_RELEASE_DIR`、`ASSET_LAB_DATA_DIR`、`ASSET_LAB_CHANNEL` 获取上下文，不把密码放在命令参数或发布日志。`config/hooks.example.json` 中的路径是待集成实现的 hook 示例，不能未经实现就声称可重启生产后端。

新旧 `dataSchemaVersion` 不同一律拒绝自动代码切换/回退。数据库迁移需另行备份、迁移审阅和恢复方案；不在发布脚本里隐式执行。实际数据库版本仍须 hook 与存储模块现场核对，不能仅依据两个 manifest 相等。

如果新服务/探活失败，脚本恢复旧指针并重新激活、探活旧服务；恢复失败保留 `pending.json`，结果不会被标为成功。进程崩溃遗留 journal 时后续发布拒绝继续；审查后可使用相同参数执行 `recover` 恢复旧指针。不要删除 journal 强行跳过，也不要恢复客户整库。

## 通过 kelao 发布

现在可只读执行：

```sh
python3 deploy/ssh-release.py preflight
```

有真实集成产物后才执行：

```sh
python3 deploy/ssh-release.py publish --bundle /absolute/reviewed-preview.tar.gz --sha256 '<核对后的摘要>' --origin https://kk666.best --base-path /asset-lab/ --channel preview --hooks /etc/asset-lab-customer/hooks-preview.json
```

包装器固定使用已有 SSH 别名 `kelao`；先读现行规则/CURRENT/变更记录，再检查独立 Hub 任务，注册并认领、上传校验工具与代码包、执行原子发布、读回状态、追加无凭据 CHANGELOG 并结束任务。有其他活跃 asset-lab 任务时拒绝抢占。它不自动写 Nginx、不分配公网域名、不操作车队/门户、不安装系统软件。

稳定发布还需要 `--allow-stable --acceptance /absolute/integration-acceptance.json`，验收文件必须明确 `integrationPassed: true`、`customerReady: true`，并记录与本包一致的 `bundleSha256`。这道校验只保证验收记录与代码包绑定，不能代替真实业务验收。

第一次实际服务安装须先按远端纪律创建独立非特权用户和数据目录，使 `asset-lab` 用户拥有其 `0700` 数据目录，并准备受保护 env 与 hooks；不要对已有目录盲目 chown/chmod。当前这些服务器目录、用户、配置、hook 和服务均未由本会话创建。以后回退使用 `ssh-release.py rollback`，同样先完成 Hub 认领，稳定回退要显式 `--allow-stable`。

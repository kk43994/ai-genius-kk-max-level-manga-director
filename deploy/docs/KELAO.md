# kelao 只读核查与候选发布位置

2026-10-27 北京时间 16:29 首次核查，后续同日复核。原始结构化证据：`../evidence/kelao-inspection.json`。仅用已有 `ssh kelao`；现行 `/root/AGENTS.md`、协作 HANDOFF/PROTOCOL/HUB、项目 CURRENT、架构废弃清单与 CHANGELOG 已阅读。

现场观察：

- `nginx -T` 配置检查返回 0，服务 active；现有 HTTP include 为 `/etc/nginx/kk666-conf.d/*.conf`，TLS/stream 有自己的分流层。已有客户线路与站点共享服务机，不能新增一个抢占 443 的通用 vhost。
- `https://kk666.best/` 实际 HTTPS 200，未禁用证书校验。根站点在 `/var/www/kk666-site`，HTTPS server 文件 `/etc/nginx/kk666-conf.d/root-kk666-best-https.conf`，内部 TLS listener `127.0.0.1:12443`。已有 `/finance/` 通过独立 snippet 提供服务。
- 根站证书覆盖 `kk666.best` 和 `www.kk666.best`，有效期 2026-10-14 至 2027-01-12。没有为资产实验室申请新域名或新证书。
- 在已加载的 Nginx、`/srv /opt /var/www` 深度 4 目录以及 asset-lab Hub 项目中，没有找到已有资产实验室部署/任务/CURRENT；这是检查范围内未发现，不宣称全盘从来不存在相关文件。
- 现有 `/opt/opc-finance/current -> releases/20260806T013907Z` 可作为不可变版本目录模式的现场参考；本轮没有改动它。
- Node v24.18.0、Python 3.14.4 可用，主盘约 79G、已用 45G、可用 32G。候选 `127.0.0.1:18769` 当时未监听，但尚未预留，部署时须重查。
- Nginx 的 mime.types 当时没有 `.mjs` 映射，示例 snippet 局部补充；没有因此修改全局 MIME 文件。

候选入口为 **`https://kk666.best/asset-lab/`**，可复用现有有效 HTTPS，以独立子路径避免占用主站根路由。该路径尚未创建/发布，根站 SPA fallback 的 200 不能当作资产实验室已存在。需要最终确认这个入口和预览访问控制，并由第 10 集成会话安装经过核验的唯一 include。

建议专属命名空间 `/srv/asset-lab-customer/`、外部数据 `/var/lib/asset-lab-customer/{preview,stable}`、保护配置 `/etc/asset-lab-customer/`；这些位置本轮均未创建。本轮没有注册/认领 Hub 任务，因为没有远端实质写入；未来 ssh 包装器会先按现行规则注册/认领再写。

准备的 `nginx-asset-lab.locations.example.conf` 不修改公网 443 分流，不替换整个站点；所有 API 仅在 `/asset-lab/` 内代理，发布静态内容只映射每个 release 的 public 子目录，永不暴露 server、数据或授权目录。`systemd` 示例只是未安装模板，单独非特权用户与数据目录权限必须在实际服务配置阶段处理。

真实部署状态：**未部署、未公网预览、未切换稳定版**。本轮没有停止或重启原服务，没有读取或修改车队/门户客户库，没有上传私密资料或创建凭据。部署脚本/配置是可审阅交付，真实服务与 URL 可用性必须在集成产物到位后另行验证。

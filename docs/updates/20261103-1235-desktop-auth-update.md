# LibTV 授权修复通过桌面更新发布

<!-- update-record: {"id":"20261103-1235-desktop-auth-update","version":"0.3.0-preview.6","date":"2026-11-03T12:35:00+08:00","title":"LibTV 授权兼容修复与桌面新版提示","releaseState":"published-evidence","verificationState":"recorded","commits":[]} -->

## 为什么改

Windows 客户能打开 LibTV 官方页面并确认，但工作台仍显示授权失败和零个账号。公开 preview.5 安装包仍只接受已从官方目录移除的 account_user；新版源码已经支持 doctor.identity，但客户还未收到新安装包。截图不能代替客户日志，实际设备恢复仍需客户更新后确认。

## 这次改了什么

- 将已验证的 LibTV 身份与项目读取兼容修复打入 preview.6，提供 Windows x64 和 macOS Apple 芯片安装包，通过固定官方下载页及更新源交付。
- 使用现有自动更新：启动约 3 秒后检查，之后每 4 小时检查一次；后台下载并校验新版，显示“稍后提醒 / 保存并安装新版”，用户确认前不安装。
- 安装前保存草稿、检查运行任务；程序与本地工作区分别存放，历史安装包保留。旧客户端不因服务端发布而突然具备更新器，0.2.3-preview.1 及更早版本仍需先覆盖安装一次。

## 验证记录

- 精确解包 preview.5 Windows 源码，以当前官方目录形状的合成响应复现 PROVIDER_IDENTITY_UNAVAILABLE；同一响应在 preview.6 完成授权并返回两个合成空间。
- 发布源码固定为 9dbf657f9f6f3e684417ac7df4ea3b6d4fd714fe；包含 c9c8957 的接口兼容修复。完整回归 11 组、862 项通过，无真实收费请求。
- Windows 安装包解包后 653 项清单 SHA-256 一致；两个平台前端一致。Mac 打包程序在隔离空工作区真实启动，版本和更新接口正常。
- Playwright 真实浏览器验证发现新版、稍后提醒、重新检查和未保存时阻止安装，桌面及 390 px 可见；测试夹具仅 favicon 404，不影响功能。
- 公开发布后 8 个变更文件 HTTPS 哈希一致，release.json 为 no-cache；使用 preview.5 Windows 安装包内的原始更新器在本机分别指定两种平台，真实读取公开源、下载、校验并返回 ready / canInstall，分段下载返回 206。未调用安装接口。
- 未执行 Windows 程序、两端系统安装器或客户电脑升级，不将模拟更新及本机验证称为客户恢复。

## 发布状态

2026-11-03 北京时间 12:36 原子发布至 `/var/www/asset-lab-releases/20261103-preview6-9dbf657`；公开下载页与更新源现为 preview.6。8 个文件变更，38 个原有文件保持原哈希，历史下载保留；未改 Nginx 配置或重启业务服务。

回退前核对实际站点指针与并发任务，再原子切回 `/var/www/asset-lab-releases/20261103-kk-director-mobile`；已升级客户端不会自动降级。备份为 `/srv/kk666/backups/assetlab-preview6-20261103`。本次安装包固定使用已公开 main 提交 9dbf657，不包含其他工作树尚未合入的 Key 授权服务或后续开发改动。

客户实际版本、是否开启自动更新以及安装后的 LibTV 连接尚未取得反馈。现有 preview.5 会显示浮动更新提示，已关闭更新者需手动检查。

## 关联位置

- [连接诊断](../rag/libtv-connectivity.md)
- [桌面更新](../rag/desktop-updates.md)
- [preview.6 版本说明](../versions/0.3.0-preview.6.md)
- [可复核发布证据](../versions/evidence/preview6-desktop-release.json)
- 仓库外检查证据：`../evidence/preview6-auth-reproduction.json`、`preview6-release-checks.json`、`preview6-package-verification.json`、`public-preview6-deployment.json`、`public-preview6-verification.json`。

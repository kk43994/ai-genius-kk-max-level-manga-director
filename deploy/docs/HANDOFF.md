# 第 9 会话交付摘要

- 独立仓库：`/Users/zhoukaihao/Documents/New project/work/asset-lab-release/repo`
- 分支：`codex/release-updates`；基于 `f2069e3a9c460e6f6d9dcf9a5fc1f4e95999cccf`。
- 集成可按本分支提交 cherry-pick；只新增第 9 模块责任目录，没有修改共享入口。
- 后端：严格 manifest v1，运行构建快照与最新发布分别查询、v1 envelope、短缓存、no-store、安全失效。
- 前端：共享 api.request、启动/6 小时/手动检测，SemVer，当前/最新/说明/兼容状态；保存 ACK/冲突/任务/下载保护；显式刷新；不会自动安装或生成。
- 发布：构建测试、白名单包、文件/清单/包 SHA-256、不可变目录、锁、current 原子切换、previous、失败回退、崩溃 journal/recover、独立数据目录、跨 schema 自动切换拒绝。
- SSH：固定 kelao + 独立 namespace，现行文档/Hub claim/上传校验/状态回读/CHANGELOG。没有执行远端写入，也没有公网部署测试包。
- 接线与限制：见 `INTEGRATION.md`；配置示例中的集成构建入口及生产 hooks 待第 10 会话补齐。当前基线 app.py 没有被改动，不能声称正式路由已集成。
- 验证：运行 `python3 deploy/verify.py`；结果与源码摘要见 `deploy/evidence/verification.json`。HTTP 同时覆盖 `/` 与 `/asset-lab/`。浏览器证明见 `browser-observations.json` 与截图。
- 浏览器演示保存是合成 sessionStorage，真实服务端草稿/tenant/任务重启需集成接线后另验收。没有 LibTV 请求、收费或最终视频生成。

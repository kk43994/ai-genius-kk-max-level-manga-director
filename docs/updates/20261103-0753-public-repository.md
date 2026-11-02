# 公开 KK DIRECTOR 仓库并更新默认分支

<!-- update-record: {"id":"20261103-0753-public-repository","version":"0.3.0-preview.6","date":"2026-11-03T07:53:00+08:00","title":"仓库正式公开，默认首页展示最新导演台","releaseState":"published-evidence","verificationState":"recorded","commits":[]} -->

## 为什么改

用户明确要求将 GitHub 仓库设为公开，并强调产品面向漫剧工作室，支持 LibTV 扩展作为额度来源，后续扩展 Lovart。仅更新功能分支不能保证访客打开仓库就看到当前版本，需要同步默认分支及实际可见性。

## 这次改了什么

- 仓库已设置为 Public；默认 main 展示当前 KK DIRECTOR 首页、最新源码、原创配图和逐次升级/RAG 目录。
- [PR #1](https://github.com/kk43994/ai-genius-kk-max-level-manga-director/pull/1) 以合并提交 `34c8bc8e3992fe12f1a0d11cd8ced3aa37b2eea5` 并入 main，保留全部独立迭代与原标签。
- 首页与 About 明确：面向漫剧工作室的 AI 导演台，LibTV 为当前创作能力与额度来源，Lovart 尚在规划中。完整中文展示名继续保留，URL 使用英文名。
- 同步知识库适用分支与公开维护规则，区分公开源码和桌面安装包发布。

## 验证记录

- 源码提交 `72c4adb450771c1d8a75675f52285a9e4dda0421` 的 [PR 检查](https://github.com/kk43994/ai-genius-kk-max-level-manga-director/actions/runs/41548324237) 与 push 检查均成功，包含 RAG、逐次记录覆盖及 `scripts/check_all.py` 完整回归。
- 官方 API 返回 `private=false`、`visibility=public`、`default_branch=main`；另用无认证 HTTP 请求读取仓库 API 和 main README，均成功，README 字节与本地一致，SHA-256 为 `b8a5b834445f10428583e3075885070edb584d2dbc6f24f086776bbe4ec372bb`。
- 真实 Chrome 确认 Public 标记、main 分支、完整中文标题、LibTV / Lovart 定位，以及正常显示的主图、流程图与功能表格；私有验收证据保留在仓库外。
- 本文只补记实际公开结果；后续文档提交的持续检查独立显示，不把先前检查冒充新提交结果。

## 发布状态

**已公开的是 GitHub 仓库和 preview.6 开发源码。** 公共桌面安装包与更新源仍为 preview.5，没有发布新安装包，也不声称其他用户电脑已升级。公开代码不等于新增开源许可证；此轮没有变更许可证。

## 关联位置

- [公开仓库](https://github.com/kk43994/ai-genius-kk-max-level-manga-director)
- [首页与品牌改造记录](20261103-0750-repository-branding.md)
- [仓库展示 RAG](../rag/repository-presentation.md)
- [版本维护规则](../rag/versioning.md)

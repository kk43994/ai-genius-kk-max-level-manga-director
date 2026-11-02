# GitHub 首页升级为 KK DIRECTOR 品牌展示

<!-- update-record: {"id":"20261103-0750-repository-branding","version":"0.3.0-preview.6","date":"2026-11-03T07:50:00+08:00","title":"重做 GitHub 首页、主视觉与项目介绍","releaseState":"source-only","verificationState":"recorded","commits":[]} -->

## 为什么改

旧 README 仍以 preview.3 与早期只读连接说明开头，无法准确展示当前统一制作画布。用户要求使用完整中文项目名，生成高级主视觉和配图，写有气势的介绍，并将仓库公开。

## 这次改了什么

- 用 KK DIRECTOR 黑金主视觉、暖纸流程图和六项功能卡片重做首页，定位为面向漫剧工作室的 AI 导演台，突出 LibTV 作为当前创作与额度来源、Lovart 作为后续扩展方向。
- 两张原创概念图通过内置 imagegen 并发生成，提示词随仓库保存；没有使用用户项目截图充当宣传图。
- 仓库已改名为 `ai-genius-kk-max-level-manga-director`，同步 About、主页链接、主题与当前 Git remote；当前源码 preview.6 和公共桌面 preview.5 分开显示。
- 新增仓库展示 RAG，将每次升级时间线、知识库、真实验收范围与源码启动入口放到首页。
- 完整保留用户指定中文标题，解释固定制作流程与可人工编辑内容；区分额度使用与余额读取，未接入的 Lovart 明确标为规划中。

## 验证记录

两张图片人工查看，文字、比例与边界完整。Gitleaks 8.30.1 扫描 128 个可达提交；两处候选经原位置复核为提交哈希与无效令牌测试样例。敏感文件及用户内容扫描、原有合成截图复核完成；没有发现真实凭据或客户原文/素材附件。公共下载页 HTTP 200。README 的 19 个本地链接全部存在，图片解码与尺寸验证通过；首轮系统 Python 缺少 Pillow，改用项目既有虚拟环境后通过。GitHub 官方 Markdown 渲染返回完整 6 个功能标题、5 张表格与 6 个图片元素。RAG 25 个来源、71 条记录及提交覆盖检查通过，git diff --check 通过。main 合并与公开状态另记发布证据；本次仅文档及图片变更，不重复真实收费生成测试。

## 发布状态

本条为源码文档和品牌素材更新；仓库改名与简介已保存，公开操作尚待最终在线核验。没有更新桌面安装包、公共更新源或客户电脑。源码验收与安装包验收继续分别记录。

## 关联位置

- [项目首页](../../README.md)
- [仓库展示 RAG](../rag/repository-presentation.md)
- [视觉资产与生成提示词](../brand/PROMPTS.md)
- [preview.6 版本记录](../versions/0.3.0-preview.6.md)

# 固定画布制作流水线

更新：2026-11-03。preview.6 开发源码，公共安装包尚未更新。

## 用户流程

主导航为制作画布、任务与版本。每部剧使用同一个版本化模板，AI 只填写剧情、角色、场景与道具；布局、占位、依赖由程序控制。分析后先有框架，再在原卡补图。卡片展开对象面板，保留画布位置和其他输入。

先在画布美术区试人物风格、场景风格，再带两张样板做人物入景试镜。MJ 用于前两项探索，Image2.5 Pro 默认用于试镜与生产。三张图人选用后，明确确认整套全剧标准；候选返回不等于选用，单图旧标准继续兼容。旧标准引用若已被改选，展示原图让人核对，不自动重新审核。

人物与场景主多视图先定，状态继承其固定版本；既有场景共享设计图仅在已持久化来源一致时兼容，新状态不绕过主图。镜头固定素材版本，参考齐备即可单独做；勾选最多 8 镜并发准备，再确认提交。未知提交不重发。

同页按剧情顺序看图片、描述、原文台词和状态；图板预演仅播放静帧与时长。提示词规范保留原图、模型、参数、源提示词及证据等级，模板改写标为待试。

## 实现与验收

frontend/workflow/canvas-template.js、art-studies.js、canvas-batch.js、prompt-recipes.js、controller.js；backend/workflow/art_studies.py、prompt_recipes.py、art_direction.py、production_lineage.py；backend/integration_drafts.py 接受新增编辑草稿命名空间，不赋予生成或审核权限。

Chrome 合成项目完成三样板、主资产与状态、参考固定、并发补图、点图保留、预演和提示词归档；390 px 无横向溢出。HTTP/SQLite 测试验证草稿重启恢复、跨租户隔离及未知字段拒绝。真实模型效果、人工审美确认和公开安装包为独立验收。

权威执行与未完成项：docs/plans/2026-11-03-canvas-production-line.md；版本记录：docs/versions/0.3.0-preview.6.md。

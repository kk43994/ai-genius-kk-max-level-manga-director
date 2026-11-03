<div align="center">

<img src="docs/brand/kk-director-hero.png" alt="KK DIRECTOR：黑金电影镜头与连续分镜组成的品牌主视觉" width="100%">

<h1>AI天才kk选手进军漫剧界直接做出满级ai漫剧导演台</h1>

<p><img src="local_client/website/logo.svg" alt="KK DIRECTOR 原创 Frame K 标识" width="64"></p>
<p><strong>KK DIRECTOR · 为漫剧工作室打造的 AI 导演台</strong></p>
<p>开局一份剧本，出手就是导演台。<br>接入 LibTV 创作与额度来源，让一间工作室的想象力，进入可复用的制作流程。</p>
<p><strong>当前支持 LibTV 扩展接入 · 后续扩展 Lovart</strong></p>

<p>
  <a href="https://github.com/kk43994/ai-genius-kk-max-level-manga-director/actions/workflows/verify.yml"><img src="https://github.com/kk43994/ai-genius-kk-max-level-manga-director/actions/workflows/verify.yml/badge.svg?branch=main" alt="源码验证状态"></a>
  <img src="https://img.shields.io/badge/SOURCE-0.3.0--preview.6-171717?style=flat-square&labelColor=171717&color=b49a66" alt="源码 0.3.0-preview.6">
  <img src="https://img.shields.io/badge/DESKTOP-0.3.0--preview.6-171717?style=flat-square&labelColor=171717&color=738f80" alt="公开桌面版 0.3.0-preview.6">
  <img src="https://img.shields.io/badge/FINAL_CUT-YOURS-171717?style=flat-square&labelColor=171717&color=b49a66" alt="创作决定由人做出">
</p>

<p>
  <a href="https://kk666.best/asset-lab/"><strong>下载桌面预览版</strong></a> ·
  <a href="#平台接入与额度来源">LibTV / Lovart</a> ·
  <a href="#从剧本到分镜">制作流程</a> ·
  <a href="#导演手里有什么">功能一览</a> ·
  <a href="docs/updates/README.md">每次升级</a> ·
  <a href="docs/rag/README.md">项目知识库</a>
</p>

<sub>主视觉与下方流程图由 imagegen 原创生成，属于品牌概念配图；实际功能与验收范围见版本记录。</sub>
</div>

---

## 这一次，导演位我坐定了

**AI 天才 kk 选手，正式进军漫剧界。**

剧本交给 AI 拆，风格由我定；角色立得住，场景接得上，每一个镜头都能回到画布上重新打磨。从一张风格样板，到整部剧的美术标准；从一句台词，到一组能看懂剧情的分镜——创作的主动权，始终在导演手里。

KK DIRECTOR 的野心很直接：**做漫剧工作室最好用的 AI 导演台。** 把平台的生成能力与额度接进来，把工作室的剧本、美术标准、资产和镜头组织起来。下一部剧，换上你的故事，继续开拍。

固定的是流程、版式与制作依赖。人物、场次、镜头、台词和画面，随时可以由人增删修改。AI 负责减少重复劳动，最后一拍，由你喊。

## 平台接入与额度来源

**工作台负责导演与制作流程，接入的平台提供生成能力与额度。** 当前通过 LibTV 官方扩展接入用户自己的账号，调用可用模型、引用素材并提交图片创作任务，实际消耗对应账号的 LibTV 额度。创作内容和最终选用决定留在导演台中统一管理。

| 平台 | 当前定位 | 接入状态 |
| :--- | :--- | :--- |
| **LibTV** | 当前创作能力与额度来源：官方授权、图片模型目录、个人素材库与生成任务。 | **已接入。** 可用能力依官方账号、授权和目录而定；官方未返回余额时显示未知，不把未知显示成 0。 |
| **Lovart** | 后续扩展的创作平台与额度来源，继续服务同一套工作室制作流程。 | **规划中。** 具体接入方式与能力待官方接口和授权条件核验，当前版本尚未接入。 |

面向工作室的方向是：复用全剧美术标准和资产，减少重复输入，在同一处看图、改图与审查剧情。未来扩展平台时，继续保留账号归属、任务回执、素材版本和人工选用记录。

## 从剧本到分镜

<img src="docs/brand/production-flow.png" alt="制作流程概念图：导入剧本、确立人物与场景风格、制作多视图资产、编排连续分镜" width="100%">

| 阶段 | 画布上发生什么 | 你来决定什么 |
| :--- | :--- | :--- |
| **01 · 剧本入场** | 导入 TXT、Markdown 或 DOCX；AI 提取角色、场景、事件与台词，先铺出剧情卡片和画面占位。 | 校对原文、补充遗漏、改写内容、增删角色与场次。 |
| **02 · 全剧美术定调** | 分别探索人物与场景风格，再做人物入景试镜，形成一套可继承的全剧美术标准。 | 哪张脸、哪种质感、什么空间气氛，值得成为这部剧的标准。 |
| **03 · 资产站稳** | 先做人物、场景主多视图，再以固定版本派生剧情状态；关键道具单独建档。 | 选用哪个版本，哪些细节需要带着原图重新调整。 |
| **04 · 镜头开拍** | 引用已确认素材，编排动作、构图与台词；按依赖批量补图，新画面回到原来的镜头卡。 | 选图、比较、修改、重抽，控制相邻镜头的衔接。 |
| **05 · 连起来看** | 在同一画布审查多视图、分镜图、描述与台词，静帧预演后导出图文分镜资料。 | 剧情是否清楚、人物是否一致、这一版是否可以交付。 |

**先有框架，后补画面；看到问题，就在问题旁边改。** 制作画布与任务版本分工明确，减少来回切页面和重新填写同一份信息。

## 导演手里有什么

<table>
<tr>
<td width="50%" valign="top">

### 一张画布，整部剧都在眼前

剧情、全剧美术试做、人物场景资产与镜头共用制作画布。卡片可移动、画布可缩放，点开对象就在旁边继续制作。尚未生成的画面保留占位，不耽误先看清故事。

</td>
<td width="50%" valign="top">

### 点图选版本，带原图改画面

图片旁直接比较与选用版本，展开重抽后填写修改意见，保留原参考和历史。Nano 洗图提供保真清理入口，新结果作为候选返回，是否替换由人决定。

</td>
</tr>
<tr>
<td valign="top">

### 模型自由选，任务一起跑

MJ 用于人物与场景风格探索；正式图片制作默认 **Lib Image 2.5 Pro**，下拉框提供当前官方目录中的图片模型。支持多组抽卡与最多 8 镜的批量准备，核对费用后并发提交。

</td>
<td valign="top">

### AI 给初稿，人有修改权

角色、场次、事件、镜头和台词可增删修改；说话人、台词类型与顺序也能调整。原文单独保留，编辑结果同步到预演和导出，删除镜头后可恢复。

</td>
</tr>
<tr>
<td valign="top">

### 好效果，留下制作配方

固定人物、场景与道具的引用版本，支持个人素材库和本地上传参考。把模型、参数、提示词与来源一起保存为规范，并区分待试、单次通过和重复验证。

</td>
<td valign="top">

### 每次进步，都有记录

源码、版本说明、RAG 与逐次升级记录一起维护。任务保留原回执，余额未知明确显示未知，已完成的图片版本持续保留。遇到问题能找到原因，也能找到当时的版本。

</td>
</tr>
</table>

## 现在可以用到哪里

| 入口 | 当前版本 | 范围 |
| :--- | :--- | :--- |
| **本仓库源码** | `0.3.0-preview.6` | 统一画布、就地编辑、版本选图、AI 内容人工纠错等最新开发功能。逐项证据见 [preview.6](docs/versions/0.3.0-preview.6.md)。 |
| **公共安装包与更新源** | `0.3.0-preview.6` | 包含 LibTV 官方接口兼容修复；启动/每 4 小时检查，发现新版后由用户决定是否安装。[发布与验证](docs/updates/20261103-1235-desktop-auth-update.md)。 |
| **图片创作** | 已接入，持续打磨 | 使用你自己的 LibTV 账号和授权；实际可用模型、费用与结果取决于官方服务。新候选由人选用。 |
| **视频与音频** | 后续阶段 | 当前交付重点是带分镜图、画面描述与角色台词的分镜脚本，以及静帧预演。 |

已有真实前端的 22 镜图文分镜制作与导出记录；新统一画布完成完整合成流程和代表性真实出图验证。**这不等于所有模型、Nano 清理质量或所有电脑安装都已验收。** 具体范围、失败记录和下一步分别写在 [版本说明](docs/versions/0.3.0-preview.6.md) 与 [制作清单](docs/plans/2026-11-03-canvas-production-line.md) 中。

## 开始创作

普通使用者从 [桌面下载页](https://kk666.best/asset-lab/) 安装，启动后在浏览器操作工作台，连接自己的 LibTV 账号，再导入剧本。日常创作不需要 Codex 或命令行。

<details>
<summary><strong>开发者：从源码启动最新画布</strong></summary>

当前依赖组合在 Python 3.14 验证；运行前确保端口 `18874` 空闲。

```bash
git clone https://github.com/kk43994/ai-genius-kk-max-level-manga-director.git
cd ai-genius-kk-max-level-manga-director
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python local_client/launch.py \
  --instance ../kk-director-instance \
  --enable-image-generation
```

以上是 macOS / Linux 终端示例；Windows 对应解释器位于 `.venv\Scripts\python.exe`。默认打开 `http://127.0.0.1:18874/asset-lab/`。实例目录放在源码之外，项目资料和授权数据不进入 Git。该参数开放经授权的图片任务入口，实际提交仍在前端确认。

维护与验证：

```bash
.venv/bin/python scripts/query_project_knowledge.py --check
.venv/bin/python scripts/check_update_history.py --check-commits
.venv/bin/python scripts/check_all.py
```

完整检查还需要 Node.js 22。提交前阅读 [协作约定](AGENTS.md)，每次有意义的迭代新增一份 [升级记录](docs/updates/TEMPLATE.md)。

</details>

## 每次升级，看得见

| 想了解什么 | 从这里看 |
| :--- | :--- |
| 这次到底改了什么 | [逐次升级时间线](docs/updates/README.md) · [CHANGELOG](CHANGELOG.md) |
| 当前功能怎么设计、改哪里 | [RAG 项目知识首页](docs/rag/README.md) |
| 哪些内容人可以修改 | [人工编辑约定](docs/rag/human-editing.md) |
| 画布生产流程与待办 | [画布流水线](docs/rag/canvas-production-line.md) · [逐项清单](docs/plans/2026-11-03-canvas-production-line.md) |
| 模型、素材、连接和更新 | [图片创作](docs/rag/image-creation.md) · [LibTV 连接](docs/rag/libtv-connectivity.md) · [桌面更新](docs/rag/desktop-updates.md) |
| 品牌主图与生成提示词 | [视觉资产说明](docs/brand/PROMPTS.md) |

RAG 在这里是随版本维护、可本地检索的项目知识源。首页直接列出最近升级内容；同一预览版本内的改动也逐次记录，CI 检查程序提交是否漏记。历史文档保留当时状态，判断当前能力请优先看最新 RAG 和版本记录。

---

<div align="center">
<strong>一部剧，可以由 AI 协作完成。<br>但每一个值得留下的镜头，都要有你的决定。</strong>
<p><sub>KK DIRECTOR · ONE CANVAS. EVERY SHOT.</sub></p>
</div>

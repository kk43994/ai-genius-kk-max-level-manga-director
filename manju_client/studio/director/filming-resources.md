# 导演台 · 镜头手法研究资料

用途：团队自己研究、自用的拍摄知识与案例索引。学习镜头的叙事目的、空间关系和可执行参数，在本项目白模中复现。此页不托管电影片段。

## 已核查的研究入口（2026-10-19）

| 资料 | 能查什么 | 适合怎样使用 |
| --- | --- | --- |
| [CineTechBench](https://github.com/PRIS-CV/CineTechBench) | 真实电影镜头标注；作者介绍覆盖七类摄影维度，600 多张电影图像和 120 个电影片段 | 研究景别、机位、构图、运镜、光线、色彩、焦距；标注与来源链接在数据集，非打包电影文件 |
| [中文运镜案例合集](https://github.com/yinxiaowai/awesome-ai-video-camera-movement-prompts) / [播放画廊](https://yinxiaowai.github.io/awesome-ai-video-camera-movement-prompts/) | 25 个示例；基本运镜、进阶效果和风格组合，配中文说明与提示词 | 先看效果再对照术语；主要是 AI 视频演示，不等于真实影视拉片库 |
| [StudioBinder 镜头指南](https://www.studiobinder.com/blog/ultimate-guide-to-camera-shots/) | 景别、构图、角度、运动与影视案例 | 阅读定义及“什么时候用”；为我们的原创拍摄卡提供教学参考 |
| [Everything AI Filmmaking](https://github.com/MRCalderon3D/everything-ai-filmmaking) | 摄影规则、分镜结构、动作词表、连续性和生产交接 | 参考其结构化表达；没有将整套框架、自动化钩子或模型服务装入本站 |
| [CinePrompt](https://github.com/SleenT/CinePrompt) | 当前仓库 README 内含一个单页实现，约 63 个词条、10 类 | 可参考分类和检索界面；没有当作成熟影视案例数据库 |

CineTechBench 的仓库将数据集标为 CC BY-NC-ND 4.0，具体说明见其 README；这里将它保留为自用研究来源。其他资料的原始说明以各仓库为准。未下载或改写完整电影数据集。

## 已安装的两个技能

1. [cinematic-director](https://github.com/wuwangzhang1216/DirectorSKILL) v2.1.0，MIT，固定版本 `c65ae0d14457053efb1e354c7e7f7e120d97fad1`。
   - 剧情节拍、人物走位、镜头目的、景别、轴线、视线、覆盖镜头、AI 生产交接。
   - 安装在 `~/.codex/skills/cinematic-director/`。
2. [style-cinematography-director](https://github.com/0xhughs/director-skills/tree/main/skills/style-cinematography-director)，MIT，固定版本 `35ca0a2b4cd55b0668aa9ea0f40273324b774bb4`。
   - 把氛围转为镜头距离、焦距、机位、光线、色彩和运动选择。
   - 安装在 `~/.codex/skills/style-cinematography-director/`，包含原仓库许可证。

安装记录保存于各技能目录的 INSTALL_PROVENANCE.json。技能给助手提供设计方法，不会自动为网页接上 AI 接口。

## 在当前导演台里的应用

- 每个镜头显示“为什么这样拍”和衔接要点。
- 空间视图显示叶宇—师心水的青色虚线轴线。
- 摄影机当前侧别与首镜起点侧别比较，提示同侧、轴线附近或另一侧。
- 轴线随人物移动更新。异象空间不使用正堂人物轴线。
- 这是几何提醒，不代替完整连续性判断；合法跨轴、三人关系重建与视线匹配仍需看实际监看画面。

## 已落地的镜头手法预设

当前网页已接入 15 种原创参数化实现：固定、推进、拉远、横移、水平摇、上下摇、升降、弧线环绕、完整环绕、跟随、光学变焦、推拉变焦、双人关系、两侧越肩。选择拍法和对象后，可直接套用到当前镜头，观看真实 Three.js 摄影机运动。

预设按当前人物位置、共享动作计算、所选景别与画幅计算机位，并记录关键帧、注视点和焦距。两侧越肩机位参考同一人物轴线；跟拍跟随实际表演位置；推拉变焦保持注视平面上的主体投影比例。不是照搬影视案例的绝对坐标。

页面同时提供轨迹俯视图、空间摄影机、实际摄影机画面、幅度/方向设置、单镜重播、撤回套用与工程保存。家具遮挡与沿途碰撞仍需通过实际画面检查，完整环绕会提醒跨轴风险。

### 预设记录字段

中文名 / 英文术语 / 叙事用途 / 人数与走位 / 景别 / 起止机位 / 注视点 / 焦距变化 / 时长与速度 / 前后镜衔接 / 示例链接 / 实现状态。

分开记录：
- 构图与机位：双人景、越肩、主观、仰俯拍等。
- 摄影机运动：固定、推拉、横移、摇、升降、跟随、环绕等。
- 光学变化：变焦、焦点转移、推拉变焦等。
- 镜头组接：正反打、动作匹配、视线匹配、揭示与反应等。

现有实现覆盖机位、运动和焦距三类。焦点转移、自动镜头组接与场景避障尚未实现；研究链接作为参考保留，未下载全部案例。

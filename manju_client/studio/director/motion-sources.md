# 人物动作 V4

更新：2026-10-22。现有男女白模与 7/8/9 头身规格保留；新增动作数据适配、世界坐标脚部约束、骨盆补偿及剧情表演层。

## 实际使用

- [Quaternius Universal Animation Library](https://quaternius.com/packs/universalanimationlibrary.html)：从作者上传的 [OpenGameArt Standard 包](https://opengameart.org/content/universal-animation-library) 下载；压缩包附 CC0-1.0 许可。此次包实查为 45 段动作及 1 个 T Pose；抽取站立、站立说话、普通步行、正式步行、坐下、起身、坐姿待机、坐姿说话、互动和胸部受击 10 段骨骼动作。没有使用其人物网格。官网 120+ 指完整产品，不能等同于这个免费包。
- 项目现有 Three.js / SkeletonUtils：克隆已绑定骨骼。自编方向适配层把源动作转换到既有骨骼上，再叠加剧情手部接触、头部注视、两段式 IK、脚部支撑及骨盆高度约束。
- 动作文件：`../models/motions/quaternius-standard.json`。许可：`../models/motions/QUATERNIUS-LICENSE.txt`。来源包及提取脚本存于项目 `work/motion-quality-v4/`。

## 调研参考，没有直接接入代码

- [pixiv/three-vrm](https://github.com/pixiv/three-vrm)：适合将来统一 VRM 人形骨骼与动画输入；当前男性白模并非 VRM，未强行迁移。
- [MULUALEM-TEKLE/IK-test](https://github.com/MULUALEM-TEKLE/IK-test)：脚部锁定与双骨 IK 的实现思路。
- [Three.js SkeletonUtils](https://github.com/mrdoob/three.js/blob/dev/examples/jsm/utils/SkeletonUtils.js)：骨骼克隆和重定向参考。

## 已落地

1. 导演台新增自然动作 / 旧版对照、起身退步快捷预演、动作试镜入口。
2. 站立和说话有非对称胸肩、手臂和呼吸变化；转头与胸肩错开起止时间。
3. 师心水先前倾起身，再侧向绕开座椅，四次交替迈步；支撑脚保持世界位置，骨盆随可达范围下调。
4. 一分钟白模中的上山、说话、抬头和叶宇反应沿绝对时间采样；倒放或任意跳转不累积误差。
5. 白模导出绑定源文件哈希；动作修改后旧输出标记待重导，历史视频保留。

## 验证与边界

已有 6 个绑定模型、42 个关节姿势回归通过。新增 3 人、900 个时间间隔 / 人的剧情动作扫描及两个人物的 5 秒山道动作扫描：未发现非有限骨骼坐标；设计的脚部目标与脚踝骨节点一致，站立支撑段无累计滑移；重复跳转相同时间得到相同结果。截图检查起身、移步、对话和抬头。

这仍是用于指导 AI 机位和动作的白模预演，不包含最终人物脸部表演、口型、衣袖布料模拟，也不等同于成片质量。脚部验证是脚踝目标误差，不能代替任意新地形的完整鞋底碰撞检测。新动作接入后，旧分镜图需逐镜复核再提交视频。

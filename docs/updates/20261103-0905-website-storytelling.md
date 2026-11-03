# 官网创作展示与交付说明

<!-- update-record: {"id":"20261103-0905-website-storytelling","version":"0.3.0-preview.6","date":"2026-11-03T09:06:05+08:00","title":"官网细节升级：品牌接入、设备下载与连贯动效","releaseState":"published-evidence","verificationState":"recorded","commits":["38cdcc3ad5ab50aa616df16345b8940cea3127e8"]} -->

## 为什么改

用户认可黑金动效方向，要求继续优化网页内容。官网需要让使用者直接理解得到什么、在哪里做决定，以及怎样开始创作，减少连续功能说明的阅读负担。

## 这次改了什么

- 五个制作阶段改为可点击展示：剧本、美术、资产、分镜、交付。每步分别呈现 AI 先做、你来决定和具体产出；键盘方向键、Home / End 可切换，未执行脚本时五阶段正文仍可阅读。
- 以三项直接操作讲清人的控制权：点图选版本、就地修改、增删 AI 初稿。增加四联概念画面与交付说明，展示图文分镜脚本、可调用资产与固定参考依据。
- 集中说明 LibTV 图片模型、个人素材库、并发与任务恢复；明确 MJ 风格探索、Lib Image 2.5 Pro 默认图片模型，Lovart / 视频 / 音频后续扩展。
- 下载区重做为带 Apple / Windows 图标的设备卡片，识别系统后突出对应入口，不推断 Mac 芯片，不自动下载；金属按钮带扫光和悬停反馈，安装、授权、导入三步随后展示，技术说明折叠。
- 接入 LibTV 与 Lovart 官方矢量 Logo，以当前服务的动态实线和未来规划的静态虚线表达关系；保存标识来源，不误指仿冒入口。
- 首屏运镜延伸到正文背景重构图；补齐流程切换、内容错峰入场、平台流动连线、胶卷扫光、卡片光感和按钮反馈。全局暂停、系统减少动态效果与离屏动画暂停保持可用。

## 验证记录

- [x] 网站构建 3 项检查、JS 语法、RAG 与差异格式检查通过；输出包括三份品牌矢量素材。
- [x] 浏览器验证五阶段点击及键盘方向键，每次只展示对应面板；平台流动动画可由全局按钮暂停，减少动态效果时关闭动画。
- [x] 实际 Mac 平台提示、模拟 Windows 高亮和手机安装提示；390 px 无横向溢出，下载卡片宽 330 px、平台示意宽 350 px，系统图标及品牌 Logo 全部加载。
- [x] 下载入口保持原安装包地址，安装说明展开、SHA-256 复制成功。
- [x] 2026-11-03 09:20 北京时间公开部署，页面、脚本、品牌资源、两份更新清单及两款安装包共 16 项 HTTPS 哈希一致；32 个原有非本轮修改文件保留。
- [x] 实现提交 `38cdcc3` 的 [分支 CI](https://github.com/kk43994/ai-genius-kk-max-level-manga-director/actions/runs/41559215399) 与 [PR CI](https://github.com/kk43994/ai-genius-kk-max-level-manga-director/actions/runs/41559297568) 均通过；[PR #3](https://github.com/kk43994/ai-genius-kk-max-level-manga-director/pull/3) 已合并，合并提交 `398922f`。

仅网站展示变更，不调用收费生成，不发布新安装包。

## 发布状态

本轮内容已于 2026-11-03 09:20 北京时间发布至官网，目标为 `20261103-kk-director-content`，保留前版 `20261103-kk-director-cinema` 以供原子回退。公共安装包与更新清单仍为 preview.5。公开品牌素材与下载地址已核对，维护端保存完整哈希和回退证据。

## 关联位置

- [官网](https://kk666.best/asset-lab/)
- [官网 RAG](../rag/public-website.md)
- [页面模板](../../local_client/website/index.template.html)
- [交互脚本](../../local_client/website/release.js)
- [上一版动效与发布证据](20261103-0810-public-website.md)

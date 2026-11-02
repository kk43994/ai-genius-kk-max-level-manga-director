# LibTV 连接、官方接口变更与余额

更新：2026-11-03。适用 preview.6 本地源码；公共安装包 preview.5 尚未包含本轮修复。

## 事实和处理

官方现行 Remote HTTP MCP 地址为 https://mcp.liblib.tv/mcp；官方插件使用动态 OAuth 注册，每位使用者独立授权。来源：[官方入口](https://www.liblib.tv/plugin)、[官方仓库 README](https://github.com/liblib-ai/marketplace/blob/main/README.md)。不需要另建本地供应商代理、共享浏览器 Cookie 或读取 CLI 凭据。

本轮真实前端诊断：当前目录移除了 account_user 和 project_info。旧工作台因此把接口变更表现为授权或生成失败。身份兼容改为 doctor.identity，项目只读兼容为 read_project(view=summary)。仅旧工具缺席时启用；旧接口报错/重复不盲目降级。账号 UUID、成员资格、当前计费账号、项目所有者和空间继续核对。

连接状态分为授权、空间核验、模型目录、余额和任务状态。只合并同会话同租户的并行只读状态请求，完成后不缓存授权、不重放写请求。暂时读失败与明确身份失效分别提示；历史余额若存在必须带原时间与同归属，不能显示为实时值。

当前官方接入未返回余额字段或可调用额度工具，权限页也没有经核实可开通的余额读取范围。因此能力明确为不支持，界面显示“余额未知”，禁用无意义刷新并保留官方积分页 https://www.liblib.art/calculation 。官网当前数值是独立人工页面读数，不注入工作台作为实时 API 余额。不能将网络失败、目录失败或身份读取失败断言为积分不足。

未提交的准备步骤失败，显示尚未收费生成，可取消该准备记录后重新准备；已尝试提交则只查原回执，不自动重发或换账号。错误不输出上游正文、令牌或签名地址。

## 实现和验证

backend/providers/libtv_identity.py、libtv_bound_tools.py；backend/generation/live.py；backend/auth/service.py；backend/tasks/errors.py；frontend/accounts/index.js、state.js、read-status.js。

真实 Chrome 已验证同身份 OAuth、空间目录和 28 个图片模型，官方项目响应字段已核对。合成测试覆盖新旧接口、重复/危险定义拒绝、身份变化与移除、项目字段异常、只读并发合并以及准备/提交错误文案。收费生成结果、图片质量、更新包仍独立验收。完整字段证据见 backend/auth/OFFICIAL_READ_EVIDENCE.md，执行状态见画布 Goal 清单。

尚可进一步改进：官方身份临时故障发生在令牌轮换后时，目前仍保守要求重授权；后续可设计加密隔离的新令牌待核验态，不能未经身份验证直接启用或自动重试收费动作。

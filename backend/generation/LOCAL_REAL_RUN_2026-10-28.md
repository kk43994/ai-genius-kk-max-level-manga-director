# 2026-10-28 本地 Chrome 真实验收

当前验收结论：MJ 真实生成、官方交付、本地四图待审已完成。参考上传和 Image2 未运行节点的连线已验证。Image2 / Nano 实际生成、逐步审核和最终 ZIP 下载尚未完成，不等于客户发布验收通过。

## 授权与运行范围

- 用户已批准本次创作权限和收费测试，实际授权为账号读取、项目读取/修改、素材上传、任务创建、素材导出六项 scope。
- 本地 Chrome 的 `http://127.0.0.1:18874/asset-lab/` 是本轮操作入口。应用使用自己的正式 OAuth 授权；不提取 Chrome cookie 或登录凭据。
- 本地入口需显式 `--enable-image-generation`，配置校验要求 `local_client=True`、`host=127.0.0.1`。默认启动和公网模式仍禁止收费生成，视频始终关闭。
- 测试使用独立的“叶宇 · 正式流程验收”项目。原剧本项目保持独立。每阶段选图仍需审核；当前四个 MJ 版本均为 pending。

## 现场验证的协议

- 模型完整创作 schema 位于 `get_model.inputContract.parameterSchemas.generate`。
- `mj-v8.1` 要求 count=4；`lib-image-2` 和 `nebula-2.1` 的可选数量为 1、2、4。界面按照阶段提供合法数量，不将 MJ 错写为 1 张。
- `account_user` 中 accountId 是计费账户。画布 projectSpaceId 属于项目空间，二者不能比较。个人账户必须核对 subject、ownerUuid、accountType=1、activeAccountId；项目须核对 ownerId、teamId=0、projectSpaceId / target_project.spaceId。
- `create_node(run=false)` 的节点号来自 plan.nodeId，并与 operationResult.subjectNodeId 交叉核验。`read_project(view=nodes)` 提供 revision.token、节点参数、参考列表和边；这些均与原始请求核对。
- 第一次成功的 Task SOT 响应为 schema_version=1、result_kind=media、readiness=TERMINAL_READY、outcome=SUCCEEDED；owner.user_uuid 和 task_id 必须与原任务一致。四个 artifact 使用同一生成节点、四个不同资源号。
- 官方交付按 outputIndex 调用 `prepare_project_delivery(watermark=keep)`，保存 operationId 及 sourceIdentity 摘要。恢复下载查询原 `get_web_operation_status`，不新建生成任务。
- `upload_ticket` 返回 parts[].method=PUT，未指定 Content-Type。自行添加该头会导致本轮签名上传失败；省略后上传成功。`upload_complete.file_ref` 是长签名句柄，只传给 upload_media，不进日志或本地任务持久化。
- 原图上传、官方素材登记、Image2 未运行节点的图片引用和边均实际验证成功。这些非收费动作不能替代 Image2 的真实生成验收。

## 真正返回的素材

1 次 MJ 生成取得 4 张 1024×1024 PNG，分别核验文件长度、MIME、解码、SHA-256 后入库。Chrome 审核列表和左侧资产卡均显示真实缩略图。任务状态为 completed，四个版本 review 均为 pending。

原 Task SOT 编号：`20261028062603717631366`。本地任务编号：`task_ebe96526ff0d419e917cf923801112bf`。

官方 Chrome 页面余额在此次生成前后观察到 4,015 → 4,000，差额 15；该观察不替代正式账单核对。另有两个本地准备记录在提交前取消，未产生正式生成。

## 修复与边界

- 原任务已成功，但本地 TUN DNS 将官方媒体域名解析到 198.18/15，下载安全检查拒绝。仅对精确白名单、且系统全部返回该保留代理地址时启用受限公共 DNS 查询；仍校验公共 IP、HTTPS 原主机证书，拒绝私网/回环、重定向、非白名单和不匹配 MIME。
- 上传签名头、长 file_ref、节点响应结构、模型数量及账号/画布空间映射按真实协议修复。
- 复用单次请求内的 MCP 会话与工具目录，逐工具调用重新检查原账号成员关系、scope、撤销状态和个人计费账户。没有缓存成员关系或自动换号。
- 中央工作流刷新后通知右侧任务栏；任务栏限制当前项目，并按新任务排序。旧错误不再覆盖已完成任务。排队、提交、生成、下载显示实际阶段，未知进度不伪造百分比。
- 剧本“人物：”段落保留完整角色描述，避免后续自动提示丢失人物设定。

仍未验收：参考生成付费回执的真实返回形状、排队/失败 Task SOT 的实际响应、Image2/Nano 生成及审核、最终 ZIP 从 Chrome 下载。未知回执继续保存原节点/请求/幂等键并停止，禁止换键重复收费。参考图上传中断后的自动恢复亦不作已完成承诺。

公网部署、Windows/macOS 安装包更新、签名和真实安装测试不在本次本地运行验收内。

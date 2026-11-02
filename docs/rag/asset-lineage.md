# 资产档案与图片谱系

状态：显式关联已实现，测试与浏览器验收见版本记录。适用：0.3.0-preview.1 开发分支。

## 身份

制作方案的 `assetId + stateId` 通过 `bindings` 指向清单的 `entityId`；图片有独立 `assetId + revisionId`、阶段、审核、owner 与不可变任务快照。同名不等于同一个资产。

旧项目的图片挂在原 entityId，原来制作方案计算新的 ent_pd_ 编号，两者即使同名也不会显示为同一档案。修复通过明确人工确认建立项目内 `productionLinks`。不修改原实体、图片、审核、账号、任务回执，也不默认批准旧图。

## 关联接口

`PUT /production-jobs/{id}/bindings`：assetId、stateId、entityId、expectedPlanVersion、expectedEntityVersion、expectedReviewVersion、expectedEditVersion、expectedBindingVersion、confirmApplicable=true。

仅同项目同类别、原账号／空间可关联；其他状态的专用 ent_pd_ / ent_shot_ 档案不能合并。方案或原档案变化会显示 changed 并阻止继续制作，直到重新核对。关联使用 CAS 并保留 productionLinkHistory。加入清单时跳过已关联项，避免再次创建。

图片跨阶段规则保持：MJ 选用后才可作为 Image2 来源；Nano 追溯原 Image2；导演引用只接受有效且已审核的 Image2 / Nano 固定版本。未审核、旧依据、跨账号图片不自动成为可用参考。

代码：`backend/analysis/production_bindings.py`、`production.py`、`backend/workflow/service.py`；界面：`frontend/workflow/production-bindings.js`；回归：`tests/analysis/test_production_bindings.py`。

## 全剧风格与生成快照

`PUT /projects/{id}/art-direction` 接受已选 MJ revisionId、sha256、notes、expectedVersion、confirmStyle=true。保存独立 artDirection / artDirectionHistory，不改剧本、plan.stylePrompt 或既有图片。规范确认不是一笔 AI 调用。

新任务工作流快照包含 artDirectionVersion；生成前和提交前校验当前规范版本、来源有效性及原账号空间。规范文本被明确加入本次实际发送提示词，用户能在费用确认页核对。更新风格后，新规范下制作的图片与旧规范快照不匹配时标为失效，历史文件保留。既有未记录美术规范版本的图片不追溯伪造快照，其适用性须由人核对。

对应代码：`backend/workflow/art_direction.py`、`backend/tasks/model.py`。测试：`tests/workflow/test_art_direction.py`。

## 选回原图后恢复依赖有效性（2026-11-03）

旧版 `_invalidate` 会把依赖暂时不成立的图片持久标成 `status=stale`；人工切换风格候选、随后选回确切原版本时，`_valid` 仍直接拒绝旧标记，造成全部规范资产和分镜持续显示待更新。此问题与供应商授权过期无关。

preview.6 对带已知依赖失效原因的旧记录重新核对实体/统一风格/全剧美术规范版本、已批准的确切来源及人物主图链。只有全部仍匹配才在只读响应中恢复 `ready`，不修改历史数据、原审核、图片、任务回执或绑定；待选、退回、其他来源、变更后的设定和未知失效状态仍不能变成已保留。有效响应去掉过时的失效文案。

`tests/analysis/test_dependency_restore.py` 覆盖整条资产与分镜恢复、真实设计与美术规范变更仍阻止恢复、退回图不自动选用、未知失效记录仍拒绝，以及读取/导出不依赖供应商授权。全量 752 项检查成功；真实 Chrome 经前端刷新恢复 20 张规范资产与 22 张已保留分镜，覆盖 42/42，实际打开原图为 1152×2048。本次未发起生成或重新审核，未公开发布客户端更新。
# 同一物料不同状态沿用形象（0.3.0-preview.2）

此节记录 preview.2 的旧实现；人物链路已由 preview.3 的主多视图规则替代。旧版规范资产参考选择器提供当前制作方案中同一 assetId 的已审核 MJ 候选，并显示来源档案名称。状态仍对应独立 entityId，生成和审核各自保存；没有复制一张图片冒充新生成，也不合并状态档案。Nano 仍只接受当前状态原始 Image2。

后端 `production_lineage.py` 使用当前剧本、分析、人工方案、资产设计指纹和显式绑定验证关系，不以名称判断。准备、提交前校验、收图和图片有效性检查都执行关系检查；移除关系或更改设定后停止继承，旧结果标为失效。交付统计承认同一物料的有效已选风格，但仍要求每个状态的 Image2 审核通过。

## 带参考图准备的真实接入修复

TaskService 的 `inputs.sources` 有意保存 revisionId、ownership、sha256，不保存审核状态副本。GenerationAdapter 原先要求快照含 `review=approved`，导致真实带图准备全部被误拒。现在只拒绝明确的未审核／失效提示，最终以 WorkflowReferenceReader 的当前已审核图、原始字节和摘要为准，未审核图片仍在工作流和接入层两次拒绝。回归增加实际 TaskService → Workflow → GenerationAdapter 的 Image2 准备，而不是只单独测试图片读取。

前端取消仅适用于 `submissionAttempted=false` 的记录，保留历史并更新当前生成草稿的准备编号。已提交或结果不明的任务仍只能恢复原任务。受控错误给出参考图、参数等具体类别；开发日志只记录固定错误码、异常类型、源码位置，不输出上游报文和签名链接。


## 人物主多视图是必要中间层（0.3.0-preview.3）

正式链路为本剧风格与人物形象 → 人物主多视图 → 人物剧情状态多视图 → 分镜。`production_states()` 为每个 character 生成独立 `__character_master__` 档案，保留原 AI 方案及全部状态编号。主档案不是数组中的首个状态；它参与 bindings 和交付统计，但不冒充某一场的状态引用。

`production_lineage.members()` 以当前方案、设计指纹、显式绑定和版本判定身份与 master/state 角色。`image2_source_allowed()` 规定：人物主图引用同一角色的已选 MJ；人物状态只引用同一角色已审核 Image2 主图，不允许 MJ、其他状态图或其他角色。准备、提交前再次核验、最终输出有效性均应用。审核变化会使依赖图失效；账号空间和原始字节校验不变。接入层允许 Image2 使用经工作流验证的 asset 原图，而非仅接受 style。

兼容：旧 MJ 图仍可供同一角色主图使用；旧任务可按不可变回执收回，但旧版 MJ 直接生成的人物状态图不满足新链路，只保留历史，不自动审核、不冒充主图。无需数据库批量改写。风格页聚合该角色历史 MJ 候选，创建的新候选进入独立主档案。前端生成草稿使用 identity-v2 命名，避免把旧状态提示词带入主图。

前端：`production-generation.js`、`creator-desk.js`。后端：`production.py`、`production_bindings.py`、`production_lineage.py`、`production_coverage.py`、`workflow/service.py`、`generation/service.py`。回归覆盖主图派生、跳步拒绝、主图退回、旧 MJ 复用及交付缺项。

## 参考上传失败与收费不明必须区分

TaskService 的 submissionAttempted 标记写在上传之前，用来防止整体重复调用。真实测试出现 upload_media 未返回可确认结果，此时只有项目回执，没有生成任务 ID。旧查询统一报回执缺失，导致永远无法继续。

LiveImageClient 查询原记录时，只有 journal steps 非空、全部为 upload_<sha256>、至少一个未完成、没有生成节点、收费 generation claim 或 originalReferenceRun，才返回 reference_upload / generationSubmitted=false。TaskService 还要求回执没有 nodeId 或 taskId，随后标记 failed + REFERENCE_UPLOAD_FAILED，保留 submissionAttempted=true 和全部旧记录。查询本身不上传、不生成；前端明确点击“重新准备本次生成”才创建新准备编号并重新确认。空日志、未知步骤、已进入节点／生成阶段一律保持原任务恢复限制。

同一个项目可能有多条仅含 projectId 的上传失败回执。TaskService 恢复时传入服务端已解析的 local_task_id，bridge 按该任务校验原 owner 与完整回执，不再凭共享项目回执反查任意任务；旧的无任务 ID 调用遇到多条仍拒绝。MCP 传输单独允许 60 秒等待，OAuth 仍为 15 秒；不自动重试请求。诊断只记录固定的超时／传输分类、HTTP 状态、工具名，不记录上游正文、凭据或链接。

参考图文件名使用内容摘要，画布挂载名另用 localTaskId 与摘要组合，避免同一张主图被多个状态任务引用时创建重名节点；同一任务内名称稳定，原调用记录不重写。生成区只显示当前最新任务的错误，历史上传失败留在任务列表，避免新任务提交时继续显示旧失败文案。


## 大量图片的读取性能（2026-11-02）

图片有效性会递归检查全剧风格、主图和剧情状态。此前同一次资产列表/图片读取中，每次继承关系检查都重新深拷贝、校验完整制作方案，随图片及引用层级增加产生大量重复计算。`production_lineage.members` 现在只在 `WorkflowRepository` 的只读快照内按项目复用结果；不跨请求、不跨租户，不缓存写入事务，新的方案及撤销审核仍按最新快照判定。

新增回归验证一次列表只计算一次、下次请求重新计算，以及写事务内修改实体后立即失效；原有改变设计和撤销主图测试继续通过。全量 725 项，722 通过、3 项原有跳过。合成三状态资产连续读取 10 次从 0.5372 秒降到 0.0896 秒（约 5.99 倍），只是本地合成样本，不代表真实 LibTV 生成加速。实际运行服务需在原提交结束后重启验证。

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
# 同一物料不同状态沿用形象（0.3.0-preview.2）

规范资产的参考选择器提供当前制作方案中同一 assetId 的已审核 MJ 候选，并显示来源档案名称。状态仍对应独立 entityId，生成和审核各自保存；没有复制一张图片冒充新生成，也不合并状态档案。Nano 仍只接受当前状态原始 Image2。

后端 `production_lineage.py` 使用当前剧本、分析、人工方案、资产设计指纹和显式绑定验证关系，不以名称判断。准备、提交前校验、收图和图片有效性检查都执行关系检查；移除关系或更改设定后停止继承，旧结果标为失效。交付统计承认同一物料的有效已选风格，但仍要求每个状态的 Image2 审核通过。

## 带参考图准备的真实接入修复

TaskService 的 `inputs.sources` 有意保存 revisionId、ownership、sha256，不保存审核状态副本。GenerationAdapter 原先要求快照含 `review=approved`，导致真实带图准备全部被误拒。现在只拒绝明确的未审核／失效提示，最终以 WorkflowReferenceReader 的当前已审核图、原始字节和摘要为准，未审核图片仍在工作流和接入层两次拒绝。回归增加实际 TaskService → Workflow → GenerationAdapter 的 Image2 准备，而不是只单独测试图片读取。

前端取消仅适用于 `submissionAttempted=false` 的记录，保留历史并更新当前生成草稿的准备编号。已提交或结果不明的任务仍只能恢复原任务。受控错误给出参考图、参数等具体类别；开发日志只记录固定错误码、异常类型、源码位置，不输出上游报文和签名链接。


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

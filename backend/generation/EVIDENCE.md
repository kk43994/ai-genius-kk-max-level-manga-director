# 官方协议证据与未补齐部分

观察日期：2026-10-27。公开 tools/list 来自第 2 模块提交 `c56463a2dc0138585b4831ff74e5880f4dca1fef` 的 `tests/auth/fixtures/libtv-tools-public-2026-10-27.json`，原导出选择 28 项；本模块仅保存用到的 14 项公开工具定义，没有账号响应、令牌或签名地址。

官方 MCP：`https://mcp.liblib.tv/mcp`。公开官方说明：[LibTV Production](https://github.com/liblib-ai/marketplace/blob/main/plugins/libtv/skills/music-driven-product-ad/references/libtv-production.md)。该说明支持实时模型核对、按原任务恢复、不将超时当失败等原则，但不提供下表的具体响应结构。已定向检查本机官方 marketplace 源码，未检出这些字段定义；已安装客户端为 Mach-O 可执行文件，未取得可核对同一 MCP 协议的源码/类型证据，未运行它、未读取其凭据或会话。

## 已确认且已编入请求的部分

| 操作 | 已确认输入与语义 | 官方 scope |
|---|---|---|
| search_models | `action=search,nodeType=image` | project:read |
| get_model | 精确 `model`；说明提到 inputContract.model / parameterSchemas | project:read |
| project_info | canonical `project_id` | project:read |
| upload_ticket | file_name/file_size/sha1_hex/part_size/projectId | media:write |
| upload_complete | path/upload_id | media:write |
| upload_media | name/idempotencyKey/projectId/fileRef/mediaType；输出 projectId/status/nodeId 已有结构化定义 | project:write |
| create_node | name/nodeType/idempotencyKey/model/projectId/prompt/params/left/run | project:write |
| read_node | exact node/projectId | project:read |
| update_node | node/projectId/idempotencyKey/model/prompt/params/leftEnsure/expectedRevision/run | project:write |
| generation_submit | project_id/idempotency_key/kind=image/request；描述明确 task_id | task:write |
| task_status | project_id/task_id；cop_ 不是生成任务 | project:read |
| prepare_project_delivery | 精确 media nodeId/outputIndex、idempotencyKey、projectId、watermark | export:write + project:read |
| get_web_operation_status | 原 operationId（wop_ 加 64 位十六进制）和 projectId | project:read |

scope 均带 `libtv:` 前缀。resource_info 的公开 schema 也保存于包内，当前主路径未调用它。

## 尚未完成的生产响应映射（是代码/协议缺项，不是单纯缺权限）

以下多数 outputSchema 仅为开放 object。`ResponseContract` 必须来自同一 MCP 协议的官方说明/源码类型，或在明确许可下取得并脱敏的真实响应。只有宽泛 schema 不足以把字段标成 verified。测试里的字段路径是合成样本，默认生产政策会拒绝它们。

| 仍缺证据的部分 | 代码要求核实的语义 | 缺失时停止的位置 |
|---|---|---|
| get_model.inputContract | 模型准确 ID；parameterSchemas 的完整容器与字段 schema；MJ/Image2/Nano 各自准确名称及控制项 | prepare 前，不能生成默认模型 |
| project_info | 返回项目 UUID 对应哪个空间、空间类型；与原绑定的比较规则 | 项目解析，不能借用默认空间 |
| upload_ticket | path/upload_id、分片数组、顺序/编号、每片 URL、PUT 协议及必要头部、官方上传主机 | 参考图上传前 |
| upload_complete | opaque file_ref 的准确字段位置和资源一致性语义 | 参考图上传前 |
| create_node/read_node/update_node | 项目/nodeId/taskId 的路径；持久保存状态、精确模型/提示词/参数/输入连线、revision；超时后的原任务引用及原提交幂等键对应关系 | 参考节点路线前 |
| task_status | 原 taskId/projectId、终态枚举和输出 nodeId 的准确位置 | 收费前的可恢复性检查 |
| prepare_project_delivery / get_web_operation_status | 每项 operationId、状态、所属项目、文件列表、原节点/输出索引、URL/MIME；可选的可信字节摘要 | 收费前/交付前，不绕过导出 |
| 媒体服务器 | 官方上传/下载主机清单及签名请求传输要求 | 收费/传输前 |

目前没有内置任何 `verified=True` 生产 ResponseContract，也没有默认 RecipeBinding 或官方 CDN 猜测值。所有这些受保护路径的协议骨架已实现；生产响应映射尚未完成，真实客户链路仍会停止。模块不会把 `raw schema` 或旧 CLI 私有响应直接解释为 MCP schema。

当前配置机制只接受显式字段路径和状态映射；若真实响应的结构、枚举、上传方法/头部或模型输入约束与当前消费者不同，应根据取得的证据调整消费者并补测试，不能只把 `verified` 改成 True。`SafeMediaTransfer` 当前支持无附加签名头的分片 PUT；若官方响应要求其他方法或头部，必须先完成相应实现。

## 最小补齐路线

1. 在不执行外部写入的前提下，先取得官方同协议文档/类型，或在明确批准 project:read 后，仅调用 search_models/get_model/project_info/read_node/task_status 读取已有样本。记录脱敏字段 schema、语义和来源版本，补精确模型配置、项目绑定验证和查询映射。
2. 上传和交付缺项优先向官方取得结构化说明/已有脱敏样本。没有证据就保持关闭；不能把一次真实上传或收费生成当 schema 探针。本轮没有执行这些操作。
3. 完成响应消费者与已核验传输域名后，第 10 模块接入组合根及受控错误展示，再运行同一组离线测试和针对新真实 schema 的契约测试。
4. 公网登录回调可用、用户明确批准所需 scope 和一次准确数量的图片费用后，再安排真人验收。须分别确认正式 Task SOT、实际图片字节、原账号空间、人工 review 和下载入库，不能只以返回任务号作为成功。

## 必须分开的四类状态

- **代码已实现**：官方请求构造、注入接口、Store/Task/Workflow 桥接、保护和恢复顺序，离线测试已执行。
- **代码/证据未完整**：上表的生产响应映射、模型绑定及媒体传输证据未补齐，当前不能开放真实生成。
- **账号授权不足**：第 2 模块交接说明报告当前 grant 仅 account:read；本模块未读取该真实 grant。project:read、media:write、project:write、task:write、export:write 分别仍需用户批准并由第 2 模块核验；不能用账号读取权限代替。
- **部署/验收未完成**：公网 callback 不由本模块解决；本轮未发布、未上传、未触发图片/视频/音频付费任务、未做真实收费链路验收。原 8768 服务和原素材保持不动。

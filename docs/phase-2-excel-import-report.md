# 阶段 2：Excel 数据导入中心与导入批次管理完成报告

## 1. 完成范围

阶段 2 仅实现 Excel 上传、结构分析、字段映射、预览、校验、标准化导入、批次历史、问题下载和受控撤销。没有实现补库建议、生产需求池、正式周排产、工序任务、报工、ERP 接口或真实库存业务计算。

支持的导入类型：

- `SHIPMENT`：销售出货明细；
- `INVENTORY`：实时库存；
- `PIPE_WIP`：水管在制品；
- `FITTING_WIP`：管件在制品；
- `REGULAR_PRODUCT`：常规排产产品清单；
- `WEEKLY_PLAN`：真实结构周计划的上传、分析、待匹配暂存和人工产品匹配；匹配后才生成标准化原始任务。

标准流程为：上传 → 工作簿/工作表分析 → 字段映射 → 100 行预览 → 全量校验 → 人工确认 → 事务导入 → 批次详情/受控撤销。上传、分析和校验均不写正式业务快照表。

## 2. 数据库迁移

新增迁移：`20260718_0002_add_excel_import_center_tables.py`、审查修复迁移 `20260718_0003_harden_phase_2_import_review_flows.py`，以及状态机、审计和可逆产品变更迁移 `20260718_0004_enforce_import_lifecycle.py`。

新增表：

- `import_batches`
- `import_row_issues`
- `products`
- `shipment_records`
- `inventory_snapshots`
- `pipe_wip_snapshots`
- `fitting_wip_snapshots`
- `regular_production_products`
- `imported_weekly_plan_raw`
- `weekly_plan_staging_rows`

所有六类业务表均保存 `import_batch_id`、`source_sheet`、`source_row_number`、必要原始值快照、`created_at` 和 `updated_at`。产品编码使用字符串列，数量使用 `Numeric(18, 4)`。产品增加 `last_import_batch_id` 来源追溯；周计划原始表增加每日计划和每日实际 JSON；待匹配表保存原名称、规格、批次、工序、设备、周期、每日/周计划与实际、匹配状态及人工匹配信息。

新增权限：`import.view`、`import.upload`、`import.validate`、`import.confirm`、`import.rollback`。初始化会幂等补齐现有角色权限，不重置用户密码。

## 3. API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/imports/upload` | 上传、限流、哈希、重复检测 |
| GET | `/api/v1/imports` | 分页及类型/状态/日期/操作人筛选 |
| GET | `/api/v1/imports/{id}` | 批次详情 |
| GET | `/api/v1/imports/{id}/sheets` | 工作表、真实范围和结构元数据 |
| POST | `/api/v1/imports/{id}/analyze` | 选表、表头识别和自动映射 |
| GET | `/api/v1/imports/{id}/preview` | 最多 100 行预览及问题标记 |
| PUT | `/api/v1/imports/{id}/mapping` | 保存人工映射和转换规则 |
| POST | `/api/v1/imports/{id}/validate` | 全量校验 |
| POST | `/api/v1/imports/{id}/confirm` | 单事务写入正式快照 |
| POST | `/api/v1/imports/{id}/rollback` | 有原因的受控撤销 |
| GET | `/api/v1/imports/{id}/issues` | 问题分页筛选 |
| GET | `/api/v1/imports/{id}/issues/export` | 带认证的 CSV 问题下载 |
| GET | `/api/v1/imports/{id}/audit-logs` | 批次操作审计链 |

所有写操作使用现有认证、后端权限依赖、统一异常结构、请求编号和审计日志。

## 4. Excel 解析与安全

- 只接受 `.xlsx`，默认 64 MB，可通过 `IMPORT_MAX_FILE_SIZE_MB` 配置。
- 原文件名只用于显示；服务器使用 UUID 文件标识，响应和错误不返回服务器路径。
- 上传流计算 SHA-256；相同导入类型、哈希和数据日期默认拒绝，管理员填写原因后可强制重传。
- `openpyxl` 使用 `keep_links=False`，不执行宏、不读取外部工作簿内容、不信任公式缓存。
- 使用只读流式读取和 200 个连续空行停止策略识别真实范围，最多扫描 500,000 行；百万格式残留行测试在 500 行内停止。
- 识别多工作表、多行表头、合并单元格、隐藏行/列、自动筛选、公式、外部引用和错误单元格。
- 合并单元格值只在明确合并范围内继承，普通空白不会盲目向下填充。
- 日期支持日期对象、Excel 序列和常用中英文文本格式；数量使用 `Decimal`。
- 数据库及审计不保存上传服务器路径；业务 `raw_data` 仅包含映射字段，不把未映射的客户、价格或金额写入审计。

## 5. 校验与事务

- 产品编码缺失、科学计数法、数量/日期失败、重复行和必填字段缺失形成 `ERROR`。
- 名称/规格冲突、负数量、库存可用量差异和普通公式形成 `WARNING`。
- 库存可用量由系统复算；Excel 可用量只作为对照。
- 周计划支持合并字段继承、计划/实际双行配对、七日计划与实际、计划周期和公式来源区分；确认导入先写 `WeeklyPlanStagingRow`，人工匹配后才写 `ImportedWeeklyPlanRaw`。
- 错误批次状态为 `VALIDATION_FAILED`，不能确认；警告批次可进入 `READY` 并确认。
- 确认导入使用单个数据库事务；异常时整体回滚并标记 `FAILED`。
- 阶段 2 尚无下游生产业务表；撤销保护已封装为独立引用检查入口，后续阶段增加外键引用时扩展该守卫。

## 6. 前端页面

- 数据导入批次列表：筛选、分页、刷新、统计和详情。
- 九步导入向导：类型、上传、选表、映射、预览、校验、确认、周计划待匹配、结果。
- 预览表：最多 100 行、横向滚动、产品列固定、Excel 行号、错误红色、警告橙色及问题筛选。
- 批次详情：文件哈希、工作表、映射、统计、问题、认证下载、真实审计记录和撤销原因输入。
- 上传、校验、确认和撤销按钮按当前用户权限显示，后端仍会强制鉴权。

## 7. 自动化测试

后端测试使用 Python/openpyxl 动态生成完全虚拟工作簿，覆盖：标准上传分析、扩展名/大小限制、重复检测、多工作表、多行表头、前导零、科学计数法、负在制、库存复算、名称规格冲突、错误阻止确认、警告确认、事务回滚、批次撤销、下游引用保护、角色权限、审计、路径脱敏、隐藏行、合并单元格、计划/实际配对、字段冲突、问题导出和百万格式行截断。

前端 Vitest 覆盖：九步向导、字段映射冲突、预览错误/警告样式、确认条件、权限控制和批次列表页面。

CI Docker 冒烟测试会动态生成 `TEST-PIPE-001` 虚拟库存工作簿，并实际执行登录、上传、分析、校验、确认和批次查询。

本地最终实际执行结果：

- `python -m pytest -q`：`63 passed, 1 warning`，最终复跑耗时 702.9 秒；警告为现有 FastAPI TestClient 上游弃用提示。
- Alembic：`upgrade head`、`downgrade base`、再次 `upgrade head`、`alembic check` 全部通过；check 输出 `No new upgrade operations detected.`。
- `npm ci --no-audit --no-fund`：成功，安装 236 个包。
- `npm.cmd run type-check`：通过。
- `npm.cmd run test:run`：3 个测试文件、8 项测试全部通过。
- `npm.cmd run build`：成功；仅有现有第三方 PURE 注释和单包大于 500 kB 的警告。
- Docker Compose：当前 Windows 环境没有 Docker CLI，无法本机实机启动；GitHub Actions 的 push 与 pull_request 两组 Backend、Frontend、Docker Compose 检查均已通过。Docker 作业真实构建并启动 PostgreSQL/backend/frontend，完成健康检查、登录，以及动态虚拟 Excel 的上传、分析、校验、确认和批次查询，最后执行 `docker compose down -v`。

## 8. 已知限制

- 周计划保存每日及周级计划/实际并先进入待匹配区，不生成正式排产模型，也不计算每日产能。
- 不解析或执行 Excel 外部链接；外部实际公式会记录来源和警告，但不会阻止可读计划量进入待匹配区。
- 自动字段同义词为首版字典，特殊模板可人工调整列映射；复杂映射模板管理留待后续阶段。
- 阶段 2 没有下游生产业务对象；引用阻止撤销的守卫已有测试，后续阶段必须接入真实外键检查。
- 上传文件当前保存在本机/容器文件系统；生产部署前应评估对象存储、保留期限和病毒扫描。

## 9. 人工验收步骤

1. 使用管理员或计划员登录，进入“数据导入”。
2. 用 openpyxl 创建只含 `TEST-*` 编码和虚拟数量的小型 `.xlsx`。
3. 完成选类型、上传、选表、字段映射、预览和校验。
4. 确认错误行不能导入，负数量/库存差异警告可在确认后导入。
5. 在批次详情核对 SHA-256、统计、问题下载和审计记录。
6. 管理员填写原因撤销已完成且未被引用的批次，确认业务快照删除且审计保留。
7. 用 VIEWER 登录，确认只能查看；用无导入权限角色确认后端返回 403。

## 10. 数据合规确认

仓库没有提交任何真实或脱敏自真实业务的 Excel 文件。所有测试工作簿均在运行时生成，仅使用 `TEST-PIPE-001`、`TEST-FITTING-001`、`TEST-CLAMP-108`、`LOT-DEMO-001` 等虚拟标识和虚拟数量；`.gitignore` 已忽略 `*.xlsx`。

## 11. PR #2 审查修复增量

本节记录 2026-07-18 的阶段 2 审查修复；如与前文初版描述不同，以本节为准。

### 11.1 隐藏行

- `include_hidden_rows` 默认是 `true`，所有物理数据行（包括隐藏行）均参与标准化和确认导入。
- 每行 `raw_data.source_row_hidden` 保留来源行隐藏状态，不再静默丢弃隐藏行。
- 用户可在上传时主动选择仅导入可见行。校验结果和批次详情分别显示隐藏数据行总数与被排除的隐藏数据行数；上传、选项修改和校验审计均记录该策略及统计。

### 11.2 快照日期

- `INVENTORY`、`PIPE_WIP`、`FITTING_WIP` 的最终快照日期按“Excel 映射值优先，否则使用批次 `source_date`”确定。
- 两处都缺失时产生 `SNAPSHOT_DATE_REQUIRED` 错误，批次不能确认；批次详情显示数据日期，快照记录保存最终使用值，因此不同批次可按日期区分。

### 11.3 真实周计划兼容与待匹配

- 支持制管、包装、成型、下料四类工作表，识别多层表头、七个每日计划列、计划/实际双行、纵向合并字段及工作表日期周期。
- 保存每日计划和每日实际；普通汇总公式、外部日报公式和人工计划值分别记录。外部实际公式不执行，也不会阻止可读计划量进入待匹配区。
- 工作簿中不同工作表周期不一致会产生 `WEEKLY_PLAN_PERIOD_MISMATCH` 警告。
- 缺少产品编码的周计划行只写 `WeeklyPlanStagingRow`，不会创建 `Product`。系统可按名称/规格搜索候选产品，但不会仅凭名称自动确认；用户通过待匹配列表和人工匹配 API 确认后，才生成 `ImportedWeeklyPlanRaw`。
- 前端向导增加“周计划待匹配”步骤。当前支持 `UNMATCHED`、`MATCHED` 和 `IGNORED` 操作，数据模型同时预留 `SUGGESTED`、`CONFLICT` 状态。

新增 API：

| 方法 | 路径 | 用途 |
|---|---|---|
| PUT | `/api/v1/imports/{id}/options` | 修改隐藏行及产品主数据冲突策略 |
| GET | `/api/v1/imports/{id}/weekly-plan-staging` | 查询周计划待匹配记录 |
| GET | `/api/v1/imports/{id}/product-candidates` | 按名称/规格搜索候选产品 |
| POST | `/api/v1/imports/{id}/weekly-plan-staging/{row_id}/match` | 人工匹配或忽略待匹配行 |

### 11.4 产品主数据冲突与补充

- 校验按产品编码与数据库现有主数据比较，名称、规格、类别、单位差异分别产生稳定 WARNING，并同时返回 Excel 值与数据库值。
- 默认策略 `FILL_EMPTY` 只用导入值补充数据库空字段；`KEEP_EXISTING` 完全保留现有主数据；`ADMIN_UPDATE` 必须由管理员填写原因后明确选择，才可覆盖非空字段。
- 所有补充和更新写入审计日志，记录字段前值、后值、原因和批次；`Product.last_import_batch_id` 记录最近产生变更的导入批次。已有非空字段不会被默认策略静默覆盖，冲突也不会被静默忽略。

### 11.5 CSV 导出安全

问题 CSV 继续使用 UTF-8 BOM。文本以 `=`、`+`、`-`、`@` 开头时采用 Excel 安全文本前缀，合法负数数值保持数值显示，中文内容不受影响。

### 11.6 新增或调整的自动化测试

- 隐藏行默认导入、显式仅导入可见行、隐藏行批次统计和审计；
- Excel 快照日期优先、`source_date` 回退、日期缺失阻止确认、跨批次日期区分；
- openpyxl 动态生成四张接近真实结构的虚拟周计划表，覆盖多层表头、七日计划/实际、合并字段、外部公式、周期冲突、待匹配和人工匹配；
- 跨两个导入批次的产品主数据四类冲突、三种处理策略、空字段补充、来源和审计；
- CSV 公式注入防护、合法负数、UTF-8 BOM 和中文。

### 11.7 已知限制

- 本阶段的周计划能力止于上传、分析、待匹配暂存和人工匹配后的原始记录；没有进入正式排产、产能计算、生产需求池或补库计算。
- 不执行 Excel 外部公式，无法得到的外部日报实际量保留公式元数据并等待后续数据来源；可读的计划量仍可暂存。
- 候选产品只提供人工搜索，不做基于名称的自动确认或模糊自动合并。

## 12. PR #2 第二轮审查修复

### 12.1 导入批次状态机与并发确认

- 正式确认只接受严格 `READY` 状态；确认事务先锁定批次并再次检查状态，再以 `WHERE status = 'READY'` 的原子更新认领为 `IMPORTING`。PostgreSQL 使用行锁，SQLite 测试环境使用原子比较更新作为等效并发控制。
- `validate` 只接受 `ANALYZED`、`VALIDATION_FAILED`、`READY`；映射只接受 `UPLOADED`、`ANALYZED`、`VALIDATION_FAILED`、`READY`。修改映射或影响解析的选项后回到 `ANALYZED`（尚未选表时保持 `UPLOADED`），必须重新校验。
- 非法状态统一使用 `IMPORT_STATE_INVALID`、`IMPORT_VALIDATION_REQUIRED`、`IMPORT_ALREADY_COMPLETED`。已完成、已撤销和失败批次不能绕过状态机。
- 两个并发确认请求只有一个能执行实际导入，另一个得到明确冲突，不会重复写入产品或业务快照。

### 12.2 重复批次复查

- `ImportBatch.source_date` 改为物理日期列并建立复合查询索引，不再依赖不可移植的 JSON 日期查询。
- 上传、修改 `source_date`、确认前统一调用相同重复检测服务，条件为导入类型、文件 SHA-256、数据日期及非 `CANCELLED`/`ROLLED_BACK` 状态。
- PostgreSQL 对重复身份获取事务级 advisory lock，覆盖“当前还没有重复行”的并发窗口；候选批次同时使用行锁。
- 修改日期形成重复时拒绝保存。只有管理员可以填写原因后强制，审批原因进入批次审计；确认前会再次检查，防止校验后的并发变化。

### 12.3 产品主数据可逆变更

- 新增 `ProductImportChange`，记录 `CREATED`、`FILLED_EMPTY`、`ADMIN_UPDATED`、字段前后值、变更字段和导入批次。
- 撤销事务会先完整预检所有产品冲突，再在同一事务内删除业务记录并删除新建产品或恢复被修改字段；任一冲突都会整体回滚。
- 当前批次新建产品若已被其他批次或周计划引用，返回 `PRODUCT_MASTER_ROLLBACK_CONFLICT`。被修改字段若后来又被其他批次修改，也拒绝旧批次自动恢复。
- `last_import_batch_id` 随字段恢复为前一批次或空值。产品恢复前后值写入 `product.master_data.rollback` 审计。

### 12.4 审计链、隐藏实际行和周期识别

- `AuditLog.context_import_batch_id` 为上传、分析、映射、选项、校验、确认、产品变更、周计划匹配/忽略、撤销和产品恢复提供可移植的批次关联；批次审计接口直接按该列查询。
- 仅导入可见行时，隐藏计划行整项排除；计划可见但实际行隐藏时，不读取实际量，保存 `actual_row_hidden`/`actual_row_excluded`，产生 `WEEKLY_ACTUAL_HIDDEN_EXCLUDED`，每日及周实际保持空值。
- 跨工作表周期判断直接复用 `infer_week_dates`，支持 `2026.7.13-7.19`、只有日号的表头、Excel 日期单元格与整数日号混用，并能借用工作簿中的年份识别 `7.10-7.16`。

### 12.5 范围确认

本轮仍未实现补库计算、生产需求池、正式排产、产能计算、工序任务或报工；没有提交真实公司 Excel，所有新增工作簿均由 openpyxl 在测试运行时动态生成。

## 13. 合并前大文件兼容与性能修复

### 13.1 上传、代理和完整性

- `IMPORT_MAX_FILE_SIZE_MB` 与 `.env.example` 默认值调整为 64；前端 Nginx 设置 `client_max_body_size 64m`。普通 API 代理超时保持 10～30 秒，上传、分析、映射、选项、预览、校验和确认接口允许最长 600 秒。
- 上传不再累积文件块或执行 `b"".join(...)`：请求体直接写入同目录临时文件，同时增量统计字节数和 SHA-256；超限立即停止并清理，安全工作簿验证通过后原子改名，数据库事务失败也删除正式文件。
- 分析、预览、校验和确认前会流式重算存储文件 SHA-256；文件被外部修改时返回 `IMPORT_FILE_INTEGRITY_FAILED`，不继续处理。
- 前端导入接口不再受全局 15 秒限制，上传显示进度及后端验证中的状态，并区分文件过大、网络超时、后端可能仍在处理和后端明确失败。

### 13.2 流式校验与事务导入

- 非周计划和周计划确认均直接消费 `iter_normalized_rows` 生成器，不再构造全量 `parsed_rows` 列表。
- 校验和确认各以一次查询加载现有 `Product` 映射。相同产品在同一文件出现 10,000 次的测试证明不会产生逐行产品查询；新产品只创建一次，变更记录按产品汇总为一条。
- 销售、库存、在制和常规产品使用 SQLAlchemy Core 每 2,000 行批量插入；周计划暂存与校验问题也分块写入。分块只 `flush`，全部解析、数量核对和审计完成后才 `commit`，任一异常仍整笔回滚。
- 确认导入会核对实际写入数与全量校验的有效行数，不一致返回 `IMPORT_ROW_COUNT_MISMATCH`。
- 大批次撤销将产品和其他批次引用改为分块集合查询，避免逐产品 N+1；产品恢复和业务记录删除继续处于同一事务。

### 13.3 周计划并发与 Docker 集成

- 周计划匹配/忽略与撤销使用同一个 `ImportBatch` 行锁，且只允许 `COMPLETED` 周计划批次执行；撤销后返回 `IMPORT_STATE_INVALID`，不会残留 `ImportedWeeklyPlanRaw`。
- Docker CI 通过前端 Nginx 地址 `http://localhost:8080/api/...` 生成并上传大于 1 MB 的 10,000 行虚拟库存工作簿，覆盖分析、未校验确认阻断、校验、确认和结果查询；没有绕过 Nginx 访问导入 API。

### 13.4 真实规模虚拟基准

新增 `backend/scripts/benchmark_large_import.py`，默认动态生成 268,000 条虚拟销售记录和约 12,000 个虚拟产品编码，并执行上传、分析、字段识别、全量校验、确认、结果/重复核对和撤销。2026-07-18 已在隔离 SQLite 环境实际运行一次：文件 38.44 MB，上传 14.61 秒、分析 92.25 秒、校验 122.18 秒、确认 160.81 秒，API 流程合计 402.27 秒，峰值 RSS 775.04 MB；268,000 条业务记录和 12,000 个产品全部核对成功，重复业务行为 0，撤销后业务记录与本批次新建产品均为 0。完整记录见 `docs/phase-2-large-import-benchmark.md`。大型 XLSX 与基准数据库运行后已删除，未提交仓库。

### 13.5 本轮验证结果

- `python -m pytest -q`：`69 passed, 1 warning`，耗时 727.5 秒；警告仅为 FastAPI TestClient 上游弃用提示。
- Alembic：`upgrade head`、`downgrade base`、再次 `upgrade head` 与 `alembic check` 全部通过；最终输出 `No new upgrade operations detected.`。
- `npm.cmd run type-check`：通过。
- `npm.cmd run test:run`：4 个测试文件、10 项测试全部通过。
- `npm.cmd run build`：通过；仅有既有第三方 PURE 注释和单包大于 500 kB 警告。
- 当前 Windows 验证环境没有 Docker CLI；提交 `b8d3af6` 的 push 与 pull_request 两组 GitHub Actions 已全部通过。两组 Backend、Frontend、Docker Compose 共 6 个作业均成功；Docker 作业真实构建并启动 PostgreSQL、backend、frontend，并通过 8080 端口完成大于 1 MB、10,000 行虚拟文件的上传、分析、未校验确认阻断、校验、确认和查询，最后执行 `docker compose down -v`。

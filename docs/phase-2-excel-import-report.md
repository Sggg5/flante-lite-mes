# 阶段 2：Excel 数据导入中心与导入批次管理完成报告

## 1. 完成范围

阶段 2 仅实现 Excel 上传、结构分析、字段映射、预览、校验、标准化导入、批次历史、问题下载和受控撤销。没有实现补库建议、生产需求池、正式周排产、工序任务、报工、ERP 接口或真实库存业务计算。

支持的导入类型：

- `SHIPMENT`：销售出货明细；
- `INVENTORY`：实时库存；
- `PIPE_WIP`：水管在制品；
- `FITTING_WIP`：管件在制品；
- `REGULAR_PRODUCT`：常规排产产品清单；
- `WEEKLY_PLAN`：现有周生产计划的标准化原始任务。

标准流程为：上传 → 工作簿/工作表分析 → 字段映射 → 100 行预览 → 全量校验 → 人工确认 → 事务导入 → 批次详情/受控撤销。上传、分析和校验均不写正式业务快照表。

## 2. 数据库迁移

新增迁移：`20260718_0002_add_excel_import_center_tables.py`，父迁移为 `20260717_0001`。

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

所有六类业务表均保存 `import_batch_id`、`source_sheet`、`source_row_number`、必要原始值快照、`created_at` 和 `updated_at`。产品编码使用字符串列，数量使用 `Numeric(18, 4)`。

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

- 只接受 `.xlsx`，默认 20 MB，可通过 `IMPORT_MAX_FILE_SIZE_MB` 配置。
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
- 周计划支持合并字段继承、计划/实际双行配对、计划周期和外部公式检查，只写 `ImportedWeeklyPlanRaw`。
- 错误批次状态为 `VALIDATION_FAILED`，不能确认；警告批次可进入 `READY` 并确认。
- 确认导入使用单个数据库事务；异常时整体回滚并标记 `FAILED`。
- 阶段 2 尚无下游生产业务表；撤销保护已封装为独立引用检查入口，后续阶段增加外键引用时扩展该守卫。

## 6. 前端页面

- 数据导入批次列表：筛选、分页、刷新、统计和详情。
- 八步导入向导：类型、上传、选表、映射、预览、校验、确认、结果。
- 预览表：最多 100 行、横向滚动、产品列固定、Excel 行号、错误红色、警告橙色及问题筛选。
- 批次详情：文件哈希、工作表、映射、统计、问题、认证下载、真实审计记录和撤销原因输入。
- 上传、校验、确认和撤销按钮按当前用户权限显示，后端仍会强制鉴权。

## 7. 自动化测试

后端测试使用 Python/openpyxl 动态生成完全虚拟工作簿，覆盖：标准上传分析、扩展名/大小限制、重复检测、多工作表、多行表头、前导零、科学计数法、负在制、库存复算、名称规格冲突、错误阻止确认、警告确认、事务回滚、批次撤销、下游引用保护、角色权限、审计、路径脱敏、隐藏行、合并单元格、计划/实际配对、字段冲突、问题导出和百万格式行截断。

前端 Vitest 覆盖：八步向导、字段映射冲突、预览错误/警告样式、确认条件、权限控制和批次列表页面。

CI Docker 冒烟测试会动态生成 `TEST-PIPE-001` 虚拟库存工作簿，并实际执行登录、上传、分析、校验、确认和批次查询。

本地最终实际执行结果：

- `python -m pytest`：`38 passed, 1 warning`，耗时 497.90 秒；警告为现有 FastAPI TestClient 上游弃用提示。
- Alembic：`upgrade head`、`downgrade 20260717_0001`、再次 `upgrade head`、`alembic check` 全部通过；check 输出 `No new upgrade operations detected.`。
- `npm ci --no-audit --no-fund`：成功，安装 236 个包。
- `npm run type-check`：通过。
- `npm run test:run`：3 个测试文件、8 项测试全部通过。
- `npm run build`：成功；仅有现有第三方 PURE 注释和单包大于 500 kB 的警告。
- Docker Compose：当前 Windows 环境没有 Docker CLI，无法本机实机启动；GitHub Actions 的 push 与 pull_request 两组 Backend、Frontend、Docker Compose 检查均已通过。Docker 作业真实构建并启动 PostgreSQL/backend/frontend，完成健康检查、登录，以及动态虚拟 Excel 的上传、分析、校验、确认和批次查询，最后执行 `docker compose down -v`。

## 8. 已知限制

- 周计划第一版保存周级标准化原始任务，不生成正式排产模型，也不计算每日产能。
- 不解析或执行 Excel 外部链接；外部引用公式会阻止相关行导入。
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

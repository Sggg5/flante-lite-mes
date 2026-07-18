# 阶段 3：补库计算、审核与生产需求池完成报告

## 完成范围

本阶段实现“已完成导入批次 → 冻结输入 → 月度销售聚合 → 全量常规产品补库建议 → 异常处理 → 人工审核 → 运行批准 → 转生产需求”的闭环。未实现正式周排产、工艺路线、设备产能、任务拆分、报工、APS、PLC 或 OEE。

## 数据库迁移

新增迁移 `20260718_0005_add_replenishment_demand_pool.py`，新增：

- `replenishment_policies`
- `replenishment_runs`
- `replenishment_suggestions`
- `replenishment_issues`
- `replenishment_order_inputs`
- `production_demands`

并为销售、库存、两类在制、常规产品和周计划增加批次/产品/日期组合索引。运行保存输入批次外键、策略与订单输入快照、来源日期、算法配置和指纹；历史结果不会随策略后续修改而变化。被任何补库运行引用的导入批次（包括已取消运行）禁止撤销，返回 `IMPORT_BATCH_REFERENCED_BY_REPLENISHMENT`。

## 计算与审核规则

- 产品全集严格来自一个已完成的 `REGULAR_PRODUCT` 批次；建议为 0 的产品也保存快照。
- 六个月销售由数据库按产品和自然月聚合，空月补 0，负销售保留并提示。
- 六种算法、三种取整方式、产品专属策略和运行默认策略全部使用 `Decimal`。
- 库存缺失阻断；在制缺失按 0 提示；负在制保留原值且有效值归零。
- 快照日期不一致默认阻断，填写放行原因可继续；未来快照禁止使用。
- 周计划可选；实际量未知必须填写已排量覆盖值和原因，未匹配周计划行会阻断。
- 建议审核支持接受、调整、拒绝和批量操作；前后值、操作人、时间和原因进入审计。
- 所有正数建议完成审核且阻断问题关闭后，必须单独批准运行，才能转换生产需求。
- `source_suggestion_id` 唯一约束、行锁和冲突回读共同保证重复及并发转换幂等。

公式细节见 [补库公式 V1](replenishment-formula-v1.md)。

## API

补库策略：`GET /api/v1/replenishment/policies`、`GET/PUT /policies/{product_id}`、`POST /policies/bulk-update`。

输入与运行：`GET /source-batches`、`POST /runs/validate-sources`、`GET/POST /runs`、`GET /runs/{id}`、`POST /runs/{id}/calculate`、`POST /runs/{id}/cancel`。

建议与问题：`GET /runs/{id}/suggestions`、`GET /suggestions/{id}`、`PUT /suggestions/{id}/review`、`POST /runs/{id}/suggestions/bulk-review`、`PUT /suggestions/{id}/scheduled-override`、`GET /runs/{id}/issues`、`POST /issues/{id}/resolve`。

批准与转换：`POST /runs/{id}/approve`、`POST /runs/{id}/convert`、`POST /suggestions/{id}/convert`。

需求池：`GET /api/v1/production-demands`、`GET /production-demands/{id}`、`POST /production-demands/{id}/cancel`。

列表接口服务端分页，并支持产品编码、名称、规格模糊搜索及状态/算法/问题/正数建议筛选。所有写操作使用既有 JWT、稳定错误码、请求编号、权限依赖和审计日志。

## 权限

新增九项权限：`replenishment.view`、`replenishment.policy.manage`、`replenishment.run.create`、`replenishment.run.calculate`、`replenishment.review`、`replenishment.approve`、`replenishment.convert`、`demand.view`、`demand.cancel`。ADMIN 全部拥有；PLANNER 可完整执行补库工作流；FOREMAN 和 VIEWER 只读查看需求/补库结果。后端强制鉴权，不依赖前端按钮隐藏。

## 前端页面

- 补库计算运行列表：运行编号、日期、算法、产品数、正数建议数、待审核、已转换、警告、阻断和状态。
- 十二步新建向导：计算日期、五个必选批次、可选周计划、默认算法、权重/取整/订单输入、日期检查、完整性提示和确认计算。
- 补库建议中心：正数/全部切换、产品和状态筛选、月度销售及完整公式字段、问题处理、单条/批量审核、运行批准和幂等转换。
- 生产需求池：分页搜索、来源和数量追踪，以及仅未分配需求可填写原因取消。

长计算和转换请求使用 600 秒超时，并显示处理中提示；网络超时提示用户先刷新状态，避免重复提交。

## 测试与性能

后端专项覆盖六种算法、空月、负销售、覆盖不足、库存/在制、快照日期、周计划未知实际量、固定结果 500、取整、零建议、审核原因、批量审核、阻断批准、策略冻结、输入指纹、权限、审计、取消保留历史、导入撤销保护、重复/并发转换、需求取消以及 10,000 条同产品聚合查询计数。

前端测试覆盖十二步向导、批次选择、算法与权重校验、分页筛选、批量接受、调整原因、阻断提示、批准、转换、需求池、权限按钮和 600 秒长请求配置。CI Docker 冒烟通过 Nginx 8080 动态生成并导入五类虚拟 Excel，验证建议 500、审核、批准、转换、需求查询、重复转换幂等和导入撤销保护。

完整 268,000 条销售、12,000 产品、2,210 常规产品实测结果见 [性能基准](phase-3-replenishment-benchmark.md)：计算 1.45 秒，总流程 17.91 秒，峰值内存 125.47 MB，2,210 条需求且无重复。

本地最终验证：

- `python -m pytest` 的单进程总命令因本机外层 20 分钟命令上限被终止；按互斥 SQLite 测试库拆成完整两组执行：基础/阶段3组 `45 passed`，阶段2 Excel 回归组 `51 passed`，合计全部 `96 passed`，只有既有 TestClient 上游弃用警告。
- Alembic `upgrade head`、`downgrade base`、再次 `upgrade head` 和 `alembic check` 全部通过；check 输出 `No new upgrade operations detected.`。
- `npm.cmd run type-check` 通过。
- `npm.cmd run test:run`：5 个测试文件、24 项测试全部通过。
- `npm.cmd run build` 通过；保留 Element Plus 主包大于 500 kB 和第三方 PURE 注释的既有构建警告。
- 本机没有 Docker CLI，无法本地启动 Compose；Draft PR 的 GitHub Actions Docker 作业会实际构建并启动 PostgreSQL、后端和 Nginx 前端，并通过 8080 执行阶段2与阶段3冒烟。

## 已知限制

- 本阶段生产需求只有最小生命周期，不分配设备、周次、工序或任务。
- 周计划只用于扣减已经人工匹配且实际量可靠/已覆盖的未开工量，不生成正式排产。
- 大规模基准为本地 SQLite 单进程结果；生产 PostgreSQL 需按实际硬件继续压测和监控。
- 运行计算当前为同步长请求；后台任务队列、进度事件和失败重试可在后续基础设施演进中评估，但不得改变输入冻结和单事务语义。

## 数据合规确认

仓库没有提交真实 Excel、客户名称、订单号、批次号、员工信息或未脱敏经营数据。测试和 Docker 冒烟仅在运行时生成 `TEST-*` / `BENCH-*` 虚拟编码和虚拟数量。

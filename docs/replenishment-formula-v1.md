# 补库公式 V1

## 计算窗口

以 `calculation_date` 之前的六个完整自然月为历史窗口。没有销售的月份按 0 计入；退货和冲销保留负号并参与月度净销售聚合。聚合由数据库 `GROUP BY product_id, year, month` 完成，不在 Python 中加载销售明细后逐行汇总。

例如计算日为 2026-07-18，六个月窗口为 2026-01 至 2026-06，三个月窗口为 2026-04 至 2026-06。

## 目标库存算法

- `SIX_MONTH_MAX`：六个月月度净销售量的最大值。
- `SIX_MONTH_AVG`：六个月净销售量之和除以 6，零销售月份计入分母。
- `THREE_MONTH_AVG`：最近三个月净销售量之和除以 3。
- `SIX_MONTH_WEIGHTED`：从最远月到最近月分别乘六个非负权重；权重之和必须在容差内等于 1。
- `FIXED_TARGET`：取产品策略或运行默认配置中的固定目标库存。
- `ORDER_BASED`：取本次运行单独冻结的订单输入量；缺失时产生 `ORDER_INPUT_REQUIRED` 阻断问题。

算法原始值先按 `MAX(value, 0)` 归零，再按照策略取整：

- `NONE`：不取整。
- `CEIL_TO_INTEGER`：向上取至整数。
- `CEIL_TO_MIN_BATCH`：向上取至最小生产批量的整数倍。

系统同时保存算法原始值 `calculated_target_qty` 和取整后的 `target_stock_qty`。全部数量计算使用 `Decimal` 和数据库 `NUMERIC(18,6)`，不使用二进制浮点数。

## 库存、在制和已排量

```text
available_qty
= on_hand_qty
 + expected_inbound_qty
 - expected_outbound_qty
```

```text
pipe_wip_effective_qty = MAX(pipe_wip_raw_qty, 0)
fitting_wip_effective_qty = MAX(fitting_wip_raw_qty, 0)
```

负在制原值保留，并产生 `NEGATIVE_WIP_CLAMPED`；仅有效值按 0 参与计算。库存缺失产生 `INVENTORY_SNAPSHOT_MISSING` 阻断；在制缺失按 0 并产生 INFO。

未选择周计划时，已排未开工量为 0，并产生 `SCHEDULED_SOURCE_NOT_SELECTED` 警告。选择周计划时，只汇总已人工匹配产品的计划行：

```text
scheduled_known_qty = SUM(MAX(planned_quantity - actual_quantity, 0))
scheduled_not_started_qty = scheduled_known_qty + scheduled_override_qty
```

实际量未知时不按 0 静默处理，而是产生 `SCHEDULED_ACTUAL_UNKNOWN` 阻断问题；计划员填写覆盖量和原因后才可解除。

## 最终建议

```text
system_suggested_qty
= MAX(
    target_stock_qty
    - available_qty
    - pipe_wip_effective_qty
    - fitting_wip_effective_qty
    - scheduled_not_started_qty,
    0
  )
```

固定验收样例：目标库存 1000，现存 200，预计入库 100，预计出库 50，水管在制 150，管件在制 -20，已排未开工 100。可用量为 250，有效在制为 150，最终建议为 500。

系统建议和人工确认量分别保存。人工接受、调整或拒绝不会覆盖系统建议；调整和拒绝必须填写原因并写审计。

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any, Iterable

from sqlalchemy import case, distinct, extract, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    FittingWipSnapshot,
    ImportBatch,
    ImportedWeeklyPlanRaw,
    InventorySnapshot,
    PipeWipSnapshot,
    Product,
    ProductionDemand,
    RegularProductionProduct,
    ReplenishmentIssue,
    ReplenishmentOrderInput,
    ReplenishmentPolicy,
    ReplenishmentRun,
    ReplenishmentSuggestion,
    ShipmentRecord,
    WeeklyPlanStagingRow,
)


ZERO = Decimal("0")
ONE = Decimal("1")
ALGORITHMS = {
    "SIX_MONTH_MAX", "SIX_MONTH_AVG", "THREE_MONTH_AVG",
    "SIX_MONTH_WEIGHTED", "FIXED_TARGET", "ORDER_BASED",
}
ROUNDING_MODES = {"NONE", "CEIL_TO_INTEGER", "CEIL_TO_MIN_BATCH"}
ACTIVE_RUN_STATUSES = {
    "DRAFT", "CALCULATING", "READY_FOR_REVIEW", "PARTIALLY_REVIEWED",
    "APPROVED", "PARTIALLY_CONVERTED", "CONVERTED",
}


class ReplenishmentError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def month_start(value: date) -> date:
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def previous_six_months(calculation_date: date) -> list[date]:
    current = month_start(calculation_date)
    return [add_months(current, offset) for offset in range(-6, 0)]


def as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def calculate_metrics(monthly: list[Decimal], weights: list[Decimal] | None = None) -> dict[str, Decimal]:
    values = [as_decimal(value) for value in monthly]
    if len(values) != 6:
        raise ValueError("monthly 必须包含六个完整月份")
    six_avg = sum(values, ZERO) / Decimal("6")
    three_avg = sum(values[-3:], ZERO) / Decimal("3")
    normalized_weights = weights
    if normalized_weights is None:
        weighted = six_avg
    else:
        total_weight = sum(normalized_weights, ZERO)
        if len(normalized_weights) != 6 or any(weight < ZERO for weight in normalized_weights) or abs(total_weight - ONE) > Decimal("0.000001"):
            raise ValueError("六个月权重必须非负且合计等于 1")
        weighted = sum((qty * weight for qty, weight in zip(values, normalized_weights, strict=True)), ZERO)
    return {
        "six_month_max": max(values),
        "six_month_avg": six_avg,
        "three_month_avg": three_avg,
        "weighted_avg": weighted,
    }


def round_quantity(quantity: Decimal, mode: str, min_batch_qty: Decimal | None) -> Decimal:
    if quantity <= ZERO:
        return ZERO
    if mode == "CEIL_TO_INTEGER":
        return quantity.to_integral_value(rounding=ROUND_CEILING)
    if mode == "CEIL_TO_MIN_BATCH":
        batch = as_decimal(min_batch_qty)
        if batch <= ZERO:
            raise ValueError("最小生产批量必须大于 0")
        return (quantity / batch).to_integral_value(rounding=ROUND_CEILING) * batch
    return quantity


def calculate_target(algorithm: str, metrics: dict[str, Decimal], fixed_target: Decimal | None, order_qty: Decimal) -> Decimal:
    targets = {
        "SIX_MONTH_MAX": metrics["six_month_max"],
        "SIX_MONTH_AVG": metrics["six_month_avg"],
        "THREE_MONTH_AVG": metrics["three_month_avg"],
        "SIX_MONTH_WEIGHTED": metrics["weighted_avg"],
        "FIXED_TARGET": as_decimal(fixed_target),
        "ORDER_BASED": order_qty,
    }
    return max(targets[algorithm], ZERO)


def calculate_suggestion(
    *, target: Decimal, available: Decimal, pipe_wip: Decimal, fitting_wip: Decimal,
    scheduled: Decimal, rounding_mode: str, min_batch_qty: Decimal | None,
) -> tuple[Decimal, Decimal]:
    raw = target - available - max(pipe_wip, ZERO) - max(fitting_wip, ZERO) - max(scheduled, ZERO)
    return raw, max(raw, ZERO)


def make_run_no(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d%H%M%S%f")
    return f"RR-{stamp}"


def make_demand_no(suggestion_id: int) -> str:
    return f"PD-R-{suggestion_id:010d}"


def canonical_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_fingerprint(
    calculation_date: date, batches: dict[str, ImportBatch | None], order_inputs: Iterable[dict[str, Any]] = (),
) -> tuple[str, dict[str, Any]]:
    snapshot = {
        "calculation_date": calculation_date.isoformat(),
        "batches": {
            key: None if batch is None else {
                "id": batch.id, "batch_no": batch.batch_no, "import_type": batch.import_type,
                "sha256": batch.file_sha256, "source_date": batch.source_date.isoformat() if batch.source_date else None,
            }
            for key, batch in batches.items()
        },
        "order_inputs": sorted(order_inputs, key=lambda item: item["product_id"]),
    }
    return canonical_fingerprint(snapshot), snapshot


def aggregate_shipments(db: Session, batch_id: int, months: list[date]) -> tuple[dict[int, list[Decimal]], int, date | None, date | None]:
    start, end = months[0], add_months(months[-1], 1)
    rows = db.execute(
        select(
            ShipmentRecord.product_id,
            extract("year", ShipmentRecord.shipment_date).label("year"),
            extract("month", ShipmentRecord.shipment_date).label("month"),
            func.sum(ShipmentRecord.quantity).label("quantity"),
            func.sum(case((ShipmentRecord.quantity < 0, 1), else_=0)).label("negative_count"),
        )
        .where(
            ShipmentRecord.import_batch_id == batch_id,
            ShipmentRecord.shipment_date >= start,
            ShipmentRecord.shipment_date < end,
        )
        .group_by(ShipmentRecord.product_id, extract("year", ShipmentRecord.shipment_date), extract("month", ShipmentRecord.shipment_date))
    ).all()
    positions = {(month.year, month.month): index for index, month in enumerate(months)}
    values: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO] * 6)
    negative_count = 0
    for product_id, year, month, quantity, negatives in rows:
        position = positions.get((int(year), int(month)))
        if position is not None:
            values[product_id][position] = as_decimal(quantity)
        negative_count += int(negatives or 0)
    min_date, max_date = db.execute(
        select(func.min(ShipmentRecord.shipment_date), func.max(ShipmentRecord.shipment_date))
        .where(ShipmentRecord.import_batch_id == batch_id)
    ).one()
    return values, negative_count, min_date, max_date


def aggregate_inventory(db: Session, batch_id: int) -> dict[int, tuple[Decimal, Decimal, Decimal, Decimal]]:
    return {
        product_id: (as_decimal(on_hand), as_decimal(inbound), as_decimal(outbound), as_decimal(available))
        for product_id, on_hand, inbound, outbound, available in db.execute(
            select(
                InventorySnapshot.product_id,
                func.sum(InventorySnapshot.on_hand_qty),
                func.sum(InventorySnapshot.expected_inbound_qty),
                func.sum(InventorySnapshot.expected_outbound_qty),
                func.sum(InventorySnapshot.calculated_available_qty),
            ).where(InventorySnapshot.import_batch_id == batch_id).group_by(InventorySnapshot.product_id)
        )
    }


def aggregate_wip(db: Session, model: type[PipeWipSnapshot] | type[FittingWipSnapshot], batch_id: int) -> dict[int, Decimal]:
    return {
        product_id: as_decimal(quantity)
        for product_id, quantity in db.execute(
            select(model.product_id, func.sum(model.quantity)).where(model.import_batch_id == batch_id).group_by(model.product_id)
        )
    }


def aggregate_scheduled(db: Session, batch_id: int | None) -> tuple[dict[int, Decimal], set[int]]:
    if batch_id is None:
        return {}, set()
    known_expression = case(
        (
            ImportedWeeklyPlanRaw.actual_quantity.is_not(None),
            case(
                (ImportedWeeklyPlanRaw.planned_quantity - ImportedWeeklyPlanRaw.actual_quantity > 0,
                 ImportedWeeklyPlanRaw.planned_quantity - ImportedWeeklyPlanRaw.actual_quantity),
                else_=0,
            ),
        ),
        else_=0,
    )
    rows = db.execute(
        select(
            ImportedWeeklyPlanRaw.product_id,
            func.sum(known_expression),
            func.sum(case((ImportedWeeklyPlanRaw.actual_quantity.is_(None), 1), else_=0)),
        ).where(ImportedWeeklyPlanRaw.import_batch_id == batch_id).group_by(ImportedWeeklyPlanRaw.product_id)
    ).all()
    scheduled: dict[int, Decimal] = {}
    unknown: set[int] = set()
    for product_id, known_qty, unknown_count in rows:
        if unknown_count:
            unknown.add(product_id)
        scheduled[product_id] = as_decimal(known_qty)
    return scheduled, unknown


def snapshot_dates(db: Session, model: Any, batch_id: int) -> list[date]:
    return list(db.scalars(select(distinct(model.snapshot_date)).where(model.import_batch_id == batch_id, model.snapshot_date.is_not(None))))


def add_issue(
    issues: list[ReplenishmentIssue], run_id: int, code: str, severity: str, message: str,
    *, product_id: int | None = None, suggestion_id: int | None = None, details: dict[str, Any] | None = None,
) -> None:
    issues.append(ReplenishmentIssue(
        run_id=run_id, suggestion_id=suggestion_id, product_id=product_id, issue_code=code,
        severity=severity, message=message, details=details, status="OPEN",
    ))


def calculate_run(db: Session, run: ReplenishmentRun, *, override: bool = False, override_reason: str | None = None) -> ReplenishmentRun:
    if run.status not in {"DRAFT", "FAILED"}:
        raise ReplenishmentError("REPLENISHMENT_STATE_INVALID", "当前补库运行状态不能计算")
    if override and (not override_reason or len(override_reason.strip()) < 2):
        raise ReplenishmentError("OVERRIDE_REASON_REQUIRED", "覆盖阻断检查必须填写原因")
    expected_batches = {
        run.shipment_batch_id: "SHIPMENT", run.inventory_batch_id: "INVENTORY",
        run.pipe_wip_batch_id: "PIPE_WIP", run.fitting_wip_batch_id: "FITTING_WIP",
        run.regular_product_batch_id: "REGULAR_PRODUCT",
    }
    if run.weekly_plan_batch_id:
        expected_batches[run.weekly_plan_batch_id] = "WEEKLY_PLAN"
    source_rows = {item.id: item for item in db.scalars(select(ImportBatch).where(ImportBatch.id.in_(expected_batches)).with_for_update())}
    for batch_id, import_type in expected_batches.items():
        batch = source_rows.get(batch_id)
        if batch is None or batch.import_type != import_type or batch.status != "COMPLETED":
            raise ReplenishmentError("REPLENISHMENT_SOURCE_CHANGED", "输入导入批次已失效，不能继续计算", {"batch_id": batch_id, "expected_type": import_type})
    claimed = db.execute(
        update(ReplenishmentRun).where(ReplenishmentRun.id == run.id, ReplenishmentRun.status.in_(["DRAFT", "FAILED"]))
        .values(status="CALCULATING")
    )
    if claimed.rowcount != 1:
        raise ReplenishmentError("REPLENISHMENT_RUN_CONFLICT", "补库运行正在被其他请求计算")
    db.flush()
    db.query(ReplenishmentSuggestion).filter(ReplenishmentSuggestion.run_id == run.id).delete(synchronize_session=False)
    db.query(ReplenishmentIssue).filter(ReplenishmentIssue.run_id == run.id).delete(synchronize_session=False)

    months = previous_six_months(run.calculation_date)
    product_ids = list(db.scalars(
        select(distinct(RegularProductionProduct.product_id)).where(
            RegularProductionProduct.import_batch_id == run.regular_product_batch_id
        ).order_by(RegularProductionProduct.product_id)
    ))
    if not product_ids:
        raise ReplenishmentError("REGULAR_PRODUCTS_REQUIRED", "没有已导入的常规排产产品")
    policies: dict[str, dict[str, Any]] = run.source_snapshot.get("policies", {})
    orders = {item.product_id: item for item in db.scalars(select(ReplenishmentOrderInput).where(ReplenishmentOrderInput.run_id == run.id))}
    calculation_snapshot = dict(run.source_snapshot)
    calculation_snapshot["order_inputs"] = [
        {"product_id": product_id, "order_qty": str(item.order_qty), "source_document_no": item.source_document_no} for product_id, item in sorted(orders.items())
    ]
    full_fingerprint = canonical_fingerprint(calculation_snapshot)
    duplicate = db.scalar(select(ReplenishmentRun.id).where(
        ReplenishmentRun.id != run.id,
        ReplenishmentRun.input_fingerprint == full_fingerprint,
        ReplenishmentRun.status.in_(ACTIVE_RUN_STATUSES),
    ).with_for_update())
    if duplicate and not run.override_reason:
        raise ReplenishmentError("REPLENISHMENT_RUN_DUPLICATE", "相同数据与策略输入已经完成过补库计算", {"run_id": duplicate})
    run.input_fingerprint = full_fingerprint
    run.source_snapshot = calculation_snapshot
    shipments, negative_count, min_date, max_date = aggregate_shipments(db, run.shipment_batch_id, months)
    inventory = aggregate_inventory(db, run.inventory_batch_id)
    pipe_wip = aggregate_wip(db, PipeWipSnapshot, run.pipe_wip_batch_id)
    fitting_wip = aggregate_wip(db, FittingWipSnapshot, run.fitting_wip_batch_id)
    scheduled, unknown_actuals = aggregate_scheduled(db, run.weekly_plan_batch_id)

    issues: list[ReplenishmentIssue] = []
    blocking_severity = "WARNING" if override else "BLOCKING"
    coverage_end = add_months(months[-1], 1) - timedelta(days=1)
    if min_date is None or max_date is None or min_date > months[0] or max_date < coverage_end:
        add_issue(issues, run.id, "SHIPMENT_WINDOW_INCOMPLETE", blocking_severity, "销售数据未覆盖前六个完整月份", details={"required_start": str(months[0]), "required_end": str(coverage_end), "actual_start": str(min_date), "actual_end": str(max_date)})
    if negative_count:
        add_issue(issues, run.id, "NEGATIVE_SHIPMENT_QUANTITY", "WARNING", "销售数据包含负数量，已按原值参与月度汇总", details={"row_count": negative_count})
    negative_months = [
        {"product_id": product_id, "month_index": index, "quantity": str(quantity)}
        for product_id, values in shipments.items() for index, quantity in enumerate(values) if quantity < ZERO
    ]
    if negative_months:
        add_issue(issues, run.id, "NEGATIVE_MONTHLY_SHIPMENT", "WARNING", "存在月度净销售负数，已保留原值参与算法", details={"count": len(negative_months)})
    all_snapshot_dates: dict[str, list[date]] = {
        "inventory": snapshot_dates(db, InventorySnapshot, run.inventory_batch_id),
        "pipe_wip": snapshot_dates(db, PipeWipSnapshot, run.pipe_wip_batch_id),
        "fitting_wip": snapshot_dates(db, FittingWipSnapshot, run.fitting_wip_batch_id),
    }
    flattened = {value for values in all_snapshot_dates.values() for value in values}
    if any(value > run.calculation_date for value in flattened):
        add_issue(issues, run.id, "SNAPSHOT_DATE_IN_FUTURE", "BLOCKING", "快照日期晚于计算日期", details={key: [str(v) for v in values] for key, values in all_snapshot_dates.items()})
    if any(len(values) != 1 for values in all_snapshot_dates.values()) or len(flattened) != 1:
        add_issue(issues, run.id, "SNAPSHOT_DATE_MISMATCH", blocking_severity, "库存与在制快照日期不一致", details={key: [str(v) for v in values] for key, values in all_snapshot_dates.items()})
    if run.weekly_plan_batch_id is None:
        add_issue(issues, run.id, "SCHEDULED_SOURCE_NOT_SELECTED", "WARNING", "未选择现有周计划，已排未开工数量按 0 计算")
    else:
        unmatched = db.scalar(select(func.count(WeeklyPlanStagingRow.id)).where(
            WeeklyPlanStagingRow.import_batch_id == run.weekly_plan_batch_id,
            WeeklyPlanStagingRow.match_status.not_in(["MATCHED", "IGNORED"]),
        )) or 0
        if unmatched:
            add_issue(issues, run.id, "SCHEDULED_ROWS_UNMATCHED", "BLOCKING", "周计划仍有未匹配产品的记录", details={"count": unmatched})

    rows: list[dict[str, Any]] = []
    order_input_missing: set[int] = set()
    for product_id in product_ids:
        policy = policies.get(str(product_id))
        algorithm = policy["algorithm"] if policy else run.default_algorithm
        rounding_mode = policy["rounding_mode"] if policy else run.rounding_mode
        weights = [as_decimal(value) for value in policy["six_month_weights"]] if policy and policy.get("six_month_weights") else None
        if algorithm == "SIX_MONTH_WEIGHTED" and weights is None:
            weights = [as_decimal(value) for value in (run.default_weight_config or [])]
        metrics = calculate_metrics(shipments.get(product_id, [ZERO] * 6), weights)
        order_qty = orders.get(product_id).order_qty if product_id in orders else ZERO
        if algorithm == "ORDER_BASED" and product_id not in orders:
            order_input_missing.add(product_id)
        policy_fixed = as_decimal(policy.get("fixed_target_qty")) if policy and policy.get("fixed_target_qty") is not None else run.default_fixed_target_qty
        policy_min_batch = as_decimal(policy.get("min_batch_qty")) if policy and policy.get("min_batch_qty") is not None else run.default_min_batch_qty
        calculated_target = calculate_target(algorithm, metrics, policy_fixed, as_decimal(order_qty))
        target = round_quantity(calculated_target, rounding_mode, policy_min_batch)
        on_hand, inbound, outbound, available = inventory.get(product_id, (ZERO, ZERO, ZERO, ZERO))
        pipe_raw = pipe_wip.get(product_id, ZERO)
        fitting_raw = fitting_wip.get(product_id, ZERO)
        scheduled_qty = scheduled.get(product_id, ZERO)
        raw, suggested = calculate_suggestion(
            target=target, available=available, pipe_wip=pipe_raw, fitting_wip=fitting_raw,
            scheduled=scheduled_qty, rounding_mode="NONE", min_batch_qty=None,
        )
        rows.append({
            "run_id": run.id, "product_id": product_id, "algorithm": algorithm,
            "algorithm_config": {"algorithm": algorithm, "rounding_mode": rounding_mode, "weights": [str(v) for v in weights] if weights else None},
            "policy_snapshot": {"algorithm": algorithm, "rounding_mode": rounding_mode, "fixed_target_qty": str(policy_fixed) if policy_fixed is not None else None, "six_month_weights": [str(v) for v in weights] if weights else None, "min_batch_qty": str(policy_min_batch) if policy_min_batch is not None else None},
            "monthly_qty_json": {month.isoformat(): str(qty) for month, qty in zip(months, shipments.get(product_id, [ZERO] * 6), strict=True)},
            "monthly_shipments": {month.isoformat(): str(qty) for month, qty in zip(months, shipments.get(product_id, [ZERO] * 6), strict=True)},
            **metrics, "fixed_target_qty": policy_fixed,
            "order_input_qty": order_qty, "calculated_target_qty": calculated_target, "target_stock_qty": target,
            "on_hand_qty": on_hand, "expected_inbound_qty": inbound, "expected_outbound_qty": outbound,
            "available_qty": available, "pipe_wip_raw_qty": pipe_raw, "pipe_wip_effective_qty": max(pipe_raw, ZERO),
            "fitting_wip_raw_qty": fitting_raw, "fitting_wip_effective_qty": max(fitting_raw, ZERO),
            "scheduled_known_qty": scheduled_qty, "scheduled_override_qty": ZERO,
            "scheduled_not_started_qty": scheduled_qty, "scheduled_source_status": "SELECTED" if run.weekly_plan_batch_id else "NONE",
            "raw_suggested_qty": raw, "system_suggested_qty": suggested,
            "confirmed_qty": ZERO if suggested == ZERO else None,
            "review_status": "NOT_REQUIRED" if suggested == ZERO else "PENDING",
            "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
        })
    for offset in range(0, len(rows), 2000):
        db.execute(ReplenishmentSuggestion.__table__.insert(), rows[offset:offset + 2000])
    db.flush()
    suggestion_ids = {
        product_id: suggestion_id
        for product_id, suggestion_id in db.execute(
            select(ReplenishmentSuggestion.product_id, ReplenishmentSuggestion.id).where(ReplenishmentSuggestion.run_id == run.id)
        ).all()
    }
    for product_id in unknown_actuals:
        add_issue(issues, run.id, "SCHEDULED_ACTUAL_UNKNOWN", "BLOCKING", "周计划实际量未知，必须填写已排数量覆盖值", product_id=product_id, suggestion_id=suggestion_ids.get(product_id))
    for product_id in order_input_missing:
        add_issue(issues, run.id, "ORDER_INPUT_REQUIRED", "BLOCKING", "订单生产策略缺少订单数量输入", product_id=product_id, suggestion_id=suggestion_ids.get(product_id))
    for product_id in product_ids:
        if product_id not in inventory:
            add_issue(issues, run.id, "INVENTORY_SNAPSHOT_MISSING", "BLOCKING", "产品缺少库存快照，不能批准建议", product_id=product_id, suggestion_id=suggestion_ids.get(product_id))
        if product_id not in pipe_wip:
            add_issue(issues, run.id, "PIPE_WIP_SNAPSHOT_MISSING", "INFO", "产品缺少水管在制快照，已按 0 参与计算", product_id=product_id, suggestion_id=suggestion_ids.get(product_id))
        if product_id not in fitting_wip:
            add_issue(issues, run.id, "FITTING_WIP_SNAPSHOT_MISSING", "INFO", "产品缺少管件在制快照，已按 0 参与计算", product_id=product_id, suggestion_id=suggestion_ids.get(product_id))
        if product_id in inventory and inventory[product_id][3] < ZERO:
            add_issue(issues, run.id, "AVAILABLE_QUANTITY_NEGATIVE", "WARNING", "产品可用库存为负，仍按原值参与计算", product_id=product_id, suggestion_id=suggestion_ids.get(product_id), details={"available_qty": str(inventory[product_id][3])})
    for wip_type, values in (("PIPE", pipe_wip), ("FITTING", fitting_wip)):
        for product_id, raw_qty in values.items():
            if raw_qty < ZERO:
                add_issue(issues, run.id, "NEGATIVE_WIP_CLAMPED", "WARNING", "在制数量为负，原值保留并按 0 参与计算", product_id=product_id, suggestion_id=suggestion_ids.get(product_id), details={"wip_type": wip_type, "quantity": str(raw_qty)})
    for offset in range(0, len(issues), 1000):
        db.add_all(issues[offset:offset + 1000])

    blocking = sum(1 for item in issues if item.severity == "BLOCKING")
    warnings = sum(1 for item in issues if item.severity == "WARNING")
    run.status = "READY_FOR_REVIEW"
    run.total_products = len(product_ids)
    run.suggestion_count = len(rows)
    run.positive_suggestion_count = sum(1 for row in rows if row["system_suggested_qty"] > ZERO)
    run.pending_review_count = run.positive_suggestion_count
    run.reviewed_count = 0
    run.blocking_issue_count = blocking
    run.warning_issue_count = warnings
    run.warning_count = warnings
    run.calculated_at = datetime.now(UTC)
    if override:
        run.override_reason = override_reason
    return run


def refresh_run_status(db: Session, run: ReplenishmentRun) -> None:
    statuses = list(db.scalars(select(ReplenishmentSuggestion.review_status).where(ReplenishmentSuggestion.run_id == run.id)))
    run.reviewed_count = sum(1 for value in statuses if value in {"ACCEPTED", "ADJUSTED", "REJECTED", "CONVERTED"})
    run.pending_review_count = sum(1 for value in statuses if value == "PENDING")
    run.approved_count = sum(1 for value in statuses if value in {"ACCEPTED", "ADJUSTED", "CONVERTED"})
    demands = db.scalar(select(func.count(ProductionDemand.id)).join(ReplenishmentSuggestion, ProductionDemand.source_suggestion_id == ReplenishmentSuggestion.id).where(ReplenishmentSuggestion.run_id == run.id)) or 0
    run.converted_count = demands
    positive_approved = db.scalar(select(func.count(ReplenishmentSuggestion.id)).where(ReplenishmentSuggestion.run_id == run.id, ReplenishmentSuggestion.review_status.in_(["ACCEPTED", "ADJUSTED", "CONVERTED"]), ReplenishmentSuggestion.confirmed_qty > 0)) or 0
    if run.status in {"APPROVED", "PARTIALLY_CONVERTED", "CONVERTED"} and positive_approved and demands == positive_approved:
        run.status = "CONVERTED"
    elif demands:
        run.status = "PARTIALLY_CONVERTED"
    elif run.status != "APPROVED" and any(value != "PENDING" and value != "NOT_REQUIRED" for value in statuses):
        run.status = "PARTIALLY_REVIEWED"
    elif run.status != "APPROVED":
        run.status = "READY_FOR_REVIEW"


def convert_suggestions(db: Session, run: ReplenishmentRun, suggestion_ids: list[int], actor_id: int) -> list[ProductionDemand]:
    if run.status not in {"APPROVED", "PARTIALLY_CONVERTED", "CONVERTED"}:
        raise ReplenishmentError("REPLENISHMENT_RUN_NOT_APPROVED", "补库运行尚未批准，不能转换生产需求")
    suggestions = list(db.scalars(
        select(ReplenishmentSuggestion).where(
            ReplenishmentSuggestion.run_id == run.id,
            ReplenishmentSuggestion.id.in_(suggestion_ids),
        ).with_for_update()
    ))
    if len(suggestions) != len(set(suggestion_ids)):
        raise ReplenishmentError("SUGGESTION_NOT_FOUND", "包含不存在或不属于当前运行的建议")
    existing = {item.source_suggestion_id: item for item in db.scalars(select(ProductionDemand).where(ProductionDemand.source_suggestion_id.in_(suggestion_ids)))}
    result: list[ProductionDemand] = []
    created_pairs: list[tuple[ReplenishmentSuggestion, ProductionDemand]] = []
    for suggestion in suggestions:
        if suggestion.id in existing:
            result.append(existing[suggestion.id])
            continue
        if suggestion.review_status not in {"ACCEPTED", "ADJUSTED"} or as_decimal(suggestion.confirmed_qty) <= ZERO:
            raise ReplenishmentError("SUGGESTION_NOT_APPROVED", "只有确认数量大于 0 的已批准建议才能转为需求")
        quantity = as_decimal(suggestion.confirmed_qty)
        demand = ProductionDemand(
            demand_no=make_demand_no(suggestion.id), product_id=suggestion.product_id,
            source_suggestion_id=suggestion.id, confirmed_qty=quantity,
            active_allocated_qty=ZERO, qualified_completed_qty=ZERO,
            remaining_to_schedule_qty=quantity, remaining_to_complete_qty=quantity,
            status="PENDING_SCHEDULE", created_by=actor_id,
        )
        db.add(demand)
        created_pairs.append((suggestion, demand))
        result.append(demand)
    db.flush()
    for suggestion, demand in created_pairs:
        suggestion.review_status = "CONVERTED"
        suggestion.converted_demand_id = demand.id
    refresh_run_status(db, run)
    return result

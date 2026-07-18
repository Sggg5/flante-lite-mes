from datetime import date, datetime, UTC
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, func, select

from app.core.database import engine
from app.core.security import hash_password
from app.models import (
    AuditLog, FittingWipSnapshot, ImportBatch, ImportedWeeklyPlanRaw, InventorySnapshot, PipeWipSnapshot,
    Product, ProductionDemand, RegularProductionProduct, ReplenishmentIssue,
    ReplenishmentRun, ReplenishmentSuggestion, Role, ShipmentRecord, User, UserRole,
)
from app.services.replenishment import (
    aggregate_shipments, calculate_metrics, calculate_suggestion, calculate_target,
    previous_six_months, round_quantity,
)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def batch(db, import_type: str, number: int, source_date: date | None = None) -> ImportBatch:
    item = ImportBatch(
        batch_no=f"B-{import_type}-{number}", import_type=import_type,
        original_filename=f"virtual-{number}.xlsx", stored_filename=f"virtual-{number}.xlsx",
        file_sha256=f"{number:064x}", source_date=source_date, file_size=100,
        status="COMPLETED", imported_rows=1, created_by=1, confirmed_by=1,
        confirmed_at=datetime.now(UTC), import_options={},
    )
    db.add(item); db.flush(); return item


def imported_kwargs(batch_id: int, row: int) -> dict:
    return {"import_batch_id": batch_id, "source_sheet": "虚拟数据", "source_row_number": row, "raw_data": {"virtual": True}}


def source_fixture(db, *, products: int = 1, monthly_qty: Decimal = Decimal("1000"), complete_coverage: bool = True, mismatch: bool = False):
    shipment = batch(db, "SHIPMENT", 1, date(2026, 6, 30))
    inventory = batch(db, "INVENTORY", 2, date(2026, 7, 10))
    pipe = batch(db, "PIPE_WIP", 3, date(2026, 7, 10))
    fitting = batch(db, "FITTING_WIP", 4, date(2026, 7, 11) if mismatch else date(2026, 7, 10))
    regular = batch(db, "REGULAR_PRODUCT", 5, date(2026, 7, 10))
    product_items = []
    for index in range(products):
        product = Product(product_code=f"VIRTUAL-{index:05d}", product_name=f"虚拟产品{index}", is_active=True)
        db.add(product); db.flush(); product_items.append(product)
        db.add(RegularProductionProduct(product_id=product.id, **imported_kwargs(regular.id, index + 2)))
        db.add(InventorySnapshot(product_id=product.id, snapshot_date=date(2026, 7, 10), on_hand_qty=Decimal("300"), expected_inbound_qty=0, expected_outbound_qty=0, source_available_qty=300, calculated_available_qty=300, **imported_kwargs(inventory.id, index + 2)))
        db.add(PipeWipSnapshot(product_id=product.id, snapshot_date=date(2026, 7, 10), quantity=Decimal("100"), **imported_kwargs(pipe.id, index + 2)))
        db.add(FittingWipSnapshot(product_id=product.id, snapshot_date=date(2026, 7, 11) if mismatch else date(2026, 7, 10), production_batch_no=f"LOT-{index}", quantity=Decimal("100"), **imported_kwargs(fitting.id, index + 2)))
        months = previous_six_months(date(2026, 7, 15))
        if not complete_coverage:
            months = months[-3:]
        for month_index, month in enumerate(months):
            shipment_date = month if month_index else month.replace(day=1)
            if month.month == 6:
                shipment_date = date(2026, 6, 30)
            db.add(ShipmentRecord(product_id=product.id, document_no=f"DOC-{index}-{month_index}", shipment_date=shipment_date, shipment_month=month, quantity=monthly_qty, production_batch_no=None, **imported_kwargs(shipment.id, index * 10 + month_index + 2)))
    db.commit()
    return {"shipment": shipment, "inventory": inventory, "pipe": pipe, "fitting": fitting, "regular": regular, "products": product_items}


def create_run(client, token: str, sources: dict, **extra):
    payload = {
        "calculation_date": "2026-07-15", "shipment_batch_id": sources["shipment"].id,
        "inventory_batch_id": sources["inventory"].id, "pipe_wip_batch_id": sources["pipe"].id,
        "fitting_wip_batch_id": sources["fitting"].id, "regular_product_batch_id": sources["regular"].id,
        **extra,
    }
    return client.post("/api/v1/replenishment/runs", json=payload, headers=auth(token))


def approve_run(client, token: str, run_id: int):
    return client.post(f"/api/v1/replenishment/runs/{run_id}/approve", json={"reason": "测试批准运行"}, headers=auth(token))


def test_decimal_algorithms_and_rounding():
    monthly = [Decimal(value) for value in ["10", "20", "30", "40", "50", "60"]]
    metrics = calculate_metrics(monthly, [Decimal(value) for value in ["0.05", "0.05", "0.10", "0.10", "0.20", "0.50"]])
    assert metrics["six_month_max"] == Decimal("60")
    assert metrics["six_month_avg"] == Decimal("35")
    assert metrics["three_month_avg"] == Decimal("50")
    assert metrics["weighted_avg"] == Decimal("48.5")
    assert calculate_target("FIXED_TARGET", metrics, Decimal("500"), Decimal("0")) == 500
    assert calculate_target("ORDER_BASED", metrics, None, Decimal("123.456")) == Decimal("123.456")
    assert round_quantity(Decimal("10.01"), "CEIL_TO_INTEGER", None) == 11
    assert round_quantity(Decimal("10.01"), "CEIL_TO_MIN_BATCH", Decimal("6")) == 12
    raw, suggested = calculate_suggestion(target=Decimal("1000"), available=Decimal("300"), pipe_wip=Decimal("100"), fitting_wip=Decimal("100"), scheduled=ZERO, rounding_mode="NONE", min_batch_qty=None)
    assert raw == suggested == Decimal("500")


def test_official_formula_sample_and_negative_result_clamp():
    available = Decimal("200") + Decimal("100") - Decimal("50")
    raw, suggested = calculate_suggestion(
        target=Decimal("1000"), available=available, pipe_wip=Decimal("150"),
        fitting_wip=Decimal("-20"), scheduled=Decimal("100"),
        rounding_mode="NONE", min_batch_qty=None,
    )
    assert available == Decimal("250")
    assert raw == suggested == Decimal("500")
    raw, suggested = calculate_suggestion(
        target=Decimal("100"), available=Decimal("200"), pipe_wip=ZERO,
        fitting_wip=ZERO, scheduled=ZERO, rounding_mode="NONE", min_batch_qty=None,
    )
    assert raw == Decimal("-100") and suggested == ZERO


def test_all_six_target_algorithms():
    metrics = calculate_metrics(
        [Decimal(value) for value in ["0", "20", "30", "40", "50", "60"]],
        [Decimal(value) for value in ["0.05", "0.05", "0.10", "0.10", "0.20", "0.50"]],
    )
    assert calculate_target("SIX_MONTH_MAX", metrics, None, ZERO) == Decimal("60")
    assert calculate_target("SIX_MONTH_AVG", metrics, None, ZERO) == Decimal("200") / 6
    assert calculate_target("THREE_MONTH_AVG", metrics, None, ZERO) == Decimal("50")
    assert calculate_target("SIX_MONTH_WEIGHTED", metrics, None, ZERO) == Decimal("48")
    assert calculate_target("FIXED_TARGET", metrics, Decimal("75"), ZERO) == Decimal("75")
    assert calculate_target("ORDER_BASED", metrics, None, Decimal("88")) == Decimal("88")


ZERO = Decimal("0")


def test_fixed_sample_calculates_500_reviews_and_converts_idempotently(client, db, admin_token):
    sources = source_fixture(db)
    product = sources["products"][0]
    policy = client.put(f"/api/v1/replenishment/policies/{product.id}", json={"algorithm": "FIXED_TARGET", "rounding_mode": "NONE", "fixed_target_qty": "1000", "reason": "固定示例"}, headers=auth(admin_token))
    assert policy.status_code == 200, policy.text
    created = create_run(client, admin_token, sources)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    calculated = client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    assert calculated.status_code == 200, calculated.text
    suggestions = client.get("/api/v1/replenishment/suggestions", params={"run_id": run_id}, headers=auth(admin_token)).json()["items"]
    assert Decimal(suggestions[0]["system_suggested_qty"]) == Decimal("500")
    suggestion_id = suggestions[0]["id"]
    reviewed = client.patch(f"/api/v1/replenishment/suggestions/{suggestion_id}", json={"action": "APPROVE", "reason": "确认补库"}, headers=auth(admin_token))
    assert reviewed.status_code == 200, reviewed.text
    assert approve_run(client, admin_token, run_id).status_code == 200
    payload = {"suggestion_ids": [suggestion_id], "reason": "转入需求池"}
    first = client.post(f"/api/v1/replenishment/runs/{run_id}/convert", json=payload, headers=auth(admin_token))
    second = client.post(f"/api/v1/replenishment/runs/{run_id}/convert", json=payload, headers=auth(admin_token))
    assert first.status_code == second.status_code == 200
    assert first.json()["items"][0]["id"] == second.json()["items"][0]["id"]
    assert db.scalar(select(func.count(ProductionDemand.id))) == 1


def test_all_regular_products_include_zero_snapshot(client, db, admin_token):
    sources = source_fixture(db, products=2)
    product = sources["products"][1]
    db.query(InventorySnapshot).filter(InventorySnapshot.product_id == product.id).delete()
    db.query(PipeWipSnapshot).filter(PipeWipSnapshot.product_id == product.id).delete()
    db.query(FittingWipSnapshot).filter(FittingWipSnapshot.product_id == product.id).delete()
    db.commit()
    run_id = create_run(client, admin_token, sources).json()["id"]
    assert client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token)).status_code == 200
    assert db.scalar(select(func.count(ReplenishmentSuggestion.id)).where(ReplenishmentSuggestion.run_id == run_id)) == 2
    codes = set(db.scalars(select(ReplenishmentIssue.issue_code).where(ReplenishmentIssue.run_id == run_id)))
    assert "INVENTORY_SNAPSHOT_MISSING" in codes
    assert "PIPE_WIP_SNAPSHOT_MISSING" in codes
    assert "FITTING_WIP_SNAPSHOT_MISSING" in codes


def test_negative_sales_are_preserved_and_reported(client, db, admin_token):
    sources = source_fixture(db)
    shipment = db.scalar(select(ShipmentRecord).order_by(ShipmentRecord.id))
    shipment.quantity = Decimal("-250")
    db.commit()
    run_id = create_run(client, admin_token, sources).json()["id"]
    response = client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    assert response.status_code == 200
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    assert any(Decimal(value) < 0 for value in suggestion.monthly_shipments.values())
    codes = set(db.scalars(select(ReplenishmentIssue.issue_code).where(ReplenishmentIssue.run_id == run_id)))
    assert {"NEGATIVE_SHIPMENT_QUANTITY", "NEGATIVE_MONTHLY_SHIPMENT"} <= codes


def test_regular_product_batch_must_be_selected_explicitly(client, db, admin_token):
    sources = source_fixture(db)
    payload = {
        "calculation_date": "2026-07-15",
        "shipment_batch_id": sources["shipment"].id,
        "inventory_batch_id": sources["inventory"].id,
        "pipe_wip_batch_id": sources["pipe"].id,
        "fitting_wip_batch_id": sources["fitting"].id,
    }
    response = client.post("/api/v1/replenishment/runs", json=payload, headers=auth(admin_token))
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_zero_suggestion_is_not_required_and_never_creates_demand(client, db, admin_token):
    sources = source_fixture(db, monthly_qty=Decimal("100"))
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    assert suggestion.system_suggested_qty == 0 and suggestion.review_status == "NOT_REQUIRED"
    approval = client.post(f"/api/v1/replenishment/runs/{run_id}/approve", json={"reason": "确认本次无需补库", "allow_no_replenishment": True}, headers=auth(admin_token))
    assert approval.status_code == 200
    conversion = client.post(f"/api/v1/replenishment/runs/{run_id}/convert", json={"suggestion_ids": [suggestion.id], "reason": "不应生成"}, headers=auth(admin_token))
    assert conversion.status_code == 409
    assert db.scalar(select(func.count(ProductionDemand.id))) == 0


def test_incomplete_sales_coverage_blocks_review_unless_admin_override(client, db, admin_token):
    sources = source_fixture(db, complete_coverage=False)
    run_id = create_run(client, admin_token, sources).json()["id"]
    assert client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token)).status_code == 200
    issue = db.scalar(select(ReplenishmentIssue).where(ReplenishmentIssue.run_id == run_id, ReplenishmentIssue.issue_code == "SHIPMENT_WINDOW_INCOMPLETE"))
    assert issue.severity == "BLOCKING"
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    client.patch(f"/api/v1/replenishment/suggestions/{suggestion.id}", json={"action": "APPROVE", "reason": "尝试确认"}, headers=auth(admin_token))
    response = approve_run(client, admin_token, run_id)
    assert response.status_code == 409
    assert response.json()["code"] == "REPLENISHMENT_BLOCKING_ISSUES"


def test_snapshot_date_mismatch_and_future_are_reported(client, db, admin_token):
    sources = source_fixture(db, mismatch=True)
    db.query(InventorySnapshot).filter(
        InventorySnapshot.import_batch_id == sources["inventory"].id
    ).update({InventorySnapshot.snapshot_date: date(2026, 7, 20)})
    db.commit()
    run_id = create_run(client, admin_token, sources).json()["id"]
    assert client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token)).status_code == 200
    codes = set(db.scalars(select(ReplenishmentIssue.issue_code).where(ReplenishmentIssue.run_id == run_id)))
    assert {"SNAPSHOT_DATE_MISMATCH", "SNAPSHOT_DATE_IN_FUTURE"} <= codes
    future_issue = db.scalar(select(ReplenishmentIssue).where(
        ReplenishmentIssue.run_id == run_id,
        ReplenishmentIssue.issue_code == "SNAPSHOT_DATE_IN_FUTURE",
    ))
    response = client.post(
        f"/api/v1/replenishment/issues/{future_issue.id}/resolve",
        json={"action": "IGNORE", "reason": "不得放行未来数据"},
        headers=auth(admin_token),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "FUTURE_SNAPSHOT_NOT_OVERRIDABLE"


def test_scheduled_known_quantity_is_deducted_and_unknown_actual_can_be_overridden(client, db, admin_token):
    sources = source_fixture(db)
    product = sources["products"][0]
    weekly_known = batch(db, "WEEKLY_PLAN", 6, date(2026, 7, 13))
    db.add(ImportedWeeklyPlanRaw(product_id=product.id, production_batch_no="VIRTUAL-WEEK-1", process_name="包装", equipment_name="CI设备", plan_start_date=date(2026, 7, 13), plan_end_date=date(2026, 7, 19), planned_quantity=Decimal("250"), actual_quantity=Decimal("50"), daily_plan={}, daily_actual={}, **imported_kwargs(weekly_known.id, 6)))
    db.commit()
    run_id = create_run(client, admin_token, sources, weekly_plan_batch_id=weekly_known.id).json()["id"]
    assert client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token)).status_code == 200
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    assert suggestion.scheduled_known_qty == Decimal("200")
    assert suggestion.system_suggested_qty == Decimal("300")

    weekly_unknown = batch(db, "WEEKLY_PLAN", 7, date(2026, 7, 13))
    db.add(ImportedWeeklyPlanRaw(product_id=product.id, production_batch_no="VIRTUAL-WEEK-2", process_name="包装", equipment_name="CI设备", plan_start_date=date(2026, 7, 13), plan_end_date=date(2026, 7, 19), planned_quantity=Decimal("250"), actual_quantity=None, daily_plan={}, daily_actual={}, **imported_kwargs(weekly_unknown.id, 7)))
    db.commit()
    unknown_run_id = create_run(client, admin_token, sources, weekly_plan_batch_id=weekly_unknown.id).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{unknown_run_id}/calculate", json={}, headers=auth(admin_token))
    unknown = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == unknown_run_id))
    issue = db.scalar(select(ReplenishmentIssue).where(ReplenishmentIssue.suggestion_id == unknown.id, ReplenishmentIssue.issue_code == "SCHEDULED_ACTUAL_UNKNOWN"))
    assert issue is not None and issue.severity == "BLOCKING"
    response = client.put(f"/api/v1/replenishment/suggestions/{unknown.id}/scheduled-override", json={"scheduled_override_qty": "150", "reason": "现场确认未开工数量"}, headers=auth(admin_token))
    assert response.status_code == 200, response.text
    assert Decimal(str(response.json()["system_suggested_qty"])) == Decimal("350")
    db.refresh(issue); assert issue.status == "RESOLVED"


def test_duplicate_run_requires_admin_reason(client, db, admin_token):
    sources = source_fixture(db)
    assert create_run(client, admin_token, sources).status_code == 201
    duplicate = create_run(client, admin_token, sources)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "REPLENISHMENT_RUN_DUPLICATE"
    forced = create_run(client, admin_token, sources, force_duplicate=True, force_reason="管理员确认重复计算")
    assert forced.status_code == 201


def test_policy_is_frozen_when_run_is_created(client, db, admin_token):
    sources = source_fixture(db)
    product_id = sources["products"][0].id
    client.put(f"/api/v1/replenishment/policies/{product_id}", json={"algorithm": "FIXED_TARGET", "fixed_target_qty": "1000", "rounding_mode": "NONE", "reason": "初始策略"}, headers=auth(admin_token))
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.put(f"/api/v1/replenishment/policies/{product_id}", json={"algorithm": "FIXED_TARGET", "fixed_target_qty": "2000", "rounding_mode": "NONE", "reason": "后续策略调整"}, headers=auth(admin_token))
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    assert suggestion.target_stock_qty == Decimal("1000")
    assert suggestion.system_suggested_qty == Decimal("500")


def test_completed_source_batch_cannot_rollback_after_run_reference(client, db, admin_token):
    sources = source_fixture(db)
    assert create_run(client, admin_token, sources).status_code == 201
    response = client.post(f"/api/v1/imports/{sources['inventory'].id}/rollback", json={"reason": "尝试撤销"}, headers=auth(admin_token))
    assert response.status_code == 409
    assert response.json()["code"] == "IMPORT_BATCH_REFERENCED_BY_REPLENISHMENT"


def test_cancelled_run_keeps_history_and_source_reference(client, db, admin_token):
    sources = source_fixture(db)
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    before = db.scalar(select(func.count(ReplenishmentSuggestion.id)).where(ReplenishmentSuggestion.run_id == run_id))
    cancelled = client.post(f"/api/v1/replenishment/runs/{run_id}/cancel", json={"reason": "取消但保留历史"}, headers=auth(admin_token))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert db.scalar(select(func.count(ReplenishmentSuggestion.id)).where(ReplenishmentSuggestion.run_id == run_id)) == before
    rollback = client.post(f"/api/v1/imports/{sources['shipment'].id}/rollback", json={"reason": "仍不可撤销"}, headers=auth(admin_token))
    assert rollback.status_code == 409


def test_viewer_can_read_but_cannot_create_or_review(client, db, admin_token):
    role = db.scalar(select(Role).where(Role.code == "VIEWER"))
    viewer = User(username="phase3-viewer", display_name="阶段三只读", password_hash=hash_password("ViewerTest123!"))
    viewer.role_links.append(UserRole(role=role)); db.add(viewer); db.commit()
    token = client.post("/api/v1/auth/login", json={"username": "phase3-viewer", "password": "ViewerTest123!"}).json()["access_token"]
    assert client.get("/api/v1/replenishment/runs", headers=auth(token)).status_code == 200
    sources = source_fixture(db)
    assert create_run(client, token, sources).status_code == 403


def test_demand_cancel_requires_no_allocation_and_is_audited(client, db, admin_token):
    sources = source_fixture(db)
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    client.patch(f"/api/v1/replenishment/suggestions/{suggestion.id}", json={"action": "APPROVE", "reason": "确认"}, headers=auth(admin_token))
    assert approve_run(client, admin_token, run_id).status_code == 200
    demand_id = client.post(f"/api/v1/replenishment/runs/{run_id}/convert", json={"suggestion_ids": [suggestion.id], "reason": "转换"}, headers=auth(admin_token)).json()["items"][0]["id"]
    cancelled = client.post(f"/api/v1/production-demands/{demand_id}/cancel", json={"reason": "业务取消"}, headers=auth(admin_token))
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "production_demand.cancel")) == 1


def test_monthly_aggregation_is_one_grouped_query(db):
    sources = source_fixture(db)
    shipment = sources["shipment"]
    product = sources["products"][0]
    rows = []
    for index in range(10_000):
        rows.append({"import_batch_id": shipment.id, "source_sheet": "虚拟大表", "source_row_number": index + 100, "raw_data": {}, "product_id": product.id, "document_no": f"BULK-{index}", "shipment_date": date(2026, (index % 6) + 1, 15), "shipment_month": date(2026, (index % 6) + 1, 1), "quantity": Decimal("1"), "production_batch_no": None, "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC)})
    db.execute(ShipmentRecord.__table__.insert(), rows); db.commit()
    selects = 0
    def count_select(conn, cursor, statement, parameters, context, executemany):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"): selects += 1
    event.listen(engine, "before_cursor_execute", count_select)
    try:
        values, _, _, _ = aggregate_shipments(db, shipment.id, previous_six_months(date(2026, 7, 15)))
    finally:
        event.remove(engine, "before_cursor_execute", count_select)
    assert sum(values[product.id]) == Decimal("16000")
    assert selects == 2


def test_policy_validation_rejects_invalid_weight_and_batch_configuration(client, db, admin_token):
    sources = source_fixture(db)
    product_id = sources["products"][0].id
    weighted = client.put(f"/api/v1/replenishment/policies/{product_id}", json={"algorithm": "SIX_MONTH_WEIGHTED", "rounding_mode": "NONE", "six_month_weights": [1, 2], "reason": "无效权重"}, headers=auth(admin_token))
    assert weighted.status_code == 422
    rounded = client.put(f"/api/v1/replenishment/policies/{product_id}", json={"algorithm": "SIX_MONTH_MAX", "rounding_mode": "CEIL_TO_MIN_BATCH", "reason": "缺批量"}, headers=auth(admin_token))
    assert rounded.status_code == 422


def test_order_based_policy_without_order_input_creates_blocking_issue(client, db, admin_token):
    sources = source_fixture(db)
    product_id = sources["products"][0].id
    assert client.put(f"/api/v1/replenishment/policies/{product_id}", json={"algorithm": "ORDER_BASED", "rounding_mode": "NONE", "reason": "订单生产"}, headers=auth(admin_token)).status_code == 200
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    issue = db.scalar(select(ReplenishmentIssue).where(ReplenishmentIssue.run_id == run_id, ReplenishmentIssue.issue_code == "ORDER_INPUT_REQUIRED"))
    assert issue is not None and issue.severity == "BLOCKING"


def test_negative_wip_is_preserved_but_effective_quantity_is_zero(client, db, admin_token):
    sources = source_fixture(db)
    product = sources["products"][0]
    pipe = db.scalar(select(PipeWipSnapshot).where(PipeWipSnapshot.product_id == product.id)); pipe.quantity = Decimal("-25")
    db.commit()
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    assert suggestion.pipe_wip_raw_qty == Decimal("-25")
    assert suggestion.pipe_wip_effective_qty == 0
    assert db.scalar(select(func.count(ReplenishmentIssue.id)).where(ReplenishmentIssue.run_id == run_id, ReplenishmentIssue.issue_code == "NEGATIVE_WIP_CLAMPED")) == 1


def test_source_batch_type_and_completed_state_are_enforced(client, db, admin_token):
    sources = source_fixture(db)
    response = create_run(client, admin_token, sources, inventory_batch_id=sources["shipment"].id)
    assert response.status_code == 409
    assert response.json()["code"] == "REPLENISHMENT_SOURCE_TYPE_INVALID"
    sources["inventory"].status = "ROLLED_BACK"; db.commit()
    response = create_run(client, admin_token, sources)
    assert response.status_code == 409
    assert response.json()["code"] == "REPLENISHMENT_SOURCE_NOT_COMPLETED"


def test_calculation_cannot_be_repeated_after_ready(client, db, admin_token):
    sources = source_fixture(db)
    run_id = create_run(client, admin_token, sources).json()["id"]
    assert client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token)).status_code == 200
    repeated = client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "REPLENISHMENT_STATE_INVALID"


def test_manual_confirmed_quantity_records_before_after_and_reason(client, db, admin_token):
    sources = source_fixture(db)
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    response = client.patch(f"/api/v1/replenishment/suggestions/{suggestion.id}", json={"action": "APPROVE", "confirmed_qty": "450", "reason": "结合现场库存调整"}, headers=auth(admin_token))
    assert response.status_code == 200
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "replenishment.suggestion.review"))
    assert Decimal(str(audit.before_data["system_suggested_qty"])) == Decimal("500")
    assert Decimal(str(audit.after_data["confirmed_qty"])) == Decimal("450")
    assert audit.reason == "结合现场库存调整"


def test_bulk_review_returns_success_count_and_failure_details(client, db, admin_token):
    sources = source_fixture(db, products=2)
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    ids = list(db.scalars(select(ReplenishmentSuggestion.id).where(ReplenishmentSuggestion.run_id == run_id)))
    response = client.post(f"/api/v1/replenishment/runs/{run_id}/suggestions/bulk-review", json={"suggestion_ids": [*ids, 999999], "action": "APPROVE", "reason": "批量接受系统建议"}, headers=auth(admin_token))
    assert response.status_code == 200, response.text
    assert response.json()["success_count"] == 2
    assert response.json()["failures"] == [{"suggestion_id": 999999, "code": "SUGGESTION_NOT_FOUND"}]
    statuses = set(db.scalars(select(ReplenishmentSuggestion.review_status).where(ReplenishmentSuggestion.run_id == run_id)))
    assert statuses == {"ACCEPTED"}


def test_allocated_demand_cannot_be_cancelled(client, db, admin_token):
    sources = source_fixture(db)
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    client.patch(f"/api/v1/replenishment/suggestions/{suggestion.id}", json={"action": "APPROVE", "reason": "确认"}, headers=auth(admin_token))
    assert approve_run(client, admin_token, run_id).status_code == 200
    demand_id = client.post(f"/api/v1/replenishment/runs/{run_id}/convert", json={"suggestion_ids": [suggestion.id], "reason": "转换"}, headers=auth(admin_token)).json()["items"][0]["id"]
    demand = db.get(ProductionDemand, demand_id); demand.active_allocated_qty = Decimal("1"); db.commit()
    response = client.post(f"/api/v1/production-demands/{demand_id}/cancel", json={"reason": "不应允许"}, headers=auth(admin_token))
    assert response.status_code == 409
    assert response.json()["code"] == "PRODUCTION_DEMAND_ALREADY_ALLOCATED"


def test_concurrent_conversion_creates_only_one_demand(client, db, admin_token):
    sources = source_fixture(db)
    run_id = create_run(client, admin_token, sources).json()["id"]
    client.post(f"/api/v1/replenishment/runs/{run_id}/calculate", json={}, headers=auth(admin_token))
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run_id))
    client.patch(f"/api/v1/replenishment/suggestions/{suggestion.id}", json={"action": "APPROVE", "reason": "并发转换前确认"}, headers=auth(admin_token))
    assert approve_run(client, admin_token, run_id).status_code == 200
    def convert_once():
        return client.post(f"/api/v1/replenishment/runs/{run_id}/convert", json={"suggestion_ids": [suggestion.id], "reason": "并发幂等验证"}, headers=auth(admin_token))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: convert_once(), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert db.scalar(
        select(func.count(ProductionDemand.id)).where(
            ProductionDemand.source_suggestion_id == suggestion.id
        )
    ) == 1

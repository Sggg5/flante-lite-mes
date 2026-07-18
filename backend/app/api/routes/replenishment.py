from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.core.errors import error_payload
from app.models import (
    AuditLog, ImportBatch, Product, ProductionDemand, RegularProductionProduct, ReplenishmentIssue, ReplenishmentOrderInput,
    ReplenishmentPolicy, ReplenishmentRun, ReplenishmentSuggestion, User,
)
from app.schemas.replenishment import (
    ApproveRunRequest, BulkPolicyRequest, BulkReviewRequest, CalculateRunRequest, ConvertSuggestionsRequest,
    CancelRequest, CreateRunRequest, PolicyUpsertRequest, ResolveIssueRequest, ReviewSuggestionRequest, ScheduledOverrideRequest,
)
from app.services.audit import write_audit_log
from app.services.identity import get_role_codes
from app.services.replenishment import (
    ACTIVE_RUN_STATUSES, ReplenishmentError, calculate_run, canonical_fingerprint,
    convert_suggestions, make_run_no, refresh_run_status, source_fingerprint,
)


router = APIRouter(prefix="/api/v1/replenishment", tags=["replenishment"])


def fail(request: Request, code: str, message: str, details: Any = None, http_status: int = 409) -> None:
    raise HTTPException(status_code=http_status, detail=error_payload(request, code, message, details))


def service_call(request: Request, action):
    try:
        return action()
    except ReplenishmentError as exc:
        fail(request, exc.code, exc.message, exc.details)


def policy_dict(policy: ReplenishmentPolicy, product: Product | None = None) -> dict[str, Any]:
    return {
        "id": policy.id, "product_id": policy.product_id,
        "product_code": product.product_code if product else None,
        "product_name": product.product_name if product else None,
        "specification": product.specification if product else None,
        "category": product.category if product else None,
        "unit": product.unit if product else None,
        "algorithm": policy.algorithm, "rounding_mode": policy.rounding_mode,
        "fixed_target_qty": policy.fixed_target_qty, "six_month_weights": policy.six_month_weights,
        "min_batch_qty": policy.min_batch_qty, "is_active": policy.is_active,
        "note": policy.note, "created_by": policy.created_by,
        "updated_by": policy.updated_by, "created_at": policy.created_at, "updated_at": policy.updated_at,
    }


def run_dict(run: ReplenishmentRun) -> dict[str, Any]:
    return {
        column: getattr(run, column) for column in [
            "id", "run_no", "calculation_date", "shipment_batch_id", "inventory_batch_id",
            "pipe_wip_batch_id", "fitting_wip_batch_id", "weekly_plan_batch_id", "input_fingerprint",
            "regular_product_batch_id",
            "status", "formula_version", "default_algorithm", "default_weight_config", "default_fixed_target_qty", "rounding_mode",
            "source_snapshot", "source_date_summary", "calculation_config", "override_reason", "error_summary",
            "total_products", "suggestion_count", "positive_suggestion_count", "pending_review_count",
            "reviewed_count", "blocking_issue_count", "warning_issue_count", "warning_count", "approved_count",
            "converted_count", "created_by", "calculated_at", "approved_by", "approved_at",
            "cancelled_by", "cancelled_at", "cancel_reason", "created_at", "updated_at",
        ]
    }


def suggestion_dict(item: ReplenishmentSuggestion, product: Product | None = None) -> dict[str, Any]:
    result = {column.name: getattr(item, column.name) for column in ReplenishmentSuggestion.__table__.columns}
    result.update({
        "product_code": product.product_code if product else None,
        "product_name": product.product_name if product else None,
        "specification": product.specification if product else None,
        "category": product.category if product else None,
        "unit": product.unit if product else None,
    })
    return result


def issue_dict(item: ReplenishmentIssue) -> dict[str, Any]:
    return {column.name: getattr(item, column.name) for column in ReplenishmentIssue.__table__.columns}


def get_run(db: Session, request: Request, run_id: int, *, lock: bool = False) -> ReplenishmentRun:
    query = select(ReplenishmentRun).where(ReplenishmentRun.id == run_id)
    if lock:
        query = query.with_for_update()
    run = db.scalar(query)
    if run is None:
        fail(request, "REPLENISHMENT_RUN_NOT_FOUND", "补库运行不存在", http_status=404)
    return run


@router.get("/products")
def search_products(keyword: str = Query(min_length=1, max_length=100), limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view"))) -> dict[str, Any]:
    pattern = f"%{keyword.strip()}%"
    products = db.scalars(select(Product).where(Product.is_active.is_(True), or_(Product.product_code.ilike(pattern), Product.product_name.ilike(pattern), Product.specification.ilike(pattern))).order_by(Product.product_code).limit(limit)).all()
    return {"items": [{"id": item.id, "product_code": item.product_code, "product_name": item.product_name, "specification": item.specification} for item in products]}


def validate_policy(payload: PolicyUpsertRequest) -> None:
    if payload.algorithm not in {"SIX_MONTH_MAX", "SIX_MONTH_AVG", "THREE_MONTH_AVG", "SIX_MONTH_WEIGHTED", "FIXED_TARGET", "ORDER_BASED"}:
        raise ValueError("algorithm")


@router.get("/policies")
def list_policies(
    keyword: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view")),
) -> dict[str, Any]:
    query = select(ReplenishmentPolicy, Product).join(Product, Product.id == ReplenishmentPolicy.product_id)
    count_query = select(func.count(ReplenishmentPolicy.id)).join(Product, Product.id == ReplenishmentPolicy.product_id)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        condition = or_(Product.product_code.ilike(pattern), Product.product_name.ilike(pattern), Product.specification.ilike(pattern))
        query, count_query = query.where(condition), count_query.where(condition)
    total = db.scalar(count_query) or 0
    rows = db.execute(query.order_by(Product.product_code).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [policy_dict(policy, product) for policy, product in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/policies/{product_id}")
def get_policy(product_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view"))) -> dict[str, Any]:
    product = db.get(Product, product_id)
    if product is None: fail(request, "PRODUCT_NOT_FOUND", "产品不存在", http_status=404)
    policy = db.scalar(select(ReplenishmentPolicy).where(ReplenishmentPolicy.product_id == product_id))
    if policy is None:
        return {"product_id": product.id, "product_code": product.product_code, "product_name": product.product_name, "algorithm": None, "uses_run_default": True}
    return policy_dict(policy, product)


@router.put("/policies/{product_id}")
def upsert_policy(
    product_id: int, payload: PolicyUpsertRequest, request: Request, db: Session = Depends(get_db),
    actor: User = Depends(require_permission("replenishment.policy.manage")),
) -> dict[str, Any]:
    product = db.get(Product, product_id)
    if product is None:
        fail(request, "PRODUCT_NOT_FOUND", "产品不存在", http_status=404)
    policy = db.scalar(select(ReplenishmentPolicy).where(ReplenishmentPolicy.product_id == product_id).with_for_update())
    before = policy_dict(policy, product) if policy else None
    values = payload.model_dump(exclude={"reason"})
    values["six_month_weights"] = [str(value) for value in payload.six_month_weights] if payload.six_month_weights else None
    if policy is None:
        policy = ReplenishmentPolicy(product_id=product_id, created_by=actor.id, updated_by=actor.id, **values)
        db.add(policy)
    else:
        for key, value in values.items():
            setattr(policy, key, value)
        policy.updated_by = actor.id
    db.flush()
    write_audit_log(db, request, user=actor, action="replenishment.policy.update", entity_type="replenishment_policy", entity_id=str(policy.id), before_data=before, after_data=policy_dict(policy, product), reason=payload.reason)
    db.commit()
    return policy_dict(policy, product)


@router.put("/policies")
@router.post("/policies/bulk-update")
def bulk_upsert_policies(
    payload: BulkPolicyRequest, request: Request, db: Session = Depends(get_db),
    actor: User = Depends(require_permission("replenishment.policy.manage")),
) -> dict[str, int]:
    products = list(db.scalars(select(Product).where(Product.id.in_(set(payload.product_ids)))))
    if len(products) != len(set(payload.product_ids)):
        fail(request, "PRODUCT_NOT_FOUND", "包含不存在的产品", http_status=404)
    existing = {item.product_id: item for item in db.scalars(select(ReplenishmentPolicy).where(ReplenishmentPolicy.product_id.in_(payload.product_ids)).with_for_update())}
    values = payload.policy.model_dump(exclude={"reason"})
    values["six_month_weights"] = [str(value) for value in (payload.policy.six_month_weights or [])] or None
    for product in products:
        policy = existing.get(product.id)
        before = policy_dict(policy, product) if policy else None
        if policy is None:
            policy = ReplenishmentPolicy(product_id=product.id, created_by=actor.id, updated_by=actor.id, **values)
            db.add(policy)
            db.flush()
        else:
            for key, value in values.items():
                setattr(policy, key, value)
            policy.updated_by = actor.id
        write_audit_log(db, request, user=actor, action="replenishment.policy.update", entity_type="replenishment_policy", entity_id=str(policy.id), before_data=before, after_data=policy_dict(policy, product), reason=payload.policy.reason)
    db.commit()
    return {"updated": len(products)}


@router.get("/source-batches")
def source_batches(import_type: str | None = None, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view"))) -> dict[str, Any]:
    allowed = {"SHIPMENT", "INVENTORY", "PIPE_WIP", "FITTING_WIP", "REGULAR_PRODUCT", "WEEKLY_PLAN"}
    query = select(ImportBatch).where(ImportBatch.status == "COMPLETED", ImportBatch.import_type.in_(allowed))
    if import_type:
        if import_type not in allowed: return {"items": []}
        query = query.where(ImportBatch.import_type == import_type)
    items = db.scalars(query.order_by(ImportBatch.confirmed_at.desc(), ImportBatch.id.desc()).limit(500)).all()
    return {"items": [{"id": item.id, "batch_no": item.batch_no, "import_type": item.import_type, "source_date": item.source_date, "imported_rows": item.imported_rows, "confirmed_at": item.confirmed_at} for item in items]}


@router.post("/runs/validate-sources")
def validate_sources(payload: CreateRunRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.run.create"))) -> dict[str, Any]:
    expected = [(payload.shipment_batch_id, "SHIPMENT"), (payload.inventory_batch_id, "INVENTORY"), (payload.pipe_wip_batch_id, "PIPE_WIP"), (payload.fitting_wip_batch_id, "FITTING_WIP")]
    if payload.regular_product_batch_id: expected.append((payload.regular_product_batch_id, "REGULAR_PRODUCT"))
    if payload.weekly_plan_batch_id: expected.append((payload.weekly_plan_batch_id, "WEEKLY_PLAN"))
    items = []
    for batch_id, import_type in expected:
        batch = db.get(ImportBatch, batch_id)
        if batch is None or batch.import_type != import_type: fail(request, "REPLENISHMENT_SOURCE_TYPE_INVALID", f"{import_type} 来源批次类型不正确")
        if batch.status != "COMPLETED": fail(request, "REPLENISHMENT_SOURCE_NOT_COMPLETED", f"{import_type} 来源批次尚未完成")
        items.append({"id": batch.id, "import_type": batch.import_type, "source_date": batch.source_date})
    dates = {str(item["source_date"]) for item in items if item["import_type"] in {"INVENTORY", "PIPE_WIP", "FITTING_WIP"}}
    return {"valid": len(dates) == 1 and all(item["source_date"] <= payload.calculation_date for item in items if item["source_date"]), "snapshot_date_mismatch": len(dates) != 1, "sources": items}


@router.get("/runs")
def list_runs(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), run_status: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view")),
) -> dict[str, Any]:
    filters = [ReplenishmentRun.status == run_status] if run_status else []
    total = db.scalar(select(func.count(ReplenishmentRun.id)).where(*filters)) or 0
    items = db.scalars(select(ReplenishmentRun).where(*filters).order_by(ReplenishmentRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [run_dict(item) for item in items], "total": total, "page": page, "page_size": page_size}


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_run(
    payload: CreateRunRequest, request: Request, db: Session = Depends(get_db),
    actor: User = Depends(require_permission("replenishment.run.create")),
) -> dict[str, Any]:
    expected = {
        "shipment": (payload.shipment_batch_id, "SHIPMENT"), "inventory": (payload.inventory_batch_id, "INVENTORY"),
        "pipe_wip": (payload.pipe_wip_batch_id, "PIPE_WIP"), "fitting_wip": (payload.fitting_wip_batch_id, "FITTING_WIP"),
    }
    regular_batch_id = payload.regular_product_batch_id
    expected["regular_product"] = (regular_batch_id, "REGULAR_PRODUCT")
    if payload.weekly_plan_batch_id is not None:
        expected["weekly_plan"] = (payload.weekly_plan_batch_id, "WEEKLY_PLAN")
    batches: dict[str, ImportBatch | None] = {}
    for key, (batch_id, import_type) in expected.items():
        batch = db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
        if batch is None or batch.import_type != import_type:
            fail(request, "REPLENISHMENT_SOURCE_TYPE_INVALID", f"{key} 来源批次类型不正确")
        if batch.status != "COMPLETED":
            fail(request, "REPLENISHMENT_SOURCE_NOT_COMPLETED", f"{key} 来源批次尚未完成")
        batches[key] = batch
    order_snapshot = [{"product_id": item.product_id, "order_qty": str(item.quantity), "source_document_no": item.source_document_no} for item in payload.order_inputs]
    fingerprint, snapshot = source_fingerprint(payload.calculation_date, batches, order_snapshot)
    source_dates = {key: batch.source_date.isoformat() if batch and batch.source_date else None for key, batch in batches.items()}
    calculation_config = {
        "default_algorithm": payload.default_algorithm,
        "default_weight_config": [str(value) for value in payload.default_weight_config] if payload.default_weight_config else None,
        "default_fixed_target_qty": str(payload.default_fixed_target_qty) if payload.default_fixed_target_qty is not None else None,
        "rounding_mode": payload.rounding_mode,
        "default_min_batch_qty": str(payload.default_min_batch_qty) if payload.default_min_batch_qty is not None else None,
    }
    snapshot["calculation_config"] = calculation_config
    regular_product_ids = select(RegularProductionProduct.product_id).where(RegularProductionProduct.import_batch_id == regular_batch_id)
    configured_policies = db.scalars(select(ReplenishmentPolicy).where(ReplenishmentPolicy.product_id.in_(regular_product_ids), ReplenishmentPolicy.is_active.is_(True))).all()
    snapshot["policies"] = {
        str(policy.product_id): {
            "algorithm": policy.algorithm, "rounding_mode": policy.rounding_mode,
            "fixed_target_qty": str(policy.fixed_target_qty) if policy.fixed_target_qty is not None else None,
            "six_month_weights": policy.six_month_weights,
            "min_batch_qty": str(policy.min_batch_qty) if policy.min_batch_qty is not None else None,
        }
        for policy in sorted(configured_policies, key=lambda item: item.product_id)
    }
    fingerprint = canonical_fingerprint(snapshot)
    duplicate = db.scalar(select(ReplenishmentRun).where(ReplenishmentRun.input_fingerprint == fingerprint, ReplenishmentRun.status.in_(ACTIVE_RUN_STATUSES)).with_for_update())
    if duplicate and not payload.force_duplicate:
        fail(request, "REPLENISHMENT_RUN_DUPLICATE", "相同输入已经存在补库运行", {"run_id": duplicate.id})
    if payload.force_duplicate:
        if "ADMIN" not in get_role_codes(actor):
            fail(request, "ADMIN_FORCE_REQUIRED", "只有管理员可以强制创建重复运行", http_status=403)
        if not payload.force_reason or len(payload.force_reason.strip()) < 2:
            fail(request, "FORCE_REASON_REQUIRED", "强制创建重复运行必须填写原因", http_status=422)
    run = ReplenishmentRun(
        run_no=make_run_no(), calculation_date=payload.calculation_date,
        shipment_batch_id=payload.shipment_batch_id, inventory_batch_id=payload.inventory_batch_id,
        pipe_wip_batch_id=payload.pipe_wip_batch_id, fitting_wip_batch_id=payload.fitting_wip_batch_id,
        regular_product_batch_id=regular_batch_id,
        weekly_plan_batch_id=payload.weekly_plan_batch_id, input_fingerprint=fingerprint,
        default_algorithm=payload.default_algorithm,
        default_weight_config=[str(value) for value in payload.default_weight_config] if payload.default_weight_config else None,
        default_fixed_target_qty=payload.default_fixed_target_qty,
        rounding_mode=payload.rounding_mode, default_min_batch_qty=payload.default_min_batch_qty,
        source_snapshot=snapshot, source_date_summary=source_dates, calculation_config=calculation_config,
        override_reason=payload.force_reason, status="DRAFT", created_by=actor.id,
    )
    db.add(run)
    db.flush()
    seen: set[int] = set()
    for item in payload.order_inputs:
        if item.product_id in seen:
            fail(request, "ORDER_INPUT_DUPLICATE", "同一产品不能重复填写订单输入", http_status=422)
        seen.add(item.product_id)
        if db.get(Product, item.product_id) is None:
            fail(request, "PRODUCT_NOT_FOUND", "订单输入包含不存在的产品", http_status=404)
        db.add(ReplenishmentOrderInput(run_id=run.id, product_id=item.product_id, order_qty=item.quantity, source_document_no=item.source_document_no, note=item.reason, created_by=actor.id))
    write_audit_log(db, request, user=actor, action="replenishment.run.create", entity_type="replenishment_run", entity_id=str(run.id), after_data=run_dict(run), reason=payload.force_reason)
    db.commit()
    return run_dict(run)


@router.get("/runs/{run_id}")
def get_run_detail(run_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view"))) -> dict[str, Any]:
    run = get_run(db, request, run_id)
    result = run_dict(run)
    result["order_inputs"] = [{"product_id": item.product_id, "order_qty": item.order_qty, "source_document_no": item.source_document_no, "note": item.note} for item in db.scalars(select(ReplenishmentOrderInput).where(ReplenishmentOrderInput.run_id == run.id))]
    suggestion_ids = [str(value) for value in db.scalars(select(ReplenishmentSuggestion.id).where(ReplenishmentSuggestion.run_id == run.id))]
    audit_filter = (AuditLog.entity_type == "replenishment_run") & (AuditLog.entity_id == str(run.id))
    if suggestion_ids:
        audit_filter = audit_filter | ((AuditLog.entity_type == "replenishment_suggestion") & (AuditLog.entity_id.in_(suggestion_ids)))
    logs = db.scalars(select(AuditLog).where(audit_filter).order_by(AuditLog.occurred_at.desc()).limit(500)).all()
    result["audit_logs"] = [{"id": log.id, "action": log.action, "entity_type": log.entity_type, "entity_id": log.entity_id, "before_data": log.before_data, "after_data": log.after_data, "reason": log.reason, "request_id": log.request_id, "occurred_at": log.occurred_at} for log in logs]
    return result


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: int, payload: CancelRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.run.create"))) -> dict[str, Any]:
    run = get_run(db, request, run_id, lock=True)
    if run.status == "CANCELLED":
        return run_dict(run)
    if run.status in {"PARTIALLY_CONVERTED", "CONVERTED"}:
        fail(request, "REPLENISHMENT_RUN_ALREADY_CONVERTED", "已有生产需求的运行不能取消")
    before = run_dict(run)
    run.status = "CANCELLED"
    run.cancelled_by, run.cancelled_at, run.cancel_reason = actor.id, datetime.now(UTC), payload.reason
    write_audit_log(db, request, user=actor, action="replenishment.run.cancel", entity_type="replenishment_run", entity_id=str(run.id), before_data=before, after_data=run_dict(run), reason=payload.reason)
    db.commit()
    return run_dict(run)


@router.post("/runs/{run_id}/calculate")
def calculate(run_id: int, payload: CalculateRunRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.run.calculate"))) -> dict[str, Any]:
    run = get_run(db, request, run_id, lock=True)
    before = run_dict(run)
    try:
        service_call(request, lambda: calculate_run(db, run, override=payload.override_blocking_checks, override_reason=payload.override_reason))
        write_audit_log(db, request, user=actor, action="replenishment.run.calculate", entity_type="replenishment_run", entity_id=str(run.id), before_data=before, after_data=run_dict(run), reason=payload.override_reason)
        db.commit()
    except HTTPException as exc:
        error = {"code": exc.detail.get("code"), "message": exc.detail.get("message")} if isinstance(exc.detail, dict) else None
        db.rollback()
        failed = db.get(ReplenishmentRun, run_id)
        if failed and failed.status in {"DRAFT", "CALCULATING"}:
            failed.status = "FAILED"
            failed.error_summary = error
            db.commit()
        raise
    return run_dict(run)


@router.get("/runs/{run_id}/issues")
def list_run_issues(run_id: int, request: Request, severity: str | None = None, issue_status: str | None = Query(None, alias="status"), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view"))) -> dict[str, Any]:
    get_run(db, request, run_id)
    filters = [ReplenishmentIssue.run_id == run_id]
    if severity: filters.append(ReplenishmentIssue.severity == severity.upper())
    if issue_status: filters.append(ReplenishmentIssue.status == issue_status.upper())
    total = db.scalar(select(func.count(ReplenishmentIssue.id)).where(*filters)) or 0
    items = db.scalars(select(ReplenishmentIssue).where(*filters).order_by(ReplenishmentIssue.severity, ReplenishmentIssue.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [issue_dict(item) for item in items], "total": total, "page": page, "page_size": page_size}


@router.post("/runs/{run_id}/issues/{issue_id}")
def resolve_issue(run_id: int, issue_id: int, payload: ResolveIssueRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.review"))) -> dict[str, Any]:
    run = get_run(db, request, run_id, lock=True)
    if run.status not in {"READY_FOR_REVIEW", "PARTIALLY_REVIEWED"}:
        fail(request, "REPLENISHMENT_STATE_INVALID", "当前运行状态不能处理问题")
    issue = db.scalar(select(ReplenishmentIssue).where(ReplenishmentIssue.id == issue_id, ReplenishmentIssue.run_id == run.id).with_for_update())
    if issue is None: fail(request, "REPLENISHMENT_ISSUE_NOT_FOUND", "补库问题不存在", http_status=404)
    if issue.issue_code == "SNAPSHOT_DATE_IN_FUTURE":
        fail(request, "FUTURE_SNAPSHOT_NOT_OVERRIDABLE", "未来日期快照禁止放行，请重新选择正确的数据批次")
    before = issue_dict(issue)
    issue.status = "RESOLVED" if payload.action == "RESOLVE" else "IGNORED"
    issue.resolved_by, issue.resolved_at, issue.resolution_note = actor.id, datetime.now(UTC), payload.reason
    run.blocking_issue_count = db.scalar(select(func.count(ReplenishmentIssue.id)).where(ReplenishmentIssue.run_id == run.id, ReplenishmentIssue.severity == "BLOCKING", ReplenishmentIssue.status == "OPEN")) or 0
    write_audit_log(db, request, user=actor, action="replenishment.issue.resolve", entity_type="replenishment_issue", entity_id=str(issue.id), before_data=before, after_data=issue_dict(issue), reason=payload.reason)
    db.commit()
    return issue_dict(issue)


@router.post("/issues/{issue_id}/resolve")
def resolve_issue_direct(issue_id: int, payload: ResolveIssueRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.review"))) -> dict[str, Any]:
    issue = db.get(ReplenishmentIssue, issue_id)
    if issue is None: fail(request, "REPLENISHMENT_ISSUE_NOT_FOUND", "补库问题不存在", http_status=404)
    return resolve_issue(issue.run_id, issue_id, payload, request, db, actor)


@router.get("/suggestions")
@router.get("/runs/{run_id}/suggestions")
def list_suggestions(run_id: int, keyword: str | None = None, review_status: str | None = None, algorithm: str | None = None, positive_only: bool = True, has_issues: bool = False, manually_adjusted: bool = False, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view"))) -> dict[str, Any]:
    query = select(ReplenishmentSuggestion, Product).join(Product, Product.id == ReplenishmentSuggestion.product_id).where(ReplenishmentSuggestion.run_id == run_id)
    count_query = select(func.count(ReplenishmentSuggestion.id)).join(Product, Product.id == ReplenishmentSuggestion.product_id).where(ReplenishmentSuggestion.run_id == run_id)
    conditions = []
    if keyword:
        pattern = f"%{keyword.strip()}%"; conditions.append(or_(Product.product_code.ilike(pattern), Product.product_name.ilike(pattern), Product.specification.ilike(pattern)))
    if review_status: conditions.append(ReplenishmentSuggestion.review_status == review_status.upper())
    if algorithm: conditions.append(ReplenishmentSuggestion.algorithm == algorithm.upper())
    if positive_only: conditions.append(ReplenishmentSuggestion.system_suggested_qty > 0)
    if has_issues: conditions.append(select(ReplenishmentIssue.id).where(ReplenishmentIssue.suggestion_id == ReplenishmentSuggestion.id, ReplenishmentIssue.status == "OPEN").exists())
    if manually_adjusted: conditions.append(ReplenishmentSuggestion.review_status == "ADJUSTED")
    query, count_query = query.where(*conditions), count_query.where(*conditions)
    total = db.scalar(count_query) or 0
    rows = db.execute(query.order_by(Product.product_code).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [suggestion_dict(item, product) for item, product in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/suggestions/{suggestion_id}")
def get_suggestion(suggestion_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.view"))) -> dict[str, Any]:
    row = db.execute(select(ReplenishmentSuggestion, Product).join(Product).where(ReplenishmentSuggestion.id == suggestion_id)).one_or_none()
    if row is None: fail(request, "SUGGESTION_NOT_FOUND", "补库建议不存在", http_status=404)
    result = suggestion_dict(row[0], row[1])
    result["issues"] = [issue_dict(item) for item in db.scalars(select(ReplenishmentIssue).where(ReplenishmentIssue.suggestion_id == suggestion_id))]
    result["demand_id"] = db.scalar(select(ProductionDemand.id).where(ProductionDemand.source_suggestion_id == suggestion_id))
    return result


def review_locked(db: Session, request: Request, run: ReplenishmentRun, suggestions: list[ReplenishmentSuggestion], payload: ReviewSuggestionRequest, actor: User) -> None:
    if run.status not in {"READY_FOR_REVIEW", "PARTIALLY_REVIEWED"}:
        fail(request, "REPLENISHMENT_STATE_INVALID", "当前运行状态不能审核")
    now = datetime.now(UTC)
    for item in suggestions:
        before = suggestion_dict(item)
        if payload.action == "APPROVE":
            confirmed = payload.confirmed_qty if payload.confirmed_qty is not None else item.system_suggested_qty
            if confirmed != item.system_suggested_qty and len(payload.reason.strip()) < 2:
                fail(request, "CONFIRMED_QTY_REASON_REQUIRED", "修改确认数量必须填写原因", http_status=422)
            item.confirmed_qty = confirmed
            item.review_status = "ACCEPTED" if confirmed == item.system_suggested_qty else "ADJUSTED"
        elif payload.action == "REJECT":
            item.confirmed_qty, item.review_status = Decimal("0"), "REJECTED"
        else:
            item.confirmed_qty, item.review_status = None, "PENDING"
        item.reviewed_by, item.reviewed_at, item.review_reason, item.change_reason = actor.id, now, payload.reason, payload.reason
        write_audit_log(db, request, user=actor, action="replenishment.suggestion.review", entity_type="replenishment_suggestion", entity_id=str(item.id), before_data=before, after_data=suggestion_dict(item), reason=payload.reason)
    refresh_run_status(db, run)


@router.patch("/suggestions/{suggestion_id}")
@router.put("/suggestions/{suggestion_id}/review")
def review_suggestion(suggestion_id: int, payload: ReviewSuggestionRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.review"))) -> dict[str, Any]:
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.id == suggestion_id).with_for_update())
    if suggestion is None: fail(request, "SUGGESTION_NOT_FOUND", "补库建议不存在", http_status=404)
    run = get_run(db, request, suggestion.run_id, lock=True)
    review_locked(db, request, run, [suggestion], payload, actor)
    db.commit()
    return suggestion_dict(suggestion, db.get(Product, suggestion.product_id))


@router.post("/suggestions/bulk-review")
def bulk_review(payload: BulkReviewRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.review"))) -> dict[str, Any]:
    suggestions = list(db.scalars(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.id.in_(set(payload.suggestion_ids))).order_by(ReplenishmentSuggestion.id).with_for_update()))
    if len(suggestions) != len(set(payload.suggestion_ids)): fail(request, "SUGGESTION_NOT_FOUND", "包含不存在的补库建议", http_status=404)
    run_ids = {item.run_id for item in suggestions}
    if len(run_ids) != 1: fail(request, "SUGGESTION_RUN_MISMATCH", "批量审核必须属于同一运行")
    run = get_run(db, request, next(iter(run_ids)), lock=True)
    review_locked(db, request, run, suggestions, payload, actor)
    db.commit()
    return {"updated": len(suggestions), "run": run_dict(run)}


@router.post("/runs/{run_id}/suggestions/bulk-review")
def bulk_review_for_run(run_id: int, payload: BulkReviewRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.review"))) -> dict[str, Any]:
    run = get_run(db, request, run_id, lock=True)
    suggestions = list(db.scalars(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run.id, ReplenishmentSuggestion.id.in_(set(payload.suggestion_ids))).order_by(ReplenishmentSuggestion.id).with_for_update()))
    missing = sorted(set(payload.suggestion_ids) - {item.id for item in suggestions})
    review_locked(db, request, run, suggestions, payload, actor)
    db.commit()
    return {"success_count": len(suggestions), "failures": [{"suggestion_id": item, "code": "SUGGESTION_NOT_FOUND"} for item in missing], "run": run_dict(run)}


@router.put("/suggestions/{suggestion_id}/scheduled-override")
def set_scheduled_override(suggestion_id: int, payload: ScheduledOverrideRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.review"))) -> dict[str, Any]:
    suggestion = db.scalar(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.id == suggestion_id).with_for_update())
    if suggestion is None: fail(request, "SUGGESTION_NOT_FOUND", "补库建议不存在", http_status=404)
    run = get_run(db, request, suggestion.run_id, lock=True)
    if run.status not in {"READY_FOR_REVIEW", "PARTIALLY_REVIEWED"}: fail(request, "REPLENISHMENT_STATE_INVALID", "当前运行状态不能修改已排数量")
    before = suggestion_dict(suggestion)
    suggestion.scheduled_override_qty = payload.scheduled_override_qty
    suggestion.scheduled_not_started_qty = suggestion.scheduled_known_qty + payload.scheduled_override_qty
    suggestion.scheduled_source_status = "OVERRIDDEN"
    raw = suggestion.target_stock_qty - suggestion.available_qty - suggestion.pipe_wip_effective_qty - suggestion.fitting_wip_effective_qty - suggestion.scheduled_not_started_qty
    suggestion.raw_suggested_qty = raw
    suggestion.system_suggested_qty = max(raw, Decimal("0"))
    suggestion.confirmed_qty = Decimal("0") if suggestion.system_suggested_qty == 0 else None
    suggestion.review_status = "NOT_REQUIRED" if suggestion.system_suggested_qty == 0 else "PENDING"
    issue = db.scalar(select(ReplenishmentIssue).where(ReplenishmentIssue.suggestion_id == suggestion.id, ReplenishmentIssue.issue_code == "SCHEDULED_ACTUAL_UNKNOWN", ReplenishmentIssue.status == "OPEN").with_for_update())
    if issue:
        issue.status, issue.resolved_by, issue.resolved_at, issue.resolution_note = "RESOLVED", actor.id, datetime.now(UTC), payload.reason
    write_audit_log(db, request, user=actor, action="replenishment.scheduled_override", entity_type="replenishment_suggestion", entity_id=str(suggestion.id), before_data=before, after_data=suggestion_dict(suggestion), reason=payload.reason)
    refresh_run_status(db, run)
    db.commit()
    return suggestion_dict(suggestion, db.get(Product, suggestion.product_id))


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: int, payload: ApproveRunRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.approve"))) -> dict[str, Any]:
    run = get_run(db, request, run_id, lock=True)
    if run.status not in {"READY_FOR_REVIEW", "PARTIALLY_REVIEWED"}: fail(request, "REPLENISHMENT_STATE_INVALID", "当前运行状态不能批准")
    blocking = db.scalar(select(func.count(ReplenishmentIssue.id)).where(ReplenishmentIssue.run_id == run.id, ReplenishmentIssue.severity == "BLOCKING", ReplenishmentIssue.status == "OPEN")) or 0
    pending = db.scalar(select(func.count(ReplenishmentSuggestion.id)).where(ReplenishmentSuggestion.run_id == run.id, ReplenishmentSuggestion.review_status == "PENDING")) or 0
    positive = db.scalar(select(func.count(ReplenishmentSuggestion.id)).where(ReplenishmentSuggestion.run_id == run.id, ReplenishmentSuggestion.review_status.in_(["ACCEPTED", "ADJUSTED"]), ReplenishmentSuggestion.confirmed_qty > 0)) or 0
    if blocking: fail(request, "REPLENISHMENT_BLOCKING_ISSUES", "存在未解决的阻断问题，不能批准")
    if pending: fail(request, "REPLENISHMENT_REVIEW_INCOMPLETE", "仍有正数建议未完成审核", {"pending_count": pending})
    if not positive and not payload.allow_no_replenishment: fail(request, "NO_REPLENISHMENT_CONFIRMATION_REQUIRED", "本次没有正数确认量，请明确确认无需补库")
    before = run_dict(run)
    run.status, run.approved_by, run.approved_at = "APPROVED", actor.id, datetime.now(UTC)
    write_audit_log(db, request, user=actor, action="replenishment.run.approve", entity_type="replenishment_run", entity_id=str(run.id), before_data=before, after_data=run_dict(run), reason=payload.reason)
    db.commit()
    return run_dict(run)


@router.post("/runs/{run_id}/convert")
def convert(run_id: int, payload: ConvertSuggestionsRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.convert"))) -> dict[str, Any]:
    run = get_run(db, request, run_id, lock=True)
    suggestion_ids = list(set(payload.suggestion_ids))
    try:
        demands = service_call(request, lambda: convert_suggestions(db, run, suggestion_ids, actor.id))
    except IntegrityError:
        # SQLite ignores SELECT ... FOR UPDATE and PostgreSQL can still observe a
        # concurrent insert at a uniqueness boundary.  The unique source link is
        # the final idempotency guard: after losing that race, return the demand
        # created by the winning request instead of leaking a database exception.
        db.rollback()
        demands = list(
            db.scalars(
                select(ProductionDemand).where(
                    ProductionDemand.source_suggestion_id.in_(suggestion_ids)
                )
            )
        )
        if len(demands) != len(suggestion_ids):
            raise
        return {
            "items": [
                {
                    "id": item.id,
                    "demand_no": item.demand_no,
                    "source_suggestion_id": item.source_suggestion_id,
                }
                for item in demands
            ],
            "run": run_dict(db.get(ReplenishmentRun, run_id)),
        }
    write_audit_log(db, request, user=actor, action="replenishment.suggestions.convert", entity_type="replenishment_run", entity_id=str(run.id), after_data={"suggestion_ids": payload.suggestion_ids, "demand_ids": [item.id for item in demands]}, reason=payload.reason)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        demands = list(db.scalars(select(ProductionDemand).where(ProductionDemand.source_suggestion_id.in_(payload.suggestion_ids))))
    return {"items": [{"id": item.id, "demand_no": item.demand_no, "source_suggestion_id": item.source_suggestion_id} for item in demands], "run": run_dict(db.get(ReplenishmentRun, run_id))}


@router.post("/suggestions/{suggestion_id}/convert")
def convert_one(suggestion_id: int, payload: CancelRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("replenishment.convert"))) -> dict[str, Any]:
    suggestion = db.get(ReplenishmentSuggestion, suggestion_id)
    if suggestion is None: fail(request, "SUGGESTION_NOT_FOUND", "补库建议不存在", http_status=404)
    return convert(suggestion.run_id, ConvertSuggestionsRequest(suggestion_ids=[suggestion_id], reason=payload.reason), request, db, actor)

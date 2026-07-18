from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.core.errors import error_payload
from app.models import Product, ProductionDemand, ReplenishmentRun, ReplenishmentSuggestion, User
from app.schemas.replenishment import CancelRequest
from app.services.audit import write_audit_log


router = APIRouter(prefix="/api/v1/production-demands", tags=["production-demands"])


def demand_dict(item: ProductionDemand, product: Product | None = None) -> dict[str, Any]:
    result = {column.name: getattr(item, column.name) for column in ProductionDemand.__table__.columns}
    result.update({"product_code": product.product_code if product else None, "product_name": product.product_name if product else None, "specification": product.specification if product else None, "unit": product.unit if product else None})
    return result


@router.get("")
def list_demands(keyword: str | None = None, demand_status: str | None = Query(None, alias="status"), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), actor: User = Depends(require_permission("demand.view"))) -> dict[str, Any]:
    query = select(ProductionDemand, Product, ReplenishmentSuggestion, ReplenishmentRun).join(Product, Product.id == ProductionDemand.product_id).join(ReplenishmentSuggestion, ReplenishmentSuggestion.id == ProductionDemand.source_suggestion_id).join(ReplenishmentRun, ReplenishmentRun.id == ReplenishmentSuggestion.run_id)
    count_query = select(func.count(ProductionDemand.id)).join(Product, Product.id == ProductionDemand.product_id)
    filters = []
    if keyword:
        pattern = f"%{keyword.strip()}%"; filters.append(or_(ProductionDemand.demand_no.ilike(pattern), Product.product_code.ilike(pattern), Product.product_name.ilike(pattern)))
    if demand_status: filters.append(ProductionDemand.status == demand_status.upper())
    total = db.scalar(count_query.where(*filters)) or 0
    rows = db.execute(query.where(*filters).order_by(ProductionDemand.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for item, product, suggestion, run in rows:
        value = demand_dict(item, product); value.update({"source_run_id": run.id, "source_run_no": run.run_no, "source_suggestion_id": suggestion.id}); items.append(value)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{demand_id}")
def get_demand(demand_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("demand.view"))) -> dict[str, Any]:
    row = db.execute(select(ProductionDemand, Product, ReplenishmentSuggestion, ReplenishmentRun).join(Product, Product.id == ProductionDemand.product_id).join(ReplenishmentSuggestion, ReplenishmentSuggestion.id == ProductionDemand.source_suggestion_id).join(ReplenishmentRun, ReplenishmentRun.id == ReplenishmentSuggestion.run_id).where(ProductionDemand.id == demand_id)).one_or_none()
    if row is None: raise HTTPException(status_code=404, detail=error_payload(request, "PRODUCTION_DEMAND_NOT_FOUND", "生产需求不存在"))
    result = demand_dict(row[0], row[1]); result["source_suggestion"] = {"id": row[2].id, "run_id": row[3].id, "run_no": row[3].run_no, "system_suggested_qty": row[2].system_suggested_qty, "confirmed_qty": row[2].confirmed_qty, "monthly_shipments": row[2].monthly_shipments, "policy_snapshot": row[2].policy_snapshot}
    return result


@router.post("/{demand_id}/cancel")
def cancel_demand(demand_id: int, payload: CancelRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("demand.cancel"))) -> dict[str, Any]:
    demand = db.scalar(select(ProductionDemand).where(ProductionDemand.id == demand_id).with_for_update())
    if demand is None: raise HTTPException(status_code=404, detail=error_payload(request, "PRODUCTION_DEMAND_NOT_FOUND", "生产需求不存在"))
    if demand.status == "CANCELLED": return demand_dict(demand, db.get(Product, demand.product_id))
    if demand.active_allocated_qty > 0:
        raise HTTPException(status_code=409, detail=error_payload(request, "PRODUCTION_DEMAND_ALREADY_ALLOCATED", "需求已有排产占用，不能取消"))
    before = demand_dict(demand)
    demand.status, demand.cancelled_by, demand.cancelled_at, demand.cancel_reason = "CANCELLED", actor.id, datetime.now(UTC), payload.reason
    write_audit_log(db, request, user=actor, action="production_demand.cancel", entity_type="production_demand", entity_id=str(demand.id), before_data=before, after_data=demand_dict(demand), reason=payload.reason)
    db.commit()
    return demand_dict(demand, db.get(Product, demand.product_id))

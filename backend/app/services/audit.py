from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def write_audit_log(
    db: Session,
    request: Request,
    *,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    context_import_batch_id: int | None = None,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditLog:
    if context_import_batch_id is None and entity_type == "import_batch" and entity_id:
        try:
            context_import_batch_id = int(entity_id)
        except ValueError:
            context_import_batch_id = None
    log = AuditLog(
        request_id=request.state.request_id,
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        context_import_batch_id=context_import_batch_id,
        before_data=jsonable_encoder(before_data) if before_data is not None else None,
        after_data=jsonable_encoder(after_data) if after_data is not None else None,
        reason=reason,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    return log

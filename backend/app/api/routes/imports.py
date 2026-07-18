from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import error_payload
from app.models import AuditLog, ImportBatch, ImportRowIssue, User
from app.schemas.imports import AnalyzeImportRequest, RollbackImportRequest, UpdateMappingRequest
from app.services.audit import write_audit_log
from app.services.excel_import import (
    IMPORT_TYPES,
    TYPE_FIELDS,
    ImportValidationError,
    analyze_workbook,
    batch_has_downstream_references,
    delete_batch_records,
    import_validated_batch,
    iter_normalized_rows,
    load_safe_workbook,
    make_batch_no,
    safe_filename,
    sha256_bytes,
    validate_batch,
)
from app.services.identity import get_role_codes


router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


def raise_import_error(request: Request, exc: ImportValidationError, http_status: int = 422) -> None:
    raise HTTPException(
        status_code=http_status,
        detail=error_payload(request, exc.code, exc.message, exc.details),
    ) from exc


def get_batch_or_404(db: Session, request: Request, batch_id: int) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_payload(request, "IMPORT_BATCH_NOT_FOUND", "导入批次不存在"),
        )
    return batch


def storage_path(batch: ImportBatch) -> Path:
    settings = get_settings()
    storage = Path(settings.import_storage_dir).resolve()
    path = (storage / batch.stored_filename).resolve()
    if path.parent != storage:
        raise ImportValidationError("STORED_FILE_INVALID", "导入文件安全标识无效")
    if not path.is_file():
        raise ImportValidationError("STORED_FILE_MISSING", "导入源文件已不存在")
    return path


def serialize_batch(batch: ImportBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "import_type": batch.import_type,
        "original_filename": batch.original_filename,
        "file_sha256": batch.file_sha256,
        "file_size": batch.file_size,
        "workbook_sheet_count": batch.workbook_sheet_count,
        "selected_sheet_name": batch.selected_sheet_name,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "warning_rows": batch.warning_rows,
        "error_rows": batch.error_rows,
        "imported_rows": batch.imported_rows,
        "field_mapping": batch.field_mapping or {},
        "import_options": batch.import_options or {},
        "error_summary": batch.error_summary or {},
        "created_by": batch.created_by,
        "created_by_name": batch.creator.display_name if batch.creator else None,
        "confirmed_by": batch.confirmed_by,
        "confirmed_at": batch.confirmed_at,
        "cancelled_by": batch.cancelled_by,
        "cancelled_at": batch.cancelled_at,
        "cancel_reason": batch.cancel_reason,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
    }


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_import(
    request: Request,
    import_type: str = Form(...),
    file: UploadFile = File(...),
    source_date: date | None = Form(default=None),
    force: bool = Form(default=False),
    force_reason: str | None = Form(default=None),
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("import.upload")),
) -> dict[str, Any]:
    normalized_type = import_type.strip().upper()
    if normalized_type not in IMPORT_TYPES:
        raise HTTPException(status_code=422, detail=error_payload(request, "IMPORT_TYPE_UNSUPPORTED", "不支持的导入类型"))
    original_name = safe_filename(file.filename)
    if Path(original_name).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=415, detail=error_payload(request, "XLSX_REQUIRED", "仅允许上传 .xlsx 文件"))
    settings = get_settings()
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > settings.import_max_file_size_bytes:
            raise HTTPException(status_code=413, detail=error_payload(request, "IMPORT_FILE_TOO_LARGE", "上传文件超过大小限制", {"max_mb": settings.import_max_file_size_mb}))
        chunks.append(chunk)
    content = b"".join(chunks)
    digest = sha256_bytes(content)
    duplicate_candidates = db.scalars(select(ImportBatch).where(ImportBatch.import_type == normalized_type, ImportBatch.file_sha256 == digest)).all()
    duplicate = next((item for item in duplicate_candidates if (item.import_options or {}).get("source_date") == (source_date.isoformat() if source_date else None) and item.status not in {"CANCELLED", "ROLLED_BACK"}), None)
    if duplicate and not force:
        raise HTTPException(status_code=409, detail=error_payload(request, "DUPLICATE_IMPORT_FILE", "相同类型、文件和数据日期已存在导入批次", {"batch_id": duplicate.id, "batch_no": duplicate.batch_no}))
    if force and ("ADMIN" not in get_role_codes(actor) or not force_reason or len(force_reason.strip()) < 2):
        raise HTTPException(status_code=403, detail=error_payload(request, "FORCE_IMPORT_REASON_REQUIRED", "仅管理员可在填写原因后强制重复导入"))
    storage = Path(settings.import_storage_dir).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}.xlsx"
    stored_path = storage / stored_name
    stored_path.write_bytes(content)
    try:
        workbook = load_safe_workbook(stored_path)
        sheet_count = len(workbook.sheetnames)
        sheet_names = list(workbook.sheetnames)
        workbook.close()
        batch = ImportBatch(
            batch_no=make_batch_no(), import_type=normalized_type, original_filename=original_name,
            stored_filename=stored_name, file_sha256=digest, file_size=size,
            workbook_sheet_count=sheet_count, status="UPLOADED", created_by=actor.id,
            import_options={"source_date": source_date.isoformat() if source_date else None, "force": force, "force_reason": force_reason},
        )
        db.add(batch)
        db.flush()
        write_audit_log(db, request, user=actor, action="import.upload", entity_type="import_batch", entity_id=str(batch.id), after_data={"batch_no": batch.batch_no, "import_type": normalized_type, "file_sha256": digest}, reason=force_reason)
        db.commit()
    except ImportValidationError as exc:
        db.rollback()
        stored_path.unlink(missing_ok=True)
        raise_import_error(request, exc)
    except Exception:
        db.rollback()
        stored_path.unlink(missing_ok=True)
        raise
    result = serialize_batch(batch)
    result["sheet_names"] = sheet_names
    return result


@router.get("")
def list_imports(
    request: Request,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    import_type: str | None = None, batch_status: str | None = Query(default=None, alias="status"),
    created_by: int | None = None, date_from: date | None = None, date_to: date | None = None,
    db: Session = Depends(get_db), actor: User = Depends(require_permission("import.view")),
) -> dict[str, Any]:
    query = select(ImportBatch)
    count_query = select(func.count(ImportBatch.id))
    filters = []
    if import_type: filters.append(ImportBatch.import_type == import_type.upper())
    if batch_status: filters.append(ImportBatch.status == batch_status.upper())
    if created_by: filters.append(ImportBatch.created_by == created_by)
    if date_from: filters.append(ImportBatch.created_at >= datetime.combine(date_from, time.min, UTC))
    if date_to: filters.append(ImportBatch.created_at <= datetime.combine(date_to, time.max, UTC))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = db.scalar(count_query) or 0
    items = db.scalars(query.order_by(ImportBatch.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize_batch(item) for item in items], "page": page, "page_size": page_size, "total": total}


@router.get("/{batch_id}")
def get_import(batch_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.view"))) -> dict[str, Any]:
    return serialize_batch(get_batch_or_404(db, request, batch_id))


@router.get("/{batch_id}/sheets")
def get_sheets(batch_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.view"))) -> dict[str, Any]:
    batch = get_batch_or_404(db, request, batch_id)
    try:
        return analyze_workbook(storage_path(batch), batch.import_type)
    except ImportValidationError as exc:
        raise_import_error(request, exc)


@router.post("/{batch_id}/analyze")
def analyze_import(batch_id: int, payload: AnalyzeImportRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.validate"))) -> dict[str, Any]:
    batch = get_batch_or_404(db, request, batch_id)
    if batch.status not in {"UPLOADED", "ANALYZED", "VALIDATION_FAILED", "READY"}:
        raise HTTPException(status_code=409, detail=error_payload(request, "IMPORT_STATE_INVALID", "当前批次状态不能重新分析"))
    try:
        analysis = analyze_workbook(storage_path(batch), batch.import_type, payload.sheet_name)
    except ImportValidationError as exc:
        raise_import_error(request, exc)
    sheet = analysis["sheets"][0]
    header_start = payload.header_row_start or sheet["header_row_start"]
    header_end = payload.header_row_end or sheet["header_row_end"]
    batch.selected_sheet_name = payload.sheet_name
    batch.field_mapping = sheet["auto_mapping"]
    batch.import_options = {**(batch.import_options or {}), "header_row_start": header_start, "header_row_end": header_end, "analysis": {key: sheet[key] for key in ("declared_rows", "last_row", "last_column", "formula_count", "external_formula_count", "error_cell_count", "scan_truncated")}}
    batch.status = "ANALYZED"
    write_audit_log(db, request, user=actor, action="import.analyze", entity_type="import_batch", entity_id=str(batch.id), before_data=None, after_data={"sheet_name": payload.sheet_name, "header_row_start": header_start, "header_row_end": header_end, "field_mapping": batch.field_mapping})
    db.commit()
    return {**serialize_batch(batch), "analysis": sheet}


@router.put("/{batch_id}/mapping")
def update_mapping(batch_id: int, payload: UpdateMappingRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.validate"))) -> dict[str, Any]:
    batch = get_batch_or_404(db, request, batch_id)
    if not batch.selected_sheet_name:
        raise HTTPException(status_code=409, detail=error_payload(request, "IMPORT_NOT_ANALYZED", "请先分析并选择工作表"))
    allowed = set(TYPE_FIELDS[batch.import_type])
    unknown = sorted(set(payload.field_mapping) - allowed)
    if unknown or any(column < 1 for column in payload.field_mapping.values()):
        raise HTTPException(status_code=422, detail=error_payload(request, "FIELD_MAPPING_INVALID", "字段映射无效", {"unknown_fields": unknown}))
    if len(set(payload.field_mapping.values())) != len(payload.field_mapping):
        raise HTTPException(status_code=422, detail=error_payload(request, "DUPLICATE_FIELD_MAPPING", "一个 Excel 列不能映射到多个业务字段"))
    before = batch.field_mapping or {}
    batch.field_mapping = payload.field_mapping
    batch.import_options = {**(batch.import_options or {}), "conversion_rules": payload.conversion_rules}
    batch.status = "ANALYZED"
    write_audit_log(db, request, user=actor, action="import.mapping.update", entity_type="import_batch", entity_id=str(batch.id), before_data={"field_mapping": before}, after_data={"field_mapping": payload.field_mapping, "conversion_rules": payload.conversion_rules})
    db.commit()
    return serialize_batch(batch)


@router.get("/{batch_id}/preview")
def preview_import(batch_id: int, request: Request, issue_filter: str | None = Query(default=None, pattern="^(ERROR|WARNING)$"), limit: int = Query(default=100, ge=1, le=100), db: Session = Depends(get_db), actor: User = Depends(require_permission("import.view"))) -> dict[str, Any]:
    batch = get_batch_or_404(db, request, batch_id)
    try:
        rows = []
        for row_number, normalized, problems in iter_normalized_rows(storage_path(batch), batch):
            if not normalized:
                continue
            severities = {item["severity"] for item in problems}
            if issue_filter and issue_filter not in severities:
                continue
            rows.append({"excel_row_number": row_number, "data": normalized, "issues": problems, "severity": "ERROR" if "ERROR" in severities else "WARNING" if "WARNING" in severities else "VALID"})
            if len(rows) >= limit:
                break
        return {"items": rows, "limit": limit}
    except ImportValidationError as exc:
        raise_import_error(request, exc)


@router.post("/{batch_id}/validate")
def validate_import(batch_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.validate"))) -> dict[str, Any]:
    batch = get_batch_or_404(db, request, batch_id)
    before = {"status": batch.status, "total_rows": batch.total_rows, "error_rows": batch.error_rows}
    try:
        result = validate_batch(db, batch, storage_path(batch))
    except ImportValidationError as exc:
        db.rollback()
        raise_import_error(request, exc)
    write_audit_log(db, request, user=actor, action="import.validate", entity_type="import_batch", entity_id=str(batch.id), before_data=before, after_data=result)
    db.commit()
    return {**serialize_batch(batch), "validation": result}


@router.post("/{batch_id}/confirm")
def confirm_import(batch_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.confirm"))) -> dict[str, Any]:
    batch = get_batch_or_404(db, request, batch_id)
    if batch.status == "COMPLETED":
        return serialize_batch(batch)
    try:
        path = storage_path(batch)
        batch.status = "IMPORTING"
        db.flush()
        imported = import_validated_batch(db, batch, path)
        batch.status = "COMPLETED"
        batch.imported_rows = imported
        batch.confirmed_by = actor.id
        batch.confirmed_at = datetime.now(UTC)
        write_audit_log(db, request, user=actor, action="import.confirm", entity_type="import_batch", entity_id=str(batch.id), before_data={"status": "READY"}, after_data={"status": "COMPLETED", "imported_rows": imported})
        db.commit()
        return serialize_batch(batch)
    except ImportValidationError as exc:
        db.rollback()
        raise_import_error(request, exc, 409)
    except Exception:
        db.rollback()
        failed_batch = db.get(ImportBatch, batch_id)
        if failed_batch:
            failed_batch.status = "FAILED"
            failed_batch.error_summary = {"IMPORT_TRANSACTION_FAILED": 1}
            write_audit_log(db, request, user=actor, action="import.confirm.failed", entity_type="import_batch", entity_id=str(batch_id), before_data={"status": "READY"}, after_data={"status": "FAILED"})
            db.commit()
        raise HTTPException(status_code=500, detail=error_payload(request, "IMPORT_TRANSACTION_FAILED", "导入事务已整体回滚")) from None


@router.post("/{batch_id}/rollback")
def rollback_import(batch_id: int, payload: RollbackImportRequest, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.rollback"))) -> dict[str, Any]:
    batch = get_batch_or_404(db, request, batch_id)
    if batch.status != "COMPLETED":
        raise HTTPException(status_code=409, detail=error_payload(request, "IMPORT_ROLLBACK_NOT_ALLOWED", "只有已完成批次可以撤销"))
    if batch_has_downstream_references(db, batch):
        raise HTTPException(status_code=409, detail=error_payload(request, "IMPORT_BATCH_REFERENCED", "导入批次已被后续业务引用，不能撤销"))
    delete_batch_records(db, batch.id)
    batch.status = "ROLLED_BACK"
    batch.cancelled_by = actor.id
    batch.cancelled_at = datetime.now(UTC)
    batch.cancel_reason = payload.reason
    write_audit_log(db, request, user=actor, action="import.rollback", entity_type="import_batch", entity_id=str(batch.id), before_data={"status": "COMPLETED", "imported_rows": batch.imported_rows}, after_data={"status": "ROLLED_BACK", "imported_rows": 0}, reason=payload.reason)
    batch.imported_rows = 0
    db.commit()
    return serialize_batch(batch)


@router.get("/{batch_id}/issues")
def list_issues(batch_id: int, request: Request, page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200), severity: str | None = None, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.view"))) -> dict[str, Any]:
    get_batch_or_404(db, request, batch_id)
    filters = [ImportRowIssue.import_batch_id == batch_id]
    if severity: filters.append(ImportRowIssue.severity == severity.upper())
    total = db.scalar(select(func.count(ImportRowIssue.id)).where(*filters)) or 0
    items = db.scalars(select(ImportRowIssue).where(*filters).order_by(ImportRowIssue.excel_row_number, ImportRowIssue.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": item.id, "sheet_name": item.sheet_name, "excel_row_number": item.excel_row_number, "severity": item.severity, "field_name": item.field_name, "raw_value": item.raw_value, "issue_code": item.issue_code, "message": item.message} for item in items], "page": page, "page_size": page_size, "total": total}


@router.get("/{batch_id}/issues/export")
def export_issues(batch_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.view"))):
    batch = get_batch_or_404(db, request, batch_id)
    items = db.scalars(select(ImportRowIssue).where(ImportRowIssue.import_batch_id == batch_id).order_by(ImportRowIssue.excel_row_number)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["工作表", "Excel行号", "严重程度", "字段", "原始值", "问题代码", "说明"])
    for item in items:
        writer.writerow([item.sheet_name, item.excel_row_number, item.severity, item.field_name or "", item.raw_value or "", item.issue_code, item.message])
    content = "\ufeff" + output.getvalue()
    return StreamingResponse(iter([content.encode("utf-8")]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{batch.batch_no}-issues.csv"'})


@router.get("/{batch_id}/audit-logs")
def list_import_audit_logs(batch_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_permission("import.view"))) -> dict[str, Any]:
    get_batch_or_404(db, request, batch_id)
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "import_batch", AuditLog.entity_id == str(batch_id))
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    ).all()
    return {"items": [{"id": log.id, "action": log.action, "user_id": log.user_id, "before_data": log.before_data, "after_data": log.after_data, "reason": log.reason, "request_id": log.request_id, "occurred_at": log.occurred_at} for log in logs]}

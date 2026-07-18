from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import PatternFill
from sqlalchemy import func, select

from app.api.routes import imports as import_routes
from app.core.config import get_settings
from app.core.security import hash_password
from app.models import AuditLog, ImportBatch, ImportedWeeklyPlanRaw, ImportRowIssue, InventorySnapshot, PipeWipSnapshot, Product, RegularProductionProduct, Role, User, UserRole


def workbook_bytes(headers, rows, *, sheet_name="数据", extra_sheet=False, multiline=False, trailing_style_row=None):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    if multiline:
        sheet.merge_cells("A1:A2")
        sheet["A1"] = headers[0]
        sheet.merge_cells("B1:C1")
        sheet["B1"] = "产品信息"
        sheet["B2"] = headers[1]
        sheet["C2"] = headers[2]
        header_end = 2
    else:
        sheet.append(headers)
        header_end = 1
    for row in rows:
        sheet.append(row)
    if trailing_style_row:
        sheet.cell(trailing_style_row, 1).fill = PatternFill(fill_type="solid", fgColor="FFFFFF")
    if extra_sheet:
        workbook.create_sheet("说明")["A1"] = "虚拟测试说明"
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue(), header_end


def upload(client, token, content, import_type="INVENTORY", filename="synthetic.xlsx", **data):
    form = {"import_type": import_type, **data}
    return client.post(
        "/api/v1/imports/upload",
        headers={"Authorization": f"Bearer {token}"},
        data=form,
        files={"file": (filename, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


def analyze(client, token, batch_id, sheet_name="数据", header_end=None):
    payload = {"sheet_name": sheet_name}
    if header_end:
        payload.update({"header_row_start": 1, "header_row_end": header_end})
    return client.post(
        f"/api/v1/imports/{batch_id}/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


def validate(client, token, batch_id):
    return client.post(
        f"/api/v1/imports/{batch_id}/validate",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_standard_upload_analyze_validate_confirm_and_inventory_recalculation(client, db, admin_token):
    content, _ = workbook_bytes(
        ["产品编码", "产品名称", "规格型号", "现存数量", "预计入库", "预计出库", "可用数量"],
        [["00001234", "虚拟水管", "DN20", 10, "3", 2, 99]],
        extra_sheet=True,
    )
    response = upload(client, admin_token, content)
    assert response.status_code == 201
    batch_id = response.json()["id"]
    assert response.json()["sheet_names"] == ["数据", "说明"]

    sheets = client.get(f"/api/v1/imports/{batch_id}/sheets", headers={"Authorization": f"Bearer {admin_token}"})
    assert sheets.status_code == 200
    assert sheets.json()["sheet_count"] == 2
    analyzed = analyze(client, admin_token, batch_id)
    assert analyzed.status_code == 200
    assert analyzed.json()["field_mapping"]["product_code"] == 1

    checked = validate(client, admin_token, batch_id)
    assert checked.status_code == 200
    assert checked.json()["status"] == "READY"
    assert checked.json()["warning_rows"] == 1

    preview = client.get(f"/api/v1/imports/{batch_id}/preview", headers={"Authorization": f"Bearer {admin_token}"})
    assert preview.json()["items"][0]["data"]["product_code"] == "00001234"
    assert preview.json()["items"][0]["data"]["calculated_available_qty"] == "11"

    confirmed = client.post(f"/api/v1/imports/{batch_id}/confirm", headers={"Authorization": f"Bearer {admin_token}"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "COMPLETED"
    assert db.scalar(select(Product).where(Product.product_code == "00001234")) is not None
    snapshot = db.scalar(select(InventorySnapshot).where(InventorySnapshot.import_batch_id == batch_id))
    assert str(snapshot.calculated_available_qty) == "11.0000"
    assert str(snapshot.source_available_qty) == "99.0000"


def test_non_xlsx_and_oversized_files_are_rejected(client, admin_token, monkeypatch):
    rejected = upload(client, admin_token, b"plain text", filename="unsafe.csv")
    assert rejected.status_code == 415
    assert rejected.json()["code"] == "XLSX_REQUIRED"
    monkeypatch.setattr(get_settings(), "import_max_file_size_mb", 0)
    too_large = upload(client, admin_token, b"x", filename="large.xlsx")
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "IMPORT_FILE_TOO_LARGE"


def test_duplicate_file_is_blocked_and_admin_may_force_with_reason(client, admin_token):
    content, _ = workbook_bytes(["产品编码"], [["TEST-PIPE-001"]])
    first = upload(client, admin_token, content, import_type="REGULAR_PRODUCT", source_date="2026-07-18")
    assert first.status_code == 201
    duplicate = upload(client, admin_token, content, import_type="REGULAR_PRODUCT", source_date="2026-07-18")
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "DUPLICATE_IMPORT_FILE"
    forced = upload(client, admin_token, content, import_type="REGULAR_PRODUCT", source_date="2026-07-18", force="true", force_reason="重新核对映射")
    assert forced.status_code == 201


def test_multiline_header_is_detected(client, admin_token):
    content, _ = workbook_bytes(["产品编码", "产品名称", "规格型号"], [["TEST-PIPE-001", "虚拟水管", "DN20"]], multiline=True)
    batch_id = upload(client, admin_token, content, import_type="REGULAR_PRODUCT").json()["id"]
    result = analyze(client, admin_token, batch_id)
    assert result.status_code == 200
    assert result.json()["analysis"]["header_row_start"] == 1
    assert result.json()["analysis"]["header_row_end"] == 2
    assert result.json()["field_mapping"] == {"product_code": 1, "product_name": 2, "specification": 3}


def test_scientific_notation_product_code_is_an_error(client, admin_token):
    content, _ = workbook_bytes(["产品编码"], [["1.2345E+11"]])
    batch_id = upload(client, admin_token, content, import_type="REGULAR_PRODUCT").json()["id"]
    analyze(client, admin_token, batch_id)
    result = validate(client, admin_token, batch_id)
    assert result.json()["status"] == "VALIDATION_FAILED"
    issues = client.get(f"/api/v1/imports/{batch_id}/issues", headers={"Authorization": f"Bearer {admin_token}"}).json()["items"]
    assert "PRODUCT_CODE_SCIENTIFIC_NOTATION" in {item["issue_code"] for item in issues}


def test_negative_wip_is_warning_and_can_be_confirmed(client, db, admin_token):
    content, _ = workbook_bytes(["产品编码", "产品名称", "未入库数量"], [["TEST-PIPE-001", "虚拟水管", -5]])
    batch_id = upload(client, admin_token, content, import_type="PIPE_WIP").json()["id"]
    analyze(client, admin_token, batch_id)
    result = validate(client, admin_token, batch_id)
    assert result.json()["status"] == "READY"
    assert result.json()["warning_rows"] == 1
    confirmed = client.post(f"/api/v1/imports/{batch_id}/confirm", headers={"Authorization": f"Bearer {admin_token}"})
    assert confirmed.status_code == 200
    snapshot = db.scalar(select(PipeWipSnapshot).where(PipeWipSnapshot.import_batch_id == batch_id))
    assert str(snapshot.quantity) == "-5.0000"


def test_product_identity_conflict_and_duplicate_are_reported(client, admin_token):
    content, _ = workbook_bytes(
        ["产品编码", "产品名称", "规格", "未入库数量"],
        [["TEST-PIPE-001", "名称一", "DN20", 1], ["TEST-PIPE-001", "名称二", "DN25", 2]],
    )
    batch_id = upload(client, admin_token, content, import_type="PIPE_WIP").json()["id"]
    analyze(client, admin_token, batch_id)
    validate(client, admin_token, batch_id)
    issues = client.get(f"/api/v1/imports/{batch_id}/issues", headers={"Authorization": f"Bearer {admin_token}"}).json()["items"]
    codes = {item["issue_code"] for item in issues}
    assert "PRODUCT_IDENTITY_CONFLICT" in codes
    assert "DUPLICATE_ROW" in codes


def test_error_rows_cannot_be_confirmed_or_enter_business_tables(client, db, admin_token):
    content, _ = workbook_bytes(["产品编码", "现存数量", "预计入库", "预计出库"], [["TEST-FITTING-001", "bad", 0, 0]])
    batch_id = upload(client, admin_token, content).json()["id"]
    analyze(client, admin_token, batch_id)
    validate(client, admin_token, batch_id)
    response = client.post(f"/api/v1/imports/{batch_id}/confirm", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 409
    assert response.json()["code"] == "IMPORT_NOT_READY"
    assert db.scalar(select(func.count(InventorySnapshot.id))) == 0


def test_transaction_failure_rolls_back_and_marks_batch_failed(client, db, admin_token, monkeypatch):
    content, _ = workbook_bytes(["产品编码"], [["TEST-CLAMP-108"]])
    batch_id = upload(client, admin_token, content, import_type="REGULAR_PRODUCT").json()["id"]
    analyze(client, admin_token, batch_id)
    validate(client, admin_token, batch_id)
    monkeypatch.setattr(import_routes, "import_validated_batch", lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic failure")))
    response = client.post(f"/api/v1/imports/{batch_id}/confirm", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 500
    db.expire_all()
    assert db.get(ImportBatch, batch_id).status == "FAILED"
    assert db.scalar(select(func.count(Product.id)).where(Product.product_code == "TEST-CLAMP-108")) == 0


def completed_regular_batch(client, admin_token):
    content, _ = workbook_bytes(["产品编码"], [["TEST-CLAMP-108"]])
    batch_id = upload(client, admin_token, content, import_type="REGULAR_PRODUCT").json()["id"]
    analyze(client, admin_token, batch_id)
    validate(client, admin_token, batch_id)
    assert client.post(f"/api/v1/imports/{batch_id}/confirm", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200
    return batch_id


def test_completed_batch_can_be_rolled_back_with_audit(client, db, admin_token):
    batch_id = completed_regular_batch(client, admin_token)
    response = client.post(f"/api/v1/imports/{batch_id}/rollback", headers={"Authorization": f"Bearer {admin_token}"}, json={"reason": "撤销虚拟测试导入"})
    assert response.status_code == 200
    assert response.json()["status"] == "ROLLED_BACK"
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "import.rollback", AuditLog.entity_id == str(batch_id)))
    assert audit.before_data["status"] == "COMPLETED"
    assert audit.after_data["status"] == "ROLLED_BACK"
    assert audit.reason == "撤销虚拟测试导入"


def test_referenced_batch_cannot_be_rolled_back(client, admin_token, monkeypatch):
    batch_id = completed_regular_batch(client, admin_token)
    monkeypatch.setattr(import_routes, "batch_has_downstream_references", lambda *args: True)
    response = client.post(f"/api/v1/imports/{batch_id}/rollback", headers={"Authorization": f"Bearer {admin_token}"}, json={"reason": "尝试撤销"})
    assert response.status_code == 409
    assert response.json()["code"] == "IMPORT_BATCH_REFERENCED"


def test_viewer_can_list_but_cannot_upload(client, db, admin_token):
    viewer_role = db.scalar(select(Role).where(Role.code == "VIEWER"))
    viewer = User(username="viewer-import", display_name="只读测试用户", password_hash=hash_password("ViewerTest123!"))
    viewer.role_links.append(UserRole(role=viewer_role))
    db.add(viewer)
    db.commit()
    login = client.post("/api/v1/auth/login", json={"username": "viewer-import", "password": "ViewerTest123!"})
    token = login.json()["access_token"]
    assert client.get("/api/v1/imports", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    content, _ = workbook_bytes(["产品编码"], [["TEST-PIPE-001"]])
    assert upload(client, token, content, import_type="REGULAR_PRODUCT").status_code == 403


def test_invalid_workbook_response_does_not_leak_server_path(client, admin_token):
    response = upload(client, admin_token, b"not a zip archive")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INVALID_WORKBOOK"
    assert "F:\\" not in str(body) and "/data/" not in str(body)


def test_effective_range_stops_before_million_formatted_rows(client, admin_token):
    content, _ = workbook_bytes(["产品编码"], [["TEST-PIPE-001"]], trailing_style_row=1_048_576)
    batch_id = upload(client, admin_token, content, import_type="REGULAR_PRODUCT").json()["id"]
    result = analyze(client, admin_token, batch_id)
    analysis = result.json()["analysis"]
    assert analysis["declared_rows"] == 1_048_576
    assert analysis["last_row"] == 2
    assert analysis["scanned_rows"] < 500


def test_upload_analyze_validate_and_confirm_are_audited(client, db, admin_token):
    batch_id = completed_regular_batch(client, admin_token)
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == str(batch_id))).all())
    assert {"import.upload", "import.analyze", "import.validate", "import.confirm"}.issubset(actions)


def test_hidden_rows_are_detected_and_skipped(client, db, admin_token):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet.append(["产品编码"])
    sheet.append(["TEST-PIPE-001"])
    sheet.append(["TEST-FITTING-001"])
    sheet.row_dimensions[3].hidden = True
    output = BytesIO()
    workbook.save(output)
    batch_id = upload(client, admin_token, output.getvalue(), import_type="REGULAR_PRODUCT").json()["id"]
    analyzed = analyze(client, admin_token, batch_id)
    assert analyzed.json()["analysis"]["hidden_row_count"] == 1
    assert validate(client, admin_token, batch_id).json()["total_rows"] == 1
    client.post(f"/api/v1/imports/{batch_id}/confirm", headers={"Authorization": f"Bearer {admin_token}"})
    assert db.scalar(select(func.count(RegularProductionProduct.id))) == 1


def test_weekly_plan_merged_cells_and_plan_actual_pair_are_standardized(client, db, admin_token):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "制管"
    sheet.append(["产品编码", "产品名称", "生产批次", "工序", "设备", "计划/实际", "开始日期", "结束日期", "计划数量"])
    sheet.append(["TEST-PIPE-001", "虚拟水管", "LOT-DEMO-001", "制管", "设备-A", "计划", "2026-07-13", "2026-07-19", 10])
    sheet.append([None, None, None, None, None, "实际", "2026-07-13", "2026-07-19", 8])
    for column in "ABCDE":
        sheet.merge_cells(f"{column}2:{column}3")
    output = BytesIO()
    workbook.save(output)
    batch_id = upload(client, admin_token, output.getvalue(), import_type="WEEKLY_PLAN").json()["id"]
    analyzed = analyze(client, admin_token, batch_id, sheet_name="制管")
    assert analyzed.status_code == 200, analyzed.text
    assert "A2:A3" in analyzed.json()["analysis"]["merged_ranges"]
    checked = validate(client, admin_token, batch_id)
    assert checked.json()["status"] == "READY"
    confirmed = client.post(f"/api/v1/imports/{batch_id}/confirm", headers={"Authorization": f"Bearer {admin_token}"})
    assert confirmed.json()["imported_rows"] == 1
    record = db.scalar(select(ImportedWeeklyPlanRaw).where(ImportedWeeklyPlanRaw.import_batch_id == batch_id))
    assert str(record.planned_quantity) == "10.0000"
    assert str(record.actual_quantity) == "8.0000"


def test_duplicate_mapping_is_rejected(client, admin_token):
    content, _ = workbook_bytes(["产品编码", "产品名称"], [["TEST-PIPE-001", "虚拟水管"]])
    batch_id = upload(client, admin_token, content, import_type="REGULAR_PRODUCT").json()["id"]
    analyze(client, admin_token, batch_id)
    response = client.put(
        f"/api/v1/imports/{batch_id}/mapping",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"field_mapping": {"product_code": 1, "product_name": 1}, "conversion_rules": {}},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "DUPLICATE_FIELD_MAPPING"


def test_issue_export_is_authenticated_csv(client, admin_token):
    content, _ = workbook_bytes(["产品编码"], [["1.2E+9"]])
    batch_id = upload(client, admin_token, content, import_type="REGULAR_PRODUCT").json()["id"]
    analyze(client, admin_token, batch_id)
    validate(client, admin_token, batch_id)
    assert client.get(f"/api/v1/imports/{batch_id}/issues/export").status_code == 401
    response = client.get(f"/api/v1/imports/{batch_id}/issues/export", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "PRODUCT_CODE_SCIENTIFIC_NOTATION" in response.content.decode("utf-8-sig")


def test_uploaded_filename_is_sanitized_and_server_path_is_never_returned(client, admin_token):
    content, _ = workbook_bytes(["产品编码"], [["TEST-PIPE-001"]])
    response = upload(client, admin_token, content, import_type="REGULAR_PRODUCT", filename="../../secret.xlsx")
    assert response.status_code == 201
    assert response.json()["original_filename"] == "secret.xlsx"
    assert "stored_filename" not in response.json()

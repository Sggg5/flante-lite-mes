from __future__ import annotations

import hashlib
import re
import zipfile
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator

from openpyxl import load_workbook
from openpyxl.cell import Cell
from openpyxl.utils.cell import range_boundaries
from openpyxl.utils.datetime import from_excel
from xml.etree.ElementTree import iterparse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    FittingWipSnapshot,
    ImportBatch,
    ImportedWeeklyPlanRaw,
    ImportRowIssue,
    InventorySnapshot,
    PipeWipSnapshot,
    Product,
    RegularProductionProduct,
    ShipmentRecord,
)


IMPORT_TYPES = {
    "SHIPMENT",
    "INVENTORY",
    "PIPE_WIP",
    "FITTING_WIP",
    "REGULAR_PRODUCT",
    "WEEKLY_PLAN",
}
TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "ROLLED_BACK"}
MUTABLE_STATUSES = {"UPLOADED", "ANALYZED", "VALIDATION_FAILED", "READY", "FAILED"}
EMPTY_ROW_STOP = 200
MAX_SCAN_ROWS = 500_000
SCIENCE_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?[Ee][+-]?\d+$")

FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "product_code": ("存货编码", "产品编码", "物料编码", "编码", "代码"),
    "product_name": ("存货名称", "产品名称", "名称", "品名"),
    "specification": ("规格型号", "规格", "型号"),
    "category": ("存货分类", "产品分类", "分类", "类别"),
    "unit": ("主计量单位", "计量单位", "单位"),
    "quantity": ("出库数量", "未入库数量", "未完成数量", "未完成", "数量"),
    "document_no": ("出库单号", "单据号", "单号"),
    "shipment_date": ("出库日期", "日期"),
    "shipment_month": ("出库月份", "月份"),
    "production_batch_no": ("生产批次号", "生产批次", "批次号", "批次", "批号"),
    "snapshot_date": ("快照日期", "统计日期", "数据日期"),
    "on_hand_qty": ("现存数量", "现存", "库存数量"),
    "expected_inbound_qty": ("预计入库数量", "预计入库"),
    "expected_outbound_qty": ("预计出库数量", "预计出库"),
    "source_available_qty": ("可用数量", "可用量"),
    "process_name": ("工序名称", "工序"),
    "equipment_name": ("设备名称", "设备", "机台"),
    "planned_quantity": ("周计划", "计划数量", "计划量"),
    "actual_quantity": ("周实际", "实际数量", "实际量"),
    "plan_start_date": ("计划开始日期", "开始日期"),
    "plan_end_date": ("计划结束日期", "结束日期"),
    "row_kind": ("计划/实际", "类型", "行类型"),
}

TYPE_FIELDS: dict[str, tuple[str, ...]] = {
    "SHIPMENT": ("product_code", "product_name", "specification", "unit", "document_no", "shipment_date", "shipment_month", "quantity", "production_batch_no"),
    "INVENTORY": ("product_code", "product_name", "specification", "category", "unit", "snapshot_date", "on_hand_qty", "expected_inbound_qty", "expected_outbound_qty", "source_available_qty"),
    "PIPE_WIP": ("product_code", "product_name", "specification", "snapshot_date", "quantity"),
    "FITTING_WIP": ("product_code", "product_name", "specification", "snapshot_date", "production_batch_no", "quantity"),
    "REGULAR_PRODUCT": ("product_code", "product_name", "specification", "category", "unit"),
    "WEEKLY_PLAN": ("product_code", "product_name", "specification", "production_batch_no", "process_name", "equipment_name", "row_kind", "plan_start_date", "plan_end_date", "planned_quantity", "actual_quantity"),
}

REQUIRED_FIELDS: dict[str, set[str]] = {
    "SHIPMENT": {"product_code", "document_no", "shipment_date", "quantity"},
    "INVENTORY": {"product_code", "on_hand_qty", "expected_inbound_qty", "expected_outbound_qty"},
    "PIPE_WIP": {"product_code", "quantity"},
    "FITTING_WIP": {"product_code", "quantity"},
    "REGULAR_PRODUCT": {"product_code"},
    "WEEKLY_PLAN": {"product_code", "production_batch_no", "process_name", "equipment_name", "planned_quantity"},
}


class ImportValidationError(ValueError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def safe_filename(filename: str | None) -> str:
    name = Path(filename or "upload.xlsx").name
    cleaned = re.sub(r"[^\w.\-()\u4e00-\u9fff ]", "_", name, flags=re.UNICODE).strip(" .")
    return (cleaned or "upload.xlsx")[:255]


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def make_batch_no() -> str:
    return f"IMP-{datetime.now(UTC):%Y%m%d%H%M%S}-{hashlib.sha1(str(datetime.now(UTC).timestamp()).encode()).hexdigest()[:8].upper()}"


def load_safe_workbook(path: Path, *, read_only: bool = True):
    try:
        return load_workbook(path, read_only=read_only, data_only=False, keep_links=False)
    except Exception as exc:
        raise ImportValidationError("INVALID_WORKBOOK", "Excel 工作簿损坏、加密或无法解析") from exc


def row_has_value(row: Iterable[Cell]) -> bool:
    return any(cell.value not in (None, "") for cell in row)


def scan_effective_range(worksheet) -> dict[str, Any]:
    last_row = 0
    last_column = 0
    empty_run = 0
    first_row = 0
    scanned_rows = 0
    formula_count = 0
    external_formula_count = 0
    error_cell_count = 0
    for row_number, row in enumerate(worksheet.iter_rows(), start=1):
        scanned_rows = row_number
        nonempty_columns = [cell.column for cell in row if cell.value not in (None, "")]
        if nonempty_columns:
            first_row = first_row or row_number
            last_row = row_number
            last_column = max(last_column, max(nonempty_columns))
            empty_run = 0
            for cell in row:
                if cell.data_type == "f":
                    formula_count += 1
                    if "[" in str(cell.value):
                        external_formula_count += 1
                elif cell.data_type == "e":
                    error_cell_count += 1
        elif first_row:
            empty_run += 1
            if empty_run >= EMPTY_ROW_STOP:
                break
        if row_number >= MAX_SCAN_ROWS:
            break
    return {
        "first_row": first_row,
        "last_row": last_row,
        "last_column": last_column,
        "scanned_rows": scanned_rows,
        "formula_count": formula_count,
        "external_formula_count": external_formula_count,
        "error_cell_count": error_cell_count,
        "scan_truncated": scanned_rows >= MAX_SCAN_ROWS,
    }


def extract_sheet_structure(path: Path, worksheet) -> dict[str, Any]:
    hidden_rows: set[int] = set()
    hidden_columns: set[int] = set()
    merged_ranges: list[str] = []
    auto_filter_range: str | None = None
    worksheet_path = getattr(worksheet, "_worksheet_path", None)
    if not worksheet_path:
        return {"hidden_rows": hidden_rows, "hidden_columns": hidden_columns, "merged_ranges": merged_ranges, "auto_filter_range": auto_filter_range}
    with zipfile.ZipFile(path) as archive, archive.open(worksheet_path.lstrip("/")) as source:
        for _, element in iterparse(source, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "row" and element.attrib.get("hidden") in {"1", "true"}:
                hidden_rows.add(int(element.attrib["r"]))
            elif tag == "col" and element.attrib.get("hidden") in {"1", "true"}:
                hidden_columns.update(range(int(element.attrib["min"]), int(element.attrib["max"]) + 1))
            elif tag == "mergeCell" and element.attrib.get("ref"):
                merged_ranges.append(element.attrib["ref"])
            elif tag == "autoFilter":
                auto_filter_range = element.attrib.get("ref")
            element.clear()
    return {"hidden_rows": hidden_rows, "hidden_columns": hidden_columns, "merged_ranges": merged_ranges, "auto_filter_range": auto_filter_range}


def merged_cell_lookup(ranges: list[str]) -> dict[tuple[int, int], tuple[int, int]]:
    lookup: dict[tuple[int, int], tuple[int, int]] = {}
    for cell_range in ranges:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
        if (max_row - min_row + 1) * (max_col - min_col + 1) > 10_000:
            continue
        for row in range(min_row, max_row + 1):
            for column in range(min_col, max_col + 1):
                lookup[(row, column)] = (min_row, min_col)
    return lookup


def normalize_header(value: Any) -> str:
    return re.sub(r"[\s\n\r　]+", "", str(value or "")).lower()


def detect_header(rows: list[list[Any]], import_type: str) -> tuple[int, int, dict[str, int]]:
    fields = TYPE_FIELDS[import_type]
    best_end = 1
    best_score = -1
    for row_index, row in enumerate(rows[:12], start=1):
        normalized = [normalize_header(value) for value in row]
        score = sum(
            1
            for field in fields
            if any(normalize_header(alias) in header for alias in FIELD_SYNONYMS[field] for header in normalized if header)
        )
        if score > best_score:
            best_score = score
            best_end = row_index
    start = best_end
    if best_end > 1 and any(value not in (None, "") for value in rows[best_end - 2]):
        start = max(1, best_end - 2)
    combined_headers: dict[int, str] = {}
    width = max((len(row) for row in rows[start - 1 : best_end]), default=0)
    for column in range(width):
        parts: list[str] = []
        for row in rows[start - 1 : best_end]:
            if column < len(row) and row[column] not in (None, ""):
                value = str(row[column]).strip()
                if not parts or parts[-1] != value:
                    parts.append(value)
        combined_headers[column + 1] = " ".join(parts)
    return start, best_end, auto_mapping(combined_headers, import_type)


def auto_mapping(headers: dict[int, str], import_type: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    used_columns: set[int] = set()
    for field in TYPE_FIELDS[import_type]:
        aliases = tuple(normalize_header(item) for item in FIELD_SYNONYMS[field])
        for column, header in headers.items():
            normalized = normalize_header(header)
            if column not in used_columns and any(alias == normalized or alias in normalized for alias in aliases):
                mapping[field] = column
                used_columns.add(column)
                break
    return mapping


def analyze_workbook(path: Path, import_type: str, selected_sheet: str | None = None) -> dict[str, Any]:
    workbook = load_safe_workbook(path)
    try:
        if selected_sheet and selected_sheet not in workbook.sheetnames:
            raise ImportValidationError("SHEET_NOT_FOUND", "指定工作表不存在")
        sheet_results: list[dict[str, Any]] = []
        target_names = [selected_sheet] if selected_sheet else workbook.sheetnames
        for name in target_names:
            worksheet = workbook[name]
            effective = scan_effective_range(worksheet)
            structure = extract_sheet_structure(path, worksheet)
            preview_rows: list[list[Any]] = []
            for row in worksheet.iter_rows(min_row=1, max_row=min(max(effective["last_row"], 1), 12)):
                preview_rows.append([cell.value for cell in row[: max(effective["last_column"], 1)]])
            header_start, header_end, mapping = detect_header(preview_rows, import_type)
            detected_dates = sorted({parsed for row in preview_rows for value in row if (parsed := parse_date(value)) is not None})
            sheet_results.append(
                {
                    "sheet_name": name,
                    "declared_rows": worksheet.max_row,
                    "declared_columns": worksheet.max_column,
                    **effective,
                    "header_row_start": header_start,
                    "header_row_end": header_end,
                    "auto_mapping": mapping,
                    "preview_headers": preview_rows[:header_end],
                    "hidden_row_count": len(structure["hidden_rows"]),
                    "hidden_column_count": len(structure["hidden_columns"]),
                    "merged_ranges": structure["merged_ranges"],
                    "auto_filter_range": structure["auto_filter_range"],
                    "detected_date_start": detected_dates[0].isoformat() if detected_dates else None,
                    "detected_date_end": detected_dates[-1].isoformat() if detected_dates else None,
                }
            )
        periods = {(item["detected_date_start"], item["detected_date_end"]) for item in sheet_results if item["detected_date_start"]}
        return {"sheet_count": len(workbook.sheetnames), "sheet_names": workbook.sheetnames, "sheets": sheet_results, "plan_period_consistent": len(periods) <= 1}
    finally:
        workbook.close()


def normalize_product_code(cell: Cell) -> tuple[str | None, str | None]:
    value = cell.value
    if value in (None, ""):
        return None, "PRODUCT_CODE_REQUIRED"
    if isinstance(value, str):
        text = value.strip()
        if SCIENCE_PATTERN.fullmatch(text):
            return text, "PRODUCT_CODE_SCIENTIFIC_NOTATION"
        return text, None
    if isinstance(value, bool):
        return str(value), "PRODUCT_CODE_FORMAT_INVALID"
    if isinstance(value, (int, float, Decimal)):
        number_format = str(cell.number_format or "")
        zero_mask = re.fullmatch(r"0+", number_format)
        if zero_mask and float(value).is_integer():
            return str(int(value)).zfill(len(number_format)), None
        if isinstance(value, float) and not value.is_integer():
            return format(value, "f").rstrip("0").rstrip("."), "PRODUCT_CODE_NUMERIC_AMBIGUOUS"
        return str(int(value)), "PRODUCT_CODE_NUMERIC_AMBIGUOUS"
    return str(value).strip(), "PRODUCT_CODE_FORMAT_INVALID"


def parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            converted = from_excel(value)
            return converted.date() if isinstance(converted, datetime) else converted
        except (ValueError, OverflowError):
            return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%Y-%m", "%Y/%m", "%Y年%m月"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            return parsed.replace(day=1) if "%d" not in fmt else parsed
        except ValueError:
            continue
    return None


def issue(row: int, severity: str, field: str | None, raw: Any, code: str, message: str) -> dict[str, Any]:
    return {
        "excel_row_number": row,
        "severity": severity,
        "field_name": field,
        "raw_value": None if raw is None else str(raw)[:2000],
        "issue_code": code,
        "message": message,
    }


def mapped_cell(row: tuple[Cell, ...], mapping: dict[str, int], field: str) -> Cell | None:
    column = mapping.get(field)
    return row[column - 1] if column and column <= len(row) else None


def iter_normalized_rows(
    path: Path,
    batch: ImportBatch,
) -> Iterator[tuple[int, dict[str, Any], list[dict[str, Any]]]]:
    options = batch.import_options or {}
    sheet_name = batch.selected_sheet_name
    if not sheet_name:
        raise ImportValidationError("SHEET_REQUIRED", "请先选择工作表并完成分析")
    mapping = {key: int(value) for key, value in (batch.field_mapping or {}).items()}
    missing = sorted(REQUIRED_FIELDS[batch.import_type] - mapping.keys())
    if missing:
        raise ImportValidationError("MAPPING_REQUIRED", "缺少必填字段映射", {"fields": missing})
    if len(set(mapping.values())) != len(mapping.values()):
        raise ImportValidationError("DUPLICATE_FIELD_MAPPING", "一个 Excel 列不能映射到多个业务字段")
    workbook = load_safe_workbook(path)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ImportValidationError("SHEET_NOT_FOUND", "指定工作表不存在")
        worksheet = workbook[sheet_name]
        structure = extract_sheet_structure(path, worksheet)
        hidden_rows = structure["hidden_rows"]
        merged_lookup = merged_cell_lookup(structure["merged_ranges"])
        master_cells: dict[tuple[int, int], Cell] = {}
        header_end = int(options.get("header_row_end", 1))
        empty_run = 0
        seen_data = False
        for row_number, row in enumerate(worksheet.iter_rows(min_row=header_end + 1), start=header_end + 1):
            for column_number, cell in enumerate(row, start=1):
                coordinate = (row_number, column_number)
                if cell.value not in (None, "") and merged_lookup.get(coordinate, coordinate) == coordinate:
                    master_cells[coordinate] = cell
            if row_number in hidden_rows:
                continue
            if not row_has_value(row):
                if seen_data:
                    empty_run += 1
                    if empty_run >= EMPTY_ROW_STOP:
                        break
                    yield row_number, {}, [issue(row_number, "INFO", None, None, "BLANK_ROW_SKIPPED", "空白数据行已跳过")]
                continue
            seen_data = True
            empty_run = 0
            normalized: dict[str, Any] = {}
            problems: list[dict[str, Any]] = []
            for field in TYPE_FIELDS[batch.import_type]:
                cell = mapped_cell(row, mapping, field)
                column = mapping.get(field)
                if cell and cell.value in (None, "") and column:
                    master = merged_lookup.get((row_number, column))
                    if master:
                        cell = master_cells.get(master, cell)
                value = cell.value if cell else None
                if cell and cell.data_type == "e":
                    problems.append(issue(row_number, "ERROR", field, value, "EXCEL_ERROR_CELL", "Excel 错误单元格无法导入"))
                if cell and cell.data_type == "f":
                    severity = "ERROR" if "[" in str(value) else "WARNING"
                    code = "EXTERNAL_FORMULA_REFERENCE" if severity == "ERROR" else "FORMULA_VALUE_UNTRUSTED"
                    problems.append(issue(row_number, severity, field, value, code, "公式结果不作为可信业务值"))
                if field == "product_code" and cell:
                    code, code_problem = normalize_product_code(cell)
                    normalized[field] = code
                    if code_problem:
                        severity = "ERROR" if code_problem == "PRODUCT_CODE_SCIENTIFIC_NOTATION" else "WARNING"
                        problems.append(issue(row_number, severity, field, value, code_problem, "产品编码格式需要确认"))
                elif field.endswith("_date") or field == "shipment_month":
                    normalized[field] = parse_date(value)
                    if value not in (None, "") and normalized[field] is None:
                        problems.append(issue(row_number, "ERROR", field, value, "DATE_INVALID", "日期无法转换"))
                elif field in {"quantity", "on_hand_qty", "expected_inbound_qty", "expected_outbound_qty", "source_available_qty", "planned_quantity", "actual_quantity"}:
                    normalized[field] = parse_decimal(value)
                    weekly_actual = batch.import_type == "WEEKLY_PLAN" and "实际" in str(normalized.get("row_kind") or "")
                    if field in REQUIRED_FIELDS[batch.import_type] and normalized[field] is None and not (field == "planned_quantity" and weekly_actual):
                        problems.append(issue(row_number, "ERROR", field, value, "QUANTITY_INVALID", "数量为空或无法转换"))
                else:
                    normalized[field] = str(value).strip() if value not in (None, "") else None
            for field in REQUIRED_FIELDS[batch.import_type]:
                weekly_actual = batch.import_type == "WEEKLY_PLAN" and "实际" in str(normalized.get("row_kind") or "")
                if normalized.get(field) in (None, "") and not (field == "planned_quantity" and weekly_actual):
                    problems.append(issue(row_number, "ERROR", field, None, "REQUIRED_FIELD_MISSING", "必填字段为空"))
            if batch.import_type == "WEEKLY_PLAN" and "实际" in str(normalized.get("row_kind") or ""):
                if normalized.get("actual_quantity") is None:
                    normalized["actual_quantity"] = normalized.get("planned_quantity")
                normalized["planned_quantity"] = None
            quantity_field = "quantity" if "quantity" in normalized else "planned_quantity"
            quantity = normalized.get(quantity_field)
            if batch.import_type in {"SHIPMENT", "PIPE_WIP", "FITTING_WIP"} and quantity is not None and quantity < 0:
                problems.append(issue(row_number, "WARNING", quantity_field, quantity, "NEGATIVE_QUANTITY", "负数量保留原值，请人工确认"))
            if batch.import_type == "INVENTORY" and all(normalized.get(name) is not None for name in ("on_hand_qty", "expected_inbound_qty", "expected_outbound_qty")):
                calculated = normalized["on_hand_qty"] + normalized["expected_inbound_qty"] - normalized["expected_outbound_qty"]
                normalized["calculated_available_qty"] = calculated
                source = normalized.get("source_available_qty")
                if source is not None and source != calculated:
                    problems.append(issue(row_number, "WARNING", "source_available_qty", source, "AVAILABLE_QTY_MISMATCH", "Excel 可用量与系统复算值不一致"))
            if batch.import_type == "WEEKLY_PLAN" and normalized.get("plan_start_date") is None and normalized.get("plan_end_date") is None:
                problems.append(issue(row_number, "ERROR", "plan_start_date", None, "WEEKLY_PLAN_PERIOD_UNRECOGNIZED", "计划周期无法识别"))
            normalized["raw_data"] = {
                field: (value.isoformat() if isinstance(value, (date, datetime)) else str(value) if isinstance(value, Decimal) else value)
                for field, value in normalized.items()
                if field != "raw_data"
            }
            yield row_number, normalized, problems
            if row_number >= MAX_SCAN_ROWS:
                break
    finally:
        workbook.close()


def validate_batch(db: Session, batch: ImportBatch, path: Path) -> dict[str, Any]:
    db.execute(delete(ImportRowIssue).where(ImportRowIssue.import_batch_id == batch.id))
    total = 0
    valid = 0
    warning_rows: set[int] = set()
    error_rows: set[int] = set()
    seen_keys: set[tuple[Any, ...]] = set()
    product_identity: dict[str, tuple[str | None, str | None]] = {}
    weekly_plan_rows: dict[tuple[Any, ...], int] = {}
    weekly_actual_rows: dict[tuple[Any, ...], int] = {}
    issue_counts: Counter[str] = Counter()
    for row_number, normalized, problems in iter_normalized_rows(path, batch):
        if not normalized:
            for problem in problems:
                db.add(ImportRowIssue(import_batch_id=batch.id, sheet_name=batch.selected_sheet_name or "", **problem))
            continue
        total += 1
        code = normalized.get("product_code")
        identity = (normalized.get("product_name"), normalized.get("specification"))
        if code and code in product_identity and product_identity[code] != identity:
            problems.append(issue(row_number, "WARNING", "product_code", code, "PRODUCT_IDENTITY_CONFLICT", "同一编码的名称或规格不一致"))
        elif code:
            product_identity[code] = identity
        if batch.import_type == "SHIPMENT":
            key = (normalized.get("document_no"), code, normalized.get("shipment_date"), normalized.get("quantity"))
        elif batch.import_type == "FITTING_WIP":
            key = (code, normalized.get("production_batch_no"), normalized.get("quantity"))
        elif batch.import_type == "WEEKLY_PLAN":
            pair_key = (code, normalized.get("production_batch_no"), normalized.get("process_name"), normalized.get("equipment_name"))
            is_actual = "实际" in str(normalized.get("row_kind") or "")
            (weekly_actual_rows if is_actual else weekly_plan_rows)[pair_key] = row_number
            key = (*pair_key, "ACTUAL" if is_actual else "PLAN")
        else:
            key = (code,)
        if key in seen_keys:
            problems.append(issue(row_number, "ERROR", None, key, "DUPLICATE_ROW", "文件内部存在重复记录"))
        seen_keys.add(key)
        severities = {problem["severity"] for problem in problems}
        if "ERROR" in severities:
            error_rows.add(row_number)
        else:
            valid += 1
        if "WARNING" in severities:
            warning_rows.add(row_number)
        for problem in problems:
            issue_counts[problem["issue_code"]] += 1
            db.add(ImportRowIssue(import_batch_id=batch.id, sheet_name=batch.selected_sheet_name or "", **problem))
    if batch.import_type == "WEEKLY_PLAN":
        unpaired = {**{key: row for key, row in weekly_plan_rows.items() if key not in weekly_actual_rows}, **{key: row for key, row in weekly_actual_rows.items() if key not in weekly_plan_rows}}
        for pair_key, row_number in unpaired.items():
            if row_number not in error_rows:
                valid = max(0, valid - 1)
            error_rows.add(row_number)
            problem = issue(row_number, "ERROR", "row_kind", pair_key, "WEEKLY_PLAN_PAIR_MISSING", "计划行和实际行无法配对")
            issue_counts[problem["issue_code"]] += 1
            db.add(ImportRowIssue(import_batch_id=batch.id, sheet_name=batch.selected_sheet_name or "", **problem))
    batch.total_rows = total
    batch.valid_rows = valid
    batch.warning_rows = len(warning_rows)
    batch.error_rows = len(error_rows)
    batch.error_summary = dict(issue_counts)
    batch.status = "VALIDATION_FAILED" if error_rows else "READY"
    db.flush()
    return {"total_rows": total, "valid_rows": valid, "warning_rows": len(warning_rows), "error_rows": len(error_rows), "status": batch.status}


def get_or_create_product(db: Session, normalized: dict[str, Any], import_type: str) -> Product:
    product = db.scalar(select(Product).where(Product.product_code == normalized["product_code"]))
    if product is None:
        product = Product(
            product_code=normalized["product_code"],
            product_name=normalized.get("product_name"),
            specification=normalized.get("specification"),
            category=normalized.get("category"),
            unit=normalized.get("unit"),
            data_source=import_type,
        )
        db.add(product)
        db.flush()
    return product


def build_record(batch: ImportBatch, row_number: int, normalized: dict[str, Any], product: Product):
    common = {
        "import_batch_id": batch.id,
        "source_sheet": batch.selected_sheet_name or "",
        "source_row_number": row_number,
        "raw_data": normalized["raw_data"],
        "product_id": product.id,
    }
    if batch.import_type == "SHIPMENT":
        return ShipmentRecord(**common, document_no=normalized["document_no"], shipment_date=normalized["shipment_date"], shipment_month=normalized.get("shipment_month"), quantity=normalized["quantity"], production_batch_no=normalized.get("production_batch_no"))
    if batch.import_type == "INVENTORY":
        return InventorySnapshot(**common, snapshot_date=normalized.get("snapshot_date"), on_hand_qty=normalized["on_hand_qty"], expected_inbound_qty=normalized["expected_inbound_qty"], expected_outbound_qty=normalized["expected_outbound_qty"], source_available_qty=normalized.get("source_available_qty"), calculated_available_qty=normalized["calculated_available_qty"])
    if batch.import_type == "PIPE_WIP":
        return PipeWipSnapshot(**common, snapshot_date=normalized.get("snapshot_date"), quantity=normalized["quantity"])
    if batch.import_type == "FITTING_WIP":
        return FittingWipSnapshot(**common, snapshot_date=normalized.get("snapshot_date"), production_batch_no=normalized.get("production_batch_no"), quantity=normalized["quantity"])
    if batch.import_type == "REGULAR_PRODUCT":
        return RegularProductionProduct(**common)
    return ImportedWeeklyPlanRaw(**common, production_batch_no=normalized["production_batch_no"], process_name=normalized["process_name"], equipment_name=normalized["equipment_name"], plan_start_date=normalized.get("plan_start_date"), plan_end_date=normalized.get("plan_end_date"), planned_quantity=normalized["planned_quantity"], actual_quantity=normalized.get("actual_quantity"))


RECORD_MODELS = (ShipmentRecord, InventorySnapshot, PipeWipSnapshot, FittingWipSnapshot, RegularProductionProduct, ImportedWeeklyPlanRaw)


def import_validated_batch(db: Session, batch: ImportBatch, path: Path) -> int:
    if batch.status not in {"READY", "IMPORTING"} or batch.error_rows:
        raise ImportValidationError("IMPORT_NOT_READY", "批次存在错误或尚未完成校验")
    imported = 0
    parsed_rows = list(iter_normalized_rows(path, batch))
    weekly_actual: dict[tuple[Any, ...], Decimal | None] = {}
    if batch.import_type == "WEEKLY_PLAN":
        for _, normalized, problems in parsed_rows:
            if normalized and not any(item["severity"] == "ERROR" for item in problems) and "实际" in str(normalized.get("row_kind") or ""):
                key = (normalized.get("product_code"), normalized.get("production_batch_no"), normalized.get("process_name"), normalized.get("equipment_name"))
                weekly_actual[key] = normalized.get("actual_quantity")
    for row_number, normalized, problems in parsed_rows:
        if not normalized or any(item["severity"] == "ERROR" for item in problems):
            continue
        if batch.import_type == "WEEKLY_PLAN":
            if "实际" in str(normalized.get("row_kind") or ""):
                continue
            key = (normalized.get("product_code"), normalized.get("production_batch_no"), normalized.get("process_name"), normalized.get("equipment_name"))
            normalized["actual_quantity"] = weekly_actual.get(key, normalized.get("actual_quantity"))
        product = get_or_create_product(db, normalized, batch.import_type)
        db.add(build_record(batch, row_number, normalized, product))
        imported += 1
    db.flush()
    return imported


def delete_batch_records(db: Session, batch_id: int) -> None:
    for model in RECORD_MODELS:
        db.execute(delete(model).where(model.import_batch_id == batch_id))


def batch_has_downstream_references(db: Session, batch: ImportBatch) -> bool:
    # Stage 2 has no downstream production models. Future stages extend this guard
    # with explicit foreign-key reference checks before allowing rollback.
    return False

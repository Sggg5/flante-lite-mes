"""Generate and execute a fully synthetic large shipment import benchmark.

The generated workbook and isolated SQLite database are deleted by default.
No company/customer/product data is read by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a synthetic Excel import benchmark")
    parser.add_argument("--rows", type=int, default=268_000)
    parser.add_argument("--products", type=int, default=12_000)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--keep-artifacts", action="store_true")
    return parser.parse_args()


def synthetic_filler(index: int) -> str:
    return "".join(
        hashlib.sha256(f"flante-synthetic-{index}-{part}".encode()).hexdigest()
        for part in range(3)
    )[:152]


def generate_workbook(path: Path, row_count: int, product_count: int) -> float:
    started = time.perf_counter()
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("虚拟销售数据")
    sheet.append(["产品编码", "产品名称", "规格", "出库单号", "出库日期", "出库数量", "生产批次号", "虚拟填充"])
    base_date = date(2026, 1, 1)
    for index in range(row_count):
        product_index = index % product_count
        sheet.append([
            f"SYNTHETIC-P{product_index:05d}",
            f"虚拟产品-{product_index:05d}",
            f"SYN-{product_index % 200:03d}",
            f"SYNTHETIC-DOC-{index:09d}",
            base_date + timedelta(days=index % 180),
            (index % 97) + 1,
            f"SYNTHETIC-LOT-{index % 5000:05d}",
            synthetic_filler(index),
        ])
    workbook.save(path)
    workbook.close()
    return time.perf_counter() - started


def peak_rss_mb() -> float:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        get_process_memory_info.restype = wintypes.BOOL
        process = get_current_process()
        if not get_process_memory_info(process, ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return counters.PeakWorkingSetSize / (1024 * 1024)
    import resource
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return maximum / 1024 if sys.platform != "darwin" else maximum / (1024 * 1024)


def require_success(response, operation: str) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"{operation} failed: HTTP {response.status_code} {response.text[:1000]}")
    return response.json()


def write_report(path: Path, metrics: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# 阶段2大文件导入性能基准

本报告由 `backend/scripts/benchmark_large_import.py` 使用完全虚拟数据生成。产品编码、单号、批次、日期和数量均为脚本构造，不包含任何真实公司数据；生成的大型 XLSX 与隔离数据库未提交仓库。

## 实测环境与规模

- 执行时间：{metrics['executed_at']}
- Python：{metrics['python_version']}
- 数据库：隔离 SQLite（功能与内存基线；PostgreSQL/Docker 由 CI 验证）
- 虚拟销售记录：{metrics['requested_rows']:,} 行
- 虚拟产品编码：{metrics['requested_products']:,} 个
- 生成文件：{metrics['file_size_mb']:.2f} MB

## 实测结果

| 阶段 | 耗时（秒） |
|---|---:|
| 生成虚拟 XLSX | {metrics['generate_seconds']:.2f} |
| 上传（含流式 SHA-256 与工作簿安全验证） | {metrics['upload_seconds']:.2f} |
| 工作表分析与字段识别 | {metrics['analyze_seconds']:.2f} |
| 全量校验 | {metrics['validate_seconds']:.2f} |
| 确认导入 | {metrics['confirm_seconds']:.2f} |
| 查询与数量核对 | {metrics['query_seconds']:.2f} |
| 撤销测试批次 | {metrics['rollback_seconds']:.2f} |
| API 流程总耗时（不含文件生成） | {metrics['api_total_seconds']:.2f} |

- 操作系统记录的进程峰值 RSS：{metrics['peak_memory_mb']:.2f} MB
- 导入业务记录：{metrics['shipment_records']:,}
- 导入产品：{metrics['product_records']:,}
- 重复业务行：{metrics['duplicate_business_rows']:,}
- 撤销后业务记录：{metrics['remaining_shipments_after_rollback']:,}
- 撤销后本批次新建产品：{metrics['remaining_products_after_rollback']:,}

## 结论与边界

本次实测覆盖上传、分析、字段识别、全量校验、确认、结果核对和撤销，行数达到实际业务规模。确认路径不保留全量标准化行列表，产品目录一次加载，业务记录以 2,000 行为块执行 flush/批量插入且仅最终 commit。该结果是当前机器上的 SQLite 基线，不等价于所有部署环境的 SLA；生产 PostgreSQL、磁盘和容器资源仍应持续监控。
"""
    path.write_text(content, encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.rows < 1 or args.products < 1 or args.products > args.rows:
        raise SystemExit("rows/products must be positive and products cannot exceed rows")

    artifact_dir = Path(tempfile.mkdtemp(prefix="flante-large-import-"))
    workbook_path = artifact_dir / "synthetic-large-import.xlsx"
    database_path = artifact_dir / "benchmark.db"
    storage_dir = artifact_dir / "imports"
    os.environ.update({
        "APP_ENV": "test",
        "SECRET_KEY": "synthetic-benchmark-secret-key-more-than-32-characters",
        "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
        "IMPORT_STORAGE_DIR": str(storage_dir),
        "IMPORT_MAX_FILE_SIZE_MB": "64",
    })

    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app.core.database import Base, SessionLocal, engine
    from app.main import app
    from app.models import ImportBatch, Product, ShipmentRecord
    from app.services.identity import seed_identity

    total_started = time.perf_counter()
    generate_seconds = generate_workbook(workbook_path, args.rows, args.products)
    file_size_mb = workbook_path.stat().st_size / (1024 * 1024)

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_identity(db, "admin", "SyntheticBenchmark123!")

    timings: dict[str, float] = {}
    try:
        with TestClient(app) as client:
            login = require_success(client.post("/api/v1/auth/login", json={"username": "admin", "password": "SyntheticBenchmark123!"}), "login")
            headers = {"Authorization": f"Bearer {login['access_token']}"}

            started = time.perf_counter()
            with workbook_path.open("rb") as source:
                uploaded = require_success(client.post(
                    "/api/v1/imports/upload",
                    headers=headers,
                    data={"import_type": "SHIPMENT"},
                    files={"file": (workbook_path.name, source, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                ), "upload")
            timings["upload_seconds"] = time.perf_counter() - started
            batch_id = uploaded["id"]

            started = time.perf_counter()
            analyzed = require_success(client.post(
                f"/api/v1/imports/{batch_id}/analyze", headers=headers, json={"sheet_name": "虚拟销售数据"}
            ), "analyze")
            timings["analyze_seconds"] = time.perf_counter() - started
            if not {"product_code", "document_no", "shipment_date", "quantity"}.issubset(analyzed["field_mapping"]):
                raise RuntimeError(f"field recognition incomplete: {analyzed['field_mapping']}")

            started = time.perf_counter()
            validated = require_success(client.post(f"/api/v1/imports/{batch_id}/validate", headers=headers), "validate")
            timings["validate_seconds"] = time.perf_counter() - started
            if validated["status"] != "READY" or validated["valid_rows"] != args.rows:
                raise RuntimeError(f"validation mismatch: {validated['status']} / {validated['valid_rows']}")

            started = time.perf_counter()
            confirmed = require_success(client.post(f"/api/v1/imports/{batch_id}/confirm", headers=headers), "confirm")
            timings["confirm_seconds"] = time.perf_counter() - started
            if confirmed["status"] != "COMPLETED" or confirmed["imported_rows"] != args.rows:
                raise RuntimeError(f"confirmation mismatch: {confirmed}")

            started = time.perf_counter()
            detail = require_success(client.get(f"/api/v1/imports/{batch_id}", headers=headers), "query batch")
            with SessionLocal() as db:
                shipment_records = db.scalar(select(func.count(ShipmentRecord.id)).where(ShipmentRecord.import_batch_id == batch_id)) or 0
                product_records = db.scalar(select(func.count(Product.id)).where(Product.product_code.like("SYNTHETIC-P%"))) or 0
                unique_source_rows = db.scalar(select(func.count(func.distinct(ShipmentRecord.source_row_number))).where(ShipmentRecord.import_batch_id == batch_id)) or 0
            duplicate_business_rows = shipment_records - unique_source_rows
            timings["query_seconds"] = time.perf_counter() - started
            if detail["imported_rows"] != args.rows or shipment_records != args.rows or product_records != args.products or duplicate_business_rows:
                raise RuntimeError("database count verification failed")

            started = time.perf_counter()
            rolled_back = require_success(client.post(
                f"/api/v1/imports/{batch_id}/rollback", headers=headers, json={"reason": "虚拟大文件基准结束后撤销"}
            ), "rollback")
            timings["rollback_seconds"] = time.perf_counter() - started
            if rolled_back["status"] != "ROLLED_BACK":
                raise RuntimeError("rollback status mismatch")
            with SessionLocal() as db:
                remaining_shipments = db.scalar(select(func.count(ShipmentRecord.id)).where(ShipmentRecord.import_batch_id == batch_id)) or 0
                remaining_products = db.scalar(select(func.count(Product.id)).where(Product.product_code.like("SYNTHETIC-P%"))) or 0
                batch = db.get(ImportBatch, batch_id)
                if batch is None or batch.status != "ROLLED_BACK":
                    raise RuntimeError("rollback persistence check failed")

        metrics = {
            "executed_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "python_version": sys.version.split()[0],
            "requested_rows": args.rows,
            "requested_products": args.products,
            "file_size_mb": file_size_mb,
            "generate_seconds": generate_seconds,
            **timings,
            "api_total_seconds": sum(timings.values()),
            "wall_total_seconds": time.perf_counter() - total_started,
            "peak_memory_mb": peak_rss_mb(),
            "shipment_records": shipment_records,
            "product_records": product_records,
            "duplicate_business_rows": duplicate_business_rows,
            "remaining_shipments_after_rollback": remaining_shipments,
            "remaining_products_after_rollback": remaining_products,
        }
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        if args.report:
            write_report(args.report.resolve(), metrics)
        return 0
    finally:
        engine.dispose()
        if not args.keep_artifacts:
            import shutil
            shutil.rmtree(artifact_dir, ignore_errors=True)
        else:
            print(f"artifacts retained at: {artifact_dir}")


if __name__ == "__main__":
    raise SystemExit(main())

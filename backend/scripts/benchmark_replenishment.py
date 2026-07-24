"""Run the Phase 3 replenishment benchmark with entirely synthetic business data.

The script writes only to an isolated temporary SQLite database. Product codes,
documents, quantities and batches are generated and do not originate from company data.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path


def peak_rss_mb() -> float:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess; get_current_process.restype = wintypes.HANDLE
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]; get_memory.restype = wintypes.BOOL
        if not get_memory(get_current_process(), ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return counters.PeakWorkingSetSize / (1024 * 1024)
    import resource
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return maximum / 1024 if sys.platform != "darwin" else maximum / (1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shipments", type=int, default=268_000)
    parser.add_argument("--products", type=int, default=12_000)
    parser.add_argument("--regular-products", type=int, default=2_210)
    parser.add_argument("--chunk-size", type=int, default=2_000)
    args = parser.parse_args()
    started = time.perf_counter()
    temporary = tempfile.TemporaryDirectory(prefix="flante-phase3-benchmark-")
    db_path = Path(temporary.name) / "benchmark.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["APP_ENV"] = "benchmark"
    os.environ["SECRET_KEY"] = "benchmark-only-secret-key-over-thirty-two-characters"

    from sqlalchemy import func, select, update
    from app.core.database import Base, SessionLocal, engine
    from app.models import (
        FittingWipSnapshot, ImportBatch, InventorySnapshot, PipeWipSnapshot, Product,
        ProductionDemand, RegularProductionProduct, ReplenishmentRun, ReplenishmentSuggestion,
        ShipmentRecord,
    )
    from app.services.identity import seed_identity
    from app.services.replenishment import calculate_run, canonical_fingerprint, convert_suggestions

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        admin = seed_identity(db, "benchmark-admin", "BenchmarkOnly123!")
        def make_batch(import_type: str, number: int, source_date: date) -> ImportBatch:
            item = ImportBatch(batch_no=f"BENCH-{import_type}-{number}", import_type=import_type, original_filename="synthetic-not-stored.xlsx", stored_filename=f"synthetic-{number}.xlsx", file_sha256=f"{number:064x}", source_date=source_date, file_size=0, status="COMPLETED", imported_rows=1, created_by=admin.id, confirmed_by=admin.id, confirmed_at=datetime.now(UTC), import_options={})
            db.add(item); db.flush(); return item
        shipment = make_batch("SHIPMENT", 1, date(2026, 6, 30)); inventory = make_batch("INVENTORY", 2, date(2026, 7, 10)); pipe = make_batch("PIPE_WIP", 3, date(2026, 7, 10)); fitting = make_batch("FITTING_WIP", 4, date(2026, 7, 10)); regular = make_batch("REGULAR_PRODUCT", 5, date(2026, 7, 10))
        batch_ids = {"shipment": shipment.id, "inventory": inventory.id, "pipe": pipe.id, "fitting": fitting.id, "regular": regular.id}
        db.commit()

        seed_started = time.perf_counter()
        now = datetime.now(UTC)
        for offset in range(0, args.products, args.chunk_size):
            db.execute(Product.__table__.insert(), [{"product_code": f"BENCH-P-{index:05d}", "product_name": f"虚拟产品{index:05d}", "is_active": True, "data_source": "BENCHMARK", "created_at": now, "updated_at": now} for index in range(offset, min(args.products, offset + args.chunk_size))])
        db.commit()
        product_ids = list(db.scalars(select(Product.id).order_by(Product.id)))
        imported_base = {"source_sheet": "完全虚拟基准", "raw_data": {"synthetic": True}, "created_at": now, "updated_at": now}
        for offset in range(0, args.regular_products, args.chunk_size):
            ids = product_ids[offset:min(args.regular_products, offset + args.chunk_size)]
            db.execute(RegularProductionProduct.__table__.insert(), [{**imported_base, "import_batch_id": batch_ids["regular"], "source_row_number": offset + index + 2, "product_id": product_id} for index, product_id in enumerate(ids)])
            db.execute(InventorySnapshot.__table__.insert(), [{**imported_base, "import_batch_id": batch_ids["inventory"], "source_row_number": offset + index + 2, "product_id": product_id, "snapshot_date": date(2026, 7, 10), "on_hand_qty": Decimal("300"), "expected_inbound_qty": Decimal("0"), "expected_outbound_qty": Decimal("0"), "source_available_qty": Decimal("300"), "calculated_available_qty": Decimal("300")} for index, product_id in enumerate(ids)])
            db.execute(PipeWipSnapshot.__table__.insert(), [{**imported_base, "import_batch_id": batch_ids["pipe"], "source_row_number": offset + index + 2, "product_id": product_id, "snapshot_date": date(2026, 7, 10), "quantity": Decimal("100")} for index, product_id in enumerate(ids)])
            db.execute(FittingWipSnapshot.__table__.insert(), [{**imported_base, "import_batch_id": batch_ids["fitting"], "source_row_number": offset + index + 2, "product_id": product_id, "snapshot_date": date(2026, 7, 10), "production_batch_no": f"BENCH-L-{offset + index:05d}", "quantity": Decimal("100")} for index, product_id in enumerate(ids)])
        db.commit()
        for offset in range(0, args.shipments, args.chunk_size):
            rows = []
            for row_index in range(offset, min(args.shipments, offset + args.chunk_size)):
                product_id = product_ids[row_index % args.products]
                month = row_index % 6 + 1
                day = 1 if row_index == 0 else (30 if row_index == args.shipments - 1 else 15)
                if month == 2 and day == 30: day = 28
                rows.append({**imported_base, "import_batch_id": batch_ids["shipment"], "source_row_number": row_index + 2, "product_id": product_id, "document_no": f"BENCH-DOC-{row_index:09d}", "shipment_date": date(2026, month, day), "shipment_month": date(2026, month, 1), "quantity": Decimal("1000"), "production_batch_no": f"BENCH-B-{row_index % 10000:05d}"})
            db.execute(ShipmentRecord.__table__.insert(), rows)
            db.commit()
        seed_seconds = time.perf_counter() - seed_started

        run = ReplenishmentRun(run_no="RR-BENCHMARK", calculation_date=date(2026, 7, 15), shipment_batch_id=batch_ids["shipment"], inventory_batch_id=batch_ids["inventory"], pipe_wip_batch_id=batch_ids["pipe"], fitting_wip_batch_id=batch_ids["fitting"], regular_product_batch_id=batch_ids["regular"], weekly_plan_batch_id=None, input_fingerprint=canonical_fingerprint(batch_ids), source_snapshot={"synthetic": True, "batches": batch_ids}, status="DRAFT", created_by=admin.id)
        db.add(run); db.commit()
        calculate_started = time.perf_counter(); calculate_run(db, run); db.commit(); calculate_seconds = time.perf_counter() - calculate_started
        query_started = time.perf_counter()
        suggestions = list(db.scalars(select(ReplenishmentSuggestion).where(ReplenishmentSuggestion.run_id == run.id, ReplenishmentSuggestion.system_suggested_qty > 0)))
        suggestion_count = db.scalar(select(func.count(ReplenishmentSuggestion.id)).where(ReplenishmentSuggestion.run_id == run.id)) or 0
        query_seconds = time.perf_counter() - query_started
        review_started = time.perf_counter()
        db.execute(update(ReplenishmentSuggestion).where(ReplenishmentSuggestion.id.in_([item.id for item in suggestions])).values(review_status="ACCEPTED", confirmed_qty=ReplenishmentSuggestion.system_suggested_qty, reviewed_by=admin.id, reviewed_at=datetime.now(UTC)))
        run.status = "APPROVED"; run.approved_by = admin.id; run.approved_at = datetime.now(UTC)
        db.commit(); review_seconds = time.perf_counter() - review_started
        convert_started = time.perf_counter(); convert_suggestions(db, run, [item.id for item in suggestions], admin.id); db.commit(); convert_seconds = time.perf_counter() - convert_started
        demand_count = db.scalar(select(func.count(ProductionDemand.id))) or 0
        duplicate_demands = db.scalar(select(func.count()).select_from(select(ProductionDemand.source_suggestion_id).group_by(ProductionDemand.source_suggestion_id).having(func.count() > 1).subquery())) or 0
        total_seconds = time.perf_counter() - started
        peak_mb = peak_rss_mb()
        print(json_output := {
            "shipments": args.shipments, "catalog_products": args.products, "regular_products": args.regular_products,
            "suggestions": suggestion_count, "positive_suggestions": len(suggestions), "demands": demand_count,
            "duplicate_demands": duplicate_demands, "seed_seconds": round(seed_seconds, 2),
            "calculate_seconds": round(calculate_seconds, 2), "query_seconds": round(query_seconds, 2),
            "review_seconds": round(review_seconds, 2), "convert_seconds": round(convert_seconds, 2),
            "total_seconds": round(total_seconds, 2), "peak_rss_mb": round(peak_mb, 2),
            "database_size_mb": round(db_path.stat().st_size / 1024 / 1024, 2),
        })
        assert suggestion_count == args.regular_products
        assert demand_count == len(suggestions)
        assert duplicate_demands == 0
    engine.dispose()
    temporary.cleanup()


if __name__ == "__main__":
    main()

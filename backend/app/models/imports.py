from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.identity import TimestampMixin


class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    import_type: Mapped[str] = mapped_column(String(40), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(100), unique=True)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    file_size: Mapped[int]
    workbook_sheet_count: Mapped[int] = mapped_column(default=0)
    selected_sheet_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), index=True, default="UPLOADED")
    total_rows: Mapped[int] = mapped_column(default=0)
    valid_rows: Mapped[int] = mapped_column(default=0)
    warning_rows: Mapped[int] = mapped_column(default=0)
    error_rows: Mapped[int] = mapped_column(default=0)
    imported_rows: Mapped[int] = mapped_column(default=0)
    field_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    import_options: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    creator = relationship("User", foreign_keys=[created_by])
    issues: Mapped[list["ImportRowIssue"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportRowIssue(Base, TimestampMixin):
    __tablename__ = "import_row_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(255))
    excel_row_number: Mapped[int] = mapped_column(index=True)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    field_name: Mapped[str | None] = mapped_column(String(100))
    raw_value: Mapped[str | None] = mapped_column(Text)
    issue_code: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)

    batch: Mapped[ImportBatch] = relationship(back_populates="issues")


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    product_name: Mapped[str | None] = mapped_column(String(255))
    specification: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(default=True)
    data_source: Mapped[str] = mapped_column(String(40), default="EXCEL_IMPORT")


class ImportedRecordMixin(TimestampMixin):
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    source_sheet: Mapped[str] = mapped_column(String(255))
    source_row_number: Mapped[int]
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON)


class ShipmentRecord(Base, ImportedRecordMixin):
    __tablename__ = "shipment_records"
    __table_args__ = (UniqueConstraint("import_batch_id", "source_sheet", "source_row_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    document_no: Mapped[str] = mapped_column(String(100), index=True)
    shipment_date: Mapped[date] = mapped_column(Date)
    shipment_month: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    production_batch_no: Mapped[str | None] = mapped_column(String(100))


class InventorySnapshot(Base, ImportedRecordMixin):
    __tablename__ = "inventory_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    snapshot_date: Mapped[date | None] = mapped_column(Date, index=True)
    on_hand_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    expected_inbound_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    expected_outbound_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    source_available_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    calculated_available_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class PipeWipSnapshot(Base, ImportedRecordMixin):
    __tablename__ = "pipe_wip_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    snapshot_date: Mapped[date | None] = mapped_column(Date, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class FittingWipSnapshot(Base, ImportedRecordMixin):
    __tablename__ = "fitting_wip_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    snapshot_date: Mapped[date | None] = mapped_column(Date, index=True)
    production_batch_no: Mapped[str | None] = mapped_column(String(100), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class RegularProductionProduct(Base, ImportedRecordMixin):
    __tablename__ = "regular_production_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)


class ImportedWeeklyPlanRaw(Base, ImportedRecordMixin):
    __tablename__ = "imported_weekly_plan_raw"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    production_batch_no: Mapped[str] = mapped_column(String(100), index=True)
    process_name: Mapped[str] = mapped_column(String(100))
    equipment_name: Mapped[str] = mapped_column(String(100))
    plan_start_date: Mapped[date | None] = mapped_column(Date)
    plan_end_date: Mapped[date | None] = mapped_column(Date)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    actual_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

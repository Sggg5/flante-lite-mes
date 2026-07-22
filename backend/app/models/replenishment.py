from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, JSON, Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import TimestampMixin


QTY = Numeric(18, 6)


class ReplenishmentPolicy(Base, TimestampMixin):
    __tablename__ = "replenishment_policies"
    __table_args__ = (
        CheckConstraint("fixed_target_qty IS NULL OR fixed_target_qty >= 0", name="ck_replenishment_policy_fixed_target_nonnegative"),
        CheckConstraint("min_batch_qty IS NULL OR min_batch_qty > 0", name="ck_replenishment_policy_min_batch_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), unique=True, index=True)
    algorithm: Mapped[str] = mapped_column(String(40), default="SIX_MONTH_MAX", index=True)
    rounding_mode: Mapped[str] = mapped_column(String(30), default="NONE")
    fixed_target_qty: Mapped[Decimal | None] = mapped_column(QTY)
    six_month_weights: Mapped[list[str] | None] = mapped_column(JSON)
    min_batch_qty: Mapped[Decimal | None] = mapped_column(QTY)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ReplenishmentRun(Base, TimestampMixin):
    __tablename__ = "replenishment_runs"
    __table_args__ = (
        Index("ix_replenishment_runs_fingerprint_status", "input_fingerprint", "status"),
        CheckConstraint("default_fixed_target_qty IS NULL OR default_fixed_target_qty >= 0", name="ck_replenishment_run_fixed_target_nonnegative"),
        CheckConstraint("default_min_batch_qty IS NULL OR default_min_batch_qty > 0", name="ck_replenishment_run_min_batch_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    calculation_date: Mapped[date] = mapped_column(Date, index=True)
    shipment_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    inventory_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    pipe_wip_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    fitting_wip_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    regular_product_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    weekly_plan_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    formula_version: Mapped[str] = mapped_column(String(30), default="PHASE3_V1")
    default_algorithm: Mapped[str] = mapped_column(String(40), default="SIX_MONTH_MAX")
    default_weight_config: Mapped[list[str] | None] = mapped_column(JSON)
    default_fixed_target_qty: Mapped[Decimal | None] = mapped_column(QTY)
    rounding_mode: Mapped[str] = mapped_column(String(30), default="NONE")
    default_min_batch_qty: Mapped[Decimal | None] = mapped_column(QTY)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_date_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    calculation_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    override_reason: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    total_products: Mapped[int] = mapped_column(default=0)
    suggestion_count: Mapped[int] = mapped_column(default=0)
    positive_suggestion_count: Mapped[int] = mapped_column(default=0)
    pending_review_count: Mapped[int] = mapped_column(default=0)
    reviewed_count: Mapped[int] = mapped_column(default=0)
    blocking_issue_count: Mapped[int] = mapped_column(default=0)
    warning_issue_count: Mapped[int] = mapped_column(default=0)
    warning_count: Mapped[int] = mapped_column(default=0)
    approved_count: Mapped[int] = mapped_column(default=0)
    converted_count: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)


class ReplenishmentSuggestion(Base, TimestampMixin):
    __tablename__ = "replenishment_suggestions"
    __table_args__ = (
        UniqueConstraint("run_id", "product_id", name="uq_replenishment_suggestion_run_product"),
        CheckConstraint("confirmed_qty IS NULL OR confirmed_qty >= 0", name="ck_replenishment_suggestion_confirmed_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("replenishment_runs.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    algorithm: Mapped[str] = mapped_column(String(40), index=True)
    algorithm_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    monthly_qty_json: Mapped[dict[str, str]] = mapped_column(JSON)
    monthly_shipments: Mapped[dict[str, str]] = mapped_column(JSON)
    six_month_max: Mapped[Decimal] = mapped_column(QTY)
    six_month_avg: Mapped[Decimal] = mapped_column(QTY)
    three_month_avg: Mapped[Decimal] = mapped_column(QTY)
    weighted_avg: Mapped[Decimal] = mapped_column(QTY)
    order_input_qty: Mapped[Decimal] = mapped_column(QTY)
    fixed_target_qty: Mapped[Decimal | None] = mapped_column(QTY)
    calculated_target_qty: Mapped[Decimal] = mapped_column(QTY)
    target_stock_qty: Mapped[Decimal] = mapped_column(QTY)
    on_hand_qty: Mapped[Decimal] = mapped_column(QTY)
    expected_inbound_qty: Mapped[Decimal] = mapped_column(QTY)
    expected_outbound_qty: Mapped[Decimal] = mapped_column(QTY)
    available_qty: Mapped[Decimal] = mapped_column(QTY)
    pipe_wip_raw_qty: Mapped[Decimal] = mapped_column(QTY)
    pipe_wip_effective_qty: Mapped[Decimal] = mapped_column(QTY)
    fitting_wip_raw_qty: Mapped[Decimal] = mapped_column(QTY)
    fitting_wip_effective_qty: Mapped[Decimal] = mapped_column(QTY)
    scheduled_not_started_qty: Mapped[Decimal] = mapped_column(QTY)
    scheduled_known_qty: Mapped[Decimal] = mapped_column(QTY)
    scheduled_override_qty: Mapped[Decimal] = mapped_column(QTY)
    scheduled_source_status: Mapped[str] = mapped_column(String(30), default="NONE")
    raw_suggested_qty: Mapped[Decimal] = mapped_column(QTY)
    system_suggested_qty: Mapped[Decimal] = mapped_column(QTY)
    confirmed_qty: Mapped[Decimal | None] = mapped_column(QTY)
    review_status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    change_reason: Mapped[str | None] = mapped_column(Text)
    converted_demand_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "production_demands.id", ondelete="SET NULL",
            name="fk_replenishment_suggestions_converted_demand_id", use_alter=True,
        ),
        index=True,
    )


class ReplenishmentIssue(Base, TimestampMixin):
    __tablename__ = "replenishment_issues"
    __table_args__ = (Index("ix_replenishment_issues_run_severity_status", "run_id", "severity", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("replenishment_runs.id", ondelete="CASCADE"), index=True)
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("replenishment_suggestions.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    issue_code: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class ReplenishmentOrderInput(Base, TimestampMixin):
    __tablename__ = "replenishment_order_inputs"
    __table_args__ = (
        UniqueConstraint("run_id", "product_id", name="uq_replenishment_order_run_product"),
        CheckConstraint("order_qty >= 0", name="ck_replenishment_order_qty_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("replenishment_runs.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    order_qty: Mapped[Decimal] = mapped_column(QTY)
    source_document_no: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class ProductionDemand(Base, TimestampMixin):
    __tablename__ = "production_demands"
    __table_args__ = (
        CheckConstraint("confirmed_qty > 0", name="ck_production_demand_confirmed_positive"),
        CheckConstraint("active_allocated_qty >= 0", name="ck_production_demand_allocated_nonnegative"),
        CheckConstraint("qualified_completed_qty >= 0", name="ck_production_demand_completed_nonnegative"),
        CheckConstraint("remaining_to_schedule_qty >= 0", name="ck_production_demand_remaining_schedule_nonnegative"),
        CheckConstraint("remaining_to_complete_qty >= 0", name="ck_production_demand_remaining_complete_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    demand_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    source_type: Mapped[str] = mapped_column(String(30), default="REPLENISHMENT")
    source_suggestion_id: Mapped[int] = mapped_column(
        ForeignKey("replenishment_suggestions.id", ondelete="RESTRICT"), unique=True, index=True
    )
    confirmed_qty: Mapped[Decimal] = mapped_column(QTY)
    active_allocated_qty: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    qualified_completed_qty: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    remaining_to_schedule_qty: Mapped[Decimal] = mapped_column(QTY)
    remaining_to_complete_qty: Mapped[Decimal] = mapped_column(QTY)
    priority: Mapped[int] = mapped_column(default=0)
    required_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="PENDING_SCHEDULE", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""Add replenishment calculation and minimal production demand pool.

Revision ID: 20260718_0005
Revises: 20260718_0004
Create Date: 2026-07-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0005"
down_revision: Union[str, None] = "20260718_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    qty = sa.Numeric(18, 6)
    op.create_index("ix_shipment_records_batch_product_date", "shipment_records", ["import_batch_id", "product_id", "shipment_date"])
    op.create_index("ix_inventory_snapshots_batch_product", "inventory_snapshots", ["import_batch_id", "product_id"])
    op.create_index("ix_pipe_wip_snapshots_batch_product", "pipe_wip_snapshots", ["import_batch_id", "product_id"])
    op.create_index("ix_fitting_wip_snapshots_batch_product", "fitting_wip_snapshots", ["import_batch_id", "product_id"])
    op.create_index("ix_regular_products_batch_product", "regular_production_products", ["import_batch_id", "product_id"])
    op.create_index("ix_weekly_plan_batch_product_period", "imported_weekly_plan_raw", ["import_batch_id", "product_id", "plan_start_date", "plan_end_date"])

    op.create_table(
        "replenishment_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("algorithm", sa.String(40), nullable=False),
        sa.Column("rounding_mode", sa.String(30), nullable=False),
        sa.Column("fixed_target_qty", qty),
        sa.Column("six_month_weights", sa.JSON()),
        sa.Column("min_batch_qty", qty),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *timestamps(),
        sa.UniqueConstraint("product_id"),
    )
    op.create_index(op.f("ix_replenishment_policies_product_id"), "replenishment_policies", ["product_id"], unique=True)
    op.create_index(op.f("ix_replenishment_policies_algorithm"), "replenishment_policies", ["algorithm"])

    op.create_table(
        "replenishment_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_no", sa.String(40), nullable=False, unique=True),
        sa.Column("calculation_date", sa.Date(), nullable=False),
        sa.Column("shipment_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("inventory_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipe_wip_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("fitting_wip_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("regular_product_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("weekly_plan_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id", ondelete="RESTRICT")),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("formula_version", sa.String(30), nullable=False),
        sa.Column("default_algorithm", sa.String(40), nullable=False),
        sa.Column("default_weight_config", sa.JSON()),
        sa.Column("default_fixed_target_qty", qty),
        sa.Column("rounding_mode", sa.String(30), nullable=False),
        sa.Column("default_min_batch_qty", qty),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_date_summary", sa.JSON(), nullable=False),
        sa.Column("calculation_config", sa.JSON(), nullable=False),
        sa.Column("override_reason", sa.Text()),
        sa.Column("error_summary", sa.JSON()),
        sa.Column("total_products", sa.Integer(), nullable=False),
        sa.Column("suggestion_count", sa.Integer(), nullable=False),
        sa.Column("positive_suggestion_count", sa.Integer(), nullable=False),
        sa.Column("pending_review_count", sa.Integer(), nullable=False),
        sa.Column("reviewed_count", sa.Integer(), nullable=False),
        sa.Column("blocking_issue_count", sa.Integer(), nullable=False),
        sa.Column("warning_issue_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("approved_count", sa.Integer(), nullable=False),
        sa.Column("converted_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.Text()),
        *timestamps(),
    )
    for name in ["run_no", "calculation_date", "shipment_batch_id", "inventory_batch_id", "pipe_wip_batch_id", "fitting_wip_batch_id", "regular_product_batch_id", "weekly_plan_batch_id", "input_fingerprint", "status", "created_by"]:
        op.create_index(op.f(f"ix_replenishment_runs_{name}"), "replenishment_runs", [name], unique=name == "run_no")
    op.create_index("ix_replenishment_runs_fingerprint_status", "replenishment_runs", ["input_fingerprint", "status"])

    op.create_table(
        "replenishment_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("replenishment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("algorithm", sa.String(40), nullable=False),
        sa.Column("algorithm_config", sa.JSON(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("monthly_qty_json", sa.JSON(), nullable=False),
        sa.Column("monthly_shipments", sa.JSON(), nullable=False),
        *[sa.Column(name, qty, nullable=False) for name in ["six_month_max", "six_month_avg", "three_month_avg", "weighted_avg", "order_input_qty", "calculated_target_qty", "target_stock_qty", "on_hand_qty", "expected_inbound_qty", "expected_outbound_qty", "available_qty", "pipe_wip_raw_qty", "pipe_wip_effective_qty", "fitting_wip_raw_qty", "fitting_wip_effective_qty", "scheduled_known_qty", "scheduled_override_qty", "scheduled_not_started_qty", "raw_suggested_qty", "system_suggested_qty"]],
        sa.Column("fixed_target_qty", qty),
        sa.Column("scheduled_source_status", sa.String(30), nullable=False),
        sa.Column("confirmed_qty", qty),
        sa.Column("review_status", sa.String(30), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_reason", sa.Text()),
        sa.Column("change_reason", sa.Text()),
        sa.Column("converted_demand_id", sa.Integer(), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("run_id", "product_id", name="uq_replenishment_suggestion_run_product"),
    )
    for name in ["run_id", "product_id", "algorithm", "review_status"]:
        op.create_index(op.f(f"ix_replenishment_suggestions_{name}"), "replenishment_suggestions", [name])
    op.create_index(op.f("ix_replenishment_suggestions_converted_demand_id"), "replenishment_suggestions", ["converted_demand_id"])

    op.create_table(
        "replenishment_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("replenishment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("suggestion_id", sa.Integer(), sa.ForeignKey("replenishment_suggestions.id", ondelete="CASCADE")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE")),
        sa.Column("issue_code", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.Text()),
        *timestamps(),
    )
    for name in ["run_id", "suggestion_id", "product_id", "issue_code", "severity", "status"]:
        op.create_index(op.f(f"ix_replenishment_issues_{name}"), "replenishment_issues", [name])
    op.create_index("ix_replenishment_issues_run_severity_status", "replenishment_issues", ["run_id", "severity", "status"])

    op.create_table(
        "replenishment_order_inputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("replenishment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_qty", qty, nullable=False),
        sa.Column("source_document_no", sa.String(100)),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("run_id", "product_id", name="uq_replenishment_order_run_product"),
    )
    op.create_index(op.f("ix_replenishment_order_inputs_run_id"), "replenishment_order_inputs", ["run_id"])
    op.create_index(op.f("ix_replenishment_order_inputs_product_id"), "replenishment_order_inputs", ["product_id"])

    op.create_table(
        "production_demands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("demand_no", sa.String(40), nullable=False, unique=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_suggestion_id", sa.Integer(), sa.ForeignKey("replenishment_suggestions.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("confirmed_qty", qty, nullable=False),
        sa.Column("active_allocated_qty", qty, nullable=False),
        sa.Column("qualified_completed_qty", qty, nullable=False),
        sa.Column("remaining_to_schedule_qty", qty, nullable=False),
        sa.Column("remaining_to_complete_qty", qty, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("required_date", sa.Date()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    for name in ["demand_no", "product_id", "source_suggestion_id", "status"]:
        op.create_index(op.f(f"ix_production_demands_{name}"), "production_demands", [name], unique=name in {"demand_no", "source_suggestion_id"})
    with op.batch_alter_table("replenishment_suggestions") as batch_op:
        batch_op.create_foreign_key("fk_replenishment_suggestions_converted_demand_id", "production_demands", ["converted_demand_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("replenishment_suggestions") as batch_op:
        batch_op.drop_constraint("fk_replenishment_suggestions_converted_demand_id", type_="foreignkey")
    for table in ["production_demands", "replenishment_order_inputs", "replenishment_issues", "replenishment_suggestions", "replenishment_runs", "replenishment_policies"]:
        op.drop_table(table)
    op.drop_index("ix_weekly_plan_batch_product_period", table_name="imported_weekly_plan_raw")
    op.drop_index("ix_regular_products_batch_product", table_name="regular_production_products")
    op.drop_index("ix_fitting_wip_snapshots_batch_product", table_name="fitting_wip_snapshots")
    op.drop_index("ix_pipe_wip_snapshots_batch_product", table_name="pipe_wip_snapshots")
    op.drop_index("ix_inventory_snapshots_batch_product", table_name="inventory_snapshots")
    op.drop_index("ix_shipment_records_batch_product_date", table_name="shipment_records")

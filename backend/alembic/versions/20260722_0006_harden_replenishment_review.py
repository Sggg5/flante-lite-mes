"""Harden replenishment review, audit context and quantity constraints.

Revision ID: 20260722_0006
Revises: 20260718_0005
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0006"
down_revision: Union[str, None] = "20260718_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINTS = {
    "replenishment_policies": [
        ("ck_replenishment_policy_fixed_target_nonnegative", "fixed_target_qty IS NULL OR fixed_target_qty >= 0"),
        ("ck_replenishment_policy_min_batch_positive", "min_batch_qty IS NULL OR min_batch_qty > 0"),
    ],
    "replenishment_runs": [
        ("ck_replenishment_run_fixed_target_nonnegative", "default_fixed_target_qty IS NULL OR default_fixed_target_qty >= 0"),
        ("ck_replenishment_run_min_batch_positive", "default_min_batch_qty IS NULL OR default_min_batch_qty > 0"),
    ],
    "replenishment_suggestions": [
        ("ck_replenishment_suggestion_confirmed_nonnegative", "confirmed_qty IS NULL OR confirmed_qty >= 0"),
    ],
    "replenishment_order_inputs": [
        ("ck_replenishment_order_qty_nonnegative", "order_qty >= 0"),
    ],
    "production_demands": [
        ("ck_production_demand_confirmed_positive", "confirmed_qty > 0"),
        ("ck_production_demand_allocated_nonnegative", "active_allocated_qty >= 0"),
        ("ck_production_demand_completed_nonnegative", "qualified_completed_qty >= 0"),
        ("ck_production_demand_remaining_schedule_nonnegative", "remaining_to_schedule_qty >= 0"),
        ("ck_production_demand_remaining_complete_nonnegative", "remaining_to_complete_qty >= 0"),
    ],
}


def upgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "context_replenishment_run_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_audit_logs_context_replenishment_run_id",
            "replenishment_runs",
            ["context_replenishment_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_audit_logs_context_replenishment_run_id", ["context_replenishment_run_id"])
    for table, constraints in CONSTRAINTS.items():
        with op.batch_alter_table(table) as batch_op:
            for name, condition in constraints:
                batch_op.create_check_constraint(name, condition)


def downgrade() -> None:
    for table, constraints in reversed(list(CONSTRAINTS.items())):
        with op.batch_alter_table(table) as batch_op:
            for name, _ in reversed(constraints):
                batch_op.drop_constraint(name, type_="check")
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_index("ix_audit_logs_context_replenishment_run_id")
        batch_op.drop_constraint("fk_audit_logs_context_replenishment_run_id", type_="foreignkey")
        batch_op.drop_column("context_replenishment_run_id")

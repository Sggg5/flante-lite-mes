"""Enforce import lifecycle and reversible product changes.

Revision ID: 20260718_0004
Revises: 20260718_0003
Create Date: 2026-07-18
"""

from datetime import date
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0004"
down_revision: Union[str, None] = "20260718_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_import_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("before_data", sa.JSON(), nullable=True),
        sa.Column("after_data", sa.JSON(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_product_import_changes_change_type"), "product_import_changes", ["change_type"])
    op.create_index(op.f("ix_product_import_changes_import_batch_id"), "product_import_changes", ["import_batch_id"])
    op.create_index(op.f("ix_product_import_changes_product_id"), "product_import_changes", ["product_id"])

    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.add_column(sa.Column("context_import_batch_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_audit_logs_context_import_batch_id"), ["context_import_batch_id"])
        batch_op.create_foreign_key(
            "fk_audit_logs_context_import_batch_id",
            "import_batches",
            ["context_import_batch_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column("import_batches", sa.Column("source_date", sa.Date(), nullable=True))
    op.create_index(op.f("ix_import_batches_source_date"), "import_batches", ["source_date"])
    op.create_index(
        "ix_import_batches_duplicate_lookup",
        "import_batches",
        ["import_type", "file_sha256", "source_date", "status"],
    )

    connection = op.get_bind()
    import_batches = sa.table(
        "import_batches",
        sa.column("id", sa.Integer()),
        sa.column("source_date", sa.Date()),
        sa.column("import_options", sa.JSON()),
    )
    for batch_id, import_options in connection.execute(sa.select(import_batches.c.id, import_batches.c.import_options)):
        raw_source_date = (import_options or {}).get("source_date")
        parsed_source_date = date.fromisoformat(raw_source_date) if raw_source_date else None
        connection.execute(
            import_batches.update().where(import_batches.c.id == batch_id).values(source_date=parsed_source_date)
        )

    audit_logs = sa.table(
        "audit_logs",
        sa.column("id", sa.Integer()),
        sa.column("action", sa.String()),
        sa.column("entity_type", sa.String()),
        sa.column("entity_id", sa.String()),
        sa.column("after_data", sa.JSON()),
        sa.column("context_import_batch_id", sa.Integer()),
    )
    weekly_staging = sa.table(
        "weekly_plan_staging_rows",
        sa.column("id", sa.Integer()),
        sa.column("import_batch_id", sa.Integer()),
    )
    for audit_id, action, entity_type, entity_id, after_data in connection.execute(
        sa.select(
            audit_logs.c.id,
            audit_logs.c.action,
            audit_logs.c.entity_type,
            audit_logs.c.entity_id,
            audit_logs.c.after_data,
        )
    ):
        context_batch_id = None
        if entity_type == "import_batch" and entity_id and entity_id.isdigit():
            context_batch_id = int(entity_id)
        elif action == "product.master_data.import":
            context_batch_id = (after_data or {}).get("import_batch_id")
        elif action == "weekly_plan.match" and entity_id and entity_id.isdigit():
            context_batch_id = connection.scalar(
                sa.select(weekly_staging.c.import_batch_id).where(weekly_staging.c.id == int(entity_id))
            )
        if context_batch_id is not None:
            connection.execute(
                audit_logs.update().where(audit_logs.c.id == audit_id).values(context_import_batch_id=int(context_batch_id))
            )


def downgrade() -> None:
    op.drop_index("ix_import_batches_duplicate_lookup", table_name="import_batches")
    op.drop_index(op.f("ix_import_batches_source_date"), table_name="import_batches")
    op.drop_column("import_batches", "source_date")
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_constraint("fk_audit_logs_context_import_batch_id", type_="foreignkey")
        batch_op.drop_index(op.f("ix_audit_logs_context_import_batch_id"))
        batch_op.drop_column("context_import_batch_id")
    op.drop_index(op.f("ix_product_import_changes_product_id"), table_name="product_import_changes")
    op.drop_index(op.f("ix_product_import_changes_import_batch_id"), table_name="product_import_changes")
    op.drop_index(op.f("ix_product_import_changes_change_type"), table_name="product_import_changes")
    op.drop_table("product_import_changes")

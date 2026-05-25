"""add_workspace_attribution_to_llm_usage

Revision ID: 6d2f8f1a9b3c
Revises: 7056e344e55a
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6d2f8f1a9b3c"
down_revision: str | Sequence[str] | None = "7056e344e55a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_usage_logs", sa.Column("workspace_id", sa.String(length=36), nullable=True))
    op.add_column("llm_usage_logs", sa.Column("attribution_source", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_llm_usage_logs_workspace_id"), "llm_usage_logs", ["workspace_id"], unique=False)
    op.create_foreign_key(
        "fk_llm_usage_logs_workspace_id_workspaces",
        "llm_usage_logs",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_llm_usage_logs_workspace_id_workspaces", "llm_usage_logs", type_="foreignkey")
    op.drop_index(op.f("ix_llm_usage_logs_workspace_id"), table_name="llm_usage_logs")
    op.drop_column("llm_usage_logs", "attribution_source")
    op.drop_column("llm_usage_logs", "workspace_id")

"""Instance 新增 last_active_workspace_id LLM 归因追踪

Revision ID: 30a1bcac4c80
Revises: c355da7aa436
Create Date: 2026-05-28 20:01:20.620930

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '30a1bcac4c80'
down_revision: str | Sequence[str] | None = 'c355da7aa436'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('instances', sa.Column('last_active_workspace_id', sa.String(length=36), nullable=True))
    op.create_foreign_key(
        'fk_instances_last_active_workspace_id',
        'instances', 'workspaces',
        ['last_active_workspace_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_instances_last_active_workspace_id', 'instances', type_='foreignkey')
    op.drop_column('instances', 'last_active_workspace_id')

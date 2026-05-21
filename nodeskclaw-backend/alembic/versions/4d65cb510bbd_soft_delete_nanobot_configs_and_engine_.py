"""soft_delete_nanobot_configs_and_engine_versions

Revision ID: 4d65cb510bbd
Revises: b9f5520c1ffb
Create Date: 2026-05-20 03:38:42.271600

"""
from datetime import datetime, timezone
from typing import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d65cb510bbd'
down_revision: str | Sequence[str] | None = 'b9f5520c1ffb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NANOBOT_REMOVAL_DELETED_AT = datetime(
    2026, 5, 20, 3, 38, 42, 271600, tzinfo=timezone.utc,
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE system_configs SET deleted_at = :deleted_at "
            "WHERE key = 'image_registry_nanobot' AND deleted_at IS NULL"
        ),
        {"deleted_at": NANOBOT_REMOVAL_DELETED_AT},
    )
    conn.execute(
        sa.text(
            "UPDATE engine_versions SET deleted_at = :deleted_at "
            "WHERE runtime = 'nanobot' AND deleted_at IS NULL"
        ),
        {"deleted_at": NANOBOT_REMOVAL_DELETED_AT},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE system_configs SET deleted_at = NULL "
            "WHERE key = 'image_registry_nanobot' AND deleted_at = :deleted_at"
        ),
        {"deleted_at": NANOBOT_REMOVAL_DELETED_AT},
    )
    conn.execute(
        sa.text(
            "UPDATE engine_versions SET deleted_at = NULL "
            "WHERE runtime = 'nanobot' AND deleted_at = :deleted_at"
        ),
        {"deleted_at": NANOBOT_REMOVAL_DELETED_AT},
    )

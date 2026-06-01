"""backfill attachments to file references

Revision ID: 9b871b5cc694
Revises: 64b548305e03
Create Date: 2026-06-02 04:15:53.931047

"""
from typing import Sequence, Union
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '9b871b5cc694'
down_revision: str | Sequence[str] | None = '64b548305e03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BATCH_SIZE = 500


def upgrade() -> None:
    """Backfill workspace_message_file_references from workspace_messages.attachments JSON."""
    conn = op.get_bind()

    messages_table = sa.table(
        'workspace_messages',
        sa.column('id', sa.String),
        sa.column('workspace_id', sa.String),
        sa.column('attachments', JSONB),
        sa.column('deleted_at', sa.DateTime),
    )

    refs_table = sa.table(
        'workspace_message_file_references',
        sa.column('id', sa.String),
        sa.column('workspace_id', sa.String),
        sa.column('message_id', sa.String),
        sa.column('source', sa.String),
        sa.column('file_id', sa.String),
        sa.column('display_name', sa.String),
        sa.column('file_size', sa.BigInteger),
        sa.column('content_type', sa.String),
        sa.column('scan_status', sa.String),
        sa.column('status', sa.String),
        sa.column('sort_order', sa.Integer),
        sa.column('deleted_at', sa.DateTime),
    )

    query = (
        sa.select(
            messages_table.c.id,
            messages_table.c.workspace_id,
            messages_table.c.attachments,
        )
        .where(messages_table.c.attachments.isnot(None))
        .where(messages_table.c.attachments != sa.cast('[]', JSONB))
        .where(messages_table.c.deleted_at.is_(None))
    )

    offset = 0
    total_inserted = 0

    while True:
        rows = conn.execute(query.limit(BATCH_SIZE).offset(offset)).fetchall()
        if not rows:
            break

        inserts = []
        for row in rows:
            message_id = row[0]
            workspace_id = row[1]
            attachments_raw = row[2]

            if isinstance(attachments_raw, str):
                try:
                    attachments = json.loads(attachments_raw)
                except (json.JSONDecodeError, TypeError):
                    continue
            else:
                attachments = attachments_raw

            if not isinstance(attachments, list):
                continue

            for idx, att in enumerate(attachments):
                if not isinstance(att, dict):
                    continue
                file_id = att.get('file_id') or att.get('id')
                if not file_id:
                    continue

                inserts.append({
                    'id': str(uuid.uuid4()),
                    'workspace_id': workspace_id,
                    'message_id': message_id,
                    'source': 'chat_attachment',
                    'file_id': file_id,
                    'display_name': att.get('name', att.get('filename', 'unknown')),
                    'file_size': int(att.get('size', att.get('file_size', 0))),
                    'content_type': att.get('content_type', 'application/octet-stream'),
                    'scan_status': 'skipped',
                    'status': 'available',
                    'sort_order': idx,
                })

        if inserts:
            stmt = sa.dialects.postgresql.insert(refs_table).values(inserts)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['message_id', 'source', 'file_id'],
                index_where=sa.text('deleted_at IS NULL'),
            )
            conn.execute(stmt)
            total_inserted += len(inserts)

        offset += BATCH_SIZE

    if total_inserted:
        op.execute(sa.text(f"-- backfilled {total_inserted} file references from attachments JSON"))


def downgrade() -> None:
    """Remove backfilled file references (only those with source='chat_attachment' and scan_status='skipped')."""
    op.execute(sa.text(
        "DELETE FROM workspace_message_file_references "
        "WHERE source = 'chat_attachment' AND scan_status = 'skipped'"
    ))

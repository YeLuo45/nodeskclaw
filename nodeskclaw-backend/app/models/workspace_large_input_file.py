"""Workspace large input file metadata."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class WorkspaceLargeInputFile(BaseModel):
    __tablename__ = "workspace_large_input_files"
    __table_args__ = (
        Index("ix_workspace_large_input_files_ws_status", "workspace_id", "status"),
        Index("ix_workspace_large_input_files_owner", "workspace_id", "owner_type", "owner_id"),
        Index(
            "ix_workspace_large_input_files_active_source",
            "workspace_id",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    upload_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("upload_sessions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    uploader_type: Mapped[str] = mapped_column(String(16), nullable=False)
    uploader_id: Mapped[str] = mapped_column(String(36), nullable=False)
    uploader_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), default="agent_input", nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), default="", nullable=False)
    retention_policy: Mapped[str] = mapped_column(String(32), default="expires_at", nullable=False)
    retention_anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream", nullable=False)
    checksum: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    scan_status: Mapped[str] = mapped_column(String(32), default="skipped", nullable=False)
    scan_reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="available", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

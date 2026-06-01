"""Upload session metadata."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class UploadSession(BaseModel):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        Index(
            "uq_upload_sessions_client_request_active",
            "workspace_id",
            "uploader_type",
            "uploader_id",
            "client_request_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL "
                "AND client_request_id IS NOT NULL "
                "AND status IN ('pending', 'uploading')"
            ),
        ),
        Index("ix_upload_sessions_ws_status_expires", "workspace_id", "status", "expires_at"),
        Index("ix_upload_sessions_ws_surface_status_created", "workspace_id", "surface", "status", "created_at"),
    )

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    uploader_type: Mapped[str] = mapped_column(String(16), nullable=False)
    uploader_id: Mapped[str] = mapped_column(String(36), nullable=False)
    uploader_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream", nullable=False)
    expected_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    checksum: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    upload_mode: Mapped[str] = mapped_column(String(32), default="backend_parts", nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), default="local", nullable=False)
    provider_upload_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    part_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    part_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_reservation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_path: Mapped[str] = mapped_column(String(1024), default="/", nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), default="", nullable=False)
    retention_policy: Mapped[str] = mapped_column(String(32), default="expires_at", nullable=False)
    conflict_strategy: Mapped[str] = mapped_column(String(32), default="fail", nullable=False)
    expected_existing_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

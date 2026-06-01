"""Upload quota reservation metadata."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class UploadQuotaReservation(BaseModel):
    __tablename__ = "upload_quota_reservations"
    __table_args__ = (
        Index(
            "uq_upload_quota_reservation_session_active",
            "session_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status = 'active' AND session_id IS NOT NULL"),
        ),
        Index("ix_upload_quota_reservations_ws_status_expires", "workspace_id", "status", "expires_at"),
        Index("ix_upload_quota_reservations_committed_file", "committed_source", "committed_file_id"),
    )

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("upload_sessions.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_source: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    committed_file_id: Mapped[str] = mapped_column(String(36), default="", nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

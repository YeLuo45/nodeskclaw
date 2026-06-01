"""Upload part metadata."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class UploadPart(BaseModel):
    __tablename__ = "upload_parts"
    __table_args__ = (
        Index(
            "uq_upload_parts_active_part",
            "session_id",
            "part_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status IN ('signed', 'uploaded')"),
        ),
        Index("ix_upload_parts_session_status", "session_id", "status"),
        Index("ix_upload_parts_workspace_session", "workspace_id", "session_id"),
    )

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("upload_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    checksum: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    etag: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    presigned_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)

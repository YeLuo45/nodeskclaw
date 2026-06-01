"""File scan job metadata."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class FileScanJob(BaseModel):
    __tablename__ = "file_scan_jobs"
    __table_args__ = (
        Index(
            "uq_file_scan_jobs_active_source",
            "source",
            "file_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status IN ('pending', 'leased')"),
        ),
        Index(
            "ix_file_scan_jobs_pending",
            "status",
            "next_attempt_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_file_scan_jobs_source",
            "workspace_id",
            "source",
            "file_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(36), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    leased_by: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(1024), default="", nullable=False)

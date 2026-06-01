"""Storage object delete retry job metadata."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class StorageObjectDeleteJob(BaseModel):
    __tablename__ = "storage_object_delete_jobs"
    __table_args__ = (
        Index(
            "uq_storage_object_delete_jobs_active",
            "source",
            "source_id",
            "storage_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status IN ('pending', 'retrying')"),
        ),
        Index(
            "ix_storage_object_delete_jobs_pending",
            "status",
            "next_attempt_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_storage_object_delete_jobs_source",
            "workspace_id",
            "source",
            "source_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str] = mapped_column(String(1024), default="", nullable=False)

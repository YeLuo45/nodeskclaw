from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_file_access_grant import AgentFileAccessGrant
from app.models.storage_object_delete_job import StorageObjectDeleteJob
from app.models.upload_part import UploadPart
from app.models.upload_quota_reservation import UploadQuotaReservation
from app.models.upload_session import UploadSession
from app.models.workspace_file import WorkspaceFile
from app.models.workspace_large_input_file import WorkspaceLargeInputFile
from app.models.workspace_message_file_reference import WorkspaceMessageFileReference
from app.services import storage_service
from app.services.upload_policy_service import build_upload_policy


SOURCE_CHAT_ATTACHMENT = "chat_attachment"
SOURCE_SHARED_FILE = "shared_file"
SOURCE_LARGE_INPUT = "large_input"
SOURCE_UPLOAD_PART = "upload_part"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def enqueue_storage_delete(
    db: AsyncSession,
    *,
    workspace_id: str,
    source: str,
    source_id: str,
    storage_key: str,
    last_error: str = "",
) -> StorageObjectDeleteJob | None:
    if not storage_key:
        return None
    existing = (await db.execute(
        select(StorageObjectDeleteJob).where(
            StorageObjectDeleteJob.source == source,
            StorageObjectDeleteJob.source_id == source_id,
            StorageObjectDeleteJob.storage_key == storage_key,
            StorageObjectDeleteJob.status.in_(["pending", "retrying"]),
            StorageObjectDeleteJob.deleted_at.is_(None),
        ).limit(1)
    )).scalar_one_or_none()
    if existing is not None:
        existing.next_attempt_at = min(existing.next_attempt_at, _now())
        if last_error:
            existing.last_error = last_error[:1024]
        await db.flush()
        return existing
    job = StorageObjectDeleteJob(
        workspace_id=workspace_id,
        source=source,
        source_id=source_id,
        storage_key=storage_key,
        status="pending",
        next_attempt_at=_now(),
        last_error=last_error[:1024],
    )
    db.add(job)
    await db.flush()
    return job


async def run_storage_delete_retry_worker(
    db: AsyncSession,
    *,
    batch_size: int = 100,
    max_attempts: int = 8,
) -> dict[str, int]:
    now = _now()
    result = await db.execute(
        select(StorageObjectDeleteJob).where(
            StorageObjectDeleteJob.deleted_at.is_(None),
            StorageObjectDeleteJob.status.in_(["pending", "retrying"]),
            StorageObjectDeleteJob.next_attempt_at <= now,
        ).order_by(
            StorageObjectDeleteJob.next_attempt_at,
            StorageObjectDeleteJob.created_at,
        ).limit(batch_size).with_for_update(skip_locked=True)
    )
    jobs = list(result.scalars().all())
    counts = {"processed": len(jobs), "succeeded": 0, "failed": 0, "retrying": 0}
    for job in jobs:
        try:
            await storage_service.delete_file(job.storage_key)
        except Exception as exc:
            job.attempt_count += 1
            job.last_error = str(exc)[:1024]
            if job.attempt_count >= max_attempts:
                job.status = "failed"
                counts["failed"] += 1
            else:
                job.status = "retrying"
                job.next_attempt_at = _now() + _retry_delay(job.attempt_count)
                counts["retrying"] += 1
            continue
        job.status = "succeeded"
        job.last_error = ""
        counts["succeeded"] += 1
    await db.commit()
    return counts


async def expire_upload_sessions(
    db: AsyncSession,
    *,
    batch_size: int = 500,
) -> int:
    now = _now()
    result = await db.execute(
        select(UploadSession).where(
            UploadSession.status.in_(["pending", "uploading"]),
            UploadSession.expires_at <= now,
            UploadSession.deleted_at.is_(None),
        ).order_by(UploadSession.expires_at).limit(batch_size).with_for_update(skip_locked=True)
    )
    sessions = list(result.scalars().all())
    count = 0
    for session in sessions:
        session.status = "expired"
        count += 1
        if session.quota_reservation_id:
            reservation = (await db.execute(
                select(UploadQuotaReservation).where(
                    UploadQuotaReservation.id == session.quota_reservation_id,
                    UploadQuotaReservation.status == "active",
                    UploadQuotaReservation.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if reservation is not None:
                reservation.status = "released"
                reservation.released_at = now
        parts = (await db.execute(
            select(UploadPart).where(
                UploadPart.session_id == session.id,
                UploadPart.status.in_(["signed", "uploaded"]),
                UploadPart.deleted_at.is_(None),
            )
        )).scalars().all()
        for part in parts:
            part.status = "failed"
            await enqueue_storage_delete(
                db,
                workspace_id=session.workspace_id,
                source=SOURCE_UPLOAD_PART,
                source_id=part.id,
                storage_key=part.storage_key,
            )
    await db.commit()
    return count


async def clean_expired_chat_attachments(
    db: AsyncSession,
    *,
    batch_size: int = 500,
) -> int:
    policy = await build_upload_policy(db)
    retention_days = int(policy["surfaces"]["chat_attachment"].get("retention_days") or 90)
    cutoff = _now() - timedelta(days=retention_days)
    result = await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.created_at < cutoff,
            WorkspaceFile.deleted_at.is_(None),
        ).order_by(WorkspaceFile.created_at).limit(batch_size).with_for_update(skip_locked=True)
    )
    files = list(result.scalars().all())
    for file_record in files:
        await enqueue_storage_delete(
            db,
            workspace_id=file_record.workspace_id,
            source=SOURCE_CHAT_ATTACHMENT,
            source_id=file_record.id,
            storage_key=file_record.storage_key,
        )
        file_record.soft_delete()
        await _mark_references_unavailable(
            db,
            workspace_id=file_record.workspace_id,
            source=SOURCE_CHAT_ATTACHMENT,
            file_id=file_record.id,
        )
        await _revoke_grants(
            db,
            workspace_id=file_record.workspace_id,
            source=SOURCE_CHAT_ATTACHMENT,
            file_id=file_record.id,
            reason="retention_expired",
        )
    await db.commit()
    return len(files)


async def clean_orphan_large_inputs(
    db: AsyncSession,
    *,
    batch_size: int = 500,
) -> int:
    now = _now()
    result = await db.execute(
        select(WorkspaceLargeInputFile).where(
            WorkspaceLargeInputFile.status == "available",
            WorkspaceLargeInputFile.deleted_at.is_(None),
            or_(
                WorkspaceLargeInputFile.owner_type == "none",
                WorkspaceLargeInputFile.expires_at <= now,
            ),
            WorkspaceLargeInputFile.expires_at.is_not(None),
            WorkspaceLargeInputFile.expires_at <= now,
        ).order_by(WorkspaceLargeInputFile.expires_at).limit(batch_size).with_for_update(skip_locked=True)
    )
    files = list(result.scalars().all())
    for file_record in files:
        await enqueue_storage_delete(
            db,
            workspace_id=file_record.workspace_id,
            source=SOURCE_LARGE_INPUT,
            source_id=file_record.id,
            storage_key=file_record.storage_key,
        )
        file_record.status = "unavailable"
        await _mark_references_unavailable(
            db,
            workspace_id=file_record.workspace_id,
            source=SOURCE_LARGE_INPUT,
            file_id=file_record.id,
        )
        await _revoke_grants(
            db,
            workspace_id=file_record.workspace_id,
            source=SOURCE_LARGE_INPUT,
            file_id=file_record.id,
            reason="large_input_expired",
        )
    await db.commit()
    return len(files)


async def run_file_cleanup_cycle(db: AsyncSession) -> dict[str, int]:
    expired_sessions = await expire_upload_sessions(db)
    chat_cleaned = await clean_expired_chat_attachments(db)
    large_inputs_cleaned = await clean_orphan_large_inputs(db)
    delete_jobs = await run_storage_delete_retry_worker(db)
    return {
        "upload_sessions_expired": expired_sessions,
        "chat_attachments_cleaned": chat_cleaned,
        "large_inputs_cleaned": large_inputs_cleaned,
        "delete_jobs_processed": delete_jobs["processed"],
        "delete_jobs_succeeded": delete_jobs["succeeded"],
        "delete_jobs_failed": delete_jobs["failed"],
        "delete_jobs_retrying": delete_jobs["retrying"],
    }


async def get_cleanup_health(db: AsyncSession) -> dict[str, Any]:
    pending_count = (await db.execute(
        select(func.count()).select_from(StorageObjectDeleteJob).where(
            StorageObjectDeleteJob.status.in_(["pending", "retrying"]),
            StorageObjectDeleteJob.deleted_at.is_(None),
        )
    )).scalar_one() or 0
    failed_count = (await db.execute(
        select(func.count()).select_from(StorageObjectDeleteJob).where(
            StorageObjectDeleteJob.status == "failed",
            StorageObjectDeleteJob.deleted_at.is_(None),
        )
    )).scalar_one() or 0
    oldest_pending = (await db.execute(
        select(func.min(StorageObjectDeleteJob.created_at)).where(
            StorageObjectDeleteJob.status.in_(["pending", "retrying"]),
            StorageObjectDeleteJob.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return {
        "worker_id": f"{socket.gethostname()}:file-cleanup",
        "pending_delete_count": int(pending_count),
        "failed_delete_count": int(failed_count),
        "oldest_pending_delete_at": oldest_pending.isoformat() if oldest_pending else None,
    }


async def _mark_references_unavailable(
    db: AsyncSession,
    *,
    workspace_id: str,
    source: str,
    file_id: str,
) -> None:
    await db.execute(
        update(WorkspaceMessageFileReference)
        .where(
            WorkspaceMessageFileReference.workspace_id == workspace_id,
            WorkspaceMessageFileReference.source == source,
            WorkspaceMessageFileReference.file_id == file_id,
            WorkspaceMessageFileReference.deleted_at.is_(None),
        )
        .values(status="unavailable")
    )


async def _revoke_grants(
    db: AsyncSession,
    *,
    workspace_id: str,
    source: str,
    file_id: str,
    reason: str,
) -> None:
    await db.execute(
        update(AgentFileAccessGrant)
        .where(
            AgentFileAccessGrant.workspace_id == workspace_id,
            AgentFileAccessGrant.source == source,
            AgentFileAccessGrant.file_id == file_id,
            AgentFileAccessGrant.revoked_at.is_(None),
            AgentFileAccessGrant.deleted_at.is_(None),
        )
        .values(
            status="revoked",
            revoked_at=func.now(),
            revoked_by=reason,
        )
    )


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(3600, 2 ** max(0, attempt_count - 1) * 60))

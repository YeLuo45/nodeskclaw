from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.blackboard_file import BlackboardFile
from app.models.file_scan_job import FileScanJob
from app.models.workspace_file import WorkspaceFile
from app.models.workspace_large_input_file import WorkspaceLargeInputFile
from app.services import config_service
from app.services.upload_policy_service import build_upload_policy


SOURCE_CHAT_ATTACHMENT = "chat_attachment"
SOURCE_SHARED_FILE = "shared_file"
SOURCE_LARGE_INPUT = "large_input"
BLOCKING_SCAN_STATUSES = {"pending", "blocked", "failed"}


class ScannerUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanResult:
    status: str
    reason: str
    vendor: str = ""
    details: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def assert_download_allowed(scan_status: str) -> None:
    status = scan_status or "skipped"
    if status == "pending":
        raise ForbiddenError("文件安全扫描未完成", "errors.upload.file_scan_pending")
    if status == "blocked":
        raise ForbiddenError("文件未通过安全扫描", "errors.upload.file_scan_blocked")
    if status == "failed":
        raise ForbiddenError("文件安全扫描失败", "errors.upload.file_scan_failed")


async def get_initial_scan_state(db: AsyncSession) -> tuple[str, str]:
    policy = await build_upload_policy(db)
    security = policy.get("security") or {}
    scan_mode = security.get("scan_mode")
    if scan_mode == "async_required":
        if not security.get("scanner_configured"):
            raise ScannerUnavailableError()
        return "pending", "queued"
    if scan_mode == "disabled":
        return "skipped", "scan_disabled"
    return "skipped", "metadata_only"


async def enqueue_scan(
    db: AsyncSession,
    *,
    workspace_id: str,
    source: str,
    file_id: str,
    storage_key: str,
) -> FileScanJob | None:
    policy = await build_upload_policy(db)
    security = policy.get("security") or {}
    if security.get("scan_mode") != "async_required":
        return None
    if not security.get("scanner_configured"):
        raise ScannerUnavailableError()

    existing = (await db.execute(
        select(FileScanJob).where(
            FileScanJob.source == source,
            FileScanJob.file_id == file_id,
            FileScanJob.status.in_(["pending", "leased"]),
            FileScanJob.deleted_at.is_(None),
        ).limit(1)
    )).scalar_one_or_none()
    if existing is not None:
        existing.workspace_id = workspace_id
        existing.storage_key = storage_key
        existing.status = "pending"
        existing.next_attempt_at = _now()
        existing.leased_by = ""
        existing.leased_until = None
        await db.flush()
        return existing

    job = FileScanJob(
        workspace_id=workspace_id,
        source=source,
        file_id=file_id,
        storage_key=storage_key,
        status="pending",
        next_attempt_at=_now(),
    )
    db.add(job)
    await db.flush()
    return job


async def retry_scan(
    db: AsyncSession,
    *,
    workspace_id: str,
    source: str,
    file_id: str,
) -> FileScanJob:
    source_file = await _resolve_source_file(db, workspace_id, source, file_id)
    if source_file is None:
        raise NotFoundError("文件不存在", "errors.upload.file_reference_not_found")
    _set_source_scan(source_file, "pending", "retry_requested")
    job = await enqueue_scan(
        db,
        workspace_id=workspace_id,
        source=source,
        file_id=file_id,
        storage_key=source_file.storage_key,
    )
    if job is None:
        raise ScannerUnavailableError()
    await db.flush()
    return job


async def lease_pending_scan_jobs(
    db: AsyncSession,
    *,
    worker_id: str | None = None,
    batch_size: int = 20,
    lease_seconds: int = 300,
) -> list[str]:
    now = _now()
    worker = worker_id or f"{socket.gethostname()}:file-scan"
    result = await db.execute(
        select(FileScanJob).where(
            FileScanJob.deleted_at.is_(None),
            FileScanJob.next_attempt_at <= now,
            or_(
                FileScanJob.status == "pending",
                (FileScanJob.status == "leased") & (FileScanJob.leased_until <= now),
            ),
        ).order_by(FileScanJob.next_attempt_at, FileScanJob.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    jobs = list(result.scalars().all())
    leased_until = now + timedelta(seconds=lease_seconds)
    for job in jobs:
        job.status = "leased"
        job.leased_by = worker
        job.leased_until = leased_until
    await db.commit()
    return [job.id for job in jobs]


async def run_pending_scan_jobs(
    db: AsyncSession,
    *,
    worker_id: str | None = None,
    batch_size: int = 20,
) -> dict[str, int]:
    leased_ids = await lease_pending_scan_jobs(db, worker_id=worker_id, batch_size=batch_size)
    counts = {"leased": len(leased_ids), "succeeded": 0, "failed": 0, "cancelled": 0}
    for job_id in leased_ids:
        outcome = await process_scan_job(db, job_id)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def process_scan_job(db: AsyncSession, job_id: str) -> str:
    job = (await db.execute(
        select(FileScanJob).where(
            FileScanJob.id == job_id,
            FileScanJob.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if job is None or job.status not in {"leased", "pending"}:
        return "cancelled"

    source_file = await _resolve_source_file(db, job.workspace_id, job.source, job.file_id)
    if source_file is None or not getattr(source_file, "storage_key", ""):
        job.status = "cancelled"
        job.last_error = "source_unavailable"
        job.deleted_at = func.now()
        await db.commit()
        return "cancelled"

    if source_file.storage_key != job.storage_key:
        job.status = "cancelled"
        job.last_error = "storage_key_changed"
        job.deleted_at = func.now()
        await db.commit()
        return "cancelled"

    policy = await build_upload_policy(db)
    max_scan_bytes = int(policy["security"]["scanner_max_file_size_bytes"])
    file_size = int(_source_size(source_file))
    if file_size > max_scan_bytes:
        _set_source_scan(source_file, "failed", "scanner_file_too_large")
        job.status = "failed"
        job.attempt_count += 1
        job.last_error = "scanner_file_too_large"
        await db.commit()
        return "failed"

    result = await _scan_object(
        db,
        storage_key=source_file.storage_key,
        filename=_source_filename(source_file),
        content_type=source_file.content_type,
        size=file_size,
    )
    if result.status == "clean":
        _set_source_scan(source_file, "clean", result.reason or "clean")
        job.status = "succeeded"
        job.last_error = ""
        await db.commit()
        return "succeeded"
    if result.status == "blocked":
        _set_source_scan(source_file, "blocked", result.reason or "blocked")
        job.status = "succeeded"
        job.last_error = result.reason or "blocked"
        await db.commit()
        return "succeeded"

    max_retries = await _effective_int(db, "upload_scanner_max_retries", settings.UPLOAD_SCANNER_MAX_RETRIES)
    job.attempt_count += 1
    job.last_error = result.reason or "scanner_failed"
    if job.attempt_count <= max_retries:
        job.status = "pending"
        job.leased_by = ""
        job.leased_until = None
        job.next_attempt_at = _now() + _retry_delay(job.attempt_count)
        await db.commit()
        return "failed"

    _set_source_scan(source_file, "failed", job.last_error)
    job.status = "failed"
    await db.commit()
    return "failed"


async def get_scan_health(db: AsyncSession) -> dict[str, Any]:
    now = _now()
    pending_count = (await db.execute(
        select(func.count()).select_from(FileScanJob).where(
            FileScanJob.status.in_(["pending", "leased"]),
            FileScanJob.deleted_at.is_(None),
        )
    )).scalar_one() or 0
    failed_count = (await db.execute(
        select(func.count()).select_from(FileScanJob).where(
            FileScanJob.status == "failed",
            FileScanJob.deleted_at.is_(None),
        )
    )).scalar_one() or 0
    oldest_pending = (await db.execute(
        select(func.min(FileScanJob.created_at)).where(
            FileScanJob.status.in_(["pending", "leased"]),
            FileScanJob.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    last_success = (await db.execute(
        select(func.max(FileScanJob.updated_at)).where(
            FileScanJob.status == "succeeded",
            FileScanJob.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return {
        "pending_count": int(pending_count),
        "failed_count": int(failed_count),
        "oldest_pending_at": oldest_pending.isoformat() if oldest_pending else None,
        "last_success_at": last_success.isoformat() if last_success else None,
        "checked_at": now.isoformat(),
    }


async def _scan_object(
    db: AsyncSession,
    *,
    storage_key: str,
    filename: str,
    content_type: str,
    size: int,
) -> ScanResult:
    provider = await _effective_str(db, "upload_scanner_provider", settings.UPLOAD_SCANNER_PROVIDER)
    endpoint = await _effective_str(db, "upload_scanner_endpoint", settings.UPLOAD_SCANNER_ENDPOINT)
    timeout = await _effective_int(db, "upload_scanner_timeout_seconds", settings.UPLOAD_SCANNER_TIMEOUT_SECONDS)
    provider = provider or "none"
    if provider == "http" and endpoint.strip():
        return await _scan_via_http(
            endpoint.strip(),
            timeout=timeout,
            storage_key=storage_key,
            filename=filename,
            content_type=content_type,
            size=size,
        )
    if provider == "clamav":
        return ScanResult("failed", "clamav_adapter_unavailable", vendor="clamav")
    return ScanResult("failed", "scanner_unavailable", vendor=provider)


async def _scan_via_http(
    endpoint: str,
    *,
    timeout: int,
    storage_key: str,
    filename: str,
    content_type: str,
    size: int,
) -> ScanResult:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                endpoint,
                json={
                    "storage_key": storage_key,
                    "filename": filename,
                    "content_type": content_type,
                    "size": size,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return ScanResult("failed", str(exc)[:255], vendor="http")

    status = str(payload.get("status") or "").lower()
    if status not in {"clean", "blocked", "failed"}:
        status = "failed"
    reason = str(payload.get("reason") or status)
    details = payload.get("details") if isinstance(payload.get("details"), dict) else None
    return ScanResult(status, reason[:255], vendor=str(payload.get("vendor") or "http"), details=details)


async def _resolve_source_file(
    db: AsyncSession,
    workspace_id: str,
    source: str,
    file_id: str,
) -> WorkspaceFile | BlackboardFile | WorkspaceLargeInputFile | None:
    if source == SOURCE_CHAT_ATTACHMENT:
        return (await db.execute(
            select(WorkspaceFile).where(
                WorkspaceFile.id == file_id,
                WorkspaceFile.workspace_id == workspace_id,
                WorkspaceFile.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
    if source == SOURCE_SHARED_FILE:
        return (await db.execute(
            select(BlackboardFile).where(
                BlackboardFile.id == file_id,
                BlackboardFile.workspace_id == workspace_id,
                BlackboardFile.is_directory.is_(False),
                BlackboardFile.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
    if source == SOURCE_LARGE_INPUT:
        return (await db.execute(
            select(WorkspaceLargeInputFile).where(
                WorkspaceLargeInputFile.id == file_id,
                WorkspaceLargeInputFile.workspace_id == workspace_id,
                WorkspaceLargeInputFile.status == "available",
                WorkspaceLargeInputFile.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
    return None


def _set_source_scan(source_file: Any, status: str, reason: str) -> None:
    source_file.scan_status = status
    source_file.scan_reason = reason[:255]
    source_file.scanned_at = _now() if status in {"clean", "blocked", "failed", "skipped"} else None


def _source_filename(source_file: Any) -> str:
    return (
        getattr(source_file, "original_name", None)
        or getattr(source_file, "name", None)
        or getattr(source_file, "display_name", None)
        or "unnamed"
    )


def _source_size(source_file: Any) -> int:
    return int(getattr(source_file, "file_size", None) or getattr(source_file, "size", 0) or 0)


async def _effective_int(db: AsyncSession, key: str, default: int) -> int:
    raw = await config_service.get_config(key, db)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


async def _effective_str(db: AsyncSession, key: str, default: str) -> str:
    raw = await config_service.get_config(key, db)
    return raw if raw is not None else default


def _retry_delay(attempt_count: int) -> timedelta:
    seconds = min(300, 2 ** max(0, attempt_count - 1) * 30)
    return timedelta(seconds=seconds)

from __future__ import annotations

import asyncio
import hashlib
import math
import shutil
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.blackboard_file import BlackboardFile
from app.models.upload_part import UploadPart
from app.models.upload_quota_reservation import UploadQuotaReservation
from app.models.upload_session import UploadSession
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.models.workspace_large_input_file import WorkspaceLargeInputFile
from app.schemas.upload import (
    UploadCancelResponse,
    UploadCompleteRequest,
    UploadPartInfo,
    UploadPartSignResponse,
    UploadPartUploadResponse,
    UploadSessionCreateRequest,
    UploadSessionInfo,
)
from app.services import file_cleanup_service, file_scan_service, storage_service
from app.services.upload_policy_service import build_upload_policy, validate_upload_request


class WorkspaceQuotaExceededError(RuntimeError):
    def __init__(self, quota_bytes: int, used_bytes: int, requested_bytes: int) -> None:
        super().__init__("workspace quota exceeded")
        self.quota_bytes = quota_bytes
        self.used_bytes = used_bytes
        self.requested_bytes = requested_bytes


class UploadScannerUnavailableError(RuntimeError):
    pass


class UploadSessionStateError(RuntimeError):
    def __init__(self, message_key: str) -> None:
        super().__init__(message_key)
        self.message_key = message_key


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_filename(filename: str) -> str:
    clean = filename.replace("\\", "/").split("/")[-1].strip()
    clean = "".join(ch for ch in clean if ch >= " " and ch != "\x7f")
    return clean[:255] or "unnamed"


def _validate_parent_path(path: str) -> str:
    normalized = path or "/"
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if not normalized.endswith("/"):
        normalized += "/"
    if ".." in PurePosixPath(normalized).parts:
        raise BadRequestError("目录路径无效", "errors.upload.invalid_path")
    return normalized


def _normalize_checksum(checksum: str | None) -> str:
    value = (checksum or "").strip().lower()
    if not value:
        return ""
    if value.startswith("sha256:"):
        value = value.removeprefix("sha256:")
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise BadRequestError("文件校验和无效", "errors.upload.checksum_mismatch")
    return f"sha256:{value}"


def _checksum_hex(checksum: str) -> str:
    return checksum.removeprefix("sha256:")


def _session_expires_at() -> datetime:
    return _now() + timedelta(minutes=120)


def _part_root(session_id: str) -> Path:
    return storage_service._get_local_dir() / ".upload-parts" / session_id


def _part_storage_key(session_id: str, part_number: int) -> str:
    return f".upload-parts/{session_id}/{part_number}-{uuid.uuid4().hex}.part"


def _part_path(storage_key: str) -> Path:
    return storage_service._get_local_dir() / storage_key


async def _delete_path(path: Path) -> None:
    def _remove() -> None:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    await asyncio.to_thread(_remove)


async def _iter_part_files(parts: list[UploadPart]) -> AsyncIterator[bytes]:
    for part in parts:
        path = _part_path(part.storage_key)
        with path.open("rb") as handle:
            while True:
                chunk = await asyncio.to_thread(handle.read, 1024 * 1024)
                if not chunk:
                    break
                yield chunk


async def _existing_shared_file(
    db: AsyncSession,
    workspace_id: str,
    parent_path: str,
    filename: str,
) -> BlackboardFile | None:
    return (await db.execute(
        select(BlackboardFile).where(
            BlackboardFile.workspace_id == workspace_id,
            BlackboardFile.parent_path == parent_path,
            BlackboardFile.name == filename,
            BlackboardFile.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def _resolve_shared_filename(
    db: AsyncSession,
    workspace_id: str,
    parent_path: str,
    filename: str,
    conflict_strategy: str,
    expected_existing_file_id: str | None,
) -> tuple[str, str]:
    if conflict_strategy not in {"fail", "keep_both", "overwrite"}:
        raise BadRequestError("同名冲突策略无效", "errors.upload.file_conflict")

    existing = await _existing_shared_file(db, workspace_id, parent_path, filename)
    if conflict_strategy == "fail":
        if existing is not None:
            raise ConflictError("目标路径已存在同名文件", "errors.upload.file_conflict")
        return filename, "fail"

    if conflict_strategy == "overwrite":
        if not expected_existing_file_id:
            raise BadRequestError("覆盖文件必须提供 expected_existing_file_id", "errors.upload.file_conflict")
        if existing is None or existing.id != expected_existing_file_id:
            raise ConflictError("目标路径已存在同名文件", "errors.upload.file_conflict")
        return existing.name, "overwrite"

    if existing is None:
        return filename, "keep_both"

    stem = PurePosixPath(filename).stem or filename
    suffix = PurePosixPath(filename).suffix
    for index in range(1, 1000):
        candidate = f"{stem} ({index}){suffix}"
        if await _existing_shared_file(db, workspace_id, parent_path, candidate) is None:
            return candidate, "keep_both"
    raise ConflictError("目标路径同名文件过多", "errors.upload.file_conflict")


async def _active_session_by_client_request(
    db: AsyncSession,
    *,
    workspace_id: str,
    uploader_type: str,
    uploader_id: str,
    surface: str,
    client_request_id: str | None,
) -> UploadSession | None:
    if not client_request_id:
        return None
    return (await db.execute(
        select(UploadSession).where(
            UploadSession.workspace_id == workspace_id,
            UploadSession.uploader_type == uploader_type,
            UploadSession.uploader_id == uploader_id,
            UploadSession.surface == surface,
            UploadSession.client_request_id == client_request_id,
            UploadSession.status.in_(["pending", "uploading"]),
            UploadSession.expires_at > _now(),
            UploadSession.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def _workspace_used_bytes(db: AsyncSession, workspace_id: str) -> int:
    workspace_files = (await db.execute(
        select(func.coalesce(func.sum(WorkspaceFile.file_size), 0)).where(
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.deleted_at.is_(None),
        )
    )).scalar_one()
    shared_files = (await db.execute(
        select(func.coalesce(func.sum(BlackboardFile.file_size), 0)).where(
            BlackboardFile.workspace_id == workspace_id,
            BlackboardFile.is_directory.is_(False),
            BlackboardFile.deleted_at.is_(None),
        )
    )).scalar_one()
    large_inputs = (await db.execute(
        select(func.coalesce(func.sum(WorkspaceLargeInputFile.size), 0)).where(
            WorkspaceLargeInputFile.workspace_id == workspace_id,
            WorkspaceLargeInputFile.status != "unavailable",
            WorkspaceLargeInputFile.deleted_at.is_(None),
        )
    )).scalar_one()
    reservations = (await db.execute(
        select(func.coalesce(func.sum(UploadQuotaReservation.reserved_bytes), 0)).where(
            UploadQuotaReservation.workspace_id == workspace_id,
            UploadQuotaReservation.status == "active",
            UploadQuotaReservation.expires_at > _now(),
            UploadQuotaReservation.deleted_at.is_(None),
        )
    )).scalar_one()
    return int(workspace_files or 0) + int(shared_files or 0) + int(large_inputs or 0) + int(reservations or 0)


async def _reserve_quota(
    db: AsyncSession,
    *,
    workspace_id: str,
    session_id: str,
    surface: str,
    actor_type: str,
    actor_id: str,
    reserved_bytes: int,
    quota_bytes: int,
    expires_at: datetime,
) -> UploadQuotaReservation:
    await db.execute(
        select(Workspace.id).where(
            Workspace.id == workspace_id,
            Workspace.deleted_at.is_(None),
        ).with_for_update()
    )
    used = await _workspace_used_bytes(db, workspace_id)
    if used + reserved_bytes > quota_bytes:
        raise WorkspaceQuotaExceededError(quota_bytes, used, reserved_bytes)
    reservation = UploadQuotaReservation(
        workspace_id=workspace_id,
        session_id=session_id,
        surface=surface,
        actor_type=actor_type,
        actor_id=actor_id,
        reserved_bytes=reserved_bytes,
        status="active",
        expires_at=expires_at,
        committed_source="",
        committed_file_id="",
    )
    db.add(reservation)
    await db.flush()
    return reservation


def _part_count(expected_size: int, part_size_bytes: int) -> int:
    if expected_size == 0:
        return 1
    return max(1, math.ceil(expected_size / part_size_bytes))


def _response_urls(workspace_id: str, session_id: str) -> tuple[str, str]:
    base = f"/api/v1/workspaces/{workspace_id}/uploads/sessions/{session_id}"
    return base, f"{base}/complete"


def _part_info(part: UploadPart) -> UploadPartInfo:
    return UploadPartInfo(
        part_number=part.part_number,
        size=part.size,
        checksum=part.checksum,
        etag=part.etag,
        status=part.status,
        uploaded_at=part.updated_at or part.created_at,
    )


async def get_session_parts(db: AsyncSession, session_id: str) -> list[UploadPart]:
    result = await db.execute(
        select(UploadPart).where(
            UploadPart.session_id == session_id,
            UploadPart.deleted_at.is_(None),
        ).order_by(UploadPart.part_number, UploadPart.created_at)
    )
    return list(result.scalars().all())


async def format_session_info(db: AsyncSession, session: UploadSession) -> UploadSessionInfo:
    status_url, complete_url = _response_urls(session.workspace_id, session.id)
    parts = await get_session_parts(db, session.id)
    return UploadSessionInfo(
        session_id=session.id,
        upload_mode=session.upload_mode,
        backend=session.storage_backend,
        part_size_bytes=session.part_size_bytes,
        part_count=session.part_count,
        expires_at=session.expires_at,
        effective_filename=session.effective_filename,
        conflict_strategy=session.conflict_strategy,
        status=session.status,
        received_size=session.received_size,
        expected_size=session.expected_size,
        surface=session.surface,
        status_url=status_url,
        complete_url=complete_url,
        parts=[_part_info(part) for part in parts],
    )


async def create_upload_session(
    db: AsyncSession,
    *,
    workspace_id: str,
    uploader_type: str,
    uploader_id: str,
    uploader_name: str,
    data: UploadSessionCreateRequest,
) -> UploadSession:
    filename = _safe_filename(data.filename)
    content_type = data.content_type or "application/octet-stream"
    checksum = _normalize_checksum(data.checksum)
    client_request_id = data.client_request_id.strip() if data.client_request_id else None

    existing_session = await _active_session_by_client_request(
        db,
        workspace_id=workspace_id,
        uploader_type=uploader_type,
        uploader_id=uploader_id,
        surface=data.surface,
        client_request_id=client_request_id,
    )
    if existing_session is not None:
        return existing_session

    await validate_upload_request(
        data.surface,
        filename=filename,
        content_type=content_type,
        size=data.expected_size,
        db=db,
    )
    policy = await build_upload_policy(db)
    if policy["security"]["scan_mode"] == "async_required" and not policy["security"]["scanner_configured"]:
        raise UploadScannerUnavailableError()

    surface_policy = policy["surfaces"][data.surface]
    part_size_bytes = int(surface_policy.get("chunk_size_bytes") or policy["surfaces"]["large_input"]["chunk_size_bytes"])
    part_size_bytes = max(part_size_bytes, math.ceil(max(data.expected_size, 1) / 10000))
    part_count = _part_count(data.expected_size, part_size_bytes)
    expires_at = _session_expires_at()
    parent_path = _validate_parent_path(data.parent_path)

    if data.surface == "shared_file":
        effective_filename, conflict_strategy = await _resolve_shared_filename(
            db,
            workspace_id,
            parent_path,
            filename,
            data.conflict_strategy,
            data.expected_existing_file_id,
        )
        purpose = data.purpose or "workspace_shared_file"
        owner_type = "none"
        owner_id = ""
        retention_policy = "manual"
    else:
        effective_filename = filename
        conflict_strategy = "none"
        purpose = data.purpose or "agent_input"
        owner_type = data.owner_type
        owner_id = data.owner_id or ""
        retention_policy = data.retention_policy
        if owner_type == "none" and retention_policy == "manual":
            retention_policy = "expires_at"

    session = UploadSession(
        workspace_id=workspace_id,
        surface=data.surface,
        uploader_type=uploader_type,
        uploader_id=uploader_id,
        uploader_name=uploader_name,
        filename=filename,
        effective_filename=effective_filename,
        content_type=content_type,
        expected_size=data.expected_size,
        received_size=0,
        checksum=checksum,
        upload_mode="backend_parts",
        storage_backend=str(policy["backend"]),
        part_size_bytes=part_size_bytes,
        part_count=part_count,
        status="pending",
        storage_key="",
        provider_upload_id="",
        parent_path=parent_path,
        purpose=purpose,
        owner_type=owner_type,
        owner_id=owner_id,
        retention_policy=retention_policy,
        conflict_strategy=conflict_strategy,
        expected_existing_file_id=data.expected_existing_file_id,
        client_request_id=client_request_id,
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()
    reservation = await _reserve_quota(
        db,
        workspace_id=workspace_id,
        session_id=session.id,
        surface=data.surface,
        actor_type=uploader_type,
        actor_id=uploader_id,
        reserved_bytes=data.expected_size,
        quota_bytes=int(policy["surfaces"]["shared_file"]["max_workspace_total_bytes"]),
        expires_at=expires_at,
    )
    session.quota_reservation_id = reservation.id
    await db.commit()
    await db.refresh(session)
    return session


async def get_upload_session(
    db: AsyncSession,
    *,
    workspace_id: str,
    session_id: str,
) -> UploadSession:
    session = (await db.execute(
        select(UploadSession).where(
            UploadSession.id == session_id,
            UploadSession.workspace_id == workspace_id,
            UploadSession.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if session is None:
        raise NotFoundError("上传会话不存在", "errors.upload.session_not_found")
    return session


def _ensure_session_writable(session: UploadSession) -> None:
    if session.status not in {"pending", "uploading"}:
        raise UploadSessionStateError("errors.upload.session_not_active")
    if session.expires_at <= _now():
        session.status = "expired"
        raise UploadSessionStateError("errors.upload.session_not_active")


async def upload_part(
    db: AsyncSession,
    *,
    workspace_id: str,
    session_id: str,
    part_number: int,
    chunks: AsyncIterable[bytes],
) -> UploadPartUploadResponse:
    session = await get_upload_session(db, workspace_id=workspace_id, session_id=session_id)
    _ensure_session_writable(session)
    if session.upload_mode != "backend_parts":
        raise UploadSessionStateError("errors.upload.direct_upload_unavailable")
    if part_number < 1 or part_number > session.part_count:
        raise BadRequestError("分片序号无效", "errors.upload.part_missing")

    existing = (await db.execute(
        select(UploadPart).where(
            UploadPart.session_id == session_id,
            UploadPart.part_number == part_number,
            UploadPart.status == "uploaded",
            UploadPart.deleted_at.is_(None),
        ).order_by(UploadPart.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    storage_key = _part_storage_key(session_id, part_number)
    path = _part_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("wb") as handle:
            async for chunk in chunks:
                total += len(chunk)
                if total > session.part_size_bytes:
                    raise storage_service.UploadTooLargeError(session.part_size_bytes, total)
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        await _delete_path(path)
        raise

    checksum = f"sha256:{digest.hexdigest()}"
    if existing is not None and existing.checksum == checksum and existing.size == total:
        await _delete_path(path)
        return UploadPartUploadResponse(
            session_id=session.id,
            part=_part_info(existing),
            received_size=session.received_size,
            status=session.status,
        )

    old_storage_key = existing.storage_key if existing is not None else ""
    old_size = existing.size if existing is not None else 0
    if existing is not None:
        existing.status = "replaced"
    part = UploadPart(
        session_id=session.id,
        workspace_id=workspace_id,
        part_number=part_number,
        size=total,
        checksum=checksum,
        etag=checksum,
        storage_key=storage_key,
        status="uploaded",
    )
    db.add(part)
    session.status = "uploading"
    session.received_size = max(0, session.received_size - old_size) + total
    await db.commit()
    await db.refresh(part)
    await db.refresh(session)
    if old_storage_key:
        await _delete_path(_part_path(old_storage_key))
    return UploadPartUploadResponse(
        session_id=session.id,
        part=_part_info(part),
        received_size=session.received_size,
        status=session.status,
    )


async def sign_part(
    db: AsyncSession,
    *,
    workspace_id: str,
    session_id: str,
    part_number: int,
) -> UploadPartSignResponse:
    session = await get_upload_session(db, workspace_id=workspace_id, session_id=session_id)
    _ensure_session_writable(session)
    if session.upload_mode != "s3_multipart":
        raise UploadSessionStateError("errors.upload.direct_upload_unavailable")
    return UploadPartSignResponse(part_number=part_number, upload_mode=session.upload_mode)


async def _uploaded_parts_for_complete(db: AsyncSession, session: UploadSession) -> list[UploadPart]:
    result = await db.execute(
        select(UploadPart).where(
            UploadPart.session_id == session.id,
            UploadPart.status == "uploaded",
            UploadPart.deleted_at.is_(None),
        ).order_by(UploadPart.part_number)
    )
    parts = list(result.scalars().all())
    numbers = [part.part_number for part in parts]
    expected_numbers = list(range(1, session.part_count + 1))
    if numbers != expected_numbers:
        raise BadRequestError("上传分片不完整", "errors.upload.part_missing")
    total = sum(part.size for part in parts)
    if total != session.expected_size:
        raise BadRequestError("上传文件大小与预期不一致", "errors.upload.checksum_mismatch")
    return parts


async def _create_shared_file_from_session(
    db: AsyncSession,
    session: UploadSession,
    *,
    storage_key: str,
    file_size: int,
    checksum: str,
    scan_status: str,
    scan_reason: str,
) -> tuple[BlackboardFile, str]:
    old_storage_key = ""
    if session.conflict_strategy == "overwrite":
        existing = await _existing_shared_file(db, session.workspace_id, session.parent_path, session.effective_filename)
        if existing is None or existing.id != session.expected_existing_file_id:
            raise ConflictError("目标路径已存在同名文件", "errors.upload.file_conflict")
        old_storage_key = existing.storage_key
        existing.storage_key = storage_key
        existing.file_size = file_size
        existing.content_type = session.content_type
        existing.uploader_type = session.uploader_type
        existing.uploader_id = session.uploader_id
        existing.uploader_name = session.uploader_name
        existing.checksum = checksum
        existing.scan_status = scan_status
        existing.scan_reason = scan_reason
        existing.scanned_at = _now() if scan_status == "skipped" else None
        return existing, old_storage_key

    if await _existing_shared_file(db, session.workspace_id, session.parent_path, session.effective_filename) is not None:
        raise ConflictError("目标路径已存在同名文件", "errors.upload.file_conflict")

    file_record = BlackboardFile(
        workspace_id=session.workspace_id,
        parent_path=session.parent_path,
        name=session.effective_filename,
        is_directory=False,
        file_size=file_size,
        content_type=session.content_type,
        storage_key=storage_key,
        uploader_type=session.uploader_type,
        uploader_id=session.uploader_id,
        uploader_name=session.uploader_name,
        checksum=checksum,
        scan_status=scan_status,
        scan_reason=scan_reason,
        scanned_at=_now() if scan_status == "skipped" else None,
    )
    db.add(file_record)
    await db.flush()
    return file_record, ""


async def _create_large_input_from_session(
    db: AsyncSession,
    session: UploadSession,
    *,
    storage_key: str,
    file_size: int,
    checksum: str,
    scan_status: str,
    scan_reason: str,
) -> WorkspaceLargeInputFile:
    now = _now()
    expires_at = None
    if session.retention_policy == "expires_at" or session.owner_type == "none":
        expires_at = now + timedelta(days=7)
    file_record = WorkspaceLargeInputFile(
        workspace_id=session.workspace_id,
        upload_session_id=session.id,
        uploader_type=session.uploader_type,
        uploader_id=session.uploader_id,
        uploader_name=session.uploader_name,
        purpose=session.purpose,
        owner_type=session.owner_type,
        owner_id=session.owner_id,
        retention_policy=session.retention_policy,
        retention_anchor_at=now,
        display_name=session.effective_filename,
        storage_key=storage_key,
        size=file_size,
        content_type=session.content_type,
        checksum=checksum,
        scan_status=scan_status,
        scan_reason=scan_reason,
        scanned_at=now if scan_status == "skipped" else None,
        status="available",
        expires_at=expires_at,
    )
    db.add(file_record)
    await db.flush()
    return file_record


async def complete_upload_session(
    db: AsyncSession,
    *,
    workspace_id: str,
    session_id: str,
    data: UploadCompleteRequest,
) -> dict:
    session = await get_upload_session(db, workspace_id=workspace_id, session_id=session_id)
    _ensure_session_writable(session)
    parts = await _uploaded_parts_for_complete(db, session)

    if data.parts is not None:
        request_parts = {part.part_number: part for part in data.parts}
        if sorted(request_parts) != list(range(1, session.part_count + 1)):
            raise BadRequestError("上传分片不完整", "errors.upload.part_missing")
        for part in parts:
            request_part = request_parts[part.part_number]
            if request_part.size is not None and request_part.size != part.size:
                raise BadRequestError("上传分片大小不一致", "errors.upload.checksum_mismatch")
            if request_part.checksum and _normalize_checksum(request_part.checksum) != part.checksum:
                raise BadRequestError("上传分片校验和不一致", "errors.upload.checksum_mismatch")

    expected_checksum = _normalize_checksum(data.checksum) or session.checksum
    storage_key = ""
    old_storage_key = ""
    try:
        storage_key, file_size, checksum_hex = await storage_service.upload_stream(
            _iter_part_files(parts),
            session.effective_filename,
            session.content_type,
            session.workspace_id,
            max_bytes=session.expected_size,
        )
        checksum = f"sha256:{checksum_hex}"
        if file_size != session.expected_size:
            raise BadRequestError("上传文件大小与预期不一致", "errors.upload.checksum_mismatch")
        if expected_checksum and _checksum_hex(expected_checksum) != checksum_hex:
            raise BadRequestError("上传文件校验和不一致", "errors.upload.checksum_mismatch")

        scan_status, scan_reason = await file_scan_service.get_initial_scan_state(db)
        if session.surface == "shared_file":
            file_record, old_storage_key = await _create_shared_file_from_session(
                db,
                session,
                storage_key=storage_key,
                file_size=file_size,
                checksum=checksum,
                scan_status=scan_status,
                scan_reason=scan_reason,
            )
            committed_source = "shared_file"
            committed_file_id = file_record.id
            display_name = file_record.name
            content_type = file_record.content_type
        else:
            file_record = await _create_large_input_from_session(
                db,
                session,
                storage_key=storage_key,
                file_size=file_size,
                checksum=checksum,
                scan_status=scan_status,
                scan_reason=scan_reason,
            )
            committed_source = "large_input"
            committed_file_id = file_record.id
            display_name = file_record.display_name
            content_type = file_record.content_type

        reservation = None
        if session.quota_reservation_id:
            reservation = (await db.execute(
                select(UploadQuotaReservation).where(
                    UploadQuotaReservation.id == session.quota_reservation_id,
                    UploadQuotaReservation.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
        if reservation is not None:
            reservation.status = "committed"
            reservation.committed_source = committed_source
            reservation.committed_file_id = committed_file_id
            reservation.released_at = _now()

        session.status = "completed"
        session.storage_key = storage_key
        session.received_size = file_size
        session.completed_at = _now()
        await db.commit()
    except Exception:
        if storage_key:
            try:
                await storage_service.delete_file(storage_key)
            except Exception:
                pass
        raise

    if old_storage_key:
        await file_cleanup_service.enqueue_storage_delete(
            db,
            workspace_id=session.workspace_id,
            source=file_cleanup_service.SOURCE_SHARED_FILE,
            source_id=committed_file_id,
            storage_key=old_storage_key,
        )
        await db.commit()
    if scan_status == "pending":
        await file_scan_service.enqueue_scan(
            db,
            workspace_id=session.workspace_id,
            source=committed_source,
            file_id=committed_file_id,
            storage_key=storage_key,
        )
        await db.commit()
    await _delete_path(_part_root(session.id))
    return {
        "session_id": session.id,
        "file": {
            "source": committed_source,
            "file_id": committed_file_id,
            "display_name": display_name,
            "size": file_size,
            "content_type": content_type,
            "scan_status": scan_status,
            "download_url_available": scan_status not in {"pending", "blocked", "failed"},
        },
    }


async def cancel_upload_session(
    db: AsyncSession,
    *,
    workspace_id: str,
    session_id: str,
) -> UploadCancelResponse:
    session = await get_upload_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status in {"completed", "cancelled", "expired"}:
        return UploadCancelResponse(session_id=session.id, status=session.status, released=False)
    session.status = "cancelled"
    released = False
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
            reservation.released_at = _now()
            released = True
    parts = await get_session_parts(db, session.id)
    for part in parts:
        if part.status in {"signed", "uploaded"}:
            part.status = "failed"
    await db.commit()
    await _delete_path(_part_root(session.id))
    return UploadCancelResponse(session_id=session.id, status="cancelled", released=released)

"""File reference and Agent download grant service."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_agent_file_download_base_url
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.models.agent_file_access_grant import AgentFileAccessGrant
from app.models.blackboard_file import BlackboardFile
from app.models.instance import Instance
from app.models.workspace_agent import WorkspaceAgent
from app.models.workspace_file import WorkspaceFile
from app.models.workspace_large_input_file import WorkspaceLargeInputFile
from app.models.workspace_message import WorkspaceMessage
from app.models.workspace_message_file_reference import WorkspaceMessageFileReference
from app.services import file_scan_service

SOURCE_CHAT_ATTACHMENT = "chat_attachment"
SOURCE_SHARED_FILE = "shared_file"
SOURCE_LARGE_INPUT = "large_input"
BLOCKING_SCAN_STATUSES = file_scan_service.BLOCKING_SCAN_STATUSES


def _input_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _snapshot(
    *,
    source: str,
    file_id: str,
    display_name: str,
    file_size: int,
    content_type: str,
    scan_status: str = "skipped",
    status: str = "available",
    sort_order: int = 0,
) -> dict:
    return {
        "source": source,
        "file_id": file_id,
        "display_name": display_name,
        "size": int(file_size or 0),
        "content_type": content_type or "",
        "scan_status": scan_status or "skipped",
        "status": status,
        "sort_order": sort_order,
        "download_url_available": status == "available" and (scan_status or "skipped") not in BLOCKING_SCAN_STATUSES,
    }


async def resolve_message_file_references(
    db: AsyncSession,
    workspace_id: str,
    *,
    file_references: list[Any] | None = None,
    legacy_file_ids: list[str] | None = None,
) -> list[dict]:
    requested: list[tuple[str, str]] = []
    for file_id in legacy_file_ids or []:
        requested.append((SOURCE_CHAT_ATTACHMENT, file_id))
    for item in file_references or []:
        source = str(_input_value(item, "source") or "").strip()
        file_id = str(_input_value(item, "file_id") or "").strip()
        if source and file_id:
            requested.append((source, file_id))

    resolved: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source, file_id in requested:
        key = (source, file_id)
        if key in seen:
            continue
        seen.add(key)
        sort_order = len(resolved)
        if source == SOURCE_CHAT_ATTACHMENT:
            ref = await _resolve_chat_attachment(db, workspace_id, file_id, sort_order)
        elif source == SOURCE_SHARED_FILE:
            ref = await _resolve_shared_file(db, workspace_id, file_id, sort_order)
        elif source == SOURCE_LARGE_INPUT:
            ref = await _resolve_large_input(db, workspace_id, file_id, sort_order)
        else:
            raise BadRequestError(
                "文件引用来源无效",
                message_key="errors.upload.file_reference_invalid_source",
            )
        resolved.append(ref)
    return resolved


async def _resolve_chat_attachment(
    db: AsyncSession,
    workspace_id: str,
    file_id: str,
    sort_order: int,
) -> dict:
    result = await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.id == file_id,
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.deleted_at.is_(None),
        )
    )
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise BadRequestError(
            "引用的对话附件不存在",
            message_key="errors.upload.file_reference_not_found",
        )
    return _snapshot(
        source=SOURCE_CHAT_ATTACHMENT,
        file_id=file_record.id,
        display_name=file_record.original_name,
        file_size=file_record.file_size,
        content_type=file_record.content_type,
        scan_status=getattr(file_record, "scan_status", "skipped"),
        sort_order=sort_order,
    )


async def _resolve_shared_file(
    db: AsyncSession,
    workspace_id: str,
    file_id: str,
    sort_order: int,
) -> dict:
    result = await db.execute(
        select(BlackboardFile).where(
            BlackboardFile.id == file_id,
            BlackboardFile.workspace_id == workspace_id,
            BlackboardFile.is_directory.is_(False),
            BlackboardFile.deleted_at.is_(None),
        )
    )
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise BadRequestError(
            "引用的共享文件不存在",
            message_key="errors.upload.file_reference_not_found",
        )
    return _snapshot(
        source=SOURCE_SHARED_FILE,
        file_id=file_record.id,
        display_name=file_record.name,
        file_size=file_record.file_size,
        content_type=file_record.content_type,
        scan_status=getattr(file_record, "scan_status", "skipped"),
        sort_order=sort_order,
    )


async def _resolve_large_input(
    db: AsyncSession,
    workspace_id: str,
    file_id: str,
    sort_order: int,
) -> dict:
    result = await db.execute(
        select(WorkspaceLargeInputFile).where(
            WorkspaceLargeInputFile.id == file_id,
            WorkspaceLargeInputFile.workspace_id == workspace_id,
            WorkspaceLargeInputFile.status == "available",
            WorkspaceLargeInputFile.deleted_at.is_(None),
        )
    )
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise BadRequestError(
            "引用的大文件输入不存在",
            message_key="errors.upload.file_reference_not_found",
        )
    now = datetime.now(timezone.utc)
    if file_record.expires_at is not None and file_record.expires_at <= now:
        raise BadRequestError(
            "引用的大文件输入已过期",
            message_key="errors.upload.file_reference_unavailable",
        )
    return _snapshot(
        source=SOURCE_LARGE_INPUT,
        file_id=file_record.id,
        display_name=file_record.display_name,
        file_size=file_record.size,
        content_type=file_record.content_type,
        scan_status=file_record.scan_status,
        status=file_record.status,
        sort_order=sort_order,
    )


def legacy_attachments_from_references(file_references: list[dict]) -> list[dict] | None:
    attachments = [
        {
            "id": ref["file_id"],
            "name": ref["display_name"],
            "size": ref["size"],
            "content_type": ref["content_type"],
        }
        for ref in file_references
        if ref.get("source") == SOURCE_CHAT_ATTACHMENT
    ]
    return attachments or None


def format_file_reference_response(ref: WorkspaceMessageFileReference) -> dict:
    return _snapshot(
        source=ref.source,
        file_id=ref.file_id,
        display_name=ref.display_name,
        file_size=ref.file_size,
        content_type=ref.content_type,
        scan_status=ref.scan_status,
        status=ref.status,
        sort_order=ref.sort_order,
    )


async def create_message_file_references(
    db: AsyncSession,
    *,
    message_id: str,
    workspace_id: str,
    file_references: list[dict] | None,
) -> None:
    for index, ref in enumerate(file_references or []):
        db.add(WorkspaceMessageFileReference(
            workspace_id=workspace_id,
            message_id=message_id,
            source=ref["source"],
            file_id=ref["file_id"],
            display_name=ref["display_name"],
            file_size=ref["size"],
            content_type=ref["content_type"],
            scan_status=ref.get("scan_status") or "skipped",
            status=ref.get("status") or "available",
            sort_order=ref.get("sort_order", index),
        ))


async def get_message_file_references(
    db: AsyncSession,
    message_ids: list[str],
) -> dict[str, list[dict]]:
    if not message_ids:
        return {}
    result = await db.execute(
        select(WorkspaceMessageFileReference).where(
            WorkspaceMessageFileReference.message_id.in_(message_ids),
            WorkspaceMessageFileReference.deleted_at.is_(None),
        ).order_by(
            WorkspaceMessageFileReference.message_id,
            WorkspaceMessageFileReference.sort_order,
            WorkspaceMessageFileReference.created_at,
        )
    )
    grouped: dict[str, list[dict]] = {}
    for ref in result.scalars().all():
        grouped.setdefault(ref.message_id, []).append(format_file_reference_response(ref))
    return grouped


def build_agent_download_url(workspace_id: str, grant_id: str) -> str:
    return f"{get_agent_file_download_base_url()}/workspaces/{workspace_id}/agent-file-grants/{grant_id}/download"


async def create_agent_grants_for_message(
    db: AsyncSession,
    *,
    workspace_id: str,
    message_id: str,
    recipient_agent_id: str,
) -> list[dict]:
    result = await db.execute(
        select(WorkspaceMessageFileReference).where(
            WorkspaceMessageFileReference.workspace_id == workspace_id,
            WorkspaceMessageFileReference.message_id == message_id,
            WorkspaceMessageFileReference.deleted_at.is_(None),
        ).order_by(WorkspaceMessageFileReference.sort_order)
    )
    refs = list(result.scalars().all())
    enriched: list[dict] = []
    for ref in refs:
        grant = await _get_or_create_agent_grant(db, ref, recipient_agent_id)
        payload = format_file_reference_response(ref)
        payload["download_url"] = build_agent_download_url(workspace_id, grant.id)
        payload["download_url_kind"] = "agent_grant"
        enriched.append(payload)
    return enriched


async def _get_or_create_agent_grant(
    db: AsyncSession,
    ref: WorkspaceMessageFileReference,
    recipient_agent_id: str,
) -> AgentFileAccessGrant:
    result = await db.execute(
        select(AgentFileAccessGrant).where(
            AgentFileAccessGrant.file_reference_id == ref.id,
            AgentFileAccessGrant.recipient_agent_id == recipient_agent_id,
            AgentFileAccessGrant.revoked_at.is_(None),
            AgentFileAccessGrant.deleted_at.is_(None),
        )
    )
    grant = result.scalar_one_or_none()
    if grant is not None:
        return grant
    grant = AgentFileAccessGrant(
        workspace_id=ref.workspace_id,
        message_id=ref.message_id,
        file_reference_id=ref.id,
        recipient_agent_id=recipient_agent_id,
        source=ref.source,
        file_id=ref.file_id,
        display_name=ref.display_name,
        file_size=ref.file_size,
        content_type=ref.content_type,
        permissions=["download"],
    )
    db.add(grant)
    await db.flush()
    return grant


async def get_agent_grant_for_download(
    db: AsyncSession,
    *,
    workspace_id: str,
    grant_id: str,
    agent: Instance,
) -> AgentFileAccessGrant:
    result = await db.execute(
        select(AgentFileAccessGrant).where(
            AgentFileAccessGrant.id == grant_id,
            AgentFileAccessGrant.workspace_id == workspace_id,
            AgentFileAccessGrant.deleted_at.is_(None),
        )
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        raise NotFoundError("文件访问授权不存在", "errors.upload.file_access_grant_not_found")
    if grant.revoked_at is not None or grant.status != "active":
        raise ForbiddenError("文件访问授权已撤销", "errors.upload.file_access_grant_revoked")
    if grant.recipient_agent_id != agent.id:
        raise ForbiddenError("Agent 无权使用该文件访问授权", "errors.upload.file_access_agent_mismatch")

    active_agent = await db.execute(
        select(WorkspaceAgent.id).where(
            WorkspaceAgent.workspace_id == grant.workspace_id,
            WorkspaceAgent.instance_id == agent.id,
            WorkspaceAgent.deleted_at.is_(None),
        ).limit(1)
    )
    if agent.workspace_id != grant.workspace_id and active_agent.scalar_one_or_none() is None:
        raise ForbiddenError("Agent 不属于该办公室", "errors.upload.file_access_agent_mismatch")

    message = (await db.execute(
        select(WorkspaceMessage.id).where(
            WorkspaceMessage.id == grant.message_id,
            WorkspaceMessage.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if message is None:
        raise NotFoundError("消息已删除，文件访问授权失效", "errors.upload.file_access_grant_not_found")
    return grant


async def resolve_grant_source_file(
    db: AsyncSession,
    grant: AgentFileAccessGrant,
) -> dict:
    if grant.source == SOURCE_CHAT_ATTACHMENT:
        result = await db.execute(
            select(WorkspaceFile).where(
                WorkspaceFile.id == grant.file_id,
                WorkspaceFile.workspace_id == grant.workspace_id,
                WorkspaceFile.deleted_at.is_(None),
            )
        )
        source_file = result.scalar_one_or_none()
        if source_file is None:
            raise NotFoundError("源文件不存在", "errors.upload.file_reference_not_found")
        return {
            "storage_key": source_file.storage_key,
            "filename": source_file.original_name,
            "content_type": source_file.content_type,
            "scan_status": getattr(source_file, "scan_status", "skipped"),
        }

    if grant.source == SOURCE_SHARED_FILE:
        result = await db.execute(
            select(BlackboardFile).where(
                BlackboardFile.id == grant.file_id,
                BlackboardFile.workspace_id == grant.workspace_id,
                BlackboardFile.is_directory.is_(False),
                BlackboardFile.deleted_at.is_(None),
            )
        )
        source_file = result.scalar_one_or_none()
        if source_file is None:
            raise NotFoundError("源文件不存在", "errors.upload.file_reference_not_found")
        return {
            "storage_key": source_file.storage_key,
            "filename": source_file.name,
            "content_type": source_file.content_type,
            "scan_status": getattr(source_file, "scan_status", "skipped"),
        }

    if grant.source == SOURCE_LARGE_INPUT:
        result = await db.execute(
            select(WorkspaceLargeInputFile).where(
                WorkspaceLargeInputFile.id == grant.file_id,
                WorkspaceLargeInputFile.workspace_id == grant.workspace_id,
                WorkspaceLargeInputFile.status == "available",
                WorkspaceLargeInputFile.deleted_at.is_(None),
            )
        )
        source_file = result.scalar_one_or_none()
        if source_file is None:
            raise NotFoundError("源文件不存在", "errors.upload.file_reference_not_found")
        now = datetime.now(timezone.utc)
        if source_file.expires_at is not None and source_file.expires_at <= now:
            raise NotFoundError("源文件已过期", "errors.upload.file_reference_not_found")
        return {
            "storage_key": source_file.storage_key,
            "filename": source_file.display_name,
            "content_type": source_file.content_type,
            "scan_status": source_file.scan_status,
        }

    raise BadRequestError("文件引用来源无效", message_key="errors.upload.file_reference_invalid_source")


def ensure_scan_allows_download(scan_status: str) -> None:
    file_scan_service.assert_download_allowed(scan_status)


async def mark_agent_grant_accessed(db: AsyncSession, grant: AgentFileAccessGrant) -> None:
    grant.last_accessed_at = datetime.now(timezone.utc)
    grant.access_count = (grant.access_count or 0) + 1
    await db.commit()

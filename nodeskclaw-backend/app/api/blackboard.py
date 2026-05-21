"""Blackboard shared-file API endpoints."""

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.security import get_auth_actor
from app.schemas.workspace import (
    FileCopyRequest,
    FileWriteRequest,
    MkdirRequest,
)
from app.services import workspace_service
from app.services.workspace_actor_access import (
    require_workspace_actor_access,
    require_workspace_actor_member,
)

router = APIRouter()


def _ok(data=None, message: str = "success"):
    from app.api.workspaces import _ok as ws_ok
    return ws_ok(data, message)


def _get_current_user_or_agent_dep():
    from app.core.security import get_current_user_or_agent
    return get_current_user_or_agent


def _broadcast(workspace_id: str, event_type: str, data: dict):
    from app.api.workspaces import broadcast_event
    broadcast_event(workspace_id, event_type, data)


def _caller_info() -> tuple[str, str, str]:
    """Return (author_type, author_id, author_name) from AuthActor context."""
    actor = get_auth_actor()
    if actor is None:
        return "human", "", ""
    return actor.actor_type, actor.actor_id, actor.actor_name


async def _enforce_agent_blackboard_topology(
    workspace_id: str, db: AsyncSession,
) -> None:
    actor = get_auth_actor()
    if actor is None or actor.actor_type != "agent":
        return
    from app.services.corridor_router import check_blackboard_access
    allowed, reason = await check_blackboard_access(workspace_id, actor.actor_id, db)
    if not allowed:
        raise HTTPException(status_code=403, detail={
            "error_code": 40360,
            "message_key": f"errors.topology.{reason}",
            "message": f"Topology access denied: {reason}",
        })


# ── Shared Files ──────────────────────────────────────

@router.get("/{workspace_id}/blackboard/files")
async def list_files(
    workspace_id: str,
    parent_path: str = Query("/"),
    db: AsyncSession = Depends(get_db),
    user=Depends(_get_current_user_or_agent_dep()),
):
    await require_workspace_actor_member(workspace_id, user, db)
    await _enforce_agent_blackboard_topology(workspace_id, db)
    files = await workspace_service.list_shared_files(db, workspace_id, parent_path)
    return _ok([f.model_dump(mode="json") for f in files])


@router.post("/{workspace_id}/blackboard/files/mkdir")
async def mkdir(
    workspace_id: str,
    data: MkdirRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(_get_current_user_or_agent_dep()),
):
    await require_workspace_actor_access(workspace_id, user, "edit_blackboard", db)
    await _enforce_agent_blackboard_topology(workspace_id, db)
    utype, uid, uname = _caller_info()
    info = await workspace_service.create_shared_directory(
        db, workspace_id, utype, uid, uname, data,
    )
    _broadcast(workspace_id, "file:created", info.model_dump(mode="json"))
    return _ok(info.model_dump(mode="json"))


@router.post("/{workspace_id}/blackboard/files/upload")
async def upload_file(
    workspace_id: str,
    data: FileWriteRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(_get_current_user_or_agent_dep()),
):
    await require_workspace_actor_access(workspace_id, user, "edit_blackboard", db)
    await _enforce_agent_blackboard_topology(workspace_id, db)
    utype, uid, uname = _caller_info()
    info = await workspace_service.upload_shared_file(
        db, workspace_id, utype, uid, uname, data,
    )
    _broadcast(workspace_id, "file:uploaded", info.model_dump(mode="json"))
    return _ok(info.model_dump(mode="json"))


@router.post("/{workspace_id}/blackboard/files/upload-multipart")
async def upload_file_multipart(
    workspace_id: str,
    file: UploadFile,
    parent_path: str = Form("/"),
    filename: str | None = Form(None),
    content_type: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(_get_current_user_or_agent_dep()),
):
    await require_workspace_actor_access(workspace_id, user, "edit_blackboard", db)
    await _enforce_agent_blackboard_topology(workspace_id, db)
    utype, uid, uname = _caller_info()
    file_bytes = await file.read()
    resolved_filename = filename or file.filename or "untitled"
    resolved_ct = content_type or file.content_type or "application/octet-stream"
    info = await workspace_service.upload_shared_file_bytes(
        db, workspace_id, utype, uid, uname,
        filename=resolved_filename,
        file_bytes=file_bytes,
        content_type=resolved_ct,
        parent_path=parent_path,
    )
    _broadcast(workspace_id, "file:uploaded", info.model_dump(mode="json"))
    return _ok(info.model_dump(mode="json"))


@router.post("/{workspace_id}/blackboard/files/{file_id}/copy")
async def copy_file(
    workspace_id: str,
    file_id: str,
    data: FileCopyRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(_get_current_user_or_agent_dep()),
):
    await require_workspace_actor_access(workspace_id, user, "edit_blackboard", db)
    await _enforce_agent_blackboard_topology(workspace_id, db)
    utype, uid, uname = _caller_info()
    info = await workspace_service.copy_shared_file(
        db, workspace_id, utype, uid, uname,
        file_id, data.target_parent_path, data.target_filename,
    )
    if info is None:
        return _ok(None, "source file not found")
    _broadcast(workspace_id, "file:uploaded", info.model_dump(mode="json"))
    return _ok(info.model_dump(mode="json"))


@router.get("/{workspace_id}/blackboard/files/{file_id}/url")
async def get_file_url(
    workspace_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(_get_current_user_or_agent_dep()),
):
    await require_workspace_actor_member(workspace_id, user, db)
    await _enforce_agent_blackboard_topology(workspace_id, db)
    url = await workspace_service.get_shared_file_url(db, workspace_id, file_id)
    if url is None:
        return _ok(None, "not found")
    return _ok({"url": url})


@router.get("/{workspace_id}/blackboard/files/{file_id}/content")
async def read_file_content(
    workspace_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(_get_current_user_or_agent_dep()),
):
    await require_workspace_actor_member(workspace_id, user, db)
    await _enforce_agent_blackboard_topology(workspace_id, db)
    result = await workspace_service.read_shared_file(db, workspace_id, file_id)
    if result is None:
        return _ok(None, "not found")
    b64, ct = result
    return _ok({"content": b64, "content_type": ct})


@router.delete("/{workspace_id}/blackboard/files/{file_id}")
async def delete_file(
    workspace_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(_get_current_user_or_agent_dep()),
):
    await require_workspace_actor_access(workspace_id, user, "edit_blackboard", db)
    await _enforce_agent_blackboard_topology(workspace_id, db)
    ok = await workspace_service.delete_shared_file(db, workspace_id, file_id)
    if ok:
        _broadcast(workspace_id, "file:deleted", {"file_id": file_id})
    return _ok({"deleted": ok})

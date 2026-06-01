from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.security import get_auth_actor, get_current_user, get_current_user_or_agent
from app.schemas.upload import UploadCompleteRequest, UploadSessionCreateRequest
from app.services import storage_service, upload_session_service
from app.services.upload_policy_service import build_upload_policy
from app.services.workspace_actor_access import require_workspace_actor_access, require_workspace_actor_member

router = APIRouter()


def _ok(data=None, message: str = "success"):
    return {"code": 0, "message": message, "data": data}


def _caller_info(user) -> tuple[str, str, str]:
    actor = get_auth_actor()
    if actor is not None:
        return actor.actor_type, actor.actor_id, actor.actor_name
    return "user", getattr(user, "id", ""), getattr(user, "name", "")


async def _enforce_agent_blackboard_topology(workspace_id: str, db: AsyncSession) -> None:
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


async def _require_upload_permission(
    workspace_id: str,
    user,
    db: AsyncSession,
    data: UploadSessionCreateRequest,
) -> None:
    if data.surface == "shared_file":
        await require_workspace_actor_access(workspace_id, user, "edit_blackboard", db)
        await _enforce_agent_blackboard_topology(workspace_id, db)
        return
    permission = "edit_blackboard" if data.purpose == "task_input" else "send_chat"
    await require_workspace_actor_access(workspace_id, user, permission, db)


def _map_upload_error(exc: Exception) -> HTTPException:
    if isinstance(exc, storage_service.UploadTooLargeError):
        return HTTPException(status_code=413, detail={
            "error_code": 41310,
            "message_key": "errors.upload.file_too_large",
            "message": "文件超过当前上传上限",
            "message_params": {
                "limit_mb": str(round(exc.limit_bytes / 1024 / 1024, 2)),
                "actual_mb": str(round(exc.actual_bytes / 1024 / 1024, 2)),
            },
        })
    if isinstance(exc, storage_service.StorageUnavailableError):
        return HTTPException(status_code=503, detail={
            "error_code": 50310,
            "message_key": "errors.upload.storage_unavailable",
            "message": "文件存储服务不可用",
            "details": {"reason_code": exc.reason_code},
        })
    if isinstance(exc, upload_session_service.WorkspaceQuotaExceededError):
        return HTTPException(status_code=507, detail={
            "error_code": 50710,
            "message_key": "errors.upload.workspace_quota_exceeded",
            "message": "工作区文件配额不足",
            "details": {
                "quota_bytes": exc.quota_bytes,
                "used_bytes": exc.used_bytes,
                "requested_bytes": exc.requested_bytes,
            },
        })
    if isinstance(exc, upload_session_service.UploadScannerUnavailableError):
        return HTTPException(status_code=503, detail={
            "error_code": 50311,
            "message_key": "errors.upload.scanner_unavailable",
            "message": "文件扫描服务不可用",
        })
    if isinstance(exc, upload_session_service.UploadSessionStateError):
        return HTTPException(status_code=409, detail={
            "error_code": 40910,
            "message_key": exc.message_key,
            "message": "上传会话当前不可写",
        })
    return HTTPException(status_code=500, detail={
        "error_code": 50000,
        "message_key": "errors.system.internal_error",
        "message": "服务器内部错误",
    })


@router.get("/upload/policy")
async def get_upload_policy(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    return _ok(await build_upload_policy(db))


@router.post("/workspaces/{workspace_id}/uploads/sessions")
async def create_upload_session(
    workspace_id: str,
    data: UploadSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
):
    await _require_upload_permission(workspace_id, user, db, data)
    uploader_type, uploader_id, uploader_name = _caller_info(user)
    try:
        session = await upload_session_service.create_upload_session(
            db,
            workspace_id=workspace_id,
            uploader_type=uploader_type,
            uploader_id=uploader_id,
            uploader_name=uploader_name,
            data=data,
        )
    except (
        storage_service.UploadTooLargeError,
        storage_service.StorageUnavailableError,
        upload_session_service.WorkspaceQuotaExceededError,
        upload_session_service.UploadScannerUnavailableError,
    ) as exc:
        raise _map_upload_error(exc) from exc
    return _ok((await upload_session_service.format_session_info(db, session)).model_dump(mode="json"))


@router.get("/workspaces/{workspace_id}/uploads/sessions/{session_id}")
async def get_upload_session(
    workspace_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
):
    await require_workspace_actor_member(workspace_id, user, db)
    session = await upload_session_service.get_upload_session(
        db,
        workspace_id=workspace_id,
        session_id=session_id,
    )
    return _ok((await upload_session_service.format_session_info(db, session)).model_dump(mode="json"))


@router.post("/workspaces/{workspace_id}/uploads/sessions/{session_id}/parts/{part_number}/sign")
async def sign_upload_part(
    workspace_id: str,
    session_id: str,
    part_number: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
):
    await require_workspace_actor_member(workspace_id, user, db)
    try:
        result = await upload_session_service.sign_part(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            part_number=part_number,
        )
    except upload_session_service.UploadSessionStateError as exc:
        raise _map_upload_error(exc) from exc
    return _ok(result.model_dump(mode="json"))


@router.put("/workspaces/{workspace_id}/uploads/sessions/{session_id}/parts/{part_number}")
async def upload_session_part(
    workspace_id: str,
    session_id: str,
    part_number: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
):
    await require_workspace_actor_member(workspace_id, user, db)
    try:
        result = await upload_session_service.upload_part(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            part_number=part_number,
            chunks=request.stream(),
        )
    except (
        storage_service.UploadTooLargeError,
        upload_session_service.UploadSessionStateError,
    ) as exc:
        raise _map_upload_error(exc) from exc
    return _ok(result.model_dump(mode="json"))


@router.post("/workspaces/{workspace_id}/uploads/sessions/{session_id}/complete")
async def complete_upload_session(
    workspace_id: str,
    session_id: str,
    data: UploadCompleteRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
):
    await require_workspace_actor_member(workspace_id, user, db)
    try:
        result = await upload_session_service.complete_upload_session(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            data=data,
        )
    except (
        storage_service.UploadTooLargeError,
        storage_service.StorageUnavailableError,
        upload_session_service.UploadSessionStateError,
    ) as exc:
        raise _map_upload_error(exc) from exc
    return _ok(result)


@router.post("/workspaces/{workspace_id}/uploads/sessions/{session_id}/cancel")
async def cancel_upload_session(
    workspace_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
):
    await require_workspace_actor_member(workspace_id, user, db)
    result = await upload_session_service.cancel_upload_session(
        db,
        workspace_id=workspace_id,
        session_id=session_id,
    )
    return _ok(result.model_dump(mode="json"))

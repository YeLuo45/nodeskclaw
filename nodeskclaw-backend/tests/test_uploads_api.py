"""Tests for upload API routes and session lifecycle."""
from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, ForbiddenError
from app.services import upload_session_service, upload_policy_service
from app.services import file_scan_service, file_cleanup_service
from app.schemas.upload import UploadSessionCreateRequest


class _ScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _ScalarsResult:
    def __init__(self, values: list) -> None:
        self._values = values

    def scalars(self):
        return self

    def all(self) -> list:
        return self._values


class _SequenceDb:
    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.added: list = []
        self.flushed = 0
        self.committed = False
        self.refreshed: list = []

    async def execute(self, _stmt):
        return self._results.pop(0)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for index, obj in enumerate(self.added, 1):
            if not getattr(obj, "id", None):
                obj.id = f"generated-{index}"

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj) -> None:
        self.refreshed.append(obj)


def _policy(**surface_overrides) -> dict:
    p = {
        "backend": "local",
        "storage_status": "available",
        "storage_reason_code": "",
        "direct_upload_supported": False,
        "surfaces": {
            "chat_attachment": {"max_file_size_bytes": 20 * 1024 * 1024},
            "shared_file": {
                "max_file_size_bytes": 200 * 1024 * 1024,
                "max_workspace_total_bytes": 10 * 1024 * 1024 * 1024,
            },
            "large_input": {
                "max_file_size_bytes": 2 * 1024 * 1024 * 1024,
                "chunk_size_bytes": 8 * 1024 * 1024,
            },
        },
        "security": {
            "scan_mode": "metadata_only",
            "scanner_configured": False,
        },
    }
    for k, v in surface_overrides.items():
        if k in p["surfaces"]:
            p["surfaces"][k].update(v)
    return p


@pytest.mark.asyncio
async def test_create_session_conflict_strategy_fail(monkeypatch) -> None:
    """conflict_strategy='fail' with existing file should raise."""

    async def validate_upload_request(*_args, **_kwargs) -> None:
        return None

    async def build_upload_policy(_db):
        return _policy()

    monkeypatch.setattr(upload_session_service, "validate_upload_request", validate_upload_request)
    monkeypatch.setattr(upload_session_service, "build_upload_policy", build_upload_policy)

    existing_file = SimpleNamespace(
        id="existing-file-1",
        file_size=2048,
        updated_at=datetime.now(timezone.utc),
    )
    db = _SequenceDb([
        _ScalarResult(None),
        _ScalarResult(existing_file),
        _ScalarResult("ws-1"),
    ])

    with pytest.raises(ConflictError) as exc:
        await upload_session_service.create_upload_session(
            db,
            workspace_id="ws-1",
            uploader_type="user",
            uploader_id="user-1",
            uploader_name="User",
            data=UploadSessionCreateRequest(
                surface="shared_file",
                filename="report.pdf",
                content_type="application/pdf",
                expected_size=1024,
                client_request_id="req-1",
                conflict_strategy="fail",
                parent_path="/docs/",
            ),
        )

    assert exc.value.message_key == "errors.upload.file_conflict"


@pytest.mark.asyncio
async def test_create_session_idempotent_with_same_client_request_id(monkeypatch) -> None:
    """Re-using client_request_id returns existing session instead of creating a new one."""

    async def validate_upload_request(*_args, **_kwargs) -> None:
        return None

    async def build_upload_policy(_db):
        return _policy()

    monkeypatch.setattr(upload_session_service, "validate_upload_request", validate_upload_request)
    monkeypatch.setattr(upload_session_service, "build_upload_policy", build_upload_policy)

    existing_session = SimpleNamespace(
        id="session-existing",
        workspace_id="ws-1",
        surface="shared_file",
        status="uploading",
        part_count=3,
        part_size_bytes=8 * 1024 * 1024,
        expected_size=20 * 1024 * 1024,
        effective_filename="report.pdf",
        content_type="application/pdf",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db = _SequenceDb([
        _ScalarResult(existing_session),
    ])

    result = await upload_session_service.create_upload_session(
        db,
        workspace_id="ws-1",
        uploader_type="user",
        uploader_id="user-1",
        uploader_name="User",
        data=UploadSessionCreateRequest(
            surface="shared_file",
            filename="report.pdf",
            content_type="application/pdf",
            expected_size=20 * 1024 * 1024,
            client_request_id="req-1",
        ),
    )

    assert result.id == "session-existing"
    assert db.committed is False


@pytest.mark.asyncio
async def test_cancel_session_releases_quota(monkeypatch) -> None:
    """Canceling a session releases the quota reservation."""
    now = datetime.now(timezone.utc)
    session = SimpleNamespace(
        id="session-1",
        workspace_id="ws-1",
        surface="shared_file",
        status="uploading",
        quota_reservation_id="reservation-1",
        expires_at=now + timedelta(hours=1),
    )
    reservation = SimpleNamespace(
        id="reservation-1",
        status="active",
        released_at=None,
    )

    async def delete_file(_key):
        return None

    monkeypatch.setattr(upload_session_service.storage_service, "delete_file", delete_file)

    db = _SequenceDb([
        _ScalarResult(session),
        _ScalarResult(reservation),
        _ScalarsResult([]),
    ])

    await upload_session_service.cancel_upload_session(db, workspace_id="ws-1", session_id="session-1")

    assert session.status == "cancelled"
    assert reservation.status == "released"
    assert reservation.released_at is not None
    assert db.committed is True


@pytest.mark.asyncio
async def test_session_expire_releases_quota(monkeypatch) -> None:
    """Expired sessions get their quota released by cleanup task."""
    now = datetime.now(timezone.utc)
    session = SimpleNamespace(
        id="session-1",
        workspace_id="ws-1",
        status="uploading",
        quota_reservation_id="reservation-1",
        expires_at=now - timedelta(minutes=5),
    )
    reservation = SimpleNamespace(
        id="reservation-1",
        status="active",
        released_at=None,
    )

    async def delete_file(_key):
        return None

    monkeypatch.setattr(upload_session_service.storage_service, "delete_file", delete_file)

    db = _SequenceDb([
        _ScalarsResult([session]),
        _ScalarResult(reservation),
        _ScalarsResult([]),
    ])

    await file_cleanup_service.expire_upload_sessions(db)

    assert session.status == "expired"
    assert reservation.status == "released"


@pytest.mark.asyncio
async def test_upload_policy_returns_complete_structure(monkeypatch) -> None:
    """build_upload_policy returns all required fields."""
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "get_storage_status", lambda: {
        "backend": "local",
        "storage_status": "available",
        "storage_reason_code": "",
        "direct_upload_supported": False,
    })

    policy = await upload_policy_service.build_upload_policy(None)

    assert "surfaces" in policy
    assert "chat_attachment" in policy["surfaces"]
    assert "shared_file" in policy["surfaces"]
    assert "large_input" in policy["surfaces"]
    assert "gateway" in policy
    assert "proxy_body_size_bytes" in policy["gateway"]
    assert "security" in policy
    assert "scan_mode" in policy["security"]
    assert policy["surfaces"]["chat_attachment"]["max_file_size_bytes"] > 0
    assert policy["surfaces"]["shared_file"]["max_file_size_bytes"] > 0

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.exceptions import ForbiddenError
from app.services import file_cleanup_service, file_scan_service


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
        self.flushed = False
        self.committed = False

    async def execute(self, _stmt):
        return self._results.pop(0)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True
        for index, obj in enumerate(self.added, 1):
            if not getattr(obj, "id", None):
                obj.id = f"job-{index}"

    async def commit(self) -> None:
        self.committed = True


def _async_required_policy() -> dict:
    return {
        "security": {
            "scan_mode": "async_required",
            "scanner_configured": True,
            "scanner_max_file_size_bytes": 1024 * 1024,
        }
    }


def test_assert_download_allowed_rejects_pending_scan() -> None:
    with pytest.raises(ForbiddenError) as exc:
        file_scan_service.assert_download_allowed("pending")

    assert exc.value.message_key == "errors.upload.file_scan_pending"


@pytest.mark.asyncio
async def test_enqueue_scan_creates_single_pending_job(monkeypatch) -> None:
    async def build_upload_policy(_db):
        return _async_required_policy()

    monkeypatch.setattr(file_scan_service, "build_upload_policy", build_upload_policy)
    db = _SequenceDb([_ScalarResult(None)])

    job = await file_scan_service.enqueue_scan(
        db,
        workspace_id="ws-1",
        source="shared_file",
        file_id="file-1",
        storage_key="key-1",
    )

    assert job is db.added[0]
    assert job.status == "pending"
    assert job.storage_key == "key-1"
    assert db.flushed is True


@pytest.mark.asyncio
async def test_storage_delete_worker_marks_success(monkeypatch) -> None:
    deleted: list[str] = []

    async def delete_file(key: str) -> None:
        deleted.append(key)

    monkeypatch.setattr(file_cleanup_service.storage_service, "delete_file", delete_file)
    job = SimpleNamespace(
        id="delete-1",
        storage_key="key-1",
        status="pending",
        attempt_count=0,
        last_error="",
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db = _SequenceDb([_ScalarsResult([job])])

    result = await file_cleanup_service.run_storage_delete_retry_worker(db)

    assert result["succeeded"] == 1
    assert job.status == "succeeded"
    assert deleted == ["key-1"]
    assert db.committed is True


@pytest.mark.asyncio
async def test_storage_delete_worker_retries_failure(monkeypatch) -> None:
    async def delete_file(_key: str) -> None:
        raise RuntimeError("storage down")

    monkeypatch.setattr(file_cleanup_service.storage_service, "delete_file", delete_file)
    job = SimpleNamespace(
        id="delete-1",
        storage_key="key-1",
        status="pending",
        attempt_count=0,
        last_error="",
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db = _SequenceDb([_ScalarsResult([job])])

    result = await file_cleanup_service.run_storage_delete_retry_worker(db, max_attempts=2)

    assert result["retrying"] == 1
    assert job.status == "retrying"
    assert job.attempt_count == 1
    assert "storage down" in job.last_error
    assert db.committed is True

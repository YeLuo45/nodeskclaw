from types import SimpleNamespace

import pytest

from app.core.config import get_agent_file_download_base_url, settings
from app.services import storage_service
from app.core.exceptions import BadRequestError
from app.services import upload_policy_service
from app.services.upload_policy_service import build_upload_policy


def test_agent_file_download_base_url_normalizes_api_prefix() -> None:
    cfg = SimpleNamespace(
        AGENT_FILE_DOWNLOAD_BASE_URL="https://agent-download.example.com/api/v1/",
        AGENT_API_BASE_URL="https://backend.example.com/api/v1",
    )

    assert get_agent_file_download_base_url(cfg) == "https://agent-download.example.com/api/v1"


def test_agent_file_download_base_url_falls_back_to_agent_api_base_url() -> None:
    cfg = SimpleNamespace(
        AGENT_FILE_DOWNLOAD_BASE_URL="",
        AGENT_API_BASE_URL="https://backend.example.com",
    )

    assert get_agent_file_download_base_url(cfg) == "https://backend.example.com/api/v1"


def test_storage_status_does_not_fallback_to_local_for_partial_s3(monkeypatch) -> None:
    monkeypatch.setattr(storage_service.settings, "UPLOAD_STORAGE_BACKEND", "auto")
    monkeypatch.setattr(storage_service.settings, "S3_ENDPOINT", "https://s3.example.com")
    monkeypatch.setattr(storage_service.settings, "S3_BUCKET", "")
    monkeypatch.setattr(storage_service.settings, "S3_ACCESS_KEY_ID", "")
    monkeypatch.setattr(storage_service.settings, "S3_SECRET_ACCESS_KEY", "")

    status = storage_service.get_storage_status()

    assert status["backend"] == "s3"
    assert status["storage_status"] == "unavailable"
    assert status["storage_reason_code"] == "s3_config_incomplete"


@pytest.mark.asyncio
async def test_upload_policy_exposes_surface_limits(monkeypatch) -> None:
    monkeypatch.setattr(storage_service, "get_storage_status", lambda: {
        "backend": "local",
        "storage_status": "available",
        "storage_reason_code": "",
        "direct_upload_supported": False,
    })

    policy = await build_upload_policy(None)

    assert policy["surfaces"]["chat_attachment"]["max_file_size_bytes"] == (
        settings.UPLOAD_CHAT_ATTACHMENT_MAX_MB * 1024 * 1024
    )
    assert policy["surfaces"]["chat_attachment"]["recommended_alternative"] == "shared_file"
    assert policy["gateway"]["proxy_body_size_bytes"] == (
        settings.UPLOAD_GATEWAY_PROXY_BODY_SIZE_MB * 1024 * 1024
    )


@pytest.mark.asyncio
async def test_async_scan_config_cannot_disable_scanner(monkeypatch) -> None:
    async def get_config(key, _db):
        values = {
            "upload_security_scan_mode": "async_required",
            "upload_scanner_provider": "http",
            "upload_scanner_endpoint": "http://scanner.local/scan",
        }
        return values.get(key)

    monkeypatch.setattr(upload_policy_service.config_service, "get_config", get_config)

    with pytest.raises(BadRequestError) as exc:
        await upload_policy_service.validate_upload_config_value(
            "upload_scanner_provider",
            "none",
            object(),
        )

    assert exc.value.message_key == "errors.upload.scanner_unavailable"

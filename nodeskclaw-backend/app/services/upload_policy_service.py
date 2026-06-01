"""Upload policy service shared by API, portal, and file services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.services import config_service
from app.services import storage_service


UPLOAD_CONFIG_KEYS = {
    "upload_chat_attachment_max_mb",
    "upload_chat_attachment_max_count",
    "upload_chat_attachment_retention_days",
    "upload_shared_file_max_mb",
    "upload_large_file_max_mb",
    "upload_chunked_upload_threshold_mb",
    "upload_chunk_size_mb",
    "upload_workspace_quota_mb",
    "upload_blocked_extensions",
    "upload_allowed_content_types",
    "upload_gateway_proxy_body_size_mb",
    "upload_proxy_read_timeout_seconds",
    "upload_proxy_send_timeout_seconds",
    "upload_security_scan_mode",
    "upload_scanner_provider",
    "upload_scanner_endpoint",
    "upload_scanner_timeout_seconds",
    "upload_scanner_max_retries",
    "upload_scanner_max_file_mb",
    "upload_scanner_fail_closed",
}


@dataclass(frozen=True)
class SurfacePolicy:
    enabled: bool
    max_file_size_bytes: int
    allowed_content_types: list[str]
    blocked_extensions: list[str]
    retention_days: int | None = None
    max_files_per_message: int | None = None
    recommended_alternative: str | None = None
    chunked_upload_threshold_bytes: int | None = None
    max_workspace_total_bytes: int | None = None
    remaining_workspace_bytes: int | None = None
    chunk_size_bytes: int | None = None
    session_ttl_minutes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "enabled": self.enabled,
                "max_file_size_bytes": self.max_file_size_bytes,
                "max_files_per_message": self.max_files_per_message,
                "retention_days": self.retention_days,
                "allowed_content_types": self.allowed_content_types,
                "blocked_extensions": self.blocked_extensions,
                "recommended_alternative": self.recommended_alternative,
                "chunked_upload_threshold_bytes": self.chunked_upload_threshold_bytes,
                "max_workspace_total_bytes": self.max_workspace_total_bytes,
                "remaining_workspace_bytes": self.remaining_workspace_bytes,
                "chunk_size_bytes": self.chunk_size_bytes,
                "session_ttl_minutes": self.session_ttl_minutes,
            }.items()
            if value is not None
        }


def _mb(value: int) -> int:
    return value * 1024 * 1024


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(raw: str | None, default: str = "") -> list[str]:
    value = default if raw is None else raw
    return [item.strip() for item in value.split(",") if item.strip()]


async def _effective_int(db: AsyncSession | None, key: str, default: int) -> int:
    if db is None:
        return default
    return _parse_int(await config_service.get_config(key, db), default)


async def _effective_str(db: AsyncSession | None, key: str, default: str) -> str:
    if db is None:
        return default
    value = await config_service.get_config(key, db)
    return value if value is not None else default


async def _effective_bool(db: AsyncSession | None, key: str, default: bool) -> bool:
    if db is None:
        return default
    return _parse_bool(await config_service.get_config(key, db), default)


def _positive(value: int, default: int) -> int:
    return value if value > 0 else default


def _normalize_scan_mode(value: str) -> str:
    return value if value in {"metadata_only", "async_required", "disabled"} else "metadata_only"


def _normalize_scanner_provider(value: str) -> str:
    return value if value in {"none", "clamav", "http"} else "none"


def _scanner_configured(provider: str, endpoint: str) -> bool:
    if provider == "none":
        return False
    if provider == "http":
        return bool(endpoint.strip())
    return True


async def build_upload_policy(
    db: AsyncSession | None = None,
    *,
    remaining_workspace_bytes: int | None = None,
) -> dict[str, Any]:
    chat_max_mb = await _effective_int(
        db, "upload_chat_attachment_max_mb", settings.UPLOAD_CHAT_ATTACHMENT_MAX_MB,
    )
    chat_max_count = await _effective_int(
        db, "upload_chat_attachment_max_count", settings.UPLOAD_CHAT_ATTACHMENT_MAX_COUNT,
    )
    chat_retention_days = await _effective_int(
        db, "upload_chat_attachment_retention_days", settings.UPLOAD_CHAT_ATTACHMENT_RETENTION_DAYS,
    )
    shared_max_mb = await _effective_int(
        db, "upload_shared_file_max_mb", settings.UPLOAD_SHARED_FILE_MAX_MB,
    )
    large_max_mb = await _effective_int(
        db, "upload_large_file_max_mb", settings.UPLOAD_LARGE_FILE_MAX_MB,
    )
    chunk_threshold_mb = await _effective_int(
        db, "upload_chunked_upload_threshold_mb", settings.UPLOAD_CHUNKED_UPLOAD_THRESHOLD_MB,
    )
    chunk_size_mb = await _effective_int(
        db, "upload_chunk_size_mb", settings.UPLOAD_CHUNK_SIZE_MB,
    )
    quota_mb = await _effective_int(
        db, "upload_workspace_quota_mb", settings.UPLOAD_WORKSPACE_QUOTA_MB,
    )
    gateway_mb = await _effective_int(
        db, "upload_gateway_proxy_body_size_mb", settings.UPLOAD_GATEWAY_PROXY_BODY_SIZE_MB,
    )
    scan_mode = _normalize_scan_mode(await _effective_str(
        db, "upload_security_scan_mode", settings.UPLOAD_SECURITY_SCAN_MODE,
    ))
    scanner_provider = _normalize_scanner_provider(await _effective_str(
        db, "upload_scanner_provider", settings.UPLOAD_SCANNER_PROVIDER,
    ))
    scanner_endpoint = await _effective_str(
        db, "upload_scanner_endpoint", settings.UPLOAD_SCANNER_ENDPOINT,
    )
    scanner_max_file_mb = await _effective_int(
        db, "upload_scanner_max_file_mb", settings.UPLOAD_SCANNER_MAX_FILE_MB,
    )
    scanner_fail_closed = await _effective_bool(
        db, "upload_scanner_fail_closed", settings.UPLOAD_SCANNER_FAIL_CLOSED,
    )
    blocked_extensions = _parse_csv(
        await _effective_str(db, "upload_blocked_extensions", settings.UPLOAD_BLOCKED_EXTENSIONS)
    )
    allowed_content_types = _parse_csv(
        await _effective_str(db, "upload_allowed_content_types", settings.UPLOAD_ALLOWED_CONTENT_TYPES)
    )

    storage_status = storage_service.get_storage_status()
    chat_max_bytes = _mb(_positive(chat_max_mb, settings.UPLOAD_CHAT_ATTACHMENT_MAX_MB))
    shared_max_bytes = _mb(_positive(shared_max_mb, settings.UPLOAD_SHARED_FILE_MAX_MB))
    large_max_bytes = _mb(_positive(large_max_mb, settings.UPLOAD_LARGE_FILE_MAX_MB))
    chunk_threshold_bytes = _mb(_positive(chunk_threshold_mb, settings.UPLOAD_CHUNKED_UPLOAD_THRESHOLD_MB))
    chunk_size_bytes = _mb(_positive(chunk_size_mb, settings.UPLOAD_CHUNK_SIZE_MB))
    quota_bytes = _mb(_positive(quota_mb, settings.UPLOAD_WORKSPACE_QUOTA_MB))
    gateway_bytes = _mb(_positive(gateway_mb, settings.UPLOAD_GATEWAY_PROXY_BODY_SIZE_MB))
    scanner_configured = _scanner_configured(scanner_provider, scanner_endpoint)

    return {
        "backend": storage_status["backend"],
        "storage_status": storage_status["storage_status"],
        "storage_reason_code": storage_status["storage_reason_code"],
        "direct_upload_supported": storage_status["direct_upload_supported"],
        "surfaces": {
            "chat_attachment": SurfacePolicy(
                enabled=storage_status["storage_status"] == "available",
                max_file_size_bytes=chat_max_bytes,
                max_files_per_message=_positive(chat_max_count, settings.UPLOAD_CHAT_ATTACHMENT_MAX_COUNT),
                retention_days=_positive(chat_retention_days, settings.UPLOAD_CHAT_ATTACHMENT_RETENTION_DAYS),
                allowed_content_types=allowed_content_types,
                blocked_extensions=blocked_extensions,
                recommended_alternative="shared_file",
            ).to_dict(),
            "shared_file": SurfacePolicy(
                enabled=storage_status["storage_status"] == "available",
                max_file_size_bytes=shared_max_bytes,
                chunked_upload_threshold_bytes=chunk_threshold_bytes,
                max_workspace_total_bytes=quota_bytes,
                remaining_workspace_bytes=quota_bytes if remaining_workspace_bytes is None else remaining_workspace_bytes,
                allowed_content_types=allowed_content_types,
                blocked_extensions=blocked_extensions,
            ).to_dict(),
            "large_input": SurfacePolicy(
                enabled=storage_status["storage_status"] == "available",
                max_file_size_bytes=large_max_bytes,
                chunk_size_bytes=chunk_size_bytes,
                session_ttl_minutes=120,
                allowed_content_types=allowed_content_types,
                blocked_extensions=blocked_extensions,
            ).to_dict(),
        },
        "gateway": {
            "proxy_body_size_bytes": gateway_bytes,
            "is_gateway_lower_than_policy": gateway_bytes < max(chat_max_bytes, chunk_threshold_bytes),
        },
        "security": {
            "scan_mode": scan_mode,
            "download_requires_clean_scan": scan_mode == "async_required",
            "scanner_configured": scanner_configured,
            "scanner_provider": scanner_provider,
            "scanner_max_file_size_bytes": _mb(_positive(scanner_max_file_mb, settings.UPLOAD_SCANNER_MAX_FILE_MB)),
            "scanner_fail_closed": scanner_fail_closed,
        },
    }


async def get_surface_max_bytes(surface: str, db: AsyncSession | None = None) -> int:
    policy = await build_upload_policy(db)
    return int(policy["surfaces"][surface]["max_file_size_bytes"])


async def validate_upload_request(
    surface: str,
    *,
    filename: str,
    content_type: str,
    size: int,
    db: AsyncSession | None = None,
) -> None:
    policy = await build_upload_policy(db)
    if policy["storage_status"] != "available":
        raise storage_service.StorageUnavailableError(str(policy["storage_reason_code"]))
    surface_policy = policy["surfaces"][surface]
    max_bytes = int(surface_policy["max_file_size_bytes"])
    if size > max_bytes:
        raise storage_service.UploadTooLargeError(max_bytes, size)

    ext = PurePosixPath(filename).suffix.lower()
    blocked_extensions = {item.lower() for item in surface_policy.get("blocked_extensions", [])}
    if ext and ext in blocked_extensions:
        raise BadRequestError(
            "文件类型不允许上传",
            message_key="errors.upload.file_type_blocked",
            message_params={"extension": ext},
        )

    allowed_content_types = {item.lower() for item in surface_policy.get("allowed_content_types", [])}
    if allowed_content_types and content_type.lower() not in allowed_content_types:
        raise BadRequestError(
            "文件媒体类型不允许上传",
            message_key="errors.upload.file_type_blocked",
            message_params={"content_type": content_type},
        )


async def validate_upload_config_value(
    key: str,
    value: str | None,
    db: AsyncSession,
) -> None:
    if key not in UPLOAD_CONFIG_KEYS:
        return

    def as_int(raw: str | None, default: int) -> int:
        return _parse_int(raw, default)

    candidate: dict[str, str | None] = {key: value}

    async def current_int(config_key: str, default: int) -> int:
        raw = candidate.get(config_key)
        if raw is None and config_key not in candidate:
            raw = await config_service.get_config(config_key, db)
        return as_int(raw, default)

    positive_keys = {
        "upload_chat_attachment_max_mb": settings.UPLOAD_CHAT_ATTACHMENT_MAX_MB,
        "upload_chat_attachment_max_count": settings.UPLOAD_CHAT_ATTACHMENT_MAX_COUNT,
        "upload_chat_attachment_retention_days": settings.UPLOAD_CHAT_ATTACHMENT_RETENTION_DAYS,
        "upload_shared_file_max_mb": settings.UPLOAD_SHARED_FILE_MAX_MB,
        "upload_large_file_max_mb": settings.UPLOAD_LARGE_FILE_MAX_MB,
        "upload_chunked_upload_threshold_mb": settings.UPLOAD_CHUNKED_UPLOAD_THRESHOLD_MB,
        "upload_chunk_size_mb": settings.UPLOAD_CHUNK_SIZE_MB,
        "upload_workspace_quota_mb": settings.UPLOAD_WORKSPACE_QUOTA_MB,
        "upload_gateway_proxy_body_size_mb": settings.UPLOAD_GATEWAY_PROXY_BODY_SIZE_MB,
        "upload_proxy_read_timeout_seconds": settings.UPLOAD_PROXY_READ_TIMEOUT_SECONDS,
        "upload_proxy_send_timeout_seconds": settings.UPLOAD_PROXY_SEND_TIMEOUT_SECONDS,
        "upload_scanner_timeout_seconds": settings.UPLOAD_SCANNER_TIMEOUT_SECONDS,
        "upload_scanner_max_file_mb": settings.UPLOAD_SCANNER_MAX_FILE_MB,
    }
    if key in positive_keys and as_int(value, 0) <= 0:
        raise BadRequestError("上传配置必须是正整数", "errors.settings.invalid_upload_config")
    if key == "upload_scanner_max_retries" and as_int(value, -1) < 0:
        raise BadRequestError("扫描重试次数不能小于 0", "errors.settings.invalid_upload_config")
    if key == "upload_security_scan_mode" and (value or "") not in {"metadata_only", "async_required", "disabled"}:
        raise BadRequestError("文件安全扫描模式无效", "errors.settings.invalid_upload_config")
    if key == "upload_scanner_provider" and (value or "") not in {"none", "clamav", "http"}:
        raise BadRequestError("文件扫描器提供方无效", "errors.settings.invalid_upload_config")

    chat_max = await current_int("upload_chat_attachment_max_mb", settings.UPLOAD_CHAT_ATTACHMENT_MAX_MB)
    shared_max = await current_int("upload_shared_file_max_mb", settings.UPLOAD_SHARED_FILE_MAX_MB)
    if chat_max > shared_max:
        raise BadRequestError(
            "对话附件上限不能大于共享文件上限",
            "errors.settings.invalid_upload_config",
        )

    if key == "upload_security_scan_mode" and value == "async_required":
        provider = await _effective_str(db, "upload_scanner_provider", settings.UPLOAD_SCANNER_PROVIDER)
        endpoint = await _effective_str(db, "upload_scanner_endpoint", settings.UPLOAD_SCANNER_ENDPOINT)
        if not _scanner_configured(_normalize_scanner_provider(provider), endpoint):
            raise BadRequestError(
                "异步扫描必需模式需要先配置扫描器",
                "errors.upload.scanner_unavailable",
            )
    if key in {"upload_scanner_provider", "upload_scanner_endpoint"}:
        scan_mode = await _effective_str(db, "upload_security_scan_mode", settings.UPLOAD_SECURITY_SCAN_MODE)
        if _normalize_scan_mode(scan_mode) == "async_required":
            provider = value if key == "upload_scanner_provider" else await _effective_str(
                db, "upload_scanner_provider", settings.UPLOAD_SCANNER_PROVIDER,
            )
            endpoint = value if key == "upload_scanner_endpoint" else await _effective_str(
                db, "upload_scanner_endpoint", settings.UPLOAD_SCANNER_ENDPOINT,
            )
            if not _scanner_configured(_normalize_scanner_provider(provider or ""), endpoint or ""):
                raise BadRequestError(
                    "异步扫描必需模式需要保持扫描器可用",
                    "errors.upload.scanner_unavailable",
                )

"""Managed runtime file resources for instance-scoped editable files."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.instance import Instance
from app.services import enterprise_file_service
from app.services.nfs_mount import NFSMountError, RemoteFS, remote_fs
from app.utils.jsonc import parse_config_json

ManagedFileContentType = Literal["markdown", "json", "yaml"]

ROLE_PROMPT_KEY = "role_prompt"
ROOT_DIR = "/root"
OPENCLAW_DEFAULT_WORKSPACE = "/root/.openclaw/workspace"
OPENCLAW_CONFIG_REL = ".openclaw/openclaw.json"
SOUL_FILENAME = "SOUL.md"


@dataclass(frozen=True)
class ManagedFilePath:
    rel_path: str
    display_path: str


@dataclass(frozen=True)
class EditableRuntimeFileResource:
    key: str
    content_type: ManagedFileContentType
    requires_restart: bool
    resolve: Callable[[Instance, RemoteFS], Awaitable[ManagedFilePath]]

    def validate(self, content: str) -> None:
        if len(content.encode("utf-8")) > enterprise_file_service.MAX_PREVIEW_BYTES:
            raise AppException(
                code=41300,
                message="文件内容超过允许大小",
                message_key="errors.managed_files.too_large",
                status_code=413,
            )


def _normalize_agent_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "main"
    lowered = raw.lower()
    if re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", raw, re.IGNORECASE):
        return lowered
    normalized = re.sub(r"[^a-z0-9_-]+", "-", lowered).strip("-")
    return normalized[:64] or "main"


def _list_agent_entries(config: dict) -> list[dict]:
    agents = config.get("agents")
    if not isinstance(agents, dict):
        return []
    entries = agents.get("list")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _resolve_default_agent_id(config: dict) -> str:
    entries = _list_agent_entries(config)
    if not entries:
        return "main"
    default_entries = [entry for entry in entries if entry.get("default")]
    chosen = default_entries[0] if default_entries else entries[0]
    return _normalize_agent_id(chosen.get("id"))


def _resolve_agent_entry(config: dict, agent_id: str) -> dict | None:
    normalized = _normalize_agent_id(agent_id)
    for entry in _list_agent_entries(config):
        if _normalize_agent_id(entry.get("id")) == normalized:
            return entry
    return None


def _resolve_user_path(value: str) -> str:
    raw = value.strip().replace("\0", "")
    if not raw:
        return raw
    if raw == "~" or raw.startswith("~/"):
        raw = f"{ROOT_DIR}{raw[1:]}"
    elif not raw.startswith("/"):
        raw = f"{ROOT_DIR}/{raw}"
    return posixpath.normpath(raw)


def _resolve_openclaw_workspace(config: dict) -> str:
    agent_id = _resolve_default_agent_id(config)
    agent = _resolve_agent_entry(config, agent_id)
    configured = agent.get("workspace") if agent else None
    if isinstance(configured, str) and configured.strip():
        return _resolve_user_path(configured)

    agents = config.get("agents") if isinstance(config.get("agents"), dict) else {}
    defaults = agents.get("defaults") if isinstance(agents.get("defaults"), dict) else {}
    fallback = defaults.get("workspace")
    if agent_id == _resolve_default_agent_id(config):
        if isinstance(fallback, str) and fallback.strip():
            return _resolve_user_path(fallback)
        return OPENCLAW_DEFAULT_WORKSPACE
    if isinstance(fallback, str) and fallback.strip():
        return posixpath.normpath(posixpath.join(_resolve_user_path(fallback), agent_id))
    return posixpath.normpath(f"/root/.openclaw/workspace-{agent_id}")


def _to_managed_path(runtime: str, container_path: str) -> ManagedFilePath:
    allowed_root = enterprise_file_service.get_allowed_root(runtime)
    allowed_abs = posixpath.normpath(f"{ROOT_DIR}/{allowed_root.strip('/')}")
    normalized = posixpath.normpath(container_path)
    if normalized != allowed_abs and not normalized.startswith(f"{allowed_abs}/"):
        raise AppException(
            code=40000,
            message="受控文件路径不在允许目录内",
            message_key="errors.managed_files.path_outside_allowed_root",
            status_code=400,
        )
    rel_path = normalized.removeprefix(f"{ROOT_DIR}/")
    safe_path = enterprise_file_service._validate_path(rel_path, allowed_root)
    if safe_path != rel_path:
        raise AppException(
            code=40000,
            message="受控文件路径不在允许目录内",
            message_key="errors.managed_files.path_outside_allowed_root",
            status_code=400,
        )
    return ManagedFilePath(rel_path=safe_path, display_path=f"{ROOT_DIR}/{safe_path}")


async def _resolve_hermes_role_prompt(instance: Instance, _fs: RemoteFS) -> ManagedFilePath:
    return _to_managed_path(instance.runtime, "/root/.hermes/SOUL.md")


async def _resolve_openclaw_role_prompt(instance: Instance, fs: RemoteFS) -> ManagedFilePath:
    config_stat = await fs.file_stat(OPENCLAW_CONFIG_REL)
    if config_stat is None:
        workspace = OPENCLAW_DEFAULT_WORKSPACE
    else:
        raw = await fs.read_text(OPENCLAW_CONFIG_REL)
        try:
            config = parse_config_json(raw or "")
        except ValueError as exc:
            raise AppException(
                code=40000,
                message=f"openclaw.json 无法解析: {exc}",
                message_key="errors.managed_files.config_parse_failed",
                status_code=400,
            ) from exc
        workspace = _resolve_openclaw_workspace(config)
    return _to_managed_path(instance.runtime, posixpath.join(workspace, SOUL_FILENAME))


_RESOURCES: dict[str, dict[str, EditableRuntimeFileResource]] = {
    ROLE_PROMPT_KEY: {
        "hermes": EditableRuntimeFileResource(
            key=ROLE_PROMPT_KEY,
            content_type="markdown",
            requires_restart=True,
            resolve=_resolve_hermes_role_prompt,
        ),
        "openclaw": EditableRuntimeFileResource(
            key=ROLE_PROMPT_KEY,
            content_type="markdown",
            requires_restart=True,
            resolve=_resolve_openclaw_role_prompt,
        ),
    },
}


def _get_resource(resource_key: str, runtime: str) -> EditableRuntimeFileResource:
    resources = _RESOURCES.get(resource_key)
    if not resources:
        raise AppException(
            code=40400,
            message="受控文件资源不存在",
            message_key="errors.managed_files.resource_not_found",
            status_code=404,
        )
    resource = resources.get(runtime)
    if not resource:
        raise AppException(
            code=40000,
            message="当前运行时不支持该受控文件资源",
            message_key="errors.managed_files.unsupported_runtime",
            status_code=400,
        )
    return resource


def _build_response(
    instance: Instance,
    resource: EditableRuntimeFileResource,
    path: ManagedFilePath,
    content: str,
    exists: bool,
) -> dict:
    return {
        "key": resource.key,
        "runtime": instance.runtime,
        "rel_path": path.rel_path,
        "display_path": path.display_path,
        "content": content,
        "exists": exists,
        "content_type": resource.content_type,
        "requires_restart": resource.requires_restart,
    }


async def read_managed_file(instance_id: str, resource_key: str, db: AsyncSession) -> dict:
    instance = await enterprise_file_service._get_running_instance(instance_id, db)
    resource = _get_resource(resource_key, instance.runtime)

    try:
        async with remote_fs(instance, db) as fs:
            path = await resource.resolve(instance, fs)
            stat = await fs.file_stat(path.rel_path)
            if stat is None:
                return _build_response(instance, resource, path, "", False)
            if stat["size"] > enterprise_file_service.MAX_PREVIEW_BYTES:
                raise AppException(
                    code=41300,
                    message="文件内容超过允许大小",
                    message_key="errors.managed_files.too_large",
                    status_code=413,
                )
            content = await fs.read_text(path.rel_path)
            return _build_response(instance, resource, path, content or "", True)
    except NFSMountError:
        raise AppException(
            code=50300,
            message="无法连接到实例",
            message_key="errors.enterprise_files.instance_not_running",
            status_code=503,
        )


async def write_managed_file(
    instance_id: str,
    resource_key: str,
    content: str,
    db: AsyncSession,
) -> dict:
    instance = await enterprise_file_service._get_running_instance(instance_id, db)
    resource = _get_resource(resource_key, instance.runtime)
    resource.validate(content)

    try:
        async with remote_fs(instance, db) as fs:
            path = await resource.resolve(instance, fs)
            await fs.write_text(path.rel_path, content)
            return _build_response(instance, resource, path, content, True)
    except NFSMountError:
        raise AppException(
            code=50300,
            message="无法连接到实例",
            message_key="errors.enterprise_files.instance_not_running",
            status_code=503,
        )

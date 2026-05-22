"""Agent Bundle parsing, validation, and runtime restore helpers."""

from __future__ import annotations

import json
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.models.instance import Instance

REQUIRED_FILES = ("AGENT.md", "SOUL.md", "config.json")
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 5 * 1024 * 1024
SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "auth_token",
    "client_secret",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
)
SECRET_REF_SUFFIXES = ("_ref", "ref", "reference")


def normalize_bundle_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:96].strip("-") or "agent-bundle"


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise BadRequestError(f"Agent Bundle 文件过大: {path.name}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BadRequestError(f"Agent Bundle 文件必须是 UTF-8 文本: {path.name}") from exc


def _safe_rel(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    normalized = posixpath.normpath(rel)
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        raise BadRequestError(f"Agent Bundle 包含非法路径: {rel}")
    if any(part.startswith(".") for part in normalized.split("/")):
        raise BadRequestError(f"Agent Bundle 不允许隐藏文件路径: {rel}")
    return normalized


def _parse_json(text: str, filename: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BadRequestError(f"{filename} 不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise BadRequestError(f"{filename} 必须是 JSON 对象")
    return data


def _parse_frontmatter(content: str, skill_path: str) -> dict[str, Any]:
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        raise BadRequestError(f"{skill_path} 缺少 YAML front matter")
    end = stripped.find("\n---", 3)
    if end == -1:
        raise BadRequestError(f"{skill_path} 缺少 YAML front matter 结束标记")
    try:
        meta = yaml.safe_load(stripped[3:end]) or {}
    except yaml.YAMLError as exc:
        raise BadRequestError(f"{skill_path} 的 YAML front matter 无法解析") from exc
    if not isinstance(meta, dict):
        raise BadRequestError(f"{skill_path} 的 YAML front matter 必须是对象")
    if not str(meta.get("name") or "").strip():
        raise BadRequestError(f"{skill_path} 缺少 name")
    if not str(meta.get("description") or "").strip():
        raise BadRequestError(f"{skill_path} 缺少 description")
    _validate_declared_script_paths(meta, skill_path)
    return meta


def _validate_declared_script_paths(meta: dict[str, Any], skill_path: str) -> None:
    declared = meta.get("scripts")
    paths: list[str] = []
    if isinstance(declared, list):
        paths = [str(item) for item in declared]
    elif isinstance(declared, dict):
        paths = [str(item) for item in declared.values()]
    for raw in paths:
        normalized = posixpath.normpath(raw)
        if normalized.startswith("../") or normalized.startswith("/") or normalized == "..":
            raise BadRequestError(f"{skill_path} 声明了非法脚本路径: {raw}")


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith(SECRET_REF_SUFFIXES) or lowered.endswith("_secret_ref"):
        return False
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def _validate_no_plaintext_secret(config: dict[str, Any]) -> None:
    env = config.get("env")
    if not isinstance(env, dict):
        return
    for key, value in env.items():
        if _is_secret_key(str(key)) and value not in (None, ""):
            raise BadRequestError(
                f"config.env.{key} 看起来是明文密钥，请改用 secretRef/tokenRef",
            )


def _load_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = _safe_rel(path, root)
        if any(part == "__MACOSX" for part in rel.split("/")):
            continue
        total += path.stat().st_size
        if total > MAX_TOTAL_BYTES:
            raise BadRequestError("Agent Bundle 总大小超过限制")
        files[rel] = _read_text(path)
    return files


def _extract_agent_name(agent_md: str, fallback: str) -> str:
    for line in agent_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def _extract_agent_description(agent_md: str) -> str | None:
    for line in agent_md.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:256]
    return None


def _skill_scripts(skill_dir: Path, root: Path) -> dict[str, str]:
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.exists():
        return {}
    scripts: dict[str, str] = {}
    for path in sorted(scripts_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = _safe_rel(path, root)
        scripts[rel] = _read_text(path)
    return scripts


def parse_agent_bundle_dir(bundle_dir: str | Path) -> dict[str, Any]:
    root = Path(bundle_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise BadRequestError("Agent Bundle 目录不存在")

    files = _load_files(root)
    missing = [name for name in REQUIRED_FILES if name not in files]
    if missing:
        raise BadRequestError(f"Agent Bundle 缺少必需文件: {', '.join(missing)}")

    config = _parse_json(files["config.json"], "config.json")
    _validate_no_plaintext_secret(config)

    skills_root = root / "skills"
    if not skills_root.exists() or not skills_root.is_dir():
        raise BadRequestError("Agent Bundle 缺少 skills 目录")

    skills: list[dict[str, Any]] = []
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        rel = _safe_rel(skill_file, root)
        content = files[rel]
        meta = _parse_frontmatter(content, rel)
        permissions = meta.get("permissions") if isinstance(meta.get("permissions"), dict) else {}
        skills.append({
            "name": str(meta["name"]),
            "slug": normalize_bundle_slug(str(meta["name"])),
            "version": str(meta.get("version") or "1.0.0"),
            "description": str(meta["description"]),
            "path": rel,
            "permissions": permissions,
            "scripts": _skill_scripts(skill_dir, root),
            "frontmatter": meta,
        })
    if not skills:
        raise BadRequestError("Agent Bundle 至少需要一个 skills/*/SKILL.md")

    bundle_slug = normalize_bundle_slug(str(config.get("slug") or root.name))
    agent_name = str(config.get("name") or _extract_agent_name(files["AGENT.md"], bundle_slug))
    upload_contract = config.get("uploadContract") or config.get("upload_contract")
    resource_recommendation = config.get("resourceRecommendation") or config.get("resource_recommendation")
    secret_refs = config.get("secretRefs") or config.get("secret_refs") or []

    return {
        "schema_version": 1,
        "name": agent_name,
        "slug": bundle_slug,
        "description": _extract_agent_description(files["AGENT.md"]),
        "config": config,
        "env": config.get("env") if isinstance(config.get("env"), dict) else {},
        "skills": skills,
        "files": files,
        "resource_recommendation": resource_recommendation if isinstance(resource_recommendation, dict) else None,
        "upload_contract": upload_contract if isinstance(upload_contract, dict) else None,
        "secret_refs": secret_refs if isinstance(secret_refs, list) else [],
    }


def parse_agent_bundle_zip(filename: str, data: bytes) -> dict[str, Any]:
    if not filename.lower().endswith(".zip"):
        raise BadRequestError("Agent Bundle 上传文件必须是 .zip")
    with tempfile.TemporaryDirectory(prefix="agent-bundle-") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "bundle.zip"
        zip_path.write_bytes(data)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for info in zf.infolist():
                    normalized = posixpath.normpath(info.filename)
                    if normalized.startswith("../") or normalized.startswith("/") or normalized == "..":
                        raise BadRequestError(f"压缩包包含非法路径: {info.filename}")
                zf.extractall(tmp_path / "bundle")
        except zipfile.BadZipFile as exc:
            raise BadRequestError("Agent Bundle 压缩包无法读取") from exc

        extracted = tmp_path / "bundle"
        children = [p for p in extracted.iterdir() if not p.name.startswith(".") and p.name != "__MACOSX"]
        if len(children) == 1 and children[0].is_dir():
            extracted = children[0]
        return parse_agent_bundle_dir(extracted)


def summarize_agent_bundle_manifest(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not manifest:
        return None
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    env = manifest.get("env") if isinstance(manifest.get("env"), dict) else {}
    return {
        "schema_version": manifest.get("schema_version", 1),
        "name": manifest.get("name"),
        "slug": manifest.get("slug"),
        "description": manifest.get("description"),
        "model": (manifest.get("config") or {}).get("model") if isinstance(manifest.get("config"), dict) else None,
        "skills": [
            {
                "name": item.get("name"),
                "slug": item.get("slug"),
                "version": item.get("version"),
                "description": item.get("description"),
                "path": item.get("path"),
                "tool_count": len((item.get("permissions") or {}).get("tools") or []),
            }
            for item in manifest.get("skills", [])
            if isinstance(item, dict)
        ],
        "files": sorted(files.keys()),
        "env_keys": sorted(env.keys()),
        "has_role_prompt": "SOUL.md" in files,
    }


def build_bundle_env_vars(
    manifest: dict[str, Any] | None,
    template_slug: str,
    instance_id: str | None = None,
) -> dict[str, str]:
    if not manifest:
        return {}
    env: dict[str, str] = {}
    for key, value in (manifest.get("env") or {}).items():
        if _is_secret_key(str(key)):
            continue
        if isinstance(value, (str, int, float, bool)):
            env[str(key)] = str(value)
    env["NODESKCLAW_AGENT_BUNDLE_DIR"] = f"/root/.openclaw/agent-bundles/{template_slug}"
    if instance_id:
        env["NODESKCLAW_AGENT_STATE_DIR"] = f"/root/.openclaw/agent-state/{instance_id}"
    if manifest.get("secret_refs"):
        env["NODESKCLAW_SECRET_REFS"] = json.dumps(manifest["secret_refs"], ensure_ascii=False)
    if manifest.get("upload_contract"):
        env["NODESKCLAW_UPLOAD_CONTRACT"] = json.dumps(manifest["upload_contract"], ensure_ascii=False)
    return env


async def restore_agent_bundle(instance: Instance, manifest: dict[str, Any], db: AsyncSession) -> None:
    from app.services.nfs_mount import remote_fs

    template_slug = normalize_bundle_slug(str(manifest.get("slug") or "agent-bundle"))
    base_rel = f".openclaw/agent-bundles/{template_slug}"
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}

    async with remote_fs(instance, db) as fs:
        await fs.remove(base_rel)
        for rel, content in files.items():
            safe_rel = posixpath.normpath(str(rel))
            if safe_rel.startswith("../") or safe_rel.startswith("/") or safe_rel == "..":
                raise BadRequestError(f"Agent Bundle 包含非法恢复路径: {rel}")
            await fs.write_text(f"{base_rel}/{safe_rel}", str(content))
        await fs.write_text(
            f"{base_rel}/.nodeskclaw-manifest.json",
            json.dumps(summarize_agent_bundle_manifest(manifest), ensure_ascii=False, indent=2),
        )

    soul = files.get("SOUL.md")
    if soul:
        from app.services.editable_runtime_file_service import ROLE_PROMPT_KEY, write_managed_file

        await write_managed_file(instance.id, ROLE_PROMPT_KEY, str(soul), db)

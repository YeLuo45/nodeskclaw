"""Agent Bundle parsing, validation, and runtime restore helpers."""

from __future__ import annotations

import json
import io
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
from app.services.runtime.gene_install_adapter import validate_skill_name_segment

REQUIRED_FILES = ("AGENT.md", "SOUL.md", "config.json")
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 5 * 1024 * 1024
MAX_ZIP_BYTES = MAX_TOTAL_BYTES + 1024 * 1024
MAX_ZIP_ENTRIES = 256
MAX_COMPRESSION_RATIO = 100
ZIP_RATIO_MIN_FILE_BYTES = 128 * 1024
ZIP_READ_CHUNK_BYTES = 64 * 1024
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
BUNDLE_REL_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
SECRET_REF_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_REF_SECRET_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
SECRET_REF_SOURCE_NAMESPACE_KEY = "_nodeskclaw_secret_ref_source_namespace"


def normalize_bundle_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:96].strip("-") or "agent-bundle"


def _validate_bundle_rel_path(raw: str, message: str | None = None) -> str:
    rel = str(raw)
    normalized = posixpath.normpath(rel)
    invalid = (
        not rel
        or normalized in ("", ".")
        or normalized != rel
        or normalized.startswith("../")
        or normalized == ".."
        or normalized.startswith("/")
        or "\\" in rel
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in rel)
        or any(not part or part.startswith(".") for part in normalized.split("/"))
        or not BUNDLE_REL_PATH_PATTERN.fullmatch(normalized)
    )
    if invalid:
        raise BadRequestError(message or f"Agent Bundle 包含非法路径: {rel}")
    return normalized


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
    return _validate_bundle_rel_path(rel)


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
    meta["name"] = validate_skill_name_segment(meta["name"], f"{skill_path} 包含非法 skill name")
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
        try:
            _validate_bundle_rel_path(raw)
        except BadRequestError as exc:
            raise BadRequestError(f"{skill_path} 声明了非法脚本路径: {raw}") from exc


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


def _validate_secret_ref_secret_name(value: str, field: str) -> str:
    text = value.strip()
    labels = text.split(".") if text else []
    if (
        not text
        or len(text) > 253
        or any(len(label) > 63 or not DNS_LABEL_PATTERN.fullmatch(label) for label in labels)
    ):
        raise BadRequestError(f"config.secretRefs.{field} 必须是合法的 K8s Secret 名称")
    return text


def _validate_secret_ref_key(value: str, field: str) -> str:
    text = value.strip()
    if not text or len(text) > 253 or not SECRET_REF_SECRET_KEY_PATTERN.fullmatch(text):
        raise BadRequestError(f"config.secretRefs.{field} 必须是合法的 K8s Secret key")
    return text


def _parse_secret_ref_token_ref(token_ref: Any, index: int) -> tuple[str, str]:
    raw = str(token_ref).strip()
    parts = raw.split("/")
    if len(parts) != 2:
        raise BadRequestError(f"config.secretRefs[{index}].tokenRef 必须使用 secretName/key 格式")
    secret_name = _validate_secret_ref_secret_name(parts[0], f"[{index}].tokenRef")
    secret_key = _validate_secret_ref_key(parts[1], f"[{index}].tokenRef")
    return secret_name, secret_key


def _validate_secret_refs(config: dict[str, Any]) -> list[dict[str, Any]]:
    refs = config.get("secretRefs")
    legacy_refs = config.get("secret_refs")
    has_refs = "secretRefs" in config and refs not in (None, "")
    has_legacy_refs = "secret_refs" in config and legacy_refs not in (None, "")
    if has_refs and has_legacy_refs:
        raise BadRequestError("config.secretRefs 和 config.secret_refs 不能同时声明")
    if has_refs:
        selected_refs = refs
    elif has_legacy_refs:
        selected_refs = legacy_refs
    else:
        return []
    if not isinstance(selected_refs, list):
        raise BadRequestError("config.secretRefs 必须是数组")

    normalized: list[dict[str, Any]] = []
    seen_env_names: set[str] = set()
    allowed_keys = {
        "env", "env_name",
        "secretName", "secret_name",
        "key", "secretKey", "secret_key",
        "tokenRef", "token_ref",
        "sourceEnv", "source_env",
        "required",
    }
    for index, ref in enumerate(selected_refs):
        if not isinstance(ref, dict):
            raise BadRequestError(f"config.secretRefs[{index}] 必须是对象")
        unknown_keys = sorted(str(key) for key in ref if str(key) not in allowed_keys)
        if unknown_keys:
            raise BadRequestError(
                f"config.secretRefs[{index}] 包含不支持的字段: {', '.join(unknown_keys)}",
            )
        forbidden = [
            key for key in ref
            if _is_secret_key(str(key)) and key not in {
                "secretName", "secret_name", "secretKey", "secret_key",
                "tokenRef", "token_ref",
            }
        ]
        if forbidden:
            raise BadRequestError(
                f"config.secretRefs[{index}] 包含疑似明文密钥字段: {', '.join(sorted(forbidden))}",
            )

        env_name = ref.get("env") or ref.get("env_name")
        secret_name = ref.get("secretName") or ref.get("secret_name")
        secret_key = ref.get("key") or ref.get("secretKey") or ref.get("secret_key")
        token_ref = ref.get("tokenRef") or ref.get("token_ref")
        if not env_name:
            raise BadRequestError(
                f"config.secretRefs[{index}] 必须声明 env、secretName/tokenRef 和 key",
            )
        if not secret_name or not secret_key:
            if token_ref:
                token_secret_name, token_secret_key = _parse_secret_ref_token_ref(token_ref, index)
                secret_name = secret_name or token_secret_name
                secret_key = secret_key or token_secret_key
            else:
                raise BadRequestError(
                    f"config.secretRefs[{index}] 必须声明 env、secretName/tokenRef 和 key",
                )

        env_text = str(env_name).strip()
        if not SECRET_REF_ENV_NAME_PATTERN.fullmatch(env_text):
            raise BadRequestError(f"config.secretRefs[{index}].env 必须是合法的环境变量名")
        if env_text in seen_env_names:
            raise BadRequestError(f"config.secretRefs[{index}].env 重复: {env_text}")
        seen_env_names.add(env_text)

        secret_name_text = _validate_secret_ref_secret_name(str(secret_name), f"[{index}].secretName")
        secret_key_text = _validate_secret_ref_key(str(secret_key), f"[{index}].key")
        if token_ref:
            token_secret_name, token_secret_key = _parse_secret_ref_token_ref(token_ref, index)
            if token_secret_name != secret_name_text or token_secret_key != secret_key_text:
                raise BadRequestError(
                    f"config.secretRefs[{index}].tokenRef 必须与 secretName/key 保持一致",
                )
        if "sourceEnv" in ref or "source_env" in ref:
            raise BadRequestError(
                f"config.secretRefs[{index}] 不允许声明 sourceEnv，请使用预先创建的 K8s Secret/tokenRef",
            )
        if "required" in ref and not isinstance(ref["required"], bool):
            raise BadRequestError(f"config.secretRefs[{index}].required 必须是布尔值")
        item = {
            "env": env_text,
            "secretName": secret_name_text,
            "key": secret_key_text,
        }
        if token_ref:
            item["tokenRef"] = f"{secret_name_text}/{secret_key_text}"
        item["required"] = ref.get("required", True) is not False
        normalized.append(item)
    return normalized


def sanitize_agent_bundle_manifest(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not manifest:
        return manifest
    sanitized = dict(manifest)
    sanitized["secret_refs"] = _validate_secret_refs(manifest)
    sanitized.pop("secretRefs", None)
    sanitized.pop(SECRET_REF_SOURCE_NAMESPACE_KEY, None)
    return sanitized


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


def _is_ignored_zip_path(rel: str) -> bool:
    return any(part == "__MACOSX" for part in rel.split("/"))


def _validate_zip_path_collision(rel: str, seen: set[str]) -> None:
    parts = rel.split("/")
    for index in range(1, len(parts)):
        if "/".join(parts[:index]) in seen:
            raise BadRequestError(f"压缩包包含路径冲突: {rel}")
    prefix = f"{rel}/"
    if any(existing.startswith(prefix) for existing in seen):
        raise BadRequestError(f"压缩包包含路径冲突: {rel}")


def _validate_zip_info(info: zipfile.ZipInfo, seen: set[str]) -> str | None:
    raw_name = info.filename.rstrip("/")
    if _is_ignored_zip_path(raw_name):
        return None

    rel = _validate_bundle_rel_path(raw_name, f"压缩包包含非法路径: {info.filename}")
    if info.is_dir():
        return None
    if rel in seen:
        raise BadRequestError(f"压缩包包含重复路径: {rel}")
    _validate_zip_path_collision(rel, seen)
    seen.add(rel)
    if info.file_size > MAX_FILE_BYTES:
        raise BadRequestError(f"Agent Bundle 文件过大: {rel}")
    if info.file_size >= ZIP_RATIO_MIN_FILE_BYTES:
        if info.compress_size <= 0:
            raise BadRequestError(f"Agent Bundle 文件压缩率异常: {rel}")
        if info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise BadRequestError(f"Agent Bundle 文件压缩率异常: {rel}")
    return rel


def _safe_zip_target(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise BadRequestError(f"压缩包包含非法路径: {rel}")
    return target


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
    secret_refs = _validate_secret_refs(config)

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
        "secret_refs": secret_refs,
    }


def parse_agent_bundle_zip(filename: str, data: bytes) -> dict[str, Any]:
    if not filename.lower().endswith(".zip"):
        raise BadRequestError("Agent Bundle 上传文件必须是 .zip")
    if len(data) > MAX_ZIP_BYTES:
        raise BadRequestError("Agent Bundle 上传文件过大")
    with tempfile.TemporaryDirectory(prefix="agent-bundle-") as tmp:
        tmp_path = Path(tmp)
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                entries: list[tuple[zipfile.ZipInfo, str]] = []
                seen: set[str] = set()
                total = 0
                for info in zf.infolist():
                    rel = _validate_zip_info(info, seen)
                    if rel is None:
                        continue
                    entries.append((info, rel))
                    if len(entries) > MAX_ZIP_ENTRIES:
                        raise BadRequestError("Agent Bundle 文件数量超过限制")
                    total += info.file_size
                    if total > MAX_TOTAL_BYTES:
                        raise BadRequestError("Agent Bundle 总大小超过限制")

                extracted_total = 0
                for info, rel in entries:
                    target = _safe_zip_target(bundle_root, rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    file_total = 0
                    with zf.open(info) as src, target.open("wb") as dst:
                        while True:
                            chunk = src.read(ZIP_READ_CHUNK_BYTES)
                            if not chunk:
                                break
                            file_total += len(chunk)
                            extracted_total += len(chunk)
                            if file_total > info.file_size or file_total > MAX_FILE_BYTES:
                                raise BadRequestError(f"Agent Bundle 文件过大: {rel}")
                            if extracted_total > MAX_TOTAL_BYTES:
                                raise BadRequestError("Agent Bundle 总大小超过限制")
                            dst.write(chunk)
        except zipfile.BadZipFile as exc:
            raise BadRequestError("Agent Bundle 压缩包无法读取") from exc

        extracted = bundle_root
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
    manifest = sanitize_agent_bundle_manifest(manifest)
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
            safe_rel = _validate_bundle_rel_path(str(rel), f"Agent Bundle 包含非法恢复路径: {rel}")
            await fs.write_text(f"{base_rel}/{safe_rel}", str(content))
        await fs.write_text(
            f"{base_rel}/.nodeskclaw-manifest.json",
            json.dumps(summarize_agent_bundle_manifest(manifest), ensure_ascii=False, indent=2),
        )

    soul = files.get("SOUL.md")
    if soul:
        from app.services.editable_runtime_file_service import ROLE_PROMPT_KEY, write_managed_file

        await write_managed_file(instance.id, ROLE_PROMPT_KEY, str(soul), db)

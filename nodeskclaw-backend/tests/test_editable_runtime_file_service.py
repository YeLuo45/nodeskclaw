from types import SimpleNamespace

import pytest

from app.api.portal import instance_files
from app.core.exceptions import AppException
from app.models.instance_member import InstanceRole
from app.services import editable_runtime_file_service as service


class FakeFS:
    def __init__(self, files: dict[str, str] | None = None):
        self.files = files or {}

    async def file_stat(self, path: str) -> dict | None:
        if path not in self.files:
            return None
        return {
            "size": len(self.files[path].encode("utf-8")),
            "modified_at": 0,
            "mime_type": "text/markdown",
        }

    async def read_text(self, path: str) -> str | None:
        return self.files.get(path)

    async def write_text(self, path: str, content: str) -> None:
        self.files[path] = content


class FakeRemoteFSContext:
    def __init__(self, fs: FakeFS):
        self.fs = fs

    async def __aenter__(self) -> FakeFS:
        return self.fs

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def make_instance(runtime: str = "openclaw") -> SimpleNamespace:
    return SimpleNamespace(id="inst-1", runtime=runtime)


async def read_with_fake_fs(monkeypatch, fs: FakeFS, runtime: str = "openclaw") -> dict:
    instance = make_instance(runtime)

    async def fake_get_running_instance(_instance_id, _db):
        return instance

    monkeypatch.setattr(service.enterprise_file_service, "_get_running_instance", fake_get_running_instance)
    monkeypatch.setattr(service, "remote_fs", lambda _instance, _db: FakeRemoteFSContext(fs))
    return await service.read_managed_file("inst-1", service.ROLE_PROMPT_KEY, db=None)


async def write_with_fake_fs(
    monkeypatch,
    fs: FakeFS,
    content: str,
    runtime: str = "openclaw",
) -> dict:
    instance = make_instance(runtime)

    async def fake_get_running_instance(_instance_id, _db):
        return instance

    monkeypatch.setattr(service.enterprise_file_service, "_get_running_instance", fake_get_running_instance)
    monkeypatch.setattr(service, "remote_fs", lambda _instance, _db: FakeRemoteFSContext(fs))
    return await service.write_managed_file("inst-1", service.ROLE_PROMPT_KEY, content, db=None)


async def test_hermes_role_prompt_resolves_to_soul_md(monkeypatch):
    fs = FakeFS({".hermes/SOUL.md": "# Hermes soul"})

    result = await read_with_fake_fs(monkeypatch, fs, runtime="hermes")

    assert result["rel_path"] == ".hermes/SOUL.md"
    assert result["display_path"] == "/root/.hermes/SOUL.md"
    assert result["content"] == "# Hermes soul"
    assert result["exists"] is True


async def test_openclaw_role_prompt_defaults_to_workspace_soul(monkeypatch):
    fs = FakeFS({".openclaw/workspace/SOUL.md": "# OpenClaw soul"})

    result = await read_with_fake_fs(monkeypatch, fs)

    assert result["rel_path"] == ".openclaw/workspace/SOUL.md"
    assert result["display_path"] == "/root/.openclaw/workspace/SOUL.md"
    assert result["content"] == "# OpenClaw soul"


async def test_openclaw_role_prompt_uses_configured_workspace(monkeypatch):
    fs = FakeFS({
        ".openclaw/openclaw.json": """
        {
          // JSONC comments are valid in openclaw.json
          "agents": {
            "defaults": { "workspace": "~/.openclaw/agents" },
            "list": [{ "id": "ops", "default": true, "workspace": "/root/.openclaw/ops" }]
          }
        }
        """,
        ".openclaw/ops/SOUL.md": "# Ops soul",
    })

    result = await read_with_fake_fs(monkeypatch, fs)

    assert result["rel_path"] == ".openclaw/ops/SOUL.md"
    assert result["content"] == "# Ops soul"


async def test_openclaw_role_prompt_rejects_workspace_outside_allowed_root(monkeypatch):
    fs = FakeFS({
        ".openclaw/openclaw.json": '{"agents":{"defaults":{"workspace":"/tmp/workspace"}}}',
    })

    with pytest.raises(AppException) as exc:
        await read_with_fake_fs(monkeypatch, fs)

    assert exc.value.message_key == "errors.managed_files.path_outside_allowed_root"


async def test_openclaw_role_prompt_rejects_unparseable_config(monkeypatch):
    fs = FakeFS({".openclaw/openclaw.json": "{invalid"})

    with pytest.raises(AppException) as exc:
        await read_with_fake_fs(monkeypatch, fs)

    assert exc.value.message_key == "errors.managed_files.config_parse_failed"


async def test_missing_soul_md_returns_empty_content(monkeypatch):
    fs = FakeFS()

    result = await read_with_fake_fs(monkeypatch, fs)

    assert result["rel_path"] == ".openclaw/workspace/SOUL.md"
    assert result["content"] == ""
    assert result["exists"] is False


async def test_write_managed_file_creates_role_prompt(monkeypatch):
    fs = FakeFS()

    result = await write_with_fake_fs(monkeypatch, fs, "# New soul")

    assert result["rel_path"] == ".openclaw/workspace/SOUL.md"
    assert result["content"] == "# New soul"
    assert fs.files[".openclaw/workspace/SOUL.md"] == "# New soul"


async def test_unknown_managed_file_resource_returns_not_found(monkeypatch):
    instance = make_instance("openclaw")

    async def fake_get_running_instance(_instance_id, _db):
        return instance

    monkeypatch.setattr(service.enterprise_file_service, "_get_running_instance", fake_get_running_instance)

    with pytest.raises(AppException) as exc:
        await service.read_managed_file("inst-1", "unknown", db=None)

    assert exc.value.message_key == "errors.managed_files.resource_not_found"


async def test_managed_file_route_requires_instance_admin(monkeypatch):
    seen = {}

    async def fake_check_instance_access(instance_id, current_user, role, db):
        seen["instance_id"] = instance_id
        seen["role"] = role

    async def fake_read_managed_file(instance_id, resource_key, db):
        return {"key": resource_key, "instance_id": instance_id}

    monkeypatch.setattr(
        instance_files.instance_member_service,
        "check_instance_access",
        fake_check_instance_access,
    )
    monkeypatch.setattr(
        instance_files.editable_runtime_file_service,
        "read_managed_file",
        fake_read_managed_file,
    )

    response = await instance_files.read_managed_file_content(
        "inst-1",
        service.ROLE_PROMPT_KEY,
        db=None,
        current_user=SimpleNamespace(id="user-1"),
    )

    assert seen == {"instance_id": "inst-1", "role": InstanceRole.admin}
    assert response.data == {"key": service.ROLE_PROMPT_KEY, "instance_id": "inst-1"}

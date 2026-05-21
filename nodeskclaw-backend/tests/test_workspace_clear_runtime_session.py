from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.api import workspaces as workspace_api
from app.services import hermes_session, nfs_mount, openclaw_session


class FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = 0

    async def execute(self, _stmt):
        self.executed += 1
        return FakeRows(self.rows)


@pytest.mark.asyncio
async def test_clear_workspace_messages_clears_chat_and_all_runtime_context(monkeypatch):
    calls: list[tuple] = []
    openclaw_instance = SimpleNamespace(
        id="instance-1",
        name="distributor",
        agent_display_name="分发运营",
        runtime="openclaw",
    )
    hermes_instance = SimpleNamespace(
        id="instance-2",
        name="engineer",
        agent_display_name="实现工程师",
        runtime="hermes",
    )

    async def fake_check(*_args, **_kwargs):
        calls.append(("check",))

    async def fake_clear_messages(_db, workspace_id):
        calls.append(("clear_messages", workspace_id))
        return 3

    def fake_broadcast(workspace_id, event, payload):
        calls.append(("broadcast", workspace_id, event, payload))

    @asynccontextmanager
    async def fake_remote_fs(fs_instance, _db):
        calls.append(("remote_fs", fs_instance.id))
        yield SimpleNamespace()

    async def fake_clear_openclaw_workspace(_fs, workspace_id):
        calls.append(("clear_openclaw_workspace", workspace_id))
        return True

    async def fake_clear_openclaw_main(_fs):
        calls.append(("clear_openclaw_main",))
        return True

    async def fake_clear_hermes_workspace(_fs, workspace_id):
        calls.append(("clear_hermes_workspace", workspace_id))
        return True

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_access", fake_check)
    monkeypatch.setattr(workspace_api.msg_service, "clear_workspace_messages", fake_clear_messages)
    monkeypatch.setattr(workspace_api, "broadcast_event", fake_broadcast)
    monkeypatch.setattr(nfs_mount, "remote_fs", fake_remote_fs)
    monkeypatch.setattr(openclaw_session, "clear_workspace_session", fake_clear_openclaw_workspace)
    monkeypatch.setattr(openclaw_session, "clear_main_session", fake_clear_openclaw_main)
    monkeypatch.setattr(hermes_session, "clear_workspace_session", fake_clear_hermes_workspace)

    result = await workspace_api.clear_workspace_messages(
        "workspace-1",
        db=FakeDb([
            (SimpleNamespace(), openclaw_instance),
            (SimpleNamespace(), hermes_instance),
        ]),
        user=SimpleNamespace(id="user-1"),
    )

    runtime_context = result["data"]["runtime_context"]
    assert result["data"]["cleared_count"] == 3
    assert runtime_context["total"] == 2
    assert runtime_context["cleared_count"] == 2
    assert runtime_context["failed_count"] == 0
    assert runtime_context["skipped_count"] == 0
    assert calls[:2] == [
        ("check",),
        ("clear_messages", "workspace-1"),
    ]
    assert ("clear_openclaw_workspace", "workspace-1") in calls
    assert ("clear_hermes_workspace", "workspace-1") in calls
    assert calls[-1][0] == "broadcast"
    broadcast_runtime_context = calls[-1][3]["runtime_context"]
    assert broadcast_runtime_context["cleared_count"] == 2
    assert broadcast_runtime_context == {
        "total": 2,
        "cleared_count": 2,
        "skipped_count": 0,
        "failed_count": 0,
    }
    assert "results" not in broadcast_runtime_context


@pytest.mark.asyncio
async def test_clear_workspace_messages_redacts_runtime_errors_from_broadcast(monkeypatch):
    calls: list[tuple] = []
    instance = SimpleNamespace(
        id="instance-1",
        name="broken-agent",
        agent_display_name="异常员工",
        runtime="openclaw",
    )

    async def fake_check(*_args, **_kwargs):
        return None

    async def fake_clear_messages(_db, _workspace_id):
        return 1

    def fake_broadcast(workspace_id, event, payload):
        calls.append(("broadcast", workspace_id, event, payload))

    @asynccontextmanager
    async def fake_remote_fs(_fs_instance, _db):
        raise RuntimeError("/root/.openclaw/private-token")
        yield

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_access", fake_check)
    monkeypatch.setattr(workspace_api.msg_service, "clear_workspace_messages", fake_clear_messages)
    monkeypatch.setattr(workspace_api, "broadcast_event", fake_broadcast)
    monkeypatch.setattr(nfs_mount, "remote_fs", fake_remote_fs)

    result = await workspace_api.clear_workspace_messages(
        "workspace-1",
        db=FakeDb([(SimpleNamespace(), instance)]),
        user=SimpleNamespace(id="user-1"),
    )

    api_runtime_context = result["data"]["runtime_context"]
    broadcast_runtime_context = calls[-1][3]["runtime_context"]
    assert api_runtime_context["failed_count"] == 1
    assert api_runtime_context["results"][0]["error"] == "/root/.openclaw/private-token"
    assert broadcast_runtime_context == {
        "total": 1,
        "cleared_count": 0,
        "skipped_count": 0,
        "failed_count": 1,
    }
    assert "results" not in broadcast_runtime_context


@pytest.mark.asyncio
async def test_clear_workspace_messages_falls_back_to_openclaw_main_session(monkeypatch):
    calls: list[tuple] = []
    instance = SimpleNamespace(
        id="instance-1",
        name="legacy-agent",
        agent_display_name="旧员工",
        runtime="openclaw",
    )

    async def fake_check(*_args, **_kwargs):
        return None

    async def fake_clear_messages(_db, _workspace_id):
        return 1

    @asynccontextmanager
    async def fake_remote_fs(fs_instance, _db):
        calls.append(("remote_fs", fs_instance.id))
        yield SimpleNamespace()

    async def fake_clear_workspace(_fs, workspace_id):
        calls.append(("clear_openclaw_workspace", workspace_id))
        return False

    async def fake_clear_main(_fs):
        calls.append(("clear_openclaw_main",))
        return True

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_access", fake_check)
    monkeypatch.setattr(workspace_api.msg_service, "clear_workspace_messages", fake_clear_messages)
    monkeypatch.setattr(workspace_api, "broadcast_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(nfs_mount, "remote_fs", fake_remote_fs)
    monkeypatch.setattr(openclaw_session, "clear_workspace_session", fake_clear_workspace)
    monkeypatch.setattr(openclaw_session, "clear_main_session", fake_clear_main)

    result = await workspace_api.clear_workspace_messages(
        "workspace-1",
        db=FakeDb([(SimpleNamespace(), instance)]),
        user=SimpleNamespace(id="user-1"),
    )

    assert result["data"]["runtime_context"]["cleared_count"] == 1
    assert calls == [
        ("remote_fs", "instance-1"),
        ("clear_openclaw_workspace", "workspace-1"),
        ("clear_openclaw_main",),
    ]


@pytest.mark.asyncio
async def test_clear_workspace_messages_skips_unsupported_runtime(monkeypatch):
    instance = SimpleNamespace(
        id="instance-1",
        name="nanobot-agent",
        agent_display_name="Nanobot",
        runtime="nanobot",
    )

    async def fake_check(*_args, **_kwargs):
        return None

    async def fake_clear_messages(_db, _workspace_id):
        return 1

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_access", fake_check)
    monkeypatch.setattr(workspace_api.msg_service, "clear_workspace_messages", fake_clear_messages)
    monkeypatch.setattr(workspace_api, "broadcast_event", lambda *_args, **_kwargs: None)

    result = await workspace_api.clear_workspace_messages(
        "workspace-1",
        db=FakeDb([(SimpleNamespace(), instance)]),
        user=SimpleNamespace(id="user-1"),
    )

    assert result["data"]["runtime_context"]["total"] == 1
    assert result["data"]["runtime_context"]["skipped_count"] == 1
    assert result["data"]["runtime_context"]["cleared_count"] == 0

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import workspaces as workspace_api
from app.services import hermes_session, nfs_mount, openclaw_session


class FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeDb:
    def __init__(self, row=None):
        self.row = row
        self.executed = 0

    async def execute(self, _stmt):
        self.executed += 1
        return FakeResult(self.row)


@pytest.mark.asyncio
async def test_clear_workspace_messages_does_not_query_runtime(monkeypatch):
    calls: list[tuple] = []

    async def fake_check(*_args, **_kwargs):
        calls.append(("check",))

    async def fake_clear_messages(_db, workspace_id):
        calls.append(("clear_messages", workspace_id))
        return 3

    def fake_broadcast(workspace_id, event, payload):
        calls.append(("broadcast", workspace_id, event, payload))

    class NoRuntimeDb:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("messages/clear must not query runtime instances")

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_access", fake_check)
    monkeypatch.setattr(workspace_api.msg_service, "clear_workspace_messages", fake_clear_messages)
    monkeypatch.setattr(workspace_api, "broadcast_event", fake_broadcast)

    result = await workspace_api.clear_workspace_messages(
        "workspace-1",
        db=NoRuntimeDb(),
        user=SimpleNamespace(id="user-1"),
    )

    assert result["data"] == {"cleared_count": 3}
    assert calls == [
        ("check",),
        ("clear_messages", "workspace-1"),
        ("broadcast", "workspace-1", "chat:cleared", {"cleared_count": 3}),
    ]


@pytest.mark.asyncio
async def test_clear_openclaw_agent_runtime_session_clears_target_only(monkeypatch):
    calls: list[tuple] = []
    agent = SimpleNamespace(
        id="agent-row-1",
        instance_id="instance-1",
        display_name="分发运营",
    )
    instance = SimpleNamespace(
        id="instance-1",
        name="distributor",
        agent_display_name="分发运营",
        runtime="openclaw",
    )

    async def fake_check(*_args, **_kwargs):
        calls.append(("check",))

    @asynccontextmanager
    async def fake_remote_fs(fs_instance, _db):
        calls.append(("remote_fs", fs_instance.id))
        yield SimpleNamespace()

    async def fake_clear_workspace_session(_fs, workspace_id):
        calls.append(("clear_openclaw_workspace", workspace_id))
        return True

    async def fake_clear_main_session(_fs):
        calls.append(("clear_openclaw_main",))
        return True

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_access", fake_check)
    monkeypatch.setattr(nfs_mount, "remote_fs", fake_remote_fs)
    monkeypatch.setattr(openclaw_session, "clear_workspace_session", fake_clear_workspace_session)
    monkeypatch.setattr(openclaw_session, "clear_main_session", fake_clear_main_session)

    result = await workspace_api.clear_agent_runtime_session(
        "workspace-1",
        "instance-1",
        db=FakeDb((agent, instance)),
        user=SimpleNamespace(id="user-1"),
    )

    assert result["data"] == {
        "cleared": True,
        "agent_id": "instance-1",
        "agent_name": "分发运营",
        "runtime": "openclaw",
    }
    assert calls == [
        ("check",),
        ("remote_fs", "instance-1"),
        ("clear_openclaw_workspace", "workspace-1"),
    ]


@pytest.mark.asyncio
async def test_clear_hermes_agent_runtime_session_clears_workspace_session(monkeypatch):
    calls: list[tuple] = []
    agent = SimpleNamespace(
        id="agent-row-2",
        instance_id="instance-2",
        display_name="实现工程师",
    )
    instance = SimpleNamespace(
        id="instance-2",
        name="engineer",
        agent_display_name="实现工程师",
        runtime="hermes",
    )

    async def fake_check(*_args, **_kwargs):
        calls.append(("check",))

    @asynccontextmanager
    async def fake_remote_fs(fs_instance, _db):
        calls.append(("remote_fs", fs_instance.id))
        yield SimpleNamespace()

    async def fake_clear_workspace_session(_fs, workspace_id):
        calls.append(("clear_hermes_workspace", workspace_id))
        return True

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_access", fake_check)
    monkeypatch.setattr(nfs_mount, "remote_fs", fake_remote_fs)
    monkeypatch.setattr(hermes_session, "clear_workspace_session", fake_clear_workspace_session)

    result = await workspace_api.clear_agent_runtime_session(
        "workspace-1",
        "instance-2",
        db=FakeDb((agent, instance)),
        user=SimpleNamespace(id="user-1"),
    )

    assert result["data"] == {
        "cleared": True,
        "agent_id": "instance-2",
        "agent_name": "实现工程师",
        "runtime": "hermes",
    }
    assert calls == [
        ("check",),
        ("remote_fs", "instance-2"),
        ("clear_hermes_workspace", "workspace-1"),
    ]


@pytest.mark.asyncio
async def test_clear_agent_runtime_session_requires_workspace_agent(monkeypatch):
    async def fake_check(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_access", fake_check)

    with pytest.raises(HTTPException) as exc:
        await workspace_api.clear_agent_runtime_session(
            "workspace-1",
            "missing-agent",
            db=FakeDb(None),
            user=SimpleNamespace(id="user-1"),
        )

    assert exc.value.status_code == 404

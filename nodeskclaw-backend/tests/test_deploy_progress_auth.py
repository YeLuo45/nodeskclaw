import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import deploy as admin_deploy_api
from app.api.portal import deploy as portal_deploy_api
from app.core.deps import get_db
from app.core.exceptions import ForbiddenError, NotFoundError, register_exception_handlers
from app.core.security import get_current_user
from app.models.instance_member import InstanceRole
from app.schemas.deploy import DeployProgress
from app.services import instance_member_service
from app.services.k8s.event_bus import EventBus, SSEEvent


def _make_app(router, prefix: str) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix=prefix)
    return app


async def _override_db() -> AsyncGenerator[SimpleNamespace, None]:
    yield SimpleNamespace()


def _user(**kwargs):
    return SimpleNamespace(
        id=kwargs.get("id", "user-1"),
        current_org_id=kwargs.get("current_org_id", "org-1"),
        is_active=True,
        must_change_password=False,
    )


def _success_snapshot(deploy_id: str = "deploy-1") -> DeployProgress:
    return DeployProgress(
        deploy_id=deploy_id,
        step=1,
        total_steps=1,
        current_step="完成",
        status="success",
        message="部署成功",
        percent=100,
        step_names=["完成"],
    )


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def _final_event(deploy_id: str = "deploy-1") -> SSEEvent:
    return SSEEvent(
        event="deploy_progress",
        data={
            "deploy_id": deploy_id,
            "step": 1,
            "total_steps": 1,
            "current_step": "完成",
            "status": "success",
            "message": "部署成功",
            "percent": 100,
        },
    )


def test_event_bus_subscription_cleanup_is_idempotent():
    event_bus = EventBus()
    _queue, cleanup = event_bus.create_subscription("deploy_progress")

    assert event_bus.subscriber_count("deploy_progress") == 1
    cleanup()
    cleanup()

    assert event_bus.subscriber_count("deploy_progress") == 0


@pytest.mark.asyncio
async def test_portal_cancel_requires_auth(monkeypatch):
    app = _make_app(portal_deploy_api.router, "/deploy")
    called = False

    async def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("access check should not run without auth")

    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "require_deploy_cancel_instance_access",
        fail_if_called,
    )
    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "cancel_deploy",
        fail_if_called,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/deploy/deploy-1/cancel")

    assert response.status_code == 401
    assert called is False


@pytest.mark.asyncio
async def test_portal_cancel_denies_user_without_admin_access(monkeypatch):
    app = _make_app(portal_deploy_api.router, "/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = _override_db
    cancel_called = False

    async def deny_access(*_args, **_kwargs):
        raise ForbiddenError("权限不足", "errors.instance.insufficient_role")

    async def cancel_deploy(*_args, **_kwargs):
        nonlocal cancel_called
        cancel_called = True
        return "部署已取消"

    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "require_deploy_cancel_instance_access",
        deny_access,
    )
    monkeypatch.setattr(portal_deploy_api.deploy_service, "cancel_deploy", cancel_deploy)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/deploy/deploy-1/cancel")

    assert response.status_code == 403
    assert cancel_called is False


@pytest.mark.asyncio
async def test_portal_cancel_allows_instance_admin(monkeypatch):
    app = _make_app(portal_deploy_api.router, "/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = _override_db
    calls: list[str] = []

    async def allow_access(deploy_id, _db, user):
        assert deploy_id == "deploy-1"
        assert user.id == "user-1"
        calls.append("access")
        return "instance-1"

    async def cancel_deploy(deploy_id):
        assert deploy_id == "deploy-1"
        calls.append("cancel")
        return "部署已取消"

    async def emit(*_args, **_kwargs):
        calls.append("audit")

    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "require_deploy_cancel_instance_access",
        allow_access,
    )
    monkeypatch.setattr(portal_deploy_api.deploy_service, "cancel_deploy", cancel_deploy)
    monkeypatch.setattr(portal_deploy_api.hooks, "emit", emit)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/deploy/deploy-1/cancel")

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "部署已取消"
    assert calls == ["access", "cancel", "audit"]


@pytest.mark.asyncio
async def test_portal_cancel_access_requires_instance_admin_role(monkeypatch):
    seen: dict[str, object] = {}

    class FakeDb:
        async def execute(self, _stmt):
            return _ScalarResult("instance-1")

    async def check_instance_access(instance_id, user, min_role, db):
        seen["instance_id"] = instance_id
        seen["user_id"] = user.id
        seen["min_role"] = min_role
        seen["db"] = db

    monkeypatch.setattr(
        instance_member_service,
        "check_instance_access",
        check_instance_access,
    )

    instance_id = await portal_deploy_api.deploy_service.require_deploy_cancel_instance_access(
        "deploy-1",
        FakeDb(),
        _user(),
    )

    assert instance_id == "instance-1"
    assert seen["instance_id"] == "instance-1"
    assert seen["user_id"] == "user-1"
    assert seen["min_role"] == InstanceRole.admin


@pytest.mark.asyncio
async def test_admin_cancel_returns_not_found_for_other_org(monkeypatch):
    app = _make_app(admin_deploy_api.router, "/admin/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user(current_org_id="org-1")
    app.dependency_overrides[get_db] = _override_db
    cancel_called = False

    async def deny_org_access(*_args, **_kwargs):
        raise NotFoundError("部署记录不存在", "errors.common.not_found")

    async def cancel_deploy(*_args, **_kwargs):
        nonlocal cancel_called
        cancel_called = True
        return "部署已取消"

    monkeypatch.setattr(
        admin_deploy_api.deploy_service,
        "require_deploy_cancel_org_access",
        deny_org_access,
    )
    monkeypatch.setattr(admin_deploy_api.deploy_service, "cancel_deploy", cancel_deploy)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/admin/deploy/deploy-1/cancel")

    assert response.status_code == 404
    assert cancel_called is False


@pytest.mark.asyncio
async def test_admin_cancel_allows_same_org(monkeypatch):
    app = _make_app(admin_deploy_api.router, "/admin/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user(current_org_id="org-1")
    app.dependency_overrides[get_db] = _override_db
    calls: list[str] = []

    async def allow_org_access(deploy_id, _db, org_id):
        assert deploy_id == "deploy-1"
        assert org_id == "org-1"
        calls.append("access")
        return "instance-1"

    async def cancel_deploy(deploy_id):
        assert deploy_id == "deploy-1"
        calls.append("cancel")
        return "部署已取消"

    async def emit(*_args, **_kwargs):
        calls.append("audit")

    monkeypatch.setattr(
        admin_deploy_api.deploy_service,
        "require_deploy_cancel_org_access",
        allow_org_access,
    )
    monkeypatch.setattr(admin_deploy_api.deploy_service, "cancel_deploy", cancel_deploy)
    monkeypatch.setattr(admin_deploy_api.hooks, "emit", emit)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/admin/deploy/deploy-1/cancel")

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "部署已取消"
    assert calls == ["access", "cancel", "audit"]


@pytest.mark.asyncio
async def test_portal_progress_requires_auth(monkeypatch):
    app = _make_app(portal_deploy_api.router, "/deploy")
    called = False

    async def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("access check should not run without auth")

    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "require_deploy_progress_instance_access",
        fail_if_called,
    )
    monkeypatch.setattr(
        portal_deploy_api.event_bus,
        "create_subscription",
        lambda *_args: (_ for _ in ()).throw(AssertionError("subscription should not be created without auth")),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/deploy/progress/deploy-1")

    assert response.status_code == 401
    assert called is False


@pytest.mark.asyncio
async def test_portal_progress_denies_user_without_instance_access(monkeypatch):
    app = _make_app(portal_deploy_api.router, "/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = _override_db
    snapshot_called = False

    async def deny_access(*_args, **_kwargs):
        raise ForbiddenError("您没有该实例的访问权限", "errors.instance.no_access")

    async def fail_snapshot(*_args, **_kwargs):
        nonlocal snapshot_called
        snapshot_called = True
        return _success_snapshot()

    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "require_deploy_progress_instance_access",
        deny_access,
    )
    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "get_deploy_progress_snapshot",
        fail_snapshot,
    )
    monkeypatch.setattr(
        portal_deploy_api.event_bus,
        "create_subscription",
        lambda *_args: (_ for _ in ()).throw(AssertionError("subscription should not be created without access")),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/deploy/progress/deploy-1")

    assert response.status_code == 403
    assert snapshot_called is False


@pytest.mark.asyncio
async def test_portal_progress_replays_snapshot_for_viewer(monkeypatch):
    app = _make_app(portal_deploy_api.router, "/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = _override_db
    cleanup_called = 0

    async def allow_access(deploy_id, _db, user):
        assert deploy_id == "deploy-1"
        assert user.id == "user-1"
        return "instance-1"

    async def get_snapshot(deploy_id, _db):
        return _success_snapshot(deploy_id)

    def create_subscription(*topics):
        assert topics == ("deploy_progress",)
        queue: asyncio.Queue[SSEEvent] = asyncio.Queue()

        def cleanup():
            nonlocal cleanup_called
            cleanup_called += 1

        return queue, cleanup

    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "require_deploy_progress_instance_access",
        allow_access,
    )
    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "get_deploy_progress_snapshot",
        get_snapshot,
    )
    monkeypatch.setattr(portal_deploy_api.event_bus, "create_subscription", create_subscription)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/deploy/progress/deploy-1")

    assert response.status_code == 200
    assert "event: deploy_progress" in response.text
    assert '"status": "success"' in response.text
    assert cleanup_called == 1


@pytest.mark.asyncio
async def test_admin_progress_returns_not_found_for_other_org(monkeypatch):
    app = _make_app(admin_deploy_api.router, "/admin/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user(current_org_id="org-1")
    app.dependency_overrides[get_db] = _override_db
    snapshot_called = False

    async def deny_org_access(*_args, **_kwargs):
        raise NotFoundError("部署记录不存在", "errors.common.not_found")

    async def fail_snapshot(*_args, **_kwargs):
        nonlocal snapshot_called
        snapshot_called = True
        return _success_snapshot()

    monkeypatch.setattr(
        admin_deploy_api.deploy_service,
        "require_deploy_progress_org_access",
        deny_org_access,
    )
    monkeypatch.setattr(
        admin_deploy_api.deploy_service,
        "get_deploy_progress_snapshot",
        fail_snapshot,
    )
    monkeypatch.setattr(
        admin_deploy_api.event_bus,
        "create_subscription",
        lambda *_args: (_ for _ in ()).throw(AssertionError("subscription should not be created without access")),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/deploy/progress/deploy-1")

    assert response.status_code == 404
    assert snapshot_called is False


@pytest.mark.asyncio
async def test_admin_progress_replays_snapshot_for_same_org(monkeypatch):
    app = _make_app(admin_deploy_api.router, "/admin/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user(current_org_id="org-1")
    app.dependency_overrides[get_db] = _override_db
    cleanup_called = 0

    async def allow_org_access(deploy_id, _db, org_id):
        assert deploy_id == "deploy-1"
        assert org_id == "org-1"
        return "instance-1"

    async def get_snapshot(deploy_id, _db):
        return _success_snapshot(deploy_id)

    def create_subscription(*topics):
        assert topics == ("deploy_progress",)
        queue: asyncio.Queue[SSEEvent] = asyncio.Queue()

        def cleanup():
            nonlocal cleanup_called
            cleanup_called += 1

        return queue, cleanup

    monkeypatch.setattr(
        admin_deploy_api.deploy_service,
        "require_deploy_progress_org_access",
        allow_org_access,
    )
    monkeypatch.setattr(
        admin_deploy_api.deploy_service,
        "get_deploy_progress_snapshot",
        get_snapshot,
    )
    monkeypatch.setattr(admin_deploy_api.event_bus, "create_subscription", create_subscription)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/deploy/progress/deploy-1")

    assert response.status_code == 200
    assert "event: deploy_progress" in response.text
    assert '"status": "success"' in response.text
    assert cleanup_called == 1


@pytest.mark.asyncio
async def test_portal_progress_keeps_final_event_published_during_snapshot_check(monkeypatch):
    app = _make_app(portal_deploy_api.router, "/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user()
    app.dependency_overrides[get_db] = _override_db
    queue: asyncio.Queue[SSEEvent] = asyncio.Queue()
    calls: list[str] = []

    async def allow_access(*_args, **_kwargs):
        calls.append("access")
        return "instance-1"

    async def no_snapshot(*_args, **_kwargs):
        calls.append("snapshot")
        queue.put_nowait(_final_event())
        return None

    def create_subscription(*topics):
        assert topics == ("deploy_progress",)
        calls.append("subscribe")

        def cleanup():
            calls.append("cleanup")

        return queue, cleanup

    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "require_deploy_progress_instance_access",
        allow_access,
    )
    monkeypatch.setattr(
        portal_deploy_api.deploy_service,
        "get_deploy_progress_snapshot",
        no_snapshot,
    )
    monkeypatch.setattr(portal_deploy_api.event_bus, "create_subscription", create_subscription)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/deploy/progress/deploy-1")

    assert response.status_code == 200
    assert "event: deploy_progress" in response.text
    assert '"deploy_id": "deploy-1"' in response.text
    assert calls == ["access", "subscribe", "snapshot", "cleanup"]


@pytest.mark.asyncio
async def test_admin_progress_keeps_final_event_published_during_snapshot_check(monkeypatch):
    app = _make_app(admin_deploy_api.router, "/admin/deploy")
    app.dependency_overrides[get_current_user] = lambda: _user(current_org_id="org-1")
    app.dependency_overrides[get_db] = _override_db
    queue: asyncio.Queue[SSEEvent] = asyncio.Queue()
    calls: list[str] = []

    async def allow_access(*_args, **_kwargs):
        calls.append("access")
        return "instance-1"

    async def no_snapshot(*_args, **_kwargs):
        calls.append("snapshot")
        queue.put_nowait(_final_event())
        return None

    def create_subscription(*topics):
        assert topics == ("deploy_progress",)
        calls.append("subscribe")

        def cleanup():
            calls.append("cleanup")

        return queue, cleanup

    monkeypatch.setattr(
        admin_deploy_api.deploy_service,
        "require_deploy_progress_org_access",
        allow_access,
    )
    monkeypatch.setattr(
        admin_deploy_api.deploy_service,
        "get_deploy_progress_snapshot",
        no_snapshot,
    )
    monkeypatch.setattr(admin_deploy_api.event_bus, "create_subscription", create_subscription)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/deploy/progress/deploy-1")

    assert response.status_code == 200
    assert "event: deploy_progress" in response.text
    assert '"deploy_id": "deploy-1"' in response.text
    assert calls == ["access", "subscribe", "snapshot", "cleanup"]

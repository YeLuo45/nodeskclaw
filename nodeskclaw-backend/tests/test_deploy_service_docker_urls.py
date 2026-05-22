from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestError
from app.schemas.deploy import DeployRequest
from app.services import deploy_service
from app.services.deploy_service import (
    DEPLOY_STEPS_BASE,
    _DeployContext,
    _require_supported_runtime,
    _restore_agent_bundle_with_retry,
    _rewrite_docker_callback_url,
    _should_sync_runtime_llm_config,
)


def test_rewrite_docker_callback_url_rewrites_docker_desktop_host() -> None:
    assert _rewrite_docker_callback_url("http://172.17.0.1:4510/api/v1") == "http://host.docker.internal:4510/api/v1"
    assert _rewrite_docker_callback_url("ws://172.17.0.1:4510/api/v1/tunnel/connect") == "ws://host.docker.internal:4510/api/v1/tunnel/connect"


def test_rewrite_docker_callback_url_leaves_remote_host_untouched() -> None:
    assert _rewrite_docker_callback_url("https://nodeskclaw.example.com/api/v1") == "https://nodeskclaw.example.com/api/v1"


def test_should_sync_runtime_llm_config_keeps_openclaw_request_scoped() -> None:
    assert _should_sync_runtime_llm_config("openclaw", True, []) is True
    assert _should_sync_runtime_llm_config("openclaw", False, ["openai"]) is False


def test_should_sync_runtime_llm_config_uses_hermes_org_defaults() -> None:
    assert _should_sync_runtime_llm_config("hermes", True, []) is True
    assert _should_sync_runtime_llm_config("hermes", False, ["openai"]) is True
    assert _should_sync_runtime_llm_config("hermes", False, []) is False


def test_should_sync_runtime_llm_config_skips_unsupported_runtime() -> None:
    assert _should_sync_runtime_llm_config("unknown_runtime", True, ["openai"]) is False


def test_require_supported_runtime_allows_registered_runtime() -> None:
    _require_supported_runtime("openclaw")
    _require_supported_runtime("hermes")


def test_require_supported_runtime_rejects_removed_nanobot_runtime() -> None:
    with pytest.raises(BadRequestError) as exc_info:
        _require_supported_runtime("nanobot")

    assert exc_info.value.status_code == 400
    assert exc_info.value.message_key == "errors.validation.invalid_runtime"
    assert "nanobot" in exc_info.value.message


@pytest.mark.asyncio
async def test_precheck_rejects_removed_nanobot_runtime_before_db_access() -> None:
    class FailingDb:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("db should not be used")

    req = DeployRequest(
        cluster_id="cluster-1",
        name="demo",
        runtime="nanobot",
        image_version="v0.1.4",
    )

    with pytest.raises(BadRequestError) as exc_info:
        await deploy_service.precheck(req, FailingDb())

    assert exc_info.value.message_key == "errors.validation.invalid_runtime"


def _deploy_context(*, should_sync_runtime_llm_config: bool) -> _DeployContext:
    return _DeployContext(
        record_id="deploy-1",
        instance_id="instance-1",
        cluster_id="cluster-1",
        name="hermes-1",
        namespace="ns-hermes",
        image_version="latest",
        replicas=1,
        cpu_request="100m",
        cpu_limit="500m",
        mem_request="256Mi",
        mem_limit="1Gi",
        storage_class=None,
        storage_size="1Gi",
        quota_cpu="1",
        quota_mem="1Gi",
        env_vars={},
        advanced_config={},
        runtime="hermes",
        should_sync_runtime_llm_config=should_sync_runtime_llm_config,
    )


@pytest.mark.asyncio
async def test_execute_deploy_pipeline_adds_config_step_when_runtime_sync_requested(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_execute_inner(ctx, async_session_factory, get_config, total, steps):
        captured["ctx"] = ctx
        captured["total"] = total
        captured["steps"] = steps

    monkeypatch.setattr(deploy_service, "_execute_deploy_inner", fake_execute_inner)

    await deploy_service.execute_deploy_pipeline(
        _deploy_context(should_sync_runtime_llm_config=True)
    )

    assert captured["total"] == len(DEPLOY_STEPS_BASE) + 1
    assert captured["steps"] == [*DEPLOY_STEPS_BASE, "应用实例配置"]


@pytest.mark.asyncio
async def test_execute_deploy_pipeline_skips_config_step_without_runtime_sync(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_execute_inner(ctx, async_session_factory, get_config, total, steps):
        captured["ctx"] = ctx
        captured["total"] = total
        captured["steps"] = steps

    monkeypatch.setattr(deploy_service, "_execute_deploy_inner", fake_execute_inner)

    await deploy_service.execute_deploy_pipeline(
        _deploy_context(should_sync_runtime_llm_config=False)
    )

    assert captured["total"] == len(DEPLOY_STEPS_BASE)
    assert captured["steps"] == DEPLOY_STEPS_BASE


@pytest.mark.asyncio
async def test_execute_deploy_pipeline_adds_agent_bundle_restore_step(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_execute_inner(ctx, async_session_factory, get_config, total, steps):
        captured["ctx"] = ctx
        captured["total"] = total
        captured["steps"] = steps

    ctx = _deploy_context(should_sync_runtime_llm_config=False)
    ctx.template_agent_bundle_manifest = {"slug": "p0-echo-agent", "files": {}, "skills": []}
    monkeypatch.setattr(deploy_service, "_execute_deploy_inner", fake_execute_inner)

    await deploy_service.execute_deploy_pipeline(ctx)

    assert captured["total"] == len(DEPLOY_STEPS_BASE) + 1
    assert captured["steps"] == [*DEPLOY_STEPS_BASE, "恢复 AI 员工模板包"]


@pytest.mark.asyncio
async def test_restore_agent_bundle_retries_transient_exec_failure(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    async def fake_restore(instance, manifest, db):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("exec not ready")

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.services.agent_bundle_service.restore_agent_bundle", fake_restore)
    monkeypatch.setattr(deploy_service.asyncio, "sleep", fake_sleep)

    await _restore_agent_bundle_with_retry(
        SimpleNamespace(id="instance-1"),
        {"slug": "bundle-1"},
        None,
        max_retries=2,
        retry_delay=0.5,
    )

    assert calls == 2
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_restore_agent_bundle_raises_after_retries(monkeypatch) -> None:
    calls = 0

    async def fake_restore(instance, manifest, db):
        nonlocal calls
        calls += 1
        raise RuntimeError("exec still unavailable")

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr("app.services.agent_bundle_service.restore_agent_bundle", fake_restore)
    monkeypatch.setattr(deploy_service.asyncio, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="exec still unavailable"):
        await _restore_agent_bundle_with_retry(
            SimpleNamespace(id="instance-1"),
            {"slug": "bundle-1"},
            None,
            max_retries=2,
            retry_delay=0.5,
        )

    assert calls == 3

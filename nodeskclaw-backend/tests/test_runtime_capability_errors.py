from types import SimpleNamespace

import pytest

from app.core.exceptions import UnsupportedCapabilityError
from app.services import channel_config_service
from app.services.channel_config_service import _require_openclaw_channel_capability
from app.services.channel_config_service import _require_runtime_capability
from app.services.gene_service import _apply_manifest_actions
from app.services.runtime.hermes_gene_install_adapter import HermesGeneInstallAdapter
from app.services.runtime.noop_gene_install_adapter import NoopGeneInstallAdapter
from app.services.runtime.registries.runtime_registry import runtime_supports_capability


def test_unsupported_capability_error_exposes_structured_details():
    error = UnsupportedCapabilityError(
        runtime_id="hermes",
        capability="tool_allow",
        operation="gene.allow_tools",
    )

    assert error.code == 40080
    assert error.status_code == 400
    assert error.message_key == "errors.runtime.unsupported_capability"
    assert error.message_params == {
        "runtime_id": "hermes",
        "capability": "tool_allow",
        "operation": "gene.allow_tools",
    }
    assert error.details == {
        "code": "UNSUPPORTED_CAPABILITY",
        "runtime_id": "hermes",
        "capability": "tool_allow",
        "operation": "gene.allow_tools",
    }


def test_runtime_supports_capability_uses_registry_declarations():
    assert runtime_supports_capability("openclaw", "repo_channel_sync") is True
    assert runtime_supports_capability("hermes", "repo_channel_sync") is False
    assert runtime_supports_capability("unknown", "repo_channel_sync") is False


def test_channel_runtime_capability_gate_raises_structured_error():
    instance = SimpleNamespace(runtime="hermes")

    with pytest.raises(UnsupportedCapabilityError) as exc:
        _require_runtime_capability(
            instance,
            "repo_channel_sync",
            "channel.deploy_repo_plugin",
        )

    assert exc.value.details == {
        "code": "UNSUPPORTED_CAPABILITY",
        "runtime_id": "hermes",
        "capability": "repo_channel_sync",
        "operation": "channel.deploy_repo_plugin",
    }


def test_openclaw_channel_capability_gate_rejects_non_openclaw_runtime(monkeypatch):
    monkeypatch.setattr(channel_config_service, "runtime_supports_capability", lambda _runtime, _capability: True)
    instance = SimpleNamespace(runtime="custom")

    with pytest.raises(UnsupportedCapabilityError) as exc:
        _require_openclaw_channel_capability(
            instance,
            "upload_channel_plugin",
            "channel.upload_plugin",
        )

    assert exc.value.details == {
        "code": "UNSUPPORTED_CAPABILITY",
        "runtime_id": "custom",
        "capability": "upload_channel_plugin",
        "operation": "channel.upload_plugin",
    }


@pytest.mark.asyncio
async def test_hermes_gene_adapter_reports_unsupported_manifest_actions():
    adapter = HermesGeneInstallAdapter()

    with pytest.raises(UnsupportedCapabilityError) as tool_exc:
        await adapter.allow_tools(object(), ["shared-files"])
    assert tool_exc.value.details["capability"] == "tool_allow"
    assert tool_exc.value.details["runtime_id"] == "hermes"

    with pytest.raises(UnsupportedCapabilityError) as config_exc:
        await adapter.apply_config(object(), {"tools": {"allow": ["shared-files"]}})
    assert config_exc.value.details["capability"] == "runtime_config_patch"
    assert config_exc.value.details["runtime_id"] == "hermes"


@pytest.mark.asyncio
async def test_noop_gene_adapter_reports_runtime_id_for_unsupported_manifest_actions():
    adapter = NoopGeneInstallAdapter(runtime_id="custom")

    with pytest.raises(UnsupportedCapabilityError) as exc:
        await adapter.allow_tools(object(), ["shared-files"])

    assert exc.value.details["runtime_id"] == "custom"
    assert exc.value.details["capability"] == "tool_allow"


@pytest.mark.asyncio
async def test_manifest_actions_record_unsupported_warnings_without_failing_install():
    warnings = await _apply_manifest_actions(
        object(),
        {
            "runtime_config": {"tools": {"allow": ["shared-files"]}},
            "tool_allow": ["shared-files"],
        },
        HermesGeneInstallAdapter(),
    )

    assert [item["capability"] for item in warnings] == [
        "runtime_config_patch",
        "tool_allow",
    ]

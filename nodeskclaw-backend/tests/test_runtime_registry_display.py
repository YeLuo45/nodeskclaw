import pytest

from app.api.engines import list_engines
from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY
from app.services.runtime.registries.runtime_registry import RuntimeProductCapabilities, RuntimeRegistry, RuntimeSpec


def test_runtime_registry_display_order_and_names():
    specs = sorted(RUNTIME_REGISTRY.all_runtimes(), key=lambda spec: spec.order)

    assert [(spec.runtime_id, spec.display_name, spec.order) for spec in specs] == [
        ("openclaw", "全能员工引擎", 0),
        ("hermes", "自进化员工引擎", 1),
    ]


def test_runtime_specs_have_complete_product_capabilities():
    expected_keys = set(RuntimeProductCapabilities.__dataclass_fields__.keys())

    for spec in RUNTIME_REGISTRY.all_runtimes():
        capabilities = spec.capability_map()
        assert set(capabilities.keys()) == expected_keys
        assert spec.gateway_port is not None
        assert spec.config_rel_path
        assert spec.config_format
        assert spec.channels_section_key
        assert spec.field_naming
        assert spec.data_dir_container_path
        assert spec.skills_dir_rel
        assert spec.scripts_dir_rel
        assert spec.backup_dirs


def test_builtin_runtime_capability_matrix_matches_first_stage_contract():
    openclaw = RUNTIME_REGISTRY.get("openclaw")
    hermes = RUNTIME_REGISTRY.get("hermes")

    assert openclaw is not None
    assert hermes is not None

    assert openclaw.capability_map()["tool_allow"] is True
    assert openclaw.capability_map()["runtime_config_patch"] is True
    assert openclaw.capability_map()["repo_channel_sync"] is True
    assert openclaw.capability_map()["web_ui"] is True

    assert hermes.capability_map()["genes"] is True
    assert hermes.capability_map()["evolution_log"] is False
    assert hermes.capability_map()["tool_allow"] is False
    assert hermes.capability_map()["runtime_config_patch"] is False
    assert hermes.capability_map()["repo_channel_sync"] is False
    assert hermes.capability_map()["web_ui"] is False


def test_runtime_registry_rejects_specs_missing_required_product_metadata():
    registry = RuntimeRegistry()

    with pytest.raises(RuntimeError, match="capabilities"):
        registry.register(RuntimeSpec(runtime_id="custom"))


@pytest.mark.asyncio
async def test_engine_listing_returns_runtime_capabilities():
    response = await list_engines(_user=object())
    engines = {item["runtime_id"]: item for item in response.data}

    assert engines["openclaw"]["capabilities"]["tool_allow"] is True
    assert engines["openclaw"]["config_rel_path"] == ".openclaw/openclaw.json"
    assert engines["openclaw"]["backup_dirs"] == [".openclaw", ".deskclaw/tools"]

    assert engines["hermes"]["capabilities"]["evolution_log"] is False
    assert engines["hermes"]["capabilities"]["tool_allow"] is False
    assert engines["hermes"]["config_rel_path"] == ".hermes/config.yaml"

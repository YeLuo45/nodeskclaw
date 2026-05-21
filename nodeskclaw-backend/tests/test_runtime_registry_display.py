from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY


def test_runtime_registry_display_order_and_names():
    specs = sorted(RUNTIME_REGISTRY.all_runtimes(), key=lambda spec: spec.order)

    assert [(spec.runtime_id, spec.display_name, spec.order) for spec in specs] == [
        ("openclaw", "全能员工引擎", 0),
        ("hermes", "自进化员工引擎", 1),
    ]

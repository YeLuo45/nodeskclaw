import pytest

from app.models.system_config import SystemConfig
from app.startup.seed import (
    DEFAULT_ENGINE_VERSION_SEEDS,
    DEFAULT_REGISTRY_CONFIGS,
    _seed_default_registry_configs,
    seed_engine_versions,
)


class FakeExecuteResult:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.keys = iter(DEFAULT_REGISTRY_CONFIGS)
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return None

    async def execute(self, _statement):
        key = next(self.keys)
        return FakeExecuteResult(self.rows.get(key))

    def add(self, row):
        self.rows[row.key] = row

    async def commit(self):
        self.commit_count += 1


class FakeEngineVersionExecuteResult:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one(self):
        return self.scalar

    def all(self):
        return self.rows


class FakeEngineVersionSession:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return None

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("unexpected execute call")
        return self.results.pop(0)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commit_count += 1


@pytest.mark.parametrize(
    "legacy_value",
    [
        "nousresearch/hermes-agent",
        "ghcr.io/routin/deskclaw-hermes",
    ],
)
@pytest.mark.asyncio
async def test_seed_default_registry_configs_upgrades_legacy_hermes_registry(
    legacy_value,
):
    rows = {
        "image_registry_hermes": SystemConfig(
            key="image_registry_hermes",
            value=legacy_value,
        ),
        "legacy-marker": SystemConfig(key="legacy-marker", value="keep"),
    }
    sessions = []

    def session_factory():
        session = FakeSession(rows)
        sessions.append(session)
        return session

    await _seed_default_registry_configs(session_factory)

    assert (
        rows["image_registry_hermes"].value
        == DEFAULT_REGISTRY_CONFIGS["image_registry_hermes"]
        == "nodesk-center-cn-beijing.cr.volces.com/public/deskclaw-hermes"
    )
    assert rows["image_registry"].value == DEFAULT_REGISTRY_CONFIGS["image_registry"]
    assert "image_registry_nanobot" not in DEFAULT_REGISTRY_CONFIGS
    assert "image_registry_nanobot" not in rows
    assert rows["legacy-marker"].value == "keep"
    assert sessions[0].commit_count == 1


@pytest.mark.asyncio
async def test_seed_engine_versions_adds_builtin_hermes_default_for_empty_catalog():
    session = FakeEngineVersionSession([
        FakeEngineVersionExecuteResult(scalar=0),
        FakeEngineVersionExecuteResult(rows=[]),
        FakeEngineVersionExecuteResult(scalar=0),
    ])

    await seed_engine_versions(lambda: session)

    assert len(session.added) == 1
    seeded = session.added[0]
    expected = DEFAULT_ENGINE_VERSION_SEEDS[0]
    assert seeded.runtime == expected["runtime"] == "hermes"
    assert seeded.version == expected["version"] == "2026.4.23-20260514"
    assert seeded.image_tag == expected["image_tag"] == "v2026.4.23-20260514"
    assert seeded.status == "published"
    assert seeded.is_default is True
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_seed_engine_versions_keeps_existing_catalog_untouched():
    session = FakeEngineVersionSession([
        FakeEngineVersionExecuteResult(scalar=1),
    ])

    await seed_engine_versions(lambda: session)

    assert session.added == []
    assert session.commit_count == 0

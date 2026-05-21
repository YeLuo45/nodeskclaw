"""Tests verifying graceful handling of removed Nanobot runtime.

Covers:
1. get_config_adapter raises ValueError for unregistered runtimes
2. channel_config_service raises BadRequestError (HTTP 400) for nanobot instances
3. RUNTIME_REGISTRY.get returns None for nanobot (historical instances don't crash)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import BadRequestError
from app.services.runtime.config_adapter import get_config_adapter
from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY


def test_get_config_adapter_raises_for_nanobot():
    with pytest.raises(ValueError, match="不支持的 runtime"):
        get_config_adapter("nanobot")


def test_runtime_registry_returns_none_for_nanobot():
    spec = RUNTIME_REGISTRY.get("nanobot")
    assert spec is None


@pytest.mark.asyncio
async def test_discover_available_channels_rejects_nanobot(monkeypatch):
    from app.services import channel_config_service

    instance = MagicMock()
    instance.runtime = "nanobot"
    db = AsyncMock()

    with pytest.raises(BadRequestError) as exc_info:
        await channel_config_service.discover_available_channels(instance, db)

    assert exc_info.value.status_code == 400
    assert "nanobot" in exc_info.value.message


@pytest.mark.asyncio
async def test_read_channel_configs_rejects_nanobot():
    from app.services import channel_config_service

    instance = MagicMock()
    instance.runtime = "nanobot"
    db = AsyncMock()

    with pytest.raises(BadRequestError) as exc_info:
        await channel_config_service.read_channel_configs(instance, db)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_write_channel_configs_rejects_nanobot():
    from app.services import channel_config_service

    instance = MagicMock()
    instance.runtime = "nanobot"
    db = AsyncMock()

    with pytest.raises(BadRequestError) as exc_info:
        await channel_config_service.write_channel_configs(instance, db, {})

    assert exc_info.value.status_code == 400

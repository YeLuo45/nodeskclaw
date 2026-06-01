import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.exceptions import ConflictError
from app.models.cluster import Cluster
from app.models.instance import Instance
from app.models.node_card import NodeCard
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_agent import WorkspaceAgent
from app.services import conversation_service, instance_service

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw@localhost:5432/nodeskclaw_test"


@pytest.fixture
async def test_db():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    try:
        async with engine.connect():
            pass
    except Exception:
        await engine.dispose()
        pytest.skip("PostgreSQL test database is not available")
    uid = uuid.uuid4().hex[:8]
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session, uid
        for model in (NodeCard, WorkspaceAgent, Instance, Workspace, Cluster, User, Organization):
            await session.execute(delete(model).where(model.id.like(f"%{uid}%")))
        await session.commit()
    await engine.dispose()


def _base_records(uid: str):
    org = Organization(id=f"org-{uid}", name="Org", slug=f"org-{uid}")
    user = User(id=f"user-{uid}", name="Tester", username=f"tester-{uid}")
    cluster = Cluster(
        id=f"cluster-{uid}",
        name="Cluster",
        org_id=org.id,
        created_by=user.id,
    )
    instance = Instance(
        id=f"inst-{uid}",
        name="Agent Origin",
        slug=f"agent-{uid}",
        cluster_id=cluster.id,
        namespace="default",
        image_version="latest",
        created_by=user.id,
        org_id=org.id,
        status="running",
    )
    return org, user, cluster, instance


@pytest.mark.asyncio
async def test_update_display_name_syncs_only_inherited_workspace_agents(
    test_db, monkeypatch: pytest.MonkeyPatch,
):
    db, uid = test_db
    synced_workspace_ids: list[str] = []

    async def record_sync(workspace_id: str, _db):
        synced_workspace_ids.append(workspace_id)
        return []

    monkeypatch.setattr(
        conversation_service,
        "sync_conversations_and_notify_topology",
        record_sync,
    )

    org, user, cluster, instance = _base_records(uid)
    inherited_workspace = Workspace(
        id=f"ws-inherited-{uid}",
        org_id=org.id,
        name="Inherited Workspace",
        description="",
        color="#111111",
        icon="bot",
        created_by=user.id,
    )
    local_workspace = Workspace(
        id=f"ws-local-{uid}",
        org_id=org.id,
        name="Local Workspace",
        description="",
        color="#222222",
        icon="bot",
        created_by=user.id,
    )
    inherited_agent = WorkspaceAgent(
        id=f"wa-inherited-{uid}",
        workspace_id=inherited_workspace.id,
        instance_id=instance.id,
        hex_q=1,
        hex_r=0,
        display_name=None,
    )
    local_agent = WorkspaceAgent(
        id=f"wa-local-{uid}",
        workspace_id=local_workspace.id,
        instance_id=instance.id,
        hex_q=1,
        hex_r=0,
        display_name="Local Alias",
    )
    inherited_card = NodeCard(
        id=f"card-inherited-{uid}",
        node_type="agent",
        node_id=instance.id,
        workspace_id=inherited_workspace.id,
        hex_q=1,
        hex_r=0,
        name="Agent Origin",
    )
    local_card = NodeCard(
        id=f"card-local-{uid}",
        node_type="agent",
        node_id=instance.id,
        workspace_id=local_workspace.id,
        hex_q=1,
        hex_r=0,
        name="Local Alias",
    )
    db.add_all([org, user])
    await db.flush()
    db.add(cluster)
    await db.flush()
    db.add_all([instance, inherited_workspace, local_workspace])
    await db.flush()
    db.add_all([inherited_agent, local_agent, inherited_card, local_card])
    await db.commit()

    result = await instance_service.update_display_name(
        instance.id,
        "Agent Renamed",
        db,
        org.id,
    )

    await db.refresh(instance)
    await db.refresh(inherited_card)
    await db.refresh(local_card)

    assert result.changed is True
    assert result.old_display_name is None
    assert result.new_display_name == "Agent Renamed"
    assert result.old_effective_name == "Agent Origin"
    assert result.new_effective_name == "Agent Renamed"
    assert result.info.display_name == "Agent Renamed"
    assert result.info.effective_name == "Agent Renamed"
    assert instance.agent_display_name == "Agent Renamed"
    assert inherited_card.name == "Agent Renamed"
    assert local_card.name == "Local Alias"
    assert synced_workspace_ids == [inherited_workspace.id]


@pytest.mark.asyncio
async def test_update_display_name_restores_original_name(test_db, monkeypatch: pytest.MonkeyPatch):
    db, uid = test_db

    async def noop(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        conversation_service,
        "sync_conversations_and_notify_topology",
        noop,
    )

    org, user, cluster, instance = _base_records(uid)
    instance.agent_display_name = "Agent Renamed"
    workspace = Workspace(
        id=f"ws-{uid}",
        org_id=org.id,
        name="Workspace",
        description="",
        color="#111111",
        icon="bot",
        created_by=user.id,
    )
    agent = WorkspaceAgent(
        id=f"wa-{uid}",
        workspace_id=workspace.id,
        instance_id=instance.id,
        hex_q=1,
        hex_r=0,
        display_name=None,
    )
    card = NodeCard(
        id=f"card-{uid}",
        node_type="agent",
        node_id=instance.id,
        workspace_id=workspace.id,
        hex_q=1,
        hex_r=0,
        name="Agent Renamed",
    )
    db.add_all([org, user])
    await db.flush()
    db.add(cluster)
    await db.flush()
    db.add_all([instance, workspace])
    await db.flush()
    db.add_all([agent, card])
    await db.commit()

    result = await instance_service.update_display_name(instance.id, None, db, org.id)

    await db.refresh(instance)
    await db.refresh(card)

    assert result.changed is True
    assert result.new_display_name is None
    assert result.new_effective_name == "Agent Origin"
    assert result.info.display_name is None
    assert result.info.effective_name == "Agent Origin"
    assert instance.agent_display_name is None
    assert card.name == "Agent Origin"


@pytest.mark.asyncio
async def test_update_display_name_rejects_workspace_node_name_conflict(
    test_db, monkeypatch: pytest.MonkeyPatch,
):
    db, uid = test_db

    async def fail_sync(*_args, **_kwargs):
        raise AssertionError("topology sync should not run on conflict")

    monkeypatch.setattr(
        conversation_service,
        "sync_conversations_and_notify_topology",
        fail_sync,
    )

    org, user, cluster, instance = _base_records(uid)
    workspace = Workspace(
        id=f"ws-{uid}",
        org_id=org.id,
        name="Workspace",
        description="",
        color="#111111",
        icon="bot",
        created_by=user.id,
    )
    agent = WorkspaceAgent(
        id=f"wa-{uid}",
        workspace_id=workspace.id,
        instance_id=instance.id,
        hex_q=1,
        hex_r=0,
        display_name=None,
    )
    own_card = NodeCard(
        id=f"card-own-{uid}",
        node_type="agent",
        node_id=instance.id,
        workspace_id=workspace.id,
        hex_q=1,
        hex_r=0,
        name="Agent Origin",
    )
    other_card = NodeCard(
        id=f"card-other-{uid}",
        node_type="human",
        node_id=f"human-{uid}",
        workspace_id=workspace.id,
        hex_q=0,
        hex_r=1,
        name="Taken Name",
    )
    db.add_all([org, user])
    await db.flush()
    db.add(cluster)
    await db.flush()
    db.add_all([instance, workspace])
    await db.flush()
    db.add_all([agent, own_card, other_card])
    await db.commit()

    with pytest.raises(ConflictError) as exc_info:
        await instance_service.update_display_name(instance.id, "Taken Name", db, org.id)

    instance_result = await db.execute(select(Instance).where(Instance.id == instance.id))
    persisted_instance = instance_result.scalar_one()
    card_result = await db.execute(select(NodeCard).where(NodeCard.id == own_card.id))
    persisted_card = card_result.scalar_one()

    assert exc_info.value.message_key == "errors.instance.display_name_conflict_in_workspace"
    assert persisted_instance.agent_display_name is None
    assert persisted_card.name == "Agent Origin"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models.cluster import Cluster
from app.models.corridor import HumanHex
from app.models.instance import Instance
from app.models.node_card import NodeCard
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_agent import WorkspaceAgent
from app.schemas.workspace import AddAgentRequest, UpdateAgentRequest
from app.services import workspace_service
from app.services import conversation_service
import app.services.corridor_router as corridor_router

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw@localhost:5432/nodeskclaw_test"
engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def require_test_db():
    try:
        async with engine.connect():
            yield
    except Exception:
        pytest.skip("PostgreSQL test database is not available")


@pytest.mark.asyncio
async def test_update_agent_syncs_node_card_position(monkeypatch: pytest.MonkeyPatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(corridor_router, "cascade_delete_connections", noop)
    monkeypatch.setattr(corridor_router, "auto_connect_hex", noop)

    async with TestSessionLocal() as db:
        org = Organization(id="org-agent-sync", name="Org", slug="org-agent-sync")
        user = User(id="user-agent-sync", name="Tester", username="tester-agent-sync")
        cluster = Cluster(
            id="cluster-agent-sync",
            name="Cluster",
            org_id=org.id,
            created_by=user.id,
        )
        workspace = Workspace(
            id="ws-agent-sync",
            org_id=org.id,
            name="Workspace",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
        )
        instance = Instance(
            id="inst-agent-sync",
            name="Agent",
            slug="agent-sync",
            cluster_id=cluster.id,
            namespace="default",
            image_version="latest",
            created_by=user.id,
            org_id=org.id,
            workspace_id=workspace.id,
            status="running",
        )
        agent = WorkspaceAgent(
            id="wa-agent-sync",
            workspace_id=workspace.id,
            instance_id=instance.id,
            hex_q=1,
            hex_r=0,
            display_name="Agent",
        )
        card = NodeCard(
            id="card-agent-sync",
            node_type="agent",
            node_id=instance.id,
            workspace_id=workspace.id,
            hex_q=1,
            hex_r=0,
            name="Agent",
        )
        db.add_all([org, user])
        await db.flush()
        db.add_all([cluster, workspace])
        await db.flush()
        db.add(instance)
        await db.flush()
        db.add_all([agent, card])
        await db.commit()

        updated = await workspace_service.update_agent(
            db,
            workspace.id,
            instance.id,
            UpdateAgentRequest(hex_q=3, hex_r=-1),
        )

        await db.refresh(card)
        assert updated is not None
        assert updated.hex_q == 3
        assert updated.hex_r == -1
        assert card.hex_q == 3
        assert card.hex_r == -1


@pytest.mark.asyncio
async def test_update_agent_syncs_node_card_name_on_rename(monkeypatch: pytest.MonkeyPatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(corridor_router, "cascade_delete_connections", noop)
    monkeypatch.setattr(corridor_router, "auto_connect_hex", noop)

    async with TestSessionLocal() as db:
        org = Organization(id="org-agent-rename", name="Org", slug="org-agent-rename")
        user = User(id="user-agent-rename", name="Tester", username="tester-agent-rename")
        cluster = Cluster(
            id="cluster-agent-rename",
            name="Cluster",
            org_id=org.id,
            created_by=user.id,
        )
        workspace = Workspace(
            id="ws-agent-rename",
            org_id=org.id,
            name="Workspace",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
        )
        instance = Instance(
            id="inst-agent-rename",
            name="Agent Origin",
            slug="agent-rename",
            cluster_id=cluster.id,
            namespace="default",
            image_version="latest",
            created_by=user.id,
            org_id=org.id,
            workspace_id=workspace.id,
            status="running",
        )
        agent = WorkspaceAgent(
            id="wa-agent-rename",
            workspace_id=workspace.id,
            instance_id=instance.id,
            hex_q=1,
            hex_r=0,
            display_name="Agent Origin",
        )
        card = NodeCard(
            id="card-agent-rename",
            node_type="agent",
            node_id=instance.id,
            workspace_id=workspace.id,
            hex_q=1,
            hex_r=0,
            name="Agent Origin",
        )
        db.add_all([org, user])
        await db.flush()
        db.add_all([cluster, workspace])
        await db.flush()
        db.add(instance)
        await db.flush()
        db.add_all([agent, card])
        await db.commit()

        updated = await workspace_service.update_agent(
            db,
            workspace.id,
            instance.id,
            UpdateAgentRequest(display_name="Agent Renamed"),
        )

        await db.refresh(card)
        assert updated is not None
        assert updated.display_name == "Agent Renamed"
        assert card.name == "Agent Renamed"


@pytest.mark.asyncio
async def test_add_agent_auto_position_skips_occupied_node_cards(monkeypatch: pytest.MonkeyPatch):
    async def noop(*args, **kwargs):
        return None

    async def auto_connect(*args, **kwargs):
        return []

    async def has_any_connections(*args, **kwargs):
        return False

    monkeypatch.setattr(corridor_router, "auto_connect_hex", auto_connect)
    monkeypatch.setattr(corridor_router, "has_any_connections", has_any_connections)
    monkeypatch.setattr(conversation_service, "sync_conversations_and_notify_topology", noop)
    monkeypatch.setattr(workspace_service, "_deploy_channel_plugin", noop)
    monkeypatch.setattr(workspace_service, "_broadcast_join_message", noop)
    monkeypatch.setattr(workspace_service, "_send_welcome_message", noop)

    async with TestSessionLocal() as db:
        org = Organization(id="org-agent-add", name="Org", slug="org-agent-add")
        user = User(id="user-agent-add", name="Tester", username="tester-agent-add")
        cluster = Cluster(
            id="cluster-agent-add",
            name="Cluster",
            org_id=org.id,
            created_by=user.id,
        )
        workspace = Workspace(
            id="ws-agent-add",
            org_id=org.id,
            name="Workspace",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
            cluster_id=cluster.id,
        )
        existing_instances = [
            Instance(
                id=f"inst-agent-add-{idx}",
                name=f"Agent {idx}",
                slug=f"agent-add-{idx}",
                cluster_id=cluster.id,
                namespace="default",
                image_version="latest",
                created_by=user.id,
                org_id=org.id,
                status="running",
            )
            for idx in range(3)
        ]
        existing_positions = [(1, 0), (1, -1), (0, -1)]
        existing_agents = [
            WorkspaceAgent(
                id=f"wa-agent-add-{idx}",
                workspace_id=workspace.id,
                instance_id=inst.id,
                hex_q=pos[0],
                hex_r=pos[1],
                display_name=inst.name,
            )
            for idx, (inst, pos) in enumerate(zip(existing_instances, existing_positions))
        ]
        existing_cards = [
            NodeCard(
                id="card-blackboard-add",
                node_type="blackboard",
                node_id=workspace.id,
                workspace_id=workspace.id,
                hex_q=0,
                hex_r=0,
                name="Blackboard",
            ),
            *[
                NodeCard(
                    id=f"card-agent-add-{idx}",
                    node_type="agent",
                    node_id=inst.id,
                    workspace_id=workspace.id,
                    hex_q=pos[0],
                    hex_r=pos[1],
                    name=inst.name,
                )
                for idx, (inst, pos) in enumerate(zip(existing_instances, existing_positions))
            ],
            NodeCard(
                id="card-human-add",
                node_type="human",
                node_id="human-agent-add",
                workspace_id=workspace.id,
                hex_q=-1,
                hex_r=0,
                name="Human",
            ),
        ]
        human = HumanHex(
            id="human-agent-add",
            workspace_id=workspace.id,
            user_id=user.id,
            hex_q=-1,
            hex_r=0,
            display_name="Human",
            created_by=user.id,
        )
        new_instance = Instance(
            id="inst-agent-add-new",
            name="Agent New",
            slug="agent-add-new",
            cluster_id=cluster.id,
            namespace="default",
            image_version="latest",
            created_by=user.id,
            org_id=org.id,
            status="running",
        )
        db.add_all([org, user])
        await db.flush()
        db.add(cluster)
        await db.flush()
        db.add(workspace)
        await db.flush()
        db.add_all([*existing_instances, new_instance])
        await db.flush()
        db.add_all([*existing_agents, *existing_cards, human])
        await db.commit()

        added = await workspace_service.add_agent(
            db,
            workspace.id,
            AddAgentRequest(instance_id=new_instance.id, display_name="Agent New"),
            user.id,
        )

        card_result = await db.execute(
            select(NodeCard).where(NodeCard.node_id == new_instance.id)
        )
        new_card = card_result.scalar_one_or_none()
        assert added.hex_q == -1
        assert added.hex_r == 1
        assert new_card is not None
        assert new_card.hex_q == -1
        assert new_card.hex_r == 1

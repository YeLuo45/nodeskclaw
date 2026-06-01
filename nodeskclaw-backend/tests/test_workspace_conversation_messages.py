from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models.conversation import Conversation
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_message import WorkspaceMessage
from app.services.workspace_message_service import get_recent_messages, record_message

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
async def test_blackboard_conversation_history_includes_legacy_unscoped_messages():
    async with TestSessionLocal() as db:
        now = datetime.now(timezone.utc)
        org = Organization(id="org-conv-msg", name="Org", slug="org-conv-msg")
        user = User(id="user-conv-msg", name="Tester", username="tester-conv-msg")
        workspace = Workspace(
            id="ws-conv-msg",
            org_id=org.id,
            name="Workspace",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
        )
        blackboard = Conversation(
            id="conv-blackboard-msg",
            workspace_id=workspace.id,
            name="Blackboard",
            is_blackboard_group=True,
            member_node_ids=["agent-1", "agent-2"],
            member_hash="blackboard-hash",
        )
        normal = Conversation(
            id="conv-normal-msg",
            workspace_id=workspace.id,
            name="Normal",
            is_blackboard_group=False,
            member_node_ids=["agent-1", "agent-3"],
            member_hash="normal-hash",
        )
        db.add_all([org, user])
        await db.flush()
        db.add(workspace)
        await db.flush()
        db.add_all([blackboard, normal])
        await db.flush()
        db.add_all([
            WorkspaceMessage(
                id="msg-legacy",
                workspace_id=workspace.id,
                sender_type="agent",
                sender_id="agent-1",
                sender_name="Legacy",
                content="legacy hello",
                message_type="chat",
                created_at=now - timedelta(minutes=3),
            ),
            WorkspaceMessage(
                id="msg-blackboard",
                workspace_id=workspace.id,
                sender_type="agent",
                sender_id="agent-2",
                sender_name="Blackboard",
                content="blackboard hello",
                message_type="chat",
                conversation_id=blackboard.id,
                created_at=now - timedelta(minutes=2),
            ),
            WorkspaceMessage(
                id="msg-normal",
                workspace_id=workspace.id,
                sender_type="agent",
                sender_id="agent-3",
                sender_name="Normal",
                content="normal hello",
                message_type="chat",
                conversation_id=normal.id,
                created_at=now - timedelta(minutes=1),
            ),
        ])
        await db.commit()

        messages = await get_recent_messages(
            db,
            workspace.id,
            conversation_id=blackboard.id,
            include_unscoped=True,
        )

        assert [message.id for message in messages] == ["msg-legacy", "msg-blackboard"]


@pytest.mark.asyncio
async def test_normal_conversation_history_excludes_legacy_unscoped_messages():
    async with TestSessionLocal() as db:
        now = datetime.now(timezone.utc)
        org = Organization(id="org-conv-normal", name="Org", slug="org-conv-normal")
        user = User(id="user-conv-normal", name="Tester", username="tester-conv-normal")
        workspace = Workspace(
            id="ws-conv-normal",
            org_id=org.id,
            name="Workspace",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
        )
        normal = Conversation(
            id="conv-normal-only",
            workspace_id=workspace.id,
            name="Normal",
            is_blackboard_group=False,
            member_node_ids=["agent-1", "agent-2"],
            member_hash="normal-only-hash",
        )
        db.add_all([org, user])
        await db.flush()
        db.add(workspace)
        await db.flush()
        db.add(normal)
        await db.flush()
        db.add_all([
            WorkspaceMessage(
                id="msg-normal-legacy",
                workspace_id=workspace.id,
                sender_type="agent",
                sender_id="agent-1",
                sender_name="Legacy",
                content="legacy hello",
                message_type="chat",
                created_at=now - timedelta(minutes=2),
            ),
            WorkspaceMessage(
                id="msg-normal-only",
                workspace_id=workspace.id,
                sender_type="agent",
                sender_id="agent-2",
                sender_name="Normal",
                content="normal hello",
                message_type="chat",
                conversation_id=normal.id,
                created_at=now - timedelta(minutes=1),
            ),
        ])
        await db.commit()

        messages = await get_recent_messages(db, workspace.id, conversation_id=normal.id)

        assert [message.id for message in messages] == ["msg-normal-only"]


@pytest.mark.asyncio
async def test_record_message_sanitizes_agent_content_and_conversation_preview():
    async with TestSessionLocal() as db:
        org = Organization(id="org-record-sanitize", name="Org", slug="org-record-sanitize")
        user = User(id="user-record-sanitize", name="Tester", username="tester-record-sanitize")
        workspace = Workspace(
            id="ws-record-sanitize",
            org_id=org.id,
            name="Workspace",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
        )
        conversation = Conversation(
            id="conv-record-sanitize",
            workspace_id=workspace.id,
            name="Normal",
            is_blackboard_group=False,
            member_node_ids=["agent-1"],
            member_hash="record-sanitize",
        )
        db.add_all([org, user])
        await db.flush()
        db.add(workspace)
        await db.flush()
        db.add(conversation)
        await db.flush()

        message = await record_message(
            db,
            workspace_id=workspace.id,
            sender_type="agent",
            sender_id="agent-1",
            sender_name="Agent",
            content="<think>English reasoning</think>\n中文正文",
            conversation_id=conversation.id,
        )

        await db.refresh(conversation)

        assert message.content == "中文正文"
        assert conversation.last_message_preview == "中文正文"

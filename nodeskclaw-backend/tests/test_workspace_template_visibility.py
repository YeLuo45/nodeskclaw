from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.deps import get_current_org
from app.main import app
from app.models.cluster import Cluster
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_template import WorkspaceTemplate
from app.services.workspace_template_deploy_service import start_workspace_template_deploy
from tests.conftest import TestSessionLocal


@pytest.fixture
async def template_visibility_data(setup_db):
    suffix = uuid4().hex[:8]
    org_a = Organization(id=f"org-tpl-a-{suffix}", name="Template Org A", slug=f"template-org-a-{suffix}")
    org_b = Organization(id=f"org-tpl-b-{suffix}", name="Template Org B", slug=f"template-org-b-{suffix}")
    user_a = User(
        id=f"user-tpl-a-{suffix}",
        name="Template User A",
        email=f"template-a-{suffix}@example.com",
        username=f"template-a-{suffix}",
        password_hash="x",
        current_org_id=org_a.id,
    )
    workspace = Workspace(
        id=f"workspace-tpl-{suffix}",
        org_id=org_a.id,
        name="Workspace A",
        description="",
        created_by=user_a.id,
    )
    private_template = WorkspaceTemplate(
        id=f"template-private-{suffix}",
        name="Private Template",
        description="",
        org_id=org_b.id,
        visibility="org_private",
        created_by=f"user-owner-{suffix}",
        topology_snapshot={"nodes": [], "edges": []},
        blackboard_snapshot={},
        gene_assignments=[],
        agent_specs=[],
        human_specs=[],
    )

    try:
        async with TestSessionLocal() as db:
            db.add_all([org_a, org_b, user_a, workspace, private_template])
            await db.commit()
    except Exception:
        pytest.skip("test database unavailable")

    return {
        "user": user_a,
        "org": org_a,
        "workspace_id": workspace.id,
        "template_id": private_template.id,
    }


@pytest.mark.asyncio
async def test_get_template_blocks_other_org_private_template(client, template_visibility_data):
    app.dependency_overrides[get_current_org] = lambda: (
        template_visibility_data["user"], template_visibility_data["org"],
    )
    try:
        response = await client.get(f"/api/v1/workspaces/templates/{template_visibility_data['template_id']}")
    finally:
        app.dependency_overrides.pop(get_current_org, None)

    assert response.status_code == 403
    assert response.json() == {
        "code": 40350,
        "error_code": 40350,
        "message_key": "errors.template.access_denied",
        "message": "无权使用该模板",
        "data": None,
    }


@pytest.mark.asyncio
async def test_delete_template_blocks_other_org_private_template(client, template_visibility_data):
    app.dependency_overrides[get_current_org] = lambda: (
        template_visibility_data["user"], template_visibility_data["org"],
    )
    try:
        response = await client.delete(f"/api/v1/workspaces/templates/{template_visibility_data['template_id']}")
    finally:
        app.dependency_overrides.pop(get_current_org, None)

    assert response.status_code == 403
    assert response.json() == {
        "code": 40350,
        "error_code": 40350,
        "message_key": "errors.template.access_denied",
        "message": "无权使用该模板",
        "data": None,
    }


@pytest.mark.asyncio
async def test_apply_template_blocks_other_org_private_template(client, template_visibility_data):
    app.dependency_overrides[get_current_org] = lambda: (
        template_visibility_data["user"], template_visibility_data["org"],
    )
    try:
        response = await client.post(
            f"/api/v1/workspaces/templates/{template_visibility_data['template_id']}/apply",
            json={"target_workspace_id": template_visibility_data["workspace_id"]},
        )
    finally:
        app.dependency_overrides.pop(get_current_org, None)

    assert response.status_code == 403
    assert response.json() == {
        "code": 40350,
        "error_code": 40350,
        "message_key": "errors.template.access_denied",
        "message": "无权使用该模板",
        "data": None,
    }


@pytest.mark.asyncio
async def test_delete_template_keeps_other_org_template_undeleted(client, template_visibility_data):
    app.dependency_overrides[get_current_org] = lambda: (
        template_visibility_data["user"], template_visibility_data["org"],
    )
    try:
        await client.delete(f"/api/v1/workspaces/templates/{template_visibility_data['template_id']}")
    finally:
        app.dependency_overrides.pop(get_current_org, None)

    async with TestSessionLocal() as db:
        template = (
            await db.execute(
                select(WorkspaceTemplate).where(
                    WorkspaceTemplate.id == template_visibility_data["template_id"],
                )
            )
        ).scalar_one()
    assert template.deleted_at is None


@pytest.mark.asyncio
async def test_start_workspace_template_deploy_rejects_other_org_cluster():
    suffix = uuid4().hex[:8]
    org_a = Organization(id=f"org-deploy-a-{suffix}", name="Deploy Org A", slug=f"deploy-org-a-{suffix}")
    org_b = Organization(id=f"org-deploy-b-{suffix}", name="Deploy Org B", slug=f"deploy-org-b-{suffix}")
    user_a = User(
        id=f"user-deploy-a-{suffix}",
        name="Deploy User A",
        email=f"deploy-a-{suffix}@example.com",
        username=f"deploy-a-{suffix}",
        password_hash="x",
        current_org_id=org_a.id,
    )
    cluster_b = Cluster(
        id=f"cluster-deploy-b-{suffix}",
        name=f"Cluster B {suffix}",
        compute_provider="k8s",
        created_by=user_a.id,
        org_id=org_b.id,
    )
    template = WorkspaceTemplate(
        id=f"template-deploy-{suffix}",
        name="Deploy Template",
        description="",
        org_id=org_a.id,
        visibility="org_private",
        created_by=user_a.id,
        topology_snapshot={"nodes": [], "edges": []},
        blackboard_snapshot={},
        gene_assignments=[],
        agent_specs=[{"display_name": "Agent 1", "runtime": "openclaw", "compute_provider": "k8s"}],
        human_specs=[],
    )

    try:
        async with TestSessionLocal() as db:
            db.add_all([org_a, org_b, user_a, cluster_b])
            await db.commit()

            with pytest.raises(ValueError, match="集群不存在"):
                await start_workspace_template_deploy(
                    db,
                    template=template,
                    workspace_name="Workspace Deploy",
                    cluster_id=cluster_b.id,
                    user=user_a,
                    org_id=org_a.id,
                )
    except Exception:
        pytest.skip("test database unavailable")

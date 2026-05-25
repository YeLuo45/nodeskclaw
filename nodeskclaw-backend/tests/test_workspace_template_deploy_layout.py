from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api import templates as templates_api
from app.models.cluster import Cluster
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_deploy import WorkspaceDeploy
from app.models.workspace_template import WorkspaceTemplate
from app.services.workspace_template_deploy_service import (
    _build_agent_specs_with_layout,
    _filter_topology_by_exclusions,
    prepare_template_deploy_layout,
    start_workspace_template_deploy,
)
from tests.conftest import TestSessionLocal


def _template(agent_specs: list[dict], *, topology: dict | None = None, humans: list[dict] | None = None):
    return WorkspaceTemplate(
        id=f"template-layout-{uuid4().hex[:8]}",
        name="Layout Template",
        description="",
        org_id="org-layout",
        visibility="org_private",
        created_by="user-layout",
        topology_snapshot=topology or {"nodes": [], "edges": []},
        blackboard_snapshot={},
        gene_assignments=[],
        agent_specs=agent_specs,
        human_specs=humans or [],
    )


def test_layout_check_reports_missing_position():
    result = prepare_template_deploy_layout(
        _template([{"display_name": "A", "runtime": "openclaw", "compute_provider": "k8s"}])
    )

    assert result["can_deploy"] is False
    assert result["issues"][0]["code"] == "missing_position"
    assert result["agent_positions"] == []


def test_layout_check_reports_blackboard_conflict():
    result = prepare_template_deploy_layout(
        _template([{"display_name": "A", "hex_q": 0, "hex_r": 0}])
    )

    assert result["can_deploy"] is False
    assert result["issues"][0]["code"] == "blackboard_conflict"


def test_layout_check_reports_duplicate_agent_position():
    result = prepare_template_deploy_layout(
        _template([
            {"display_name": "A", "hex_q": 1, "hex_r": 0},
            {"display_name": "B", "hex_q": 1, "hex_r": 0},
        ])
    )

    assert result["can_deploy"] is False
    assert any(issue["code"] == "duplicate_position" for issue in result["issues"])


def test_layout_check_accepts_override_to_empty_hex():
    result = prepare_template_deploy_layout(
        _template([{"display_name": "A"}]),
        agent_positions=[{"agent_index": 0, "hex_q": 2, "hex_r": -1}],
    )

    assert result["can_deploy"] is True
    assert result["agent_positions"] == [{"agent_index": 0, "hex_q": 2, "hex_r": -1}]


def test_deploy_layout_requires_explicit_confirmed_positions():
    result = prepare_template_deploy_layout(
        _template([{"display_name": "A", "hex_q": 1, "hex_r": 0}]),
        require_explicit_agent_positions=True,
    )

    assert result["can_deploy"] is False
    assert result["issues"][0]["code"] == "missing_position"


@pytest.mark.asyncio
async def test_layout_check_endpoint_requires_explicit_positions(monkeypatch):
    template = _template([{"display_name": "A", "hex_q": 1, "hex_r": 0}])

    async def fake_get_template_with_access(template_id, org_id, db):
        assert template_id == template.id
        assert org_id == template.org_id
        assert db is not None
        return template

    monkeypatch.setattr(templates_api, "_get_template_with_access", fake_get_template_with_access)

    response = await templates_api.check_template_deploy_layout(
        template.id,
        templates_api.TemplateDeployLayoutCheckRequest(),
        org_ctx=(None, SimpleNamespace(id=template.org_id)),
        db=SimpleNamespace(),
    )

    assert response["data"]["can_deploy"] is False
    assert response["data"]["issues"][0]["code"] == "missing_position"


@pytest.mark.asyncio
async def test_layout_check_endpoint_accepts_confirmed_positions(monkeypatch):
    template = _template([{"display_name": "A", "hex_q": 1, "hex_r": 0}])

    async def fake_get_template_with_access(*_args):
        return template

    monkeypatch.setattr(templates_api, "_get_template_with_access", fake_get_template_with_access)

    response = await templates_api.check_template_deploy_layout(
        template.id,
        templates_api.TemplateDeployLayoutCheckRequest(
            agent_positions=[{"agent_index": 0, "hex_q": 2, "hex_r": -1}],
        ),
        org_ctx=(None, SimpleNamespace(id=template.org_id)),
        db=SimpleNamespace(),
    )

    assert response["data"]["can_deploy"] is True
    assert response["data"]["agent_positions"] == [{"agent_index": 0, "hex_q": 2, "hex_r": -1}]


def test_layout_rewrites_topology_edges_after_agent_move():
    template = _template(
        [{"display_name": "A", "hex_q": 1, "hex_r": 0}],
        topology={
            "nodes": [{"node_type": "corridor", "hex_q": 2, "hex_r": 0}],
            "edges": [{"a_q": 1, "a_r": 0, "b_q": 2, "b_r": 0, "direction": "both"}],
        },
    )
    layout = prepare_template_deploy_layout(
        template,
        agent_positions=[{"agent_index": 0, "hex_q": 3, "hex_r": -1}],
    )
    agent_specs, rewrites = _build_agent_specs_with_layout(
        list(template.agent_specs or []),
        layout["selected_agent_indices"],
        layout["agent_positions"],
    )
    topology = _filter_topology_by_exclusions(
        template.topology_snapshot,
        list(template.agent_specs or []),
        layout["selected_agent_indices"],
        layout["excluded_corridor_coords"],
        rewrites,
    )

    assert agent_specs[0]["hex_q"] == 3
    assert topology["edges"][0]["a_q"] == 3
    assert topology["edges"][0]["a_r"] == -1


@pytest.mark.asyncio
async def test_deploy_rejects_invalid_layout_before_creating_resources():
    suffix = uuid4().hex[:8]
    org = Organization(id=f"org-layout-{suffix}", name="Layout Org", slug=f"layout-org-{suffix}")
    user = User(
        id=f"user-layout-{suffix}",
        name="Layout User",
        email=f"layout-{suffix}@example.com",
        username=f"layout-{suffix}",
        password_hash="x",
        current_org_id=org.id,
    )
    cluster = Cluster(
        id=f"cluster-layout-{suffix}",
        name=f"Cluster {suffix}",
        compute_provider="k8s",
        created_by=user.id,
        org_id=org.id,
    )
    template = WorkspaceTemplate(
        id=f"template-layout-{suffix}",
        name="Layout Template",
        description="",
        org_id=org.id,
        visibility="org_private",
        created_by=user.id,
        topology_snapshot={"nodes": [], "edges": []},
        blackboard_snapshot={},
        gene_assignments=[],
        agent_specs=[{"display_name": "A", "runtime": "openclaw", "compute_provider": "k8s"}],
        human_specs=[],
    )

    try:
        async with TestSessionLocal() as db:
            db.add_all([org, user, cluster, template])
            await db.commit()

            with pytest.raises(ValueError, match="模板部署布局未通过校验"):
                await start_workspace_template_deploy(
                    db,
                    template=template,
                    workspace_name="Layout Workspace",
                    cluster_id=cluster.id,
                    user=user,
                    org_id=org.id,
                )

            workspace_count = (
                await db.execute(select(func.count()).select_from(Workspace))
            ).scalar_one()
            deploy_count = (
                await db.execute(select(func.count()).select_from(WorkspaceDeploy))
            ).scalar_one()
    except Exception:
        pytest.skip("test database unavailable")

    assert workspace_count == 0
    assert deploy_count == 0

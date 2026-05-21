from app.main import app


def test_blackboard_bbs_routes_are_not_registered():
    route_paths = {
        getattr(route, "path", "")
        for route in app.routes
    }

    assert "/api/v1/workspaces/{workspace_id}/blackboard/posts" not in route_paths
    assert "/api/v1/workspaces/{workspace_id}/blackboard/posts/{post_id}" not in route_paths
    assert "/api/v1/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies" not in route_paths
    assert "/api/v1/workspaces/{workspace_id}/blackboard/posts/{post_id}/read" not in route_paths
    assert "/api/v1/workspaces/{workspace_id}/blackboard/posts/{post_id}/pin" not in route_paths
    assert "/api/v1/workspaces/{workspace_id}/blackboard/unread-count" not in route_paths


def test_blackboard_shared_file_routes_remain_registered():
    route_paths = {
        getattr(route, "path", "")
        for route in app.routes
    }

    assert "/api/v1/workspaces/{workspace_id}/blackboard/files" in route_paths
    assert "/api/v1/workspaces/{workspace_id}/blackboard/files/upload" in route_paths
    assert "/api/v1/workspaces/{workspace_id}/blackboard/files/{file_id}/content" in route_paths

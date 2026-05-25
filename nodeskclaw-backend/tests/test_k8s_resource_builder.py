from app.services.k8s.resource_builder import build_labels, build_network_policy


def test_network_policy_allows_common_ingress_controller_namespaces() -> None:
    policy = build_network_policy(
        name="agent-isolation",
        namespace="agent-ns",
        labels=build_labels("agent", "v1", "instance-1"),
        peer_namespaces=[],
        platform_namespace="nodeskclaw-system",
        ingress_enabled=True,
        egress_enabled=False,
    )

    ingress_from = policy["spec"]["ingress"][0]["from"]
    allowed_namespaces = {
        item["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]
        for item in ingress_from
        if "namespaceSelector" in item
    }

    assert "nodeskclaw-system" in allowed_namespaces
    assert "kube-system" in allowed_namespaces
    assert "ingress-nginx" in allowed_namespaces

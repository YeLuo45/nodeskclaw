import io
import json
import os
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import BadRequestError
from app.api.instance_templates import _read_upload_file_limited
from app.models.gene import ContentVisibility, Gene, GeneSource
from app.models.instance_template import InstanceTemplateType
from app.models.organization import Organization
from app.models.user import User
from app.services.agent_bundle_service import (
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
    MAX_ZIP_BYTES,
    MAX_ZIP_ENTRIES,
    SECRET_REF_SOURCE_NAMESPACE_KEY,
    ZIP_RATIO_MIN_FILE_BYTES,
    build_bundle_env_vars,
    parse_agent_bundle_dir,
    parse_agent_bundle_zip,
    restore_agent_bundle,
    sanitize_agent_bundle_manifest,
    summarize_agent_bundle_manifest,
)
from app.services.deploy_service import _collect_secret_env_refs
from app.services import instance_template_service
from app.services.instance_template_service import (
    _next_agent_bundle_placeholder_name,
    _suggest_agent_bundle_display_name,
    _template_to_info,
    get_template_agent_bundle_manifest,
    get_template_deploy_env_vars,
    import_agent_bundle_manifest,
)
from app.services.k8s.resource_builder import build_configmap, build_deployment, build_labels

FIXTURES = Path(__file__).parent / "fixtures" / "agent_bundles"
TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw@localhost:5432/nodeskclaw_test"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def make_agent_bundle_zip(extra_path: str, extra_content: str = "payload") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("config.json", json.dumps({"name": "Q", "slug": "q", "model": "mock/q", "env": {}}))
        zf.writestr("AGENT.md", "# Q\nhello")
        zf.writestr("SOUL.md", "soul")
        zf.writestr(
            "skills/echo/SKILL.md",
            "---\nname: echo\nversion: 1.0.0\ndescription: Echo skill\npermissions:\n  tools: []\n---\n# Echo\n",
        )
        zf.writestr(extra_path, extra_content)
    return buf.getvalue()


def make_base_agent_bundle_zip(
    entries: list[tuple[str, bytes | str]] | None = None,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compression) as zf:
        zf.writestr("config.json", json.dumps({"name": "Q", "slug": "q", "model": "mock/q", "env": {}}))
        zf.writestr("AGENT.md", "# Q\nhello")
        zf.writestr("SOUL.md", "soul")
        zf.writestr(
            "skills/echo/SKILL.md",
            "---\nname: echo\nversion: 1.0.0\ndescription: Echo skill\npermissions:\n  tools: []\n---\n# Echo\n",
        )
        for path, content in entries or []:
            zf.writestr(path, content)
    return buf.getvalue()


def make_agent_bundle_zip_with_config(config: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("config.json", json.dumps(config))
        zf.writestr("AGENT.md", "# Q\nhello")
        zf.writestr("SOUL.md", "soul")
        zf.writestr(
            "skills/echo/SKILL.md",
            "---\nname: echo\nversion: 1.0.0\ndescription: Echo skill\npermissions:\n  tools: []\n---\n# Echo\n",
        )
    return buf.getvalue()


def make_agent_bundle_zip_with_skill_name(skill_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("config.json", json.dumps({"name": "Q", "slug": "q", "model": "mock/q", "env": {}}))
        zf.writestr("AGENT.md", "# Q\nhello")
        zf.writestr("SOUL.md", "soul")
        zf.writestr(
            "skills/echo/SKILL.md",
            "\n".join([
                "---",
                f"name: {json.dumps(skill_name)}",
                "version: 1.0.0",
                "description: Echo skill",
                "permissions:",
                "  tools: []",
                "---",
                "# Echo",
            ]),
        )
    return buf.getvalue()


class FakeUploadFile:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.offset >= len(self.data):
            return b""
        if size is None or size < 0:
            size = len(self.data) - self.offset
        chunk = self.data[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


@pytest.fixture
async def require_test_db():
    try:
        async with engine.connect():
            yield
    except Exception:
        pytest.skip("PostgreSQL test database is not available")


@pytest.mark.parametrize(
    "name",
    [
        "p0_echo_agent",
        "p1_template_import_agent",
        "p2_stateful_local_agent",
        "p2a_external_service_agent",
        "p3_resource_profile_agent",
        "p4_oauth_probe_agent",
        "p5_video_clone_mock_agent",
        "p5_video_clone_real_sanitized",
    ],
)
def test_parse_valid_agent_bundle_fixtures(name: str) -> None:
    manifest = parse_agent_bundle_dir(FIXTURES / name)

    assert manifest["schema_version"] == 1
    assert manifest["slug"]
    assert manifest["files"]["AGENT.md"]
    assert manifest["files"]["SOUL.md"]
    assert len(manifest["skills"]) >= 1
    assert manifest["skills"][0]["description"]


@pytest.mark.parametrize(
    "name, message",
    [
        ("invalid_missing_soul", "SOUL.md"),
        ("invalid_secret_in_config", "明文密钥"),
        ("invalid_script_path", "非法脚本路径"),
        ("invalid_bad_skill_frontmatter", "缺少 description"),
    ],
)
def test_parse_invalid_agent_bundle_fixtures(name: str, message: str) -> None:
    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_dir(FIXTURES / name)

    assert message in exc.value.message


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "skills/echo/bad'name.txt",
        "skills/echo/bad;name.txt",
        "skills/echo/bad name.txt",
        "skills/echo/bad$name.txt",
        "skills\\echo\\bad.txt",
        "skills/echo/bad\nname.txt",
        "skills/echo/./bad.txt",
        "skills//echo/bad.txt",
    ],
)
def test_parse_agent_bundle_zip_rejects_shell_sensitive_paths(unsafe_path: str) -> None:
    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", make_agent_bundle_zip(unsafe_path))

    assert "非法路径" in exc.value.message


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../../workspace/pwned",
        "../x",
        "x/y",
        "x\\y",
        ".hidden",
        "..",
        "bad name",
        "bad;name",
        "bad$name",
        "bad\nname",
    ],
)
def test_parse_agent_bundle_zip_rejects_unsafe_skill_names(unsafe_name: str) -> None:
    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", make_agent_bundle_zip_with_skill_name(unsafe_name))

    assert "skill name" in exc.value.message


@pytest.mark.parametrize(
    "skill_name",
    [
        "echo",
        "content-video-clone-workflow",
        "team_culture.v1",
    ],
)
def test_parse_agent_bundle_zip_accepts_safe_skill_names(skill_name: str) -> None:
    manifest = parse_agent_bundle_zip("bundle.zip", make_agent_bundle_zip_with_skill_name(skill_name))

    assert manifest["skills"][0]["name"] == skill_name


def test_parse_agent_bundle_zip_does_not_call_extractall(monkeypatch) -> None:
    def fail_extractall(*_args, **_kwargs):
        raise AssertionError("extractall should not be used")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", fail_extractall)

    manifest = parse_agent_bundle_zip("bundle.zip", make_agent_bundle_zip("README.md", "hello"))

    assert manifest["slug"] == "q"
    assert manifest["files"]["README.md"] == "hello"


def test_parse_agent_bundle_zip_rejects_total_size_before_reading_entries(monkeypatch) -> None:
    entries = [(f"docs/part-{idx}.txt", "a" * 82_000) for idx in range((MAX_TOTAL_BYTES // 82_000) + 2)]
    data = make_base_agent_bundle_zip(entries, compression=zipfile.ZIP_DEFLATED)
    assert len(data) < 100_000

    def fail_open(*_args, **_kwargs):
        raise AssertionError("oversized bundle should be rejected before reading entries")

    monkeypatch.setattr(zipfile.ZipFile, "open", fail_open)

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "总大小超过限制" in exc.value.message


def test_parse_agent_bundle_zip_rejects_single_oversized_file() -> None:
    data = make_base_agent_bundle_zip([("docs/large.txt", "a" * (MAX_FILE_BYTES + 1))])

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "文件过大" in exc.value.message


def test_parse_agent_bundle_zip_rejects_too_many_entries() -> None:
    entries = [(f"docs/file-{idx}.txt", "x") for idx in range(MAX_ZIP_ENTRIES + 1)]
    data = make_base_agent_bundle_zip(entries)

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "文件数量超过限制" in exc.value.message


def test_parse_agent_bundle_zip_rejects_high_compression_ratio() -> None:
    data = make_base_agent_bundle_zip(
        [("docs/compressed.txt", "a" * ZIP_RATIO_MIN_FILE_BYTES)],
        compression=zipfile.ZIP_DEFLATED,
    )

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "压缩率异常" in exc.value.message


def test_parse_agent_bundle_zip_rejects_secret_ref_source_env() -> None:
    data = make_agent_bundle_zip_with_config({
        "name": "Q",
        "slug": "q",
        "model": "mock/q",
        "secretRefs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
            "sourceEnv": "JWT_SECRET",
        }],
    })

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "不允许声明 sourceEnv" in exc.value.message


def test_parse_agent_bundle_zip_rejects_empty_secret_ref_source_env() -> None:
    data = make_agent_bundle_zip_with_config({
        "name": "Q",
        "slug": "q",
        "model": "mock/q",
        "secretRefs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
            "sourceEnv": "",
        }],
    })

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "不允许声明 sourceEnv" in exc.value.message


def test_parse_agent_bundle_zip_rejects_secret_ref_unknown_source() -> None:
    data = make_agent_bundle_zip_with_config({
        "name": "Q",
        "slug": "q",
        "model": "mock/q",
        "secretRefs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
            "source": {"value": "plain-token"},
        }],
    })

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "不支持的字段: source" in exc.value.message


@pytest.mark.parametrize("field_name", ["secretRefs", "secret_refs"])
def test_parse_agent_bundle_zip_rejects_non_array_secret_refs(field_name: str) -> None:
    data = make_agent_bundle_zip_with_config({
        "name": "Q",
        "slug": "q",
        "model": "mock/q",
        field_name: {},
    })

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "config.secretRefs 必须是数组" in exc.value.message


def test_parse_agent_bundle_zip_rejects_duplicate_secret_ref_fields() -> None:
    data = make_agent_bundle_zip_with_config({
        "name": "Q",
        "slug": "q",
        "model": "mock/q",
        "secretRefs": [],
        "secret_refs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
            "source": {"value": "plain-token"},
        }],
    })

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "不能同时声明" in exc.value.message


@pytest.mark.parametrize(
    "secret_refs, message",
    [
        ([{"env": "1TOKEN", "secretName": "mock-token", "key": "access_token"}], "环境变量名"),
        ([{"env": "OAUTH_ACCESS_TOKEN", "secretName": "Mock_Token", "key": "access_token"}], "Secret 名称"),
        ([{"env": "OAUTH_ACCESS_TOKEN", "secretName": "mock-token", "key": "access/token"}], "Secret key"),
        (
            [{
                "env": "OAUTH_ACCESS_TOKEN",
                "secretName": "mock-token",
                "key": "access_token",
                "tokenRef": "mock-token/other_key",
            }],
            "保持一致",
        ),
        (
            [
                {"env": "OAUTH_ACCESS_TOKEN", "secretName": "mock-token", "key": "access_token"},
                {"env": "OAUTH_ACCESS_TOKEN", "secretName": "mock-token", "key": "refresh_token"},
            ],
            "重复",
        ),
        ([{"env": "OAUTH_ACCESS_TOKEN", "secretName": "mock-token", "key": "access_token", "required": "false"}], "布尔值"),
    ],
)
def test_parse_agent_bundle_zip_rejects_invalid_secret_refs(secret_refs: list[dict], message: str) -> None:
    data = make_agent_bundle_zip_with_config({
        "name": "Q",
        "slug": "q",
        "model": "mock/q",
        "secretRefs": secret_refs,
    })

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert message in exc.value.message


def test_parse_agent_bundle_zip_normalizes_token_ref_only_secret_refs() -> None:
    data = make_agent_bundle_zip_with_config({
        "name": "Q",
        "slug": "q",
        "model": "mock/q",
        "secretRefs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "tokenRef": "mock-oauth-token/access_token",
            "required": False,
        }],
    })

    manifest = parse_agent_bundle_zip("bundle.zip", data)

    assert manifest["secret_refs"] == [{
        "env": "OAUTH_ACCESS_TOKEN",
        "tokenRef": "mock-oauth-token/access_token",
        "required": False,
        "secretName": "mock-oauth-token",
        "key": "access_token",
    }]


def test_sanitize_agent_bundle_manifest_rejects_legacy_secret_ref_unknown_source() -> None:
    manifest = {
        "slug": "legacy-oauth-agent",
        "env": {},
        "secret_refs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
            "source": {"value": "plain-token"},
        }],
    }

    with pytest.raises(BadRequestError) as exc:
        sanitize_agent_bundle_manifest(manifest)

    assert "不支持的字段: source" in exc.value.message


def test_build_bundle_env_vars_rejects_legacy_secret_ref_unknown_source() -> None:
    manifest = {
        "slug": "legacy-oauth-agent",
        "env": {},
        "secret_refs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
            "source": {"value": "plain-token"},
        }],
    }

    with pytest.raises(BadRequestError) as exc:
        build_bundle_env_vars(manifest, "legacy-oauth-agent")

    assert "不支持的字段: source" in exc.value.message


def test_build_bundle_env_vars_normalizes_legacy_secret_ref_aliases() -> None:
    manifest = {
        "slug": "legacy-oauth-agent",
        "env": {},
        "secret_refs": [{
            "env_name": "OAUTH_ACCESS_TOKEN",
            "token_ref": "mock-oauth-token/access_token",
            "required": False,
        }],
    }

    env = build_bundle_env_vars(manifest, "legacy-oauth-agent")

    assert json.loads(env["NODESKCLAW_SECRET_REFS"]) == [{
        "env": "OAUTH_ACCESS_TOKEN",
        "secretName": "mock-oauth-token",
        "key": "access_token",
        "tokenRef": "mock-oauth-token/access_token",
        "required": False,
    }]


def test_parse_agent_bundle_zip_rejects_duplicate_paths() -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        data = make_base_agent_bundle_zip([("docs/dup.txt", "one"), ("docs/dup.txt", "two")])

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "重复路径" in exc.value.message


def test_parse_agent_bundle_zip_rejects_path_prefix_collision() -> None:
    data = make_base_agent_bundle_zip([("docs/collision.txt", "one"), ("docs/collision.txt/nested.txt", "two")])

    with pytest.raises(BadRequestError) as exc:
        parse_agent_bundle_zip("bundle.zip", data)

    assert "路径冲突" in exc.value.message


@pytest.mark.asyncio
async def test_read_upload_file_limited_reads_small_upload_in_chunks() -> None:
    data = b"a" * (MAX_ZIP_BYTES - 1)
    file = FakeUploadFile(data)

    assert await _read_upload_file_limited(file) == data
    assert all(size == 64 * 1024 for size in file.read_sizes[:-1])


@pytest.mark.asyncio
async def test_read_upload_file_limited_rejects_oversized_upload() -> None:
    data = b"a" * (MAX_ZIP_BYTES + 1)
    file = FakeUploadFile(data)

    with pytest.raises(BadRequestError) as exc:
        await _read_upload_file_limited(file)

    assert "上传文件过大" in exc.value.message


@pytest.mark.asyncio
async def test_restore_agent_bundle_rejects_unsafe_manifest_path(monkeypatch) -> None:
    class FakeFS:
        async def remove(self, _path):
            return None

        async def write_text(self, _path, _content):
            raise AssertionError("unsafe manifest path should be rejected before remote write")

    class FakeRemoteFSContext:
        async def __aenter__(self):
            return FakeFS()

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr("app.services.nfs_mount.remote_fs", lambda _instance, _db: FakeRemoteFSContext())

    with pytest.raises(BadRequestError) as exc:
        await restore_agent_bundle(
            SimpleNamespace(id="inst-1"),
            {"slug": "safe", "files": {"skills/echo/bad'name.txt": "payload"}},
            db=None,
        )

    assert "非法恢复路径" in exc.value.message


def test_agent_bundle_summary_hides_file_content() -> None:
    manifest = parse_agent_bundle_dir(FIXTURES / "p2_stateful_local_agent")
    summary = summarize_agent_bundle_manifest(manifest)

    assert summary is not None
    assert "files" in summary
    assert "skills/stateful/scripts/run_stateful.py" in summary["files"]
    assert "print(os.environ" not in str(summary)


def test_bundle_env_vars_filter_secret_values_and_keep_refs() -> None:
    manifest = parse_agent_bundle_dir(FIXTURES / "p4_oauth_probe_agent")
    env = build_bundle_env_vars(manifest, manifest["slug"], instance_id="inst-1")

    assert env["NODESKCLAW_AGENT_BUNDLE_DIR"] == "/root/.openclaw/agent-bundles/p4-oauth-probe-agent"
    assert env["NODESKCLAW_AGENT_STATE_DIR"] == "/root/.openclaw/agent-state/inst-1"
    assert env["OAUTH_TOKEN_REF"] == "mock-oauth-token/access_token"
    assert "OAUTH_ACCESS_TOKEN" not in env
    assert "NODESKCLAW_SECRET_REFS" in env
    assert json.loads(env["NODESKCLAW_SECRET_REFS"]) == [{
        "env": "OAUTH_ACCESS_TOKEN",
        "secretName": "mock-oauth-token",
        "key": "access_token",
        "tokenRef": "mock-oauth-token/access_token",
        "required": True,
    }]


def test_oauth_probe_script_calls_mock_broker_with_injected_token() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            auth = self.headers.get("Authorization")
            token_ref = self.headers.get("X-Token-Ref")
            ok = auth == "Bearer injected-token" and token_ref == "mock-oauth-token/access_token"
            body = json.dumps({"ok": ok, "token_ref": token_ref}).encode()
            self.send_response(200 if ok else 401)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = FIXTURES / "p4_oauth_probe_agent" / "skills" / "oauth-probe" / "scripts" / "probe_oauth.py"
        env = {
            **os.environ,
            "DESKCLAW_TRUSTED_OAUTH_EXCHANGE_URL": f"http://127.0.0.1:{server.server_port}/exchange",
            "OAUTH_TOKEN_REF": "mock-oauth-token/access_token",
            "OAUTH_ACCESS_TOKEN": "injected-token",
        }
        result = subprocess.run(
            [sys.executable, str(script)],
            env=env,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == 200
    assert payload["token_ref"] == "mock-oauth-token/access_token"
    assert payload["broker"]["ok"] is True


def test_external_service_probe_script_calls_configured_service() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "path": self.path}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = FIXTURES / "p2a_external_service_agent" / "skills" / "external-service-probe" / "scripts" / "probe_external.py"
        env = {
            **os.environ,
            "EXTERNAL_API_BASE": f"http://127.0.0.1:{server.server_port}",
            "EXTERNAL_API_PATH": "/probe",
        }
        result = subprocess.run(
            [sys.executable, str(script)],
            env=env,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == 200
    assert payload["path"].startswith("/probe")


def test_secret_env_refs_are_injected_as_k8s_secret_refs_not_configmap_data() -> None:
    manifest = parse_agent_bundle_dir(FIXTURES / "p4_oauth_probe_agent")
    refs = _collect_secret_env_refs(manifest)
    labels = build_labels("agent", "inst-1", "v1")

    configmap = build_configmap("agent-config", "ns", {"VISIBLE": "1"}, labels)
    deployment = build_deployment(
        name="agent",
        namespace="ns",
        image="example/agent:v1",
        replicas=1,
        labels=labels,
        configmap_name="agent-config",
        env_vars={"VISIBLE": "1"},
        advanced_config={"secret_env_refs": refs},
    )

    env_by_name = {item.name: item for item in deployment.spec.template.spec.containers[0].env}
    assert configmap.data == {"VISIBLE": "1"}
    assert "OAUTH_ACCESS_TOKEN" not in configmap.data
    assert "source_env" not in refs[0]
    assert env_by_name["OAUTH_ACCESS_TOKEN"].value_from.secret_key_ref.name == "mock-oauth-token"
    assert env_by_name["OAUTH_ACCESS_TOKEN"].value_from.secret_key_ref.key == "access_token"


def test_optional_secret_env_refs_are_injected_as_optional_k8s_refs() -> None:
    data = make_agent_bundle_zip_with_config({
        "name": "Q",
        "slug": "q",
        "model": "mock/q",
        "secretRefs": [{
            "env": "OPTIONAL_ACCESS_TOKEN",
            "secretName": "mock-token",
            "key": "access_token",
            "required": False,
        }],
    })
    manifest = parse_agent_bundle_zip("bundle.zip", data)
    refs = _collect_secret_env_refs(manifest)
    deployment = build_deployment(
        name="agent",
        namespace="ns",
        image="example/agent:v1",
        replicas=1,
        labels=build_labels("agent", "inst-1", "v1"),
        advanced_config={"secret_env_refs": refs},
    )

    env_by_name = {item.name: item for item in deployment.spec.template.spec.containers[0].env}
    selector = env_by_name["OPTIONAL_ACCESS_TOKEN"].value_from.secret_key_ref
    assert selector.name == "mock-token"
    assert selector.key == "access_token"
    assert selector.optional is True


def test_agent_bundle_display_name_uses_only_explicit_display_name() -> None:
    video_manifest = parse_agent_bundle_dir(FIXTURES / "p5_video_clone_mock_agent")
    explicit_manifest = {
        "name": "plain-text-skills-agent",
        "slug": "plain-text-skills-agent",
        "description": "",
        "config": {"display_name": "文本编辑助理"},
    }

    assert _suggest_agent_bundle_display_name(video_manifest) is None
    assert _suggest_agent_bundle_display_name(explicit_manifest) == "文本编辑助理"


def test_agent_bundle_placeholder_name_uses_next_expert_index() -> None:
    assert _next_agent_bundle_placeholder_name([]) == "专家1"
    assert _next_agent_bundle_placeholder_name(["专家1", "数字人视频复刻专家"]) == "专家2"
    assert _next_agent_bundle_placeholder_name(["专家1", "专家2", "专家4"]) == "专家3"


@pytest.mark.asyncio
async def test_import_agent_bundle_creates_private_template_and_genes(require_test_db) -> None:
    manifest = parse_agent_bundle_dir(FIXTURES / "p1_template_import_agent")
    suffix = uuid4().hex[:8]
    manifest["slug"] = f"{manifest['slug']}-{suffix}"

    async with TestSessionLocal() as db:
        org = Organization(
            id=f"org-agent-bundle-{suffix}",
            name="Agent Bundle Org",
            slug=f"agent-bundle-org-{suffix}",
        )
        user = User(
            id=f"user-agent-bundle-{suffix}",
            name="Agent Bundle User",
            username=f"agent-bundle-user-{suffix}",
            current_org_id=org.id,
        )
        db.add_all([org, user])
        await db.commit()

        template = await import_agent_bundle_manifest(
            db,
            manifest,
            user_id=user.id,
            org_id=org.id,
        )

        assert template.template_type == "agent_bundle"
        assert template.name == "专家1"
        assert template.slug == f"p1-template-import-agent-{suffix}"
        assert template.agent_bundle is not None
        assert template.agent_bundle["name"] == "Template Import Agent"
        assert template.agent_bundle["files"] == ["AGENT.md", "SOUL.md", "config.json", "skills/importer/SKILL.md"]
        assert template.gene_slugs

        result = await db.execute(select(Gene).where(Gene.slug.in_(template.gene_slugs)))
        genes = list(result.scalars().all())

        assert len(genes) == len(template.gene_slugs)
        assert all(g.source == GeneSource.agent for g in genes)
        assert all(g.visibility == ContentVisibility.org_private for g in genes)
        assert all(g.is_published is False for g in genes)


@pytest.mark.asyncio
async def test_template_deploy_accessors_reject_legacy_secret_ref_unknown_source(monkeypatch) -> None:
    suffix = uuid4().hex[:8]
    manifest = {
        "slug": f"legacy-oauth-agent-{suffix}",
        "name": "Legacy OAuth Agent",
        "env": {},
        "secret_refs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
            "source": {"value": "plain-token"},
        }],
    }

    async def fake_get_template_model(*_args, **_kwargs):
        return SimpleNamespace(
            slug=f"legacy-oauth-agent-{suffix}",
            template_type=InstanceTemplateType.agent_bundle,
            agent_bundle_manifest=json.dumps(manifest, ensure_ascii=False),
        )

    monkeypatch.setattr(instance_template_service, "_get_template_model", fake_get_template_model)

    with pytest.raises(BadRequestError) as manifest_exc:
        await get_template_agent_bundle_manifest(SimpleNamespace(), "tpl-1", "org-1")
    with pytest.raises(BadRequestError) as env_exc:
        await get_template_deploy_env_vars(SimpleNamespace(), "tpl-1", "org-1")

    assert "不支持的字段: source" in manifest_exc.value.message
    assert "不支持的字段: source" in env_exc.value.message


@pytest.mark.asyncio
async def test_org_private_agent_bundle_manifest_has_no_platform_secret_source(monkeypatch) -> None:
    manifest = {
        "slug": "oauth-agent",
        "name": "OAuth Agent",
        "env": {},
        "secret_refs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
        }],
    }

    async def fake_get_template_model(*_args, **_kwargs):
        return SimpleNamespace(
            template_type=InstanceTemplateType.agent_bundle,
            agent_bundle_manifest=json.dumps(manifest, ensure_ascii=False),
            org_id="org-1",
            visibility=ContentVisibility.org_private.value,
        )

    monkeypatch.setattr(instance_template_service, "_get_template_model", fake_get_template_model)

    deployed_manifest = await get_template_agent_bundle_manifest(SimpleNamespace(), "tpl-1", "org-1")
    refs = _collect_secret_env_refs(deployed_manifest)

    assert SECRET_REF_SOURCE_NAMESPACE_KEY not in deployed_manifest
    assert refs == [{
        "env": "OAUTH_ACCESS_TOKEN",
        "secret_name": "mock-oauth-token",
        "key": "access_token",
        "required": True,
    }]


@pytest.mark.asyncio
async def test_global_public_agent_bundle_manifest_marks_platform_secret_source(monkeypatch) -> None:
    manifest = {
        "slug": "oauth-agent",
        "name": "OAuth Agent",
        "env": {},
        "secret_refs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
        }],
    }

    async def fake_get_template_model(*_args, **_kwargs):
        return SimpleNamespace(
            template_type=InstanceTemplateType.agent_bundle,
            agent_bundle_manifest=json.dumps(manifest, ensure_ascii=False),
            org_id=None,
            visibility=ContentVisibility.public.value,
        )

    monkeypatch.setattr(instance_template_service, "_get_template_model", fake_get_template_model)
    monkeypatch.setattr(instance_template_service.settings, "PLATFORM_NAMESPACE", "nodeskclaw-system")

    deployed_manifest = await get_template_agent_bundle_manifest(SimpleNamespace(), "tpl-1", "org-1")
    refs = _collect_secret_env_refs(deployed_manifest)

    assert deployed_manifest[SECRET_REF_SOURCE_NAMESPACE_KEY] == "nodeskclaw-system"
    assert "source_namespace" not in deployed_manifest["secret_refs"][0]
    assert refs == [{
        "env": "OAUTH_ACCESS_TOKEN",
        "secret_name": "mock-oauth-token",
        "key": "access_token",
        "required": True,
        "source_namespace": "nodeskclaw-system",
    }]


def _template_info_model(
    manifest: dict,
    *,
    secret_refs: list[dict] | None = None,
    template_type: str = InstanceTemplateType.agent_bundle.value,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="tpl-1",
        name="Template",
        slug="template",
        description=None,
        short_description=None,
        icon=None,
        gene_slugs="[]",
        template_type=template_type,
        agent_bundle_manifest=json.dumps(manifest, ensure_ascii=False),
        resource_recommendation=None,
        upload_contract=None,
        secret_refs=json.dumps(secret_refs or [], ensure_ascii=False),
        bundle_storage_key=None,
        source_instance_id=None,
        is_published=True,
        is_featured=False,
        use_count=0,
        created_by=None,
        org_id="org-1",
        created_at=None,
    )


def test_template_info_uses_sanitized_manifest_secret_refs_not_raw_column() -> None:
    manifest = {
        "slug": "oauth-agent",
        "name": "OAuth Agent",
        "env": {},
        "secret_refs": [{
            "env_name": "OAUTH_ACCESS_TOKEN",
            "token_ref": "mock-oauth-token/access_token",
            "required": False,
        }],
    }
    raw_column_refs = [{
        "env": "OAUTH_ACCESS_TOKEN",
        "secretName": "mock-oauth-token",
        "key": "access_token",
        "source": {"value": "plain-token"},
    }]

    info = _template_to_info(_template_info_model(manifest, secret_refs=raw_column_refs))

    assert info.secret_refs == [{
        "env": "OAUTH_ACCESS_TOKEN",
        "secretName": "mock-oauth-token",
        "key": "access_token",
        "tokenRef": "mock-oauth-token/access_token",
        "required": False,
    }]
    serialized = json.dumps(info.model_dump(mode="json"), ensure_ascii=False)
    assert "plain-token" not in serialized
    assert '"source":' not in serialized


def test_sanitize_agent_bundle_manifest_strips_internal_secret_source_key() -> None:
    manifest = {
        "slug": "oauth-agent",
        "name": "OAuth Agent",
        "env": {},
        SECRET_REF_SOURCE_NAMESPACE_KEY: "nodeskclaw-system",
        "secret_refs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
        }],
    }

    sanitized = sanitize_agent_bundle_manifest(manifest)

    assert SECRET_REF_SOURCE_NAMESPACE_KEY not in sanitized


def test_template_info_ignores_invalid_legacy_manifest_secret_refs() -> None:
    manifest = {
        "slug": "legacy-oauth-agent",
        "name": "Legacy OAuth Agent",
        "env": {},
        "secret_refs": [{
            "env": "OAUTH_ACCESS_TOKEN",
            "secretName": "mock-oauth-token",
            "key": "access_token",
            "source": {"value": "plain-token"},
        }],
    }

    info = _template_to_info(_template_info_model(manifest))

    assert info.agent_bundle is not None
    assert info.agent_bundle["slug"] == "legacy-oauth-agent"
    assert info.secret_refs == []
    serialized = json.dumps(info.model_dump(mode="json"), ensure_ascii=False)
    assert "plain-token" not in serialized
    assert '"source":' not in serialized

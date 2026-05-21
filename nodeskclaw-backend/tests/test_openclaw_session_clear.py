import json

import pytest

from app.services.openclaw_session import clear_main_session, clear_workspace_session


class FakeFS:
    def __init__(self, files: dict[str, str] | None = None):
        self.files = files or {}

    async def read_text(self, path: str):
        return self.files.get(path)

    async def write_text(self, path: str, content: str) -> None:
        self.files[path] = content


@pytest.mark.asyncio
async def test_clear_main_session_resets_store_and_file():
    sessions_path = ".openclaw/agents/main/sessions/sessions.json"
    session_file = ".openclaw/agents/main/sessions/agent_main_main.jsonl"
    fs = FakeFS({
        sessions_path: json.dumps({
            "main": {
                "sessionId": "main",
                "sessionFile": "/root/.openclaw/agents/main/sessions/agent_main_main.jsonl",
                "model": "gpt-5",
            },
            "agent:main:desk-1": {
                "sessionId": "agent_main_desk-1",
                "sessionFile": "/root/.openclaw/agents/main/sessions/agent_main_desk-1.jsonl",
            },
        }),
        session_file: '{"type":"message"}\n',
    })

    await clear_main_session(fs)

    store = json.loads(fs.files[sessions_path])
    assert "main" not in store
    assert store["agent:main:main"]["sessionId"] == "agent_main_main"
    assert store["agent:main:main"]["sessionFile"] == "/root/.openclaw/agents/main/sessions/agent_main_main.jsonl"
    assert store["agent:main:main"]["model"] == "gpt-5"
    assert fs.files[session_file] == ""


@pytest.mark.asyncio
async def test_clear_workspace_session_matches_agent_main_workspace_key():
    sessions_path = ".openclaw/agents/main/sessions/sessions.json"
    target_file = ".openclaw/agents/main/sessions/agent_main_desk-1.jsonl"
    other_file = ".openclaw/agents/main/sessions/agent_main_other.jsonl"
    fs = FakeFS({
        sessions_path: json.dumps({
            "agent:main:desk-1": {
                "sessionId": "agent_main_desk-1",
                "sessionFile": "/root/.openclaw/agents/main/sessions/agent_main_desk-1.jsonl",
            },
            "agent:main:other": {
                "sessionId": "agent_main_other",
                "sessionFile": "/root/.openclaw/agents/main/sessions/agent_main_other.jsonl",
            },
        }),
        target_file: '{"role":"user"}\n',
        other_file: '{"role":"user"}\n',
    })

    assert await clear_workspace_session(fs, "desk-1") is True

    store = json.loads(fs.files[sessions_path])
    assert "agent:main:desk-1" not in store
    assert "agent:main:other" in store
    assert fs.files[target_file] == ""
    assert fs.files[other_file] == '{"role":"user"}\n'


@pytest.mark.asyncio
async def test_clear_workspace_session_rejects_unsafe_session_files():
    sessions_path = ".openclaw/agents/main/sessions/sessions.json"
    safe_file = ".openclaw/agents/main/sessions/agent_main_desk-1.jsonl"
    unsafe_file = ".ssh/authorized_keys"
    traversal_file = ".openclaw/agents/main/sessions/../config.json"
    fs = FakeFS({
        sessions_path: json.dumps({
            "agent:main:desk-1": {
                "sessionId": "agent_main_desk-1",
                "sessionFile": "/root/.openclaw/agents/main/sessions/agent_main_desk-1.jsonl",
            },
            "workspace:desk-1": {
                "sessionId": "workspace:desk-1",
                "sessionFile": "/root/.ssh/authorized_keys",
            },
            "legacy": {
                "workspaceId": "desk-1",
                "sessionFile": "/root/.openclaw/agents/main/sessions/../config.json",
            },
        }),
        safe_file: "safe",
        unsafe_file: "do-not-touch",
        traversal_file: "do-not-touch",
    })

    assert await clear_workspace_session(fs, "desk-1") is True

    assert fs.files[safe_file] == ""
    assert fs.files[unsafe_file] == "do-not-touch"
    assert fs.files[traversal_file] == "do-not-touch"

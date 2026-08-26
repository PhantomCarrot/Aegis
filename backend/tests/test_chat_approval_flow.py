"""
Tests for the confirmation flow (M3): mutant/destructive commands via
run_command, guardrail classification, ApprovalRequired → user response →
actual execution cycle. See docs/security-model.md and ADR 0002 (the AI SDK
protocol's native approval mechanism).
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import tenants as tenants_module
from app.exec.base import ExecResult
from app.exec.local import LocalExecutor
from app.stream import ollama_provider

TENANTS_YAML = """
default_tenant: demo
tenants:
  demo:
    name: "Demo"
    tools_enabled: [kubectl, run_command]
"""


@pytest.fixture
def client(monkeypatch, tmp_path):
    tenants_file = tmp_path / "tenants.yaml"
    tenants_file.write_text(TENANTS_YAML)

    monkeypatch.setenv("AEGIS_BACKEND_TOKENS", "test-token")
    monkeypatch.setenv("AEGIS_TENANTS_FILE", str(tenants_file))
    monkeypatch.setenv("AEGIS_GLOBAL_CONFIG_FILE", str(tmp_path / "absent-global.yaml"))
    tenants_module.reset_registry()

    from app.main import app

    yield TestClient(app)

    tenants_module.reset_registry()


AUTH = {"Authorization": "Bearer test-token"}


def _sse_events(raw_text: str) -> list[dict | None]:
    events = []
    for block in raw_text.split("\n\n"):
        if not block.strip():
            continue
        assert block.startswith("data: ")
        payload = block[len("data: "):]
        events.append(None if payload == "[DONE]" else json.loads(payload))
    return events


def _fake_run_command_call(command: str):
    def fake_stream(_messages, _tools, _model, ollama_url=None):
        async def gen():
            yield ollama_provider.OllamaToolCall(id="call_1", name="run_command", arguments={"command": command})

        return gen()

    return fake_stream


def _user_message(text: str) -> dict:
    return {"id": "m1", "role": "user", "parts": [{"type": "text", "text": text}]}


def test_mutant_command_in_modify_mode_triggers_approval(client, monkeypatch):
    monkeypatch.setattr(
        ollama_provider, "stream_chat", _fake_run_command_call("kubectl scale deployment foo --replicas=3")
    )

    body = {
        "id": "chat-1",
        "messages": [_user_message("Scale foo to 3 replicas")],
        "safetyMode": "modify",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]

    assert "tool-approval-request" in types
    assert "data-approval-details" in types
    assert "tool-output-available" not in types  # not executed without confirmation
    assert types[-2:] == ["finish-step", "finish"]  # the loop stops right there

    approval = next(e for e in events if e["type"] == "tool-approval-request")
    details = next(e for e in events if e["type"] == "data-approval-details")
    assert approval["toolCallId"] == "call_1"
    assert details["id"] == approval["approvalId"]
    assert details["data"]["category"] == "mutant"


def test_destructive_command_in_modify_mode_is_denied_outright(client, monkeypatch):
    monkeypatch.setattr(ollama_provider, "stream_chat", _fake_run_command_call("kubectl delete pod foo"))

    body = {
        "id": "chat-2",
        "messages": [_user_message("Delete pod foo")],
        "safetyMode": "modify",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]

    assert "tool-approval-request" not in types  # denied outright, no confirmation possible
    assert "tool-output-error" in types


def test_mutant_command_in_readonly_mode_is_denied_outright(client, monkeypatch):
    monkeypatch.setattr(
        ollama_provider, "stream_chat", _fake_run_command_call("kubectl scale deployment foo --replicas=3")
    )

    body = {
        "id": "chat-3",
        "messages": [_user_message("Scale foo")],
        "safetyMode": "readonly",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]
    assert "tool-approval-request" not in types
    assert "tool-output-error" in types


def _pending_approval_message(command: str, approved: bool) -> dict:
    return {
        "id": "m2",
        "role": "assistant",
        "parts": [{
            "type": "dynamic-tool",
            "toolCallId": "call_1",
            "toolName": "run_command",
            "state": "approval-responded",
            "input": {"command": command},
            "approval": {"id": "appr_call_1", "approved": approved},
        }],
    }


def test_approved_pending_action_executes_for_real_and_llm_continues(client, monkeypatch):
    calls = {"n": 0}

    def fake_stream(_messages, _tools, _model, ollama_url=None):
        calls["n"] += 1

        async def gen():
            yield ollama_provider.OllamaTextChunk("Done.")

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    async def fake_local_run(self, command, **kwargs):
        return ExecResult(stdout="deployment.apps/foo scaled", stderr="", returncode=0, command=command)

    monkeypatch.setattr(LocalExecutor, "run", fake_local_run)

    body = {
        "id": "chat-4",
        "messages": [
            _user_message("Scale foo to 3 replicas"),
            _pending_approval_message("kubectl scale deployment foo --replicas=3", approved=True),
        ],
        "safetyMode": "modify",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]

    assert "tool-output-available" in types
    tool_output = next(e for e in events if e["type"] == "tool-output-available")
    assert tool_output["toolCallId"] == "call_1"
    assert "scaled" in tool_output["output"]["stdout"]

    # The LLM takes back over after the actual execution.
    assert "text-delta" in types
    assert calls["n"] == 1


def test_denied_pending_action_is_not_executed(client, monkeypatch):
    executed = {"called": False}

    async def fake_local_run(self, command, **kwargs):
        executed["called"] = True
        return ExecResult(stdout="", stderr="", returncode=0, command=command)

    monkeypatch.setattr(LocalExecutor, "run", fake_local_run)

    def fake_stream(_messages, _tools, _model, ollama_url=None):
        async def gen():
            yield ollama_provider.OllamaTextChunk("Got it, cancelled.")

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    body = {
        "id": "chat-5",
        "messages": [
            _user_message("Scale foo to 3 replicas"),
            _pending_approval_message("kubectl scale deployment foo --replicas=3", approved=False),
        ],
        "safetyMode": "modify",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]

    assert "tool-output-denied" in types
    assert "tool-output-available" not in types
    assert executed["called"] is False

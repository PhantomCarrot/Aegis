"""
End-to-end integration test for the /api/chat router: request → agent loop
→ SSE encoding → HTTP response, with a fake Ollama provider (no dependency
on a real Ollama in the tests).
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import tenants as tenants_module
from app.stream import ollama_provider

TENANTS_YAML = """
default_tenant: demo
tenants:
  demo:
    name: "Demo"
    tools_enabled: [kubectl]
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
    """Parses the SSE body into a list of JSON payloads (None for [DONE])."""
    events = []
    for block in raw_text.split("\n\n"):
        if not block.strip():
            continue
        assert block.startswith("data: ")
        payload = block[len("data: "):]
        events.append(None if payload == "[DONE]" else json.loads(payload))
    return events


def _fake_stream_text_only(*_args, **_kwargs):
    async def gen():
        yield ollama_provider.OllamaTextChunk("Bonjour, ")
        yield ollama_provider.OllamaTextChunk("je peux t'aider.")

    return gen()


def test_chat_streams_text_response(client, monkeypatch):
    monkeypatch.setattr(ollama_provider, "stream_chat", _fake_stream_text_only)

    body = {
        "id": "chat-1",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "Hi"}]}],
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        assert r.status_code == 200
        assert r.headers["x-vercel-ai-ui-message-stream"] == "v1"
        assert r.headers["content-type"].startswith("text/event-stream")
        raw = "".join(r.iter_text())

    events = _sse_events(raw)
    assert events[-1] is None  # [DONE]
    types = [e["type"] for e in events if e is not None]
    assert types == ["start", "start-step", "text-start", "text-delta", "text-delta", "text-end", "finish-step", "finish"]

    deltas = [e["delta"] for e in events if e is not None and e["type"] == "text-delta"]
    assert "".join(deltas) == "Bonjour, je peux t'aider."


def test_chat_runs_tool_call_and_returns_output(client, monkeypatch):
    calls = {"n": 0}

    def fake_stream(_messages, _tools, _model, ollama_url=None):
        calls["n"] += 1

        async def gen():
            if calls["n"] == 1:
                yield ollama_provider.OllamaToolCall(id="call_1", name="kubectl_get", arguments={"resource": "pods"})
            else:
                yield ollama_provider.OllamaTextChunk("No pods found.")

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    async def fake_local_run(self, command, **kwargs):
        from app.exec.base import ExecResult
        return ExecResult(stdout="No resources found.", stderr="", returncode=0, command=" ".join(command))

    from app.exec.local import LocalExecutor
    monkeypatch.setattr(LocalExecutor, "run", fake_local_run)

    body = {
        "id": "chat-2",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "List the pods"}]}],
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        assert r.status_code == 200
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]
    assert "tool-input-available" in types
    assert "tool-output-available" in types

    tool_input = next(e for e in events if e["type"] == "tool-input-available")
    assert tool_input["toolName"] == "kubectl_get"
    assert tool_input["dynamic"] is True

    tool_output = next(e for e in events if e["type"] == "tool-output-available")
    assert "No resources found" in tool_output["output"]["stdout"]
    # Transparency: where did the command run? (tenant "demo" = local by default)
    assert tool_output["output"]["executed_via"] == "local"


def test_chat_rejects_tool_call_disabled_via_runtime_toggle(client, monkeypatch):
    """
    Tenant "demo" allows the kubectl group, so kubectl_get is normally in
    the tool_schemas sent to Ollama. Here we send enabledTools without
    kubectl_get (runtime UI toggle) — even if the LLM calls it anyway, it
    must NOT be executed (see loop.py, allowed_tool_names).
    """
    def fake_stream(_messages, _tools, _model, ollama_url=None):
        async def gen():
            yield ollama_provider.OllamaToolCall(id="call_1", name="kubectl_get", arguments={"resource": "pods"})

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    async def fake_local_run(self, command, **kwargs):
        raise AssertionError("kubectl_get should never have been executed — disabled at runtime")

    from app.exec.local import LocalExecutor
    monkeypatch.setattr(LocalExecutor, "run", fake_local_run)

    body = {
        "id": "chat-4",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "List the pods"}]}],
        "enabledTools": [],  # everything disabled at runtime
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        assert r.status_code == 200
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]
    assert "tool-output-error" in types
    assert "tool-output-available" not in types

    error_event = next(e for e in events if e["type"] == "tool-output-error")
    assert "disabled" in error_event["errorText"] or "Unknown" in error_event["errorText"]


def test_chat_requires_auth(client):
    body = {"id": "chat-3", "messages": []}
    r = client.post("/api/chat", json=body)
    assert r.status_code == 401

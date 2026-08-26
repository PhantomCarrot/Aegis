"""
Verifies that guardrail decisions are properly traced in the audit logger
(app.logging_config.AUDIT_LOGGER_NAME) — see docs/security-model.md.
Doesn't test the exact format, just that the event is emitted.
"""
import logging

from app.agent.loop import run_agent_loop
from app.config.schema import TenantConfig
from app.logging_config import AUDIT_LOGGER_NAME
from app.stream import ollama_provider


def _fake_run_command_call(command: str):
    def fake_stream(_messages, _tools, _model, ollama_url=None):
        async def gen():
            yield ollama_provider.OllamaToolCall(id="call_1", name="run_command", arguments={"command": command})

        return gen()

    return fake_stream


async def test_guardrail_decision_is_audit_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        ollama_provider, "stream_chat", _fake_run_command_call("kubectl scale deployment foo --replicas=3")
    )

    tenant = TenantConfig(id="demo", name="Demo", tools_enabled=["run_command"])

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER_NAME):
        events = [e async for e in run_agent_loop(tenant, [{"role": "user", "content": "scale"}], "modify", "fake-model")]

    assert any(e.__class__.__name__ == "ApprovalRequired" for e in events)
    audit_records = [r for r in caplog.records if r.name == AUDIT_LOGGER_NAME]
    assert any("guardrail" in r.message and "tenant=demo" in r.message for r in audit_records)

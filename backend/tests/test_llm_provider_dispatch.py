"""
Tests for schema validation of `llm.*` (AirLLMConfig/LMStudioConfig/
LLMConfig) and the get_stream_chat_fn() dispatcher that resolves which
provider module answers a tenant's chat turns. See docs/llm-providers.md.
"""
import pytest

from app.config.schema import TenantConfig
from app.stream import airllm_provider, lmstudio_provider, ollama_provider
from app.stream.providers import get_stream_chat_fn

# ─── Schema ──────────────────────────────────────────────────────────────────

def test_default_provider_is_ollama():
    tenant = TenantConfig(id="t1", name="T1")
    assert tenant.llm.provider == "ollama"


def test_lmstudio_provider_has_default_url():
    tenant = TenantConfig(id="t1", name="T1", llm={"provider": "lmstudio"})
    assert tenant.llm.lmstudio.url == "http://localhost:1234"


def test_airllm_provider_without_config_block_is_rejected():
    with pytest.raises(Exception, match="airllm"):
        TenantConfig(id="t1", name="T1", llm={"provider": "airllm"})


def test_airllm_provider_with_config_block_is_accepted():
    tenant = TenantConfig(
        id="t1", name="T1",
        llm={"provider": "airllm", "airllm": {"model": "meta-llama/Llama-3.2-3B-Instruct"}},
    )
    assert tenant.llm.airllm.model == "meta-llama/Llama-3.2-3B-Instruct"
    assert tenant.llm.airllm.device == "cpu"  # default
    assert tenant.llm.airllm.compression is None


def test_airllm_rejects_unknown_compression_value():
    with pytest.raises(Exception):
        TenantConfig(
            id="t1", name="T1",
            llm={"provider": "airllm", "airllm": {"model": "x", "compression": "not-a-real-option"}},
        )


# ─── Dispatch ────────────────────────────────────────────────────────────────

async def _drain(gen):
    async for _ in gen:
        pass


async def test_dispatches_to_ollama_by_default(monkeypatch):
    tenant = TenantConfig(id="t1", name="T1")
    fn = get_stream_chat_fn(tenant)

    called = {}

    async def fake_stream_chat(messages, tools, model, ollama_url=None):
        called["ollama_url"] = ollama_url
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream_chat)
    await _drain(fn([], [], "model"))
    assert called["ollama_url"] == tenant.ollama.url


async def test_dispatches_to_lmstudio(monkeypatch):
    tenant = TenantConfig(id="t1", name="T1", llm={"provider": "lmstudio", "lmstudio": {"url": "http://x:1234"}})
    fn = get_stream_chat_fn(tenant)

    called = {}

    async def fake_stream_chat(messages, tools, model, base_url=None):
        called["base_url"] = base_url
        return
        yield  # pragma: no cover

    monkeypatch.setattr(lmstudio_provider, "stream_chat", fake_stream_chat)
    await _drain(fn([], [], "some-model"))
    assert called["base_url"] == "http://x:1234"


async def test_dispatches_to_airllm(monkeypatch):
    tenant = TenantConfig(
        id="t1", name="T1",
        llm={"provider": "airllm", "airllm": {"model": "meta-llama/Llama-3.2-3B-Instruct"}},
    )
    fn = get_stream_chat_fn(tenant)

    called = {}

    async def fake_stream_chat(messages, tools, model, config=None):
        called["config"] = config
        return
        yield  # pragma: no cover

    monkeypatch.setattr(airllm_provider, "stream_chat", fake_stream_chat)
    await _drain(fn([], [], "ignored"))
    assert called["config"] is tenant.llm.airllm

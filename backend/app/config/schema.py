"""
Multi-tenant config schema (pydantic v2).

Two files, two responsibilities:
- config/global.yaml   → installation-wide defaults (optional, falls back
                          to the Python defaults below if absent)
- config/tenants.yaml  → the list of tenants themselves (required)

Each tenant can override any defaults field, field by field (deep merge,
see app/config/tenants.py) — no need to redefine everything just to change
one setting.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OllamaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Always used for RAG embeddings (nomic-embed-text via /api/embed, see
    # docs/rag.md), regardless of which chat provider `llm.provider` picks
    # below — embeddings aren't pluggable yet, only chat is.
    url: str = "http://localhost:11434"


class LMStudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # LM Studio's local server, OpenAI-compatible (/v1/chat/completions,
    # /v1/models) — start it with `lms server start` or via the app's own
    # "Local Server" tab. See docs/llm-providers.md.
    url: str = "http://localhost:1234"


class AirLLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # HF repo id (e.g. "meta-llama/Llama-3.2-3B-Instruct") or a local path
    # to an already-downloaded checkpoint — passed straight to
    # AutoModel.from_pretrained(). See docs/llm-providers.md.
    model: str
    device: str = "cpu"  # "cpu" | "cuda:0" | ... — AirLLM auto-dispatches to MLX on macOS regardless
    compression: Literal["4bit", "8bit"] | None = None  # needs bitsandbytes if set
    max_seq_len: int = 2048
    max_new_tokens: int = 512


class LLMConfig(BaseModel):
    """Which backend answers chat turns for this tenant — see docs/llm-providers.md."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["ollama", "lmstudio", "airllm"] = "ollama"
    lmstudio: LMStudioConfig = Field(default_factory=LMStudioConfig)
    # None unless provider == "airllm": there's no sane default HF model to
    # silently fall back to, and loading one is expensive enough that
    # picking wrong by default would be a bad surprise.
    airllm: AirLLMConfig | None = None

    @model_validator(mode="after")
    def _airllm_requires_config(self) -> "LLMConfig":
        if self.provider == "airllm" and self.airllm is None:
            raise ValueError("llm.provider == 'airllm' requires an llm.airllm block (at least `model`)")
        return self


class SSHExecConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    user: str
    port: int = 22
    key_path: str
    # Optional SSH certificate paired with key_path — for setups using
    # short-lived certificate-based auth (e.g. Azure AD via `az ssh
    # config`, HashiCorp Vault SSH secrets engine) instead of a static key.
    # The certificate is only checked at connection time; an already-open
    # session stays valid past its expiry, so refreshing the file in place
    # (same path, new content) is enough — no Aegis restart needed.
    certificate_path: str | None = None
    # Path to a known_hosts file (OpenSSH format) to pin the remote host's
    # key. Absent = verification disabled (default V1 behavior, documented
    # as a risk in docs/execution-model.md) — fill this in before any
    # deployment that crosses an untrusted network.
    known_hosts_path: str | None = None


class ExecConfig(BaseModel):
    """Where the tenant's commands run — see docs/execution-model.md."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["local", "ssh"] = "local"
    ssh: SSHExecConfig | None = None

    @model_validator(mode="after")
    def _ssh_requires_config(self) -> "ExecConfig":
        if self.mode == "ssh" and self.ssh is None:
            raise ValueError("exec.mode == 'ssh' requires an exec.ssh block")
        return self


class GlobalConfig(BaseModel):
    """Content of config/global.yaml — optional, Python defaults otherwise."""

    model_config = ConfigDict(extra="forbid")

    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    exec: ExecConfig = Field(default_factory=ExecConfig)


class TenantConfig(BaseModel):
    """A resolved tenant (defaults + overrides already merged)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    exec: ExecConfig = Field(default_factory=ExecConfig)
    # "" = not specified in config → resolved to a tenant-scoped path (see
    # the validator below). A shared default like "~/.kube/aegis" for all
    # tenants would leak one tenant's kubeconfig to another as soon as
    # neither specifies it.
    kubeconfig_dir: str = ""
    # None = Terraform state scraping disabled for this tenant (most won't
    # use it — unlike kubeconfig_dir, there's no sane directory to guess as
    # a default). A path on the machine that actually runs the command
    # (local, or the SSH host for exec.mode == "ssh") — see docs/rag.md.
    terraform_dir: str | None = None
    # Which cloud CLI grammar cloud_cli (the tool) speaks — see
    # app/agent/tools/cloud_providers.py. Only "az" is actually implemented
    # today; a tenants.yaml requesting an unimplemented provider fails
    # explicitly at load time rather than silently falling back.
    cloud_provider: Literal["az"] = "az"
    tools_enabled: list[str] = Field(default_factory=list)
    domain_notes: str = ""

    @model_validator(mode="after")
    def _default_kubeconfig_dir_is_tenant_scoped(self) -> "TenantConfig":
        if not self.kubeconfig_dir:
            self.kubeconfig_dir = f"~/.kube/aegis/{self.id}"
        return self


class TenantsFile(BaseModel):
    """Raw content of config/tenants.yaml, before merging with the defaults."""

    model_config = ConfigDict(extra="forbid")

    default_tenant: str
    tenants: dict[str, dict[str, Any]]

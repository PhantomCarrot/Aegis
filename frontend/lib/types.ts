export type Tenant = {
  id: string;
  name: string;
  tools_enabled: string[];
};

export type TenantsResponse = {
  default_tenant: string | null;
  tenants: Tenant[];
  error?: string;
};

// Mirrors backend/app/config/schema.py — the shape a tenant-admin form
// reads from GET /api/tenants/{id} (unredacted) and writes back via
// POST /api/tenants / PUT /api/tenants/{id}. See TenantAdminPanel.tsx.

export type OllamaConfig = { url: string };
export type LMStudioConfig = { url: string };
export type AirLLMConfig = {
  model: string;
  device: string;
  compression: "4bit" | "8bit" | null;
  max_seq_len: number;
  max_new_tokens: number;
};
export type LLMConfig = {
  provider: "ollama" | "lmstudio" | "airllm";
  lmstudio: LMStudioConfig;
  airllm: AirLLMConfig | null;
};
export type SSHExecConfig = {
  host: string;
  user: string;
  port: number;
  key_path: string;
  certificate_path: string | null;
  known_hosts_path: string | null;
};
export type ExecConfig = { mode: "local" | "ssh"; ssh: SSHExecConfig | null };

export type TenantFullConfig = {
  id: string;
  name: string;
  ollama: OllamaConfig;
  llm: LLMConfig;
  exec: ExecConfig;
  kubeconfig_dir: string;
  tools_enabled: string[];
  domain_notes: string;
};

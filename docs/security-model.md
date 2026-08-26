# Security model

## What this is

Aegis runs real commands against real infrastructure at an LLM's request — that must never happen blindly. Two independent mechanisms protect the operator:

1. **Secret anonymization**: before any data (a command result) goes to the LLM, an anonymizer detects and replaces sensitive values with reversible placeholders.
2. **Graduated safety modes + human confirmation**: every command is classified `safe` / `mutant` / `destructive`. Depending on the active mode (ReadOnly / Modify / Root), a command is either run directly, blocked, or submitted for confirmation.

Status: fully implemented and verified end to end (backend + UI + real LLM) — `app/agent/anonymizer.py`, `app/agent/guardrails.py`, wired into `app/agent/loop.py`. `kubectl_get` is always-safe (never subject to the guardrail); `run_command` dynamically classifies the command it's given.

## Anonymization — a concrete example

A raw command result, before it's sent to the LLM:

```json
{"stdout": "{\"token\": \"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U\"}"}
```

What the LLM actually sees:

```json
{"stdout": "{\"token\": \"[SECRET-1]\"}"}
```

The `[SECRET-1] → eyJhbGci...` mapping stays only in backend memory for that conversation turn; the LLM never sees it. This covers, among other things:

- JWTs (`header.payload.signature`)
- long base64 values, connection strings (`AccountKey=`, `password=`...), long hex tokens
- sensitive JSON keys (`password`, `secret`, `token`, `clientSecret`...) — only when the *key* is sensitive, not any value that merely looks like a secret (`description: "eyJ..."` is left untouched)
- specific cases: `az keyvault secret show` (stdout = the raw value), `kubectl get/describe secret` (the `data:` YAML block)

See `backend/tests/test_anonymizer.py` for exact coverage, including a bug found and fixed while writing the tests (redaction of a kubectl secret's `data:` block didn't work in the original logic, for lack of tests).

## Safety modes

| Mode | safe | mutant | destructive |
|---|---|---|---|
| **ReadOnly** | executed | denied | denied |
| **Modify** | executed | confirm | denied |
| **Root** | executed | confirm | confirm |

Classification (`app/agent/guardrails.py`) by command patterns (e.g. `kubectl delete` → destructive, `kubectl apply` → mutant, `kubectl get` → safe). `__confirmed__` bypasses everything: it's the state set after a user has explicitly approved a confirmation.

## Confirmation flow

When a tool is classified `mutant`/`destructive` and the active mode requires confirmation, the agent loop (`app/agent/loop.py`):

1. Emits `ApprovalRequired` (→ `tool-approval-request` + a custom `data-approval-details` part with the human-readable summary and category — see [`protocol.md`](protocol.md)) and **stops the whole generator**: it's impossible to continue without the user's response, which will only arrive in a future HTTP request.
2. The frontend (`ConfirmCard.tsx`) displays the request; the user confirms or cancels → `addToolApprovalResponse()` (a native Vercel AI SDK mechanism, not a custom system — see [ADR 0002](adr/0002-native-tool-approval-instead-of-custom-confirmation.md)).
3. `useChat` automatically resends the full history, including the `dynamic-tool` part now updated to `approval-responded` state (`sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses`).
4. The router (`_find_pending_approval`, `app/routers/chat.py`) detects this pending part, actually runs the tool (`safety_mode="__confirmed__"`) if approved — or emits `tool-output-denied` otherwise — then lets the LLM take back over with the result.

This round-trip is verified by 5 integration tests (`backend/tests/test_chat_approval_flow.py`) and under real conditions (browser + local Ollama): confirmation request, execution after confirmation, denial without execution.

**A gotcha found while testing with a real model**: without explicit instructions, the LLM can be tempted to "simulate" a confirmation in text (`"Do you confirm? (yes/no)"`) instead of calling the tool and letting the platform handle confirmation. The system prompt (`app/agent/prompt.py`) now explicitly states that confirmation is handled by the interface, not by the LLM.

## Audit

Every guardrail decision (allow/deny/confirm) and every resolution of a pending confirmation (approved/denied) are traced in a dedicated logger (`aegis.audit`, see `app/logging_config.py`) — tenant, tool, category, active safety mode, decision. Level adjustable via `AEGIS_LOG_LEVEL`. Verified by `backend/tests/test_audit_logging.py`.

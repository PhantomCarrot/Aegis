"""
Secret anonymizer — detects and replaces sensitive values with reversible
placeholders before anything is sent to the LLM.

This is a central trust argument for the product: even a local LLM never
sees a secret in the clear extracted from a command result. See
docs/security-model.md.

Near-verbatim port of uAegis's Anonymizer class (backend/agent.py) — logic
already battle-tested, no rewrite.
"""
from __future__ import annotations

import base64
import json
import re


class Anonymizer:
    # JSON keys considered sensitive.
    SENSITIVE_KEYS = {
        "value", "password", "secret", "key", "token",
        "connectionstring", "secrettext", "primarykey", "secondarykey",
        "clientsecret", "accesskey",
    }

    # Commands that read secret values directly (stdout = the value).
    SECRET_CMD_PATTERNS = [
        "keyvault secret show",
        "keyvault secret download",
    ]
    # kubectl commands that expose base64-encoded secret values.
    KUBECTL_SECRET_READ_PATTERNS = [
        r"kubectl\s+get\s+secret",
        r"kubectl\s+describe\s+secret",
    ]

    def __init__(self) -> None:
        self._counter = 0
        self._forward: dict[str, str] = {}  # real → placeholder
        self._reverse: dict[str, str] = {}  # placeholder → real
        self._turn_start = 0

    def start_turn(self) -> None:
        self._turn_start = self._counter

    @property
    def turn_count(self) -> int:
        return self._counter - self._turn_start

    @property
    def reverse_map(self) -> dict[str, str]:
        return dict(self._reverse)

    def _next_placeholder(self) -> str:
        self._counter += 1
        return f"[SECRET-{self._counter}]"

    def _is_secret_value(self, value: object) -> bool:
        if not isinstance(value, str):
            return False
        v = value.strip()
        if len(v) < 20:
            return False
        # JWT (header.payload.signature)
        parts = v.split(".")
        if len(parts) == 3 and all(len(p) > 10 for p in parts) and len(v) > 100:
            return True
        # Long base64
        try:
            decoded = base64.b64decode(v + "==")
            if len(decoded) > 60:
                return True
        except Exception:
            pass
        # Connection strings
        if any(k in v.lower() for k in ["accountkey=", "sharedaccesssignature", "password=", "pwd=", "secret="]):
            return True
        # Long hex tokens
        if re.match(r"^[0-9a-fA-F]{40,}$", v):
            return True
        # Long random-looking alphanumeric (API keys, etc.)
        if (len(v) > 60 and " " not in v
                and re.search(r"[A-Z]", v) and re.search(r"[0-9]", v) and re.search(r"[a-z]", v)):
            return True
        return False

    def _replace(self, value: str) -> str:
        if value in self._forward:
            return self._forward[value]
        ph = self._next_placeholder()
        self._forward[value] = ph
        self._reverse[ph] = value
        return ph

    def anonymize_result(
        self, tool_name: str, tool_args: dict, result: dict, safety_mode: str = "readonly"
    ) -> dict:
        if not result:
            return result
        # In confirmed root mode, the user explicitly requested full access.
        if safety_mode in ("root", "__confirmed__"):
            return result
        result = dict(result)

        cmd = tool_args.get("command", "") if tool_name == "run_command" else ""
        cmd_norm = " ".join(cmd.lower().split())

        # Case 1: keyvault command → stdout = the raw value.
        if any(p in cmd_norm for p in self.SECRET_CMD_PATTERNS):
            stdout = result.get("stdout", "").strip()
            if stdout:
                result["stdout"] = self._replace(stdout)

        # Case 2: kubectl get/describe secret → redact the data: block (base64).
        if any(re.search(p, cmd_norm) for p in self.KUBECTL_SECRET_READ_PATTERNS):
            for field in ("stdout", "output"):
                text = result.get(field, "")
                if text:
                    result[field] = self._redact_kubectl_secret_data(text)

        # Case 3: scan the JSON fields of stdout.
        for field in ("stdout", "output"):
            text = result.get(field, "")
            if not text:
                continue
            try:
                parsed = json.loads(text)
                modified, changed = self._anonymize_obj(parsed)
                if changed:
                    result[field] = json.dumps(modified, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass

        return result

    def _redact_kubectl_secret_data(self, text: str) -> str:
        """
        Replaces base64 values in the (root-level) `data:` section of a
        kubectl secret with [REDACTED].

        Note: the original version of this logic (uAegis) exited the
        `data:` block on the first indented line it encountered, regardless
        of its indentation level — so it never actually redacted anything
        in practice. Fixed here: only a root-level line (indent 0) marks
        the end of the block.
        """
        lines = text.splitlines()
        out = []
        in_data = False
        for line in lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            if indent == 0 and re.match(r"data\s*:", stripped):
                in_data = True
                out.append(line)
                continue

            if in_data and stripped and not stripped.startswith("#") and indent == 0:
                # New root-level key → end of the data block.
                in_data = False

            if in_data and re.match(r"\S.*:\s+\S", stripped):
                # line "  key: base64value" → redact the value.
                key_part = re.match(r"(\s*\S+:\s+)", line)
                if key_part:
                    out.append(key_part.group(1) + "[REDACTED]")
                    continue

            out.append(line)
        return "\n".join(out)

    def _anonymize_obj(self, obj: object, depth: int = 0) -> tuple[object, bool]:
        if depth > 6:
            return obj, False
        changed = False
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k.lower() in self.SENSITIVE_KEYS and isinstance(v, str) and self._is_secret_value(v):
                    out[k] = self._replace(v)
                    changed = True
                elif isinstance(v, (dict, list)):
                    new_v, c = self._anonymize_obj(v, depth + 1)
                    out[k] = new_v
                    changed = changed or c
                else:
                    out[k] = v
            return out, changed
        elif isinstance(obj, list):
            out_list = []
            for item in obj:
                new_item, c = self._anonymize_obj(item, depth + 1)
                out_list.append(new_item)
                changed = changed or c
            return out_list, changed
        return obj, False

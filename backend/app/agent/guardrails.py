"""
Guardrails — classifies commands as safe/mutant/destructive and applies the
3 safety modes (readonly/modify/root). See docs/security-model.md.

Port of _classify_cmd/DESTRUCTIVE_PATTERNS/MUTANT_PATTERNS from uAegis
(backend/agent.py) — logic already battle-tested, no rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

SafetyMode = Literal["readonly", "modify", "root", "__confirmed__"]

# Destructive = deletes or replaces resources.
DESTRUCTIVE_PATTERNS = [
    "kubectl delete",
    "kubectl del ",
    "kubectl replace",
    "argocd app delete",
    "argocd delete",
    "helm uninstall",
    "helm delete",
    "helm rollback",
]

# Mutant = modifies or creates state without deleting.
MUTANT_PATTERNS = [
    "kubectl patch",
    "kubectl edit",
    "kubectl set ",
    "kubectl apply",
    "kubectl create",
    "kubectl rollout",
    "kubectl scale",
    "kubectl label",
    "kubectl annotate",
    "kubectl taint",
    "argocd app rollback",
    "argocd rollback",
    "argocd app sync",
    "argocd app set",
    "helm install",
    "helm upgrade",
    "helm template",  # can write to stdout but isn't destructive — conservative
]


class CommandCategory(str, Enum):
    SAFE = "safe"
    MUTANT = "mutant"
    DESTRUCTIVE = "destructive"


class GuardrailAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


@dataclass
class Classification:
    category: CommandCategory
    label: str


@dataclass
class Decision:
    action: GuardrailAction
    reason: str = ""


def classify_command(cmd: str) -> Classification:
    """Classifies a shell command: safe / mutant / destructive."""
    # Normalize internal whitespace to avoid bypass via double-space/tab.
    cmd_lower = " ".join(cmd.lower().split())
    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern in cmd_lower:
            return Classification(CommandCategory.DESTRUCTIVE, f"Destructive command: `{cmd.strip()}`")
    for pattern in MUTANT_PATTERNS:
        if pattern in cmd_lower:
            return Classification(CommandCategory.MUTANT, f"Mutating command: `{cmd.strip()}`")
    return Classification(CommandCategory.SAFE, "")


def decide(category: CommandCategory, safety_mode: SafetyMode) -> Decision:
    """
    Applies the 3-safety-mode policy to a command category.

    | Mode      | safe   | mutant  | destructive |
    |-----------|--------|---------|-------------|
    | readonly  | allow  | deny    | deny        |
    | modify    | allow  | confirm | deny        |
    | root      | allow  | confirm | confirm     |

    `__confirmed__` bypasses everything: the user has already explicitly
    approved (see routers/chat.py, approval flow).
    """
    if safety_mode == "__confirmed__":
        return Decision(GuardrailAction.ALLOW)

    if category == CommandCategory.SAFE:
        return Decision(GuardrailAction.ALLOW)

    if safety_mode == "readonly":
        return Decision(GuardrailAction.DENY, "ReadOnly mode — switch to Modify or Root for this action.")

    if safety_mode == "modify":
        if category == CommandCategory.DESTRUCTIVE:
            return Decision(GuardrailAction.DENY, "Modify mode — deletion refused, switch to Root.")
        return Decision(GuardrailAction.CONFIRM)

    if safety_mode == "root":
        return Decision(GuardrailAction.CONFIRM)

    return Decision(GuardrailAction.DENY, f"Unknown safety mode: {safety_mode!r}")

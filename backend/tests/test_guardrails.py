import pytest

from app.agent.guardrails import CommandCategory, GuardrailAction, classify_command, decide

# ─── Classification ────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "kubectl get pods -n demo",
    "kubectl describe pod foo",
    "kubectl logs foo",
    "argocd app list",
    "az resource list",
])
def test_classify_safe_commands(cmd):
    assert classify_command(cmd).category == CommandCategory.SAFE


@pytest.mark.parametrize("cmd", [
    "kubectl patch deployment foo -p '...'",
    "kubectl apply -f manifest.yaml",
    "kubectl scale deployment foo --replicas=3",
    "argocd app sync foo",
    "helm upgrade foo ./chart",
])
def test_classify_mutant_commands(cmd):
    assert classify_command(cmd).category == CommandCategory.MUTANT


@pytest.mark.parametrize("cmd", [
    "kubectl delete pod foo",
    "kubectl replace -f manifest.yaml",
    "argocd app delete foo",
    "helm uninstall foo",
])
def test_classify_destructive_commands(cmd):
    assert classify_command(cmd).category == CommandCategory.DESTRUCTIVE


def test_classify_ignores_double_spaces_and_tabs_bypass_attempt():
    # Internal whitespace normalization — no bypass via "delete" with weird spacing.
    assert classify_command("kubectl  delete   pod foo").category == CommandCategory.DESTRUCTIVE
    assert classify_command("kubectl\tdelete\tpod foo").category == CommandCategory.DESTRUCTIVE


def test_classify_is_case_insensitive():
    assert classify_command("KUBECTL DELETE POD foo").category == CommandCategory.DESTRUCTIVE


# ─── Decision by mode ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("mode", "category", "expected"),
    [
        ("readonly", CommandCategory.SAFE, GuardrailAction.ALLOW),
        ("readonly", CommandCategory.MUTANT, GuardrailAction.DENY),
        ("readonly", CommandCategory.DESTRUCTIVE, GuardrailAction.DENY),
        ("modify", CommandCategory.SAFE, GuardrailAction.ALLOW),
        ("modify", CommandCategory.MUTANT, GuardrailAction.CONFIRM),
        ("modify", CommandCategory.DESTRUCTIVE, GuardrailAction.DENY),
        ("root", CommandCategory.SAFE, GuardrailAction.ALLOW),
        ("root", CommandCategory.MUTANT, GuardrailAction.CONFIRM),
        ("root", CommandCategory.DESTRUCTIVE, GuardrailAction.CONFIRM),
    ],
)
def test_decide_matrix(mode, category, expected):
    assert decide(category, mode).action == expected


def test_confirmed_bypasses_everything():
    for category in CommandCategory:
        assert decide(category, "__confirmed__").action == GuardrailAction.ALLOW

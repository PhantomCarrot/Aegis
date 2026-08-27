import json

from app.agent.anonymizer import Anonymizer


def test_short_values_are_not_anonymized():
    a = Anonymizer()
    result = a.anonymize_result("run_command", {}, {"stdout": json.dumps({"password": "short"})})
    assert "SECRET" not in result["stdout"]


def test_jwt_like_value_is_anonymized():
    a = Anonymizer()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = a.anonymize_result("run_command", {}, {"stdout": json.dumps({"token": jwt})})
    assert jwt not in result["stdout"]
    assert "[SECRET-1]" in result["stdout"]
    assert a.reverse_map["[SECRET-1]"] == jwt


def test_same_secret_gets_same_placeholder():
    a = Anonymizer()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    payload = json.dumps({"token": jwt, "other": {"secret": jwt}})
    a.anonymize_result("run_command", {}, {"stdout": payload})
    # Both occurrences point to the same placeholder — a single entry in the map.
    assert len(a.reverse_map) == 1


def test_non_sensitive_keys_are_left_alone():
    a = Anonymizer()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    # "description" isn't in SENSITIVE_KEYS — even if the value looks like a secret, we leave it alone.
    result = a.anonymize_result("run_command", {}, {"stdout": json.dumps({"description": jwt})})
    assert jwt in result["stdout"]


def test_root_mode_bypasses_anonymization():
    a = Anonymizer()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = a.anonymize_result(
        "run_command", {}, {"stdout": json.dumps({"token": jwt})}, safety_mode="root"
    )
    assert jwt in result["stdout"]


def test_keyvault_secret_show_redacts_raw_stdout():
    a = Anonymizer()
    secret_value = "S3cr3tValueThatIsVeryLongAndRandomLooking123456789=="
    result = a.anonymize_result(
        "run_command",
        {"command": "az keyvault secret show --vault-name kv --name foo --query value -o tsv"},
        {"stdout": secret_value},
    )
    assert secret_value not in result["stdout"]
    assert result["stdout"] == "[SECRET-1]"


def test_kubectl_get_secret_redacts_data_block():
    a = Anonymizer()
    yaml_output = (
        "apiVersion: v1\n"
        "data:\n"
        "  password: c3VwZXJzZWNyZXR2YWx1ZWJhc2U2NGVuY29kZWQ=\n"
        "kind: Secret\n"
        "metadata:\n"
        "  name: foo\n"
    )
    result = a.anonymize_result(
        "run_command",
        {"command": "kubectl get secret foo -o yaml"},
        {"stdout": yaml_output},
    )
    assert "c3VwZXJzZWNyZXR2YWx1ZWJhc2U2NGVuY29kZWQ=" not in result["stdout"]
    assert "[REDACTED]" in result["stdout"]
    assert "name: foo" in result["stdout"]  # the rest of the YAML is intact


def test_kubectl_get_secret_redacts_multiple_keys_and_stops_at_root_level():
    a = Anonymizer()
    yaml_output = (
        "apiVersion: v1\n"
        "data:\n"
        "  password: c3VwZXJzZWNyZXR2YWx1ZWJhc2U2NGVuY29kZWQ=\n"
        "  username: YWRtaW51c2VybmFtZWJhc2U2NGVuY29kZWQ=\n"
        "kind: Secret\n"
        "metadata:\n"
        "  name: foo\n"
    )
    result = a.anonymize_result(
        "run_command",
        {"command": "kubectl get secret foo -o yaml"},
        {"stdout": yaml_output},
    )
    assert "c3VwZXJzZWNyZXR2YWx1ZWJhc2U2NGVuY29kZWQ=" not in result["stdout"]
    assert "YWRtaW51c2VybmFtZWJhc2U2NGVuY29kZWQ=" not in result["stdout"]
    assert result["stdout"].count("[REDACTED]") == 2
    assert "kind: Secret" in result["stdout"]
    assert "name: foo" in result["stdout"]


def test_turn_counter_tracks_secrets_found_in_current_turn():
    a = Anonymizer()
    a.start_turn()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    a.anonymize_result("run_command", {}, {"stdout": json.dumps({"token": jwt})})
    assert a.turn_count == 1


def test_anonymize_text_redacts_secret_tokens_in_free_text():
    a = Anonymizer()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    text = f"The API token is {jwt} and it never expires."
    result = a.anonymize_text(text)
    assert jwt not in result
    assert "[SECRET-1]" in result
    assert "The API token is" in result and "and it never expires." in result


def test_anonymize_text_reuses_placeholder_from_anonymize_result():
    a = Anonymizer()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    a.anonymize_result("run_command", {}, {"stdout": json.dumps({"token": jwt})})
    result = a.anonymize_text(f"Reused token: {jwt}")
    # Same secret, same turn — same placeholder, not a new [SECRET-2].
    assert "[SECRET-1]" in result
    assert len(a.reverse_map) == 1


def test_anonymize_text_leaves_ordinary_text_alone():
    a = Anonymizer()
    text = "The demo namespace has 3 pods, all Running."
    assert a.anonymize_text(text) == text


def test_anonymize_text_root_mode_bypasses_anonymization():
    a = Anonymizer()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    text = f"token: {jwt}"
    assert a.anonymize_text(text, safety_mode="root") == text


def test_anonymize_text_redacts_kubectl_secret_data_block():
    a = Anonymizer()
    yaml_output = (
        "apiVersion: v1\n"
        "data:\n"
        "  password: c3VwZXJzZWNyZXR2YWx1ZWJhc2U2NGVuY29kZWQ=\n"
        "kind: Secret\n"
        "metadata:\n"
        "  name: foo\n"
    )
    result = a.anonymize_text(yaml_output)
    assert "c3VwZXJzZWNyZXR2YWx1ZWJhc2U2NGVuY29kZWQ=" not in result
    assert "[REDACTED]" in result
    assert "name: foo" in result

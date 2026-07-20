"""Static checks for channel launch operator assets and safe defaults."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_channel_launch_control_script_is_valid_and_help_is_offline() -> None:
    script = REPO_ROOT / "scripts" / "channel-launch-control.sh"
    script_text = script.read_text(encoding="utf-8")

    syntax = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    help_result = subprocess.run(
        [str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert syntax.returncode == 0, syntax.stderr
    assert help_result.returncode == 0, help_result.stderr
    assert "ADMIN_API_KEY" in help_result.stdout
    assert "CONFIRM_AUTONOMOUS_DELIVERY=YES" in help_result.stdout
    assert (
        'body=\'{"canary_enabled":false,"canary_hourly_limit":0,'
        '"canary_daily_limit":0}\'' in script_text
    )


def test_channel_launch_script_keeps_admin_credential_out_of_curl_args(
    tmp_path: Path,
) -> None:
    script = REPO_ROOT / "scripts" / "channel-launch-control.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl_args = tmp_path / "curl-args.log"
    curl_input = tmp_path / "curl-input.log"
    curl_env = tmp_path / "curl-env.log"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/bin/bash\n"
        'printf \'%s\\n\' "$*" >> "$CURL_ARGS_LOG"\n'
        'printf \'%s\' "${ADMIN_API_KEY:-}" > "$CURL_ENV_LOG"\n'
        'cat > "$CURL_INPUT_LOG"\n'
        "printf '{}\\n'\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_jq = fake_bin / "jq"
    fake_jq.write_text("#!/bin/bash\ncat\n", encoding="utf-8")
    fake_jq.chmod(0o755)
    credential = "opaque-test-value"
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "ADMIN_BASE_URL": "admin-api",
        "ADMIN_API_KEY": credential,
        "CURL_ARGS_LOG": str(curl_args),
        "CURL_INPUT_LOG": str(curl_input),
        "CURL_ENV_LOG": str(curl_env),
    }

    result = subprocess.run(
        [str(script), "kill"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert credential not in curl_args.read_text(encoding="utf-8")
    assert curl_env.read_text(encoding="utf-8") == ""
    assert "--header @-" in curl_args.read_text(encoding="utf-8")
    assert f"X-API-KEY: {credential}" in curl_input.read_text(encoding="utf-8")


def test_channel_launch_script_rejects_unwired_web_channel() -> None:
    script = REPO_ROOT / "scripts" / "channel-launch-control.sh"
    script_text = script.read_text(encoding="utf-8")

    assert "matrix | bisq2)" in script_text
    assert "matrix | bisq2 | web)" not in script_text


def test_compose_keeps_global_autonomous_delivery_disabled_by_default() -> None:
    compose_path = REPO_ROOT / "docker" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    environment = compose["services"]["api"]["environment"]

    assert "AUTONOMOUS_DELIVERY_ENABLED=${AUTONOMOUS_DELIVERY_ENABLED:-false}" in (
        environment
    )


def test_runbook_covers_required_channel_launch_drills() -> None:
    runbook = (REPO_ROOT / "docs" / "runbooks" / "channel-launch.md").read_text(
        encoding="utf-8"
    )

    for section in (
        "Matrix delivery",
        "Bisq delivery",
        "Escalation",
        "Timeout",
        "Duplicate event",
        "Transport failure",
        "Kill switch",
        "Shadow exit criteria",
        "Rollback",
    ):
        assert section in runbook

    assert "AUTONOMOUS_DELIVERY_ENABLED=false" in runbook
    assert "would_have_sent" in runbook


def test_runbook_defines_exact_per_channel_shadow_floors() -> None:
    runbook = (REPO_ROOT / "docs" / "runbooks" / "channel-launch.md").read_text(
        encoding="utf-8"
    )
    normalized_runbook = " ".join(runbook.split())

    assert "seven consecutive healthy days" in normalized_runbook
    assert "every unique direct-delivery candidate" in normalized_runbook
    for disposition in (
        "accepted_unchanged",
        "accepted_non_substantive_edit",
        "accepted_substantive_edit",
        "rejected",
    ):
        assert disposition in runbook
    assert "reviewed_count >= 100" in runbook
    assert "accepted_count / reviewed_count >= 0.95" in runbook
    assert "substantive_edit_count / reviewed_count <= 0.10" in runbook
    assert "A substantively edited answer" in normalized_runbook
    assert "/admin/training/learning/readiness" in runbook
    assert "is not this per-channel shadow promotion gate" in runbook


def test_runbook_does_not_expect_a_queue_item_after_disabling_bisq() -> None:
    runbook = (REPO_ROOT / "docs" / "runbooks" / "channel-launch.md").read_text(
        encoding="utf-8"
    )
    normalized_runbook = " ".join(runbook.split())

    assert "Confirm the Bisq scope reports `disabled`" in normalized_runbook
    assert (
        "do not expect a queued item while the channel is disabled"
        in normalized_runbook
    )


def test_runbook_requires_safe_bisq_scope_activation() -> None:
    runbook = (REPO_ROOT / "docs" / "runbooks" / "channel-launch.md").read_text(
        encoding="utf-8"
    )
    normalized_runbook = " ".join(runbook.split())

    assert "drain or close every legacy pending Bisq escalation" in normalized_runbook
    assert "Never backfill missing origin identity" in normalized_runbook
    assert "Recreate the API container (do not merely restart it)" in normalized_runbook
    assert "activation requires a fresh full baseline snapshot" in normalized_runbook
    assert (
        "baseline acquisition retries independently of generation" in normalized_runbook
    )

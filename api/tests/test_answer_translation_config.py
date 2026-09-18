"""Independent model selection and fail-closed reasoning configuration."""

import pytest
from app.core.config import Settings
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def isolate_model_environment(monkeypatch):
    for name in ("OPENAI_MODEL", "TRANSLATION_MODEL", "OPENAI_REASONING_EFFORT"):
        monkeypatch.delenv(name, raising=False)


def test_existing_defaults_remain_nano():
    settings = Settings(_env_file=None)
    assert settings.OPENAI_MODEL == "openai:gpt-4.1-nano"
    assert settings.TRANSLATION_MODEL == "openai:gpt-4.1-nano"
    assert settings.OPENAI_REASONING_EFFORT == "low"


def test_astra_opt_in_keeps_translation_independent(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "openai:gpt-6-astra")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")
    settings = Settings(_env_file=None)
    assert settings.OPENAI_MODEL == "openai:gpt-6-astra"
    assert settings.TRANSLATION_MODEL == "openai:gpt-4.1-nano"
    assert settings.OPENAI_REASONING_EFFORT == "high"
    monkeypatch.setenv("TRANSLATION_MODEL", "openai:gpt-4o-mini")
    assert Settings(_env_file=None).TRANSLATION_MODEL == "openai:gpt-4o-mini"


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_supported_reasoning_effort(effort):
    assert (
        Settings(OPENAI_REASONING_EFFORT=effort, _env_file=None).OPENAI_REASONING_EFFORT
        == effort
    )


@pytest.mark.parametrize("effort", ["", "none", "minimal", "ultra", "HIGH"])
def test_invalid_reasoning_effort_fails_closed(effort):
    with pytest.raises(ValidationError, match="OPENAI_REASONING_EFFORT"):
        Settings(OPENAI_REASONING_EFFORT=effort, _env_file=None)

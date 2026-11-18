"""The deployment contract must deliver explicit, inactive model budgets."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from app.channels.staff_assist.context_trial import ContextTrial

from tests.channels.test_context_trial import trial_settings

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[3]
MONEY = {
    "MATRIX_CONTEXT_TRIAL_BUDGET_USD": "60",
    "MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD": "10",
    "MATRIX_CONTEXT_TRIAL_INPUT_USD_PER_MILLION": "12.5",
    "MATRIX_CONTEXT_TRIAL_OUTPUT_USD_PER_MILLION": "50",
}


def api_money_environment(operator_values):
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())
    entries = compose["services"]["api"]["environment"]
    result = {}
    for entry in entries:
        key, _, expression = entry.partition("=")
        if key in MONEY:
            # This constrained contract deliberately permits no default spend.
            match = re.fullmatch(r"\$\{([A-Z_]+):-\}", expression)
            assert match and match[1] == key
            result[key] = operator_values.get(key, "")
    assert result.keys() == MONEY.keys()
    return result


def test_approved_budget_reaches_trial_descriptor_without_enabling_policy():
    settings = trial_settings(
        **api_money_environment(MONEY),
        OPENAI_MODEL="openai:gpt-6-astra",
        MAX_TOKENS=4000,
    )
    trial = ContextTrial.from_settings(settings)
    assert trial.budget_nanodollars == 60 * 10**9
    assert trial.daily_budget_nanodollars == 10 * 10**9
    assert trial.max_cases == 0
    assert ContextTrial.from_settings(SimpleNamespace(**MONEY)) is None


def test_example_and_compose_leave_all_spend_amounts_unset():
    assert set(api_money_environment({}).values()) == {""}
    example = (ROOT / "docker/.env.example").read_text().splitlines()
    for name in MONEY:
        assert f"{name}=" in example


@pytest.mark.parametrize("missing", MONEY)
def test_partial_operator_budget_cannot_bind(missing):
    values = dict(MONEY)
    del values[missing]
    with pytest.raises(ValueError, match="both budgets and both price ceilings"):
        ContextTrial.from_settings(trial_settings(**api_money_environment(values)))

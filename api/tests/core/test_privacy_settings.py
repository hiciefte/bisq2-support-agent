import pytest
from app.core.config import Settings
from pydantic import ValidationError


@pytest.mark.parametrize("retention_days", [0, 31])
def test_personal_data_retention_window_is_bounded(retention_days: int) -> None:
    with pytest.raises(ValidationError):
        Settings(DATA_RETENTION_DAYS=retention_days)


def test_escalation_retention_cannot_exceed_maximum_window() -> None:
    with pytest.raises(ValidationError):
        Settings(ESCALATION_RETENTION_DAYS=31)

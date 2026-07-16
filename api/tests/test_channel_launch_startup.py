"""Startup behavior for channel launch-control failures."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app import main as main_module


def test_launch_control_initialization_failure_keeps_app_available(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    """Initialization failure leaves autonomous delivery unavailable."""

    class FailingLaunchControl:
        def __init__(self, **kwargs) -> None:
            raise RuntimeError("synthetic launch-control failure")

    monkeypatch.setattr(
        main_module,
        "ChannelLaunchControlService",
        FailingLaunchControl,
    )
    settings = SimpleNamespace(
        DATA_DIR=str(tmp_path),
        AUTONOMOUS_DELIVERY_ENABLED=True,
    )

    with caplog.at_level(logging.CRITICAL, logger="app.main"):
        service = main_module._initialize_channel_launch_control(settings)

    assert service is None
    assert "Channel launch control initialization failed" in caplog.text

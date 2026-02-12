"""Verify Web domain module is importable from consolidated paths."""


def test_web_identity_importable():
    from app.channels.plugins.web.identity import derive_web_user_context

    assert derive_web_user_context is not None


def test_web_config_importable():
    from app.channels.plugins.web.config import WebChannelConfig

    assert WebChannelConfig is not None

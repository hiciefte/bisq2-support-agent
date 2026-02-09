"""Tests for ReactionHandlerProtocol: runtime_checkable isinstance checks."""

from unittest.mock import MagicMock

from app.channels.reactions import (
    ReactionHandlerBase,
    ReactionHandlerProtocol,
)


class ValidHandler:
    """A class that satisfies the protocol without inheriting."""

    channel_id = "valid"

    async def start_listening(self) -> None:
        pass

    async def stop_listening(self) -> None:
        pass


class InvalidHandler:
    """A class that does NOT satisfy the protocol."""

    pass


class ConcreteABCHandler(ReactionHandlerBase):
    """Handler via ABC inheritance."""

    channel_id = "concrete"

    async def start_listening(self) -> None:
        pass

    async def stop_listening(self) -> None:
        pass


class TestReactionHandlerProtocol:
    """Test Protocol isinstance checks."""

    def test_valid_handler_satisfies_protocol(self):
        handler = ValidHandler()
        assert isinstance(handler, ReactionHandlerProtocol)

    def test_invalid_handler_does_not_satisfy_protocol(self):
        handler = InvalidHandler()
        assert not isinstance(handler, ReactionHandlerProtocol)

    def test_abc_handler_satisfies_protocol(self):
        handler = ConcreteABCHandler(
            runtime=MagicMock(),
            processor=MagicMock(),
        )
        assert isinstance(handler, ReactionHandlerProtocol)

"""Tests for ReactionHandlerBase ABC: enforcement, config loading, rating mapping."""

from unittest.mock import MagicMock

import pytest
from app.channels.reactions import (
    ReactionHandlerBase,
    ReactionProcessor,
    ReactionRating,
)


class ConcreteHandler(ReactionHandlerBase):
    """Concrete test implementation of ReactionHandlerBase."""

    channel_id = "test_channel"

    async def start_listening(self) -> None:
        pass

    async def stop_listening(self) -> None:
        pass


class TestReactionHandlerBaseABC:
    """Test ABC enforcement."""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ReactionHandlerBase(
                runtime=MagicMock(),
                processor=MagicMock(),
            )

    def test_concrete_can_be_instantiated(self):
        handler = ConcreteHandler(
            runtime=MagicMock(),
            processor=MagicMock(),
        )
        assert handler.channel_id == "test_channel"


class TestReactionHandlerBaseEmojiMapping:
    """Test emoji-to-rating mapping."""

    def test_default_emoji_map(self):
        handler = ConcreteHandler(
            runtime=MagicMock(),
            processor=MagicMock(),
        )
        assert handler.map_emoji_to_rating("\U0001f44d") == ReactionRating.POSITIVE
        assert handler.map_emoji_to_rating("\U0001f44e") == ReactionRating.NEGATIVE
        assert handler.map_emoji_to_rating("\u2764\ufe0f") == ReactionRating.POSITIVE

    def test_custom_emoji_map(self):
        handler = ConcreteHandler(
            runtime=MagicMock(),
            processor=MagicMock(),
            emoji_rating_map={"\U0001f525": ReactionRating.POSITIVE},
        )
        assert handler.map_emoji_to_rating("\U0001f525") == ReactionRating.POSITIVE

    def test_unmapped_emoji_returns_none(self):
        handler = ConcreteHandler(
            runtime=MagicMock(),
            processor=MagicMock(),
        )
        assert handler.map_emoji_to_rating("\U0001f921") is None  # clown face


class TestReactionHandlerBaseProcessor:
    """Test processor resolution."""

    def test_processor_stored(self):
        processor = MagicMock(spec=ReactionProcessor)
        handler = ConcreteHandler(
            runtime=MagicMock(),
            processor=processor,
        )
        assert handler.processor is processor

    def test_runtime_stored(self):
        runtime = MagicMock()
        handler = ConcreteHandler(
            runtime=runtime,
            processor=MagicMock(),
        )
        assert handler.runtime is runtime

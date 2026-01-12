"""Input validation for Matrix messages.

Validates message content, sender IDs, and event IDs to prevent
injection attacks and resource exhaustion.
"""

from typing import Optional

# Maximum lengths based on Matrix spec and security best practices
MAX_MESSAGE_LENGTH = 10_000  # 10KB max for message content
MAX_SENDER_LENGTH = 255  # Standard Matrix user ID length
MAX_EVENT_ID_LENGTH = 255  # Standard Matrix event ID length


class ValidationError(Exception):
    """Raised when validation fails."""

    pass


def validate_message(message: str) -> None:
    """Validate message content.

    Args:
        message: The message content to validate

    Raises:
        ValidationError: If message fails validation
    """
    if not isinstance(message, str):
        raise ValidationError(f"Message must be a string, got {type(message)}")

    # Check byte length (not character length) for proper size limiting
    # UTF-8 multi-byte characters (emojis, Asian chars) need byte-level check
    try:
        message_bytes = message.encode("utf-8")
    except UnicodeEncodeError as e:
        raise ValidationError(f"Invalid UTF-8 encoding in message: {e}")

    if len(message_bytes) > MAX_MESSAGE_LENGTH:
        raise ValidationError(
            f"Message too long: {len(message_bytes)} bytes > {MAX_MESSAGE_LENGTH}"
        )


def validate_sender(sender: str) -> None:
    """Validate sender ID.

    Args:
        sender: The sender ID to validate (e.g., @user:matrix.org)

    Raises:
        ValidationError: If sender ID fails validation
    """
    if not isinstance(sender, str):
        raise ValidationError(f"Sender must be a string, got {type(sender)}")

    # Check length
    if len(sender) > MAX_SENDER_LENGTH:
        raise ValidationError(f"Sender too long: {len(sender)} > {MAX_SENDER_LENGTH}")

    # Check basic Matrix ID format (@localpart:domain)
    if not sender.startswith("@"):
        raise ValidationError(f"Sender must start with '@', got: {sender[:20]}...")

    if ":" not in sender:
        raise ValidationError(
            f"Sender must contain ':' separator, got: {sender[:20]}..."
        )


def validate_event_id(event_id: str) -> None:
    """Validate event ID.

    Args:
        event_id: The event ID to validate (e.g., $abc123:matrix.org)

    Raises:
        ValidationError: If event ID fails validation
    """
    if not isinstance(event_id, str):
        raise ValidationError(f"Event ID must be a string, got {type(event_id)}")

    # Check length
    if len(event_id) > MAX_EVENT_ID_LENGTH:
        raise ValidationError(
            f"Event ID too long: {len(event_id)} > {MAX_EVENT_ID_LENGTH}"
        )

    # Check basic Matrix event ID format ($localpart:domain)
    if not event_id.startswith("$"):
        raise ValidationError(f"Event ID must start with '$', got: {event_id[:20]}...")

    if ":" not in event_id:
        raise ValidationError(
            f"Event ID must contain ':' separator, got: {event_id[:20]}..."
        )


def validate_room_id(room_id: str) -> None:
    """Validate room ID.

    Args:
        room_id: The room ID to validate (e.g., !room:matrix.org)

    Raises:
        ValidationError: If room ID fails validation
    """
    if not isinstance(room_id, str):
        raise ValidationError(f"Room ID must be a string, got {type(room_id)}")

    # Check length
    if len(room_id) > MAX_EVENT_ID_LENGTH:  # Reuse same limit
        raise ValidationError(
            f"Room ID too long: {len(room_id)} > {MAX_EVENT_ID_LENGTH}"
        )

    # Check basic Matrix room ID format (!localpart:domain)
    if not room_id.startswith("!"):
        raise ValidationError(f"Room ID must start with '!', got: {room_id[:20]}...")

    if ":" not in room_id:
        raise ValidationError(
            f"Room ID must contain ':' separator, got: {room_id[:20]}..."
        )


def validate_matrix_message(
    message: str, sender: str, event_id: str, room_id: Optional[str] = None
) -> None:
    """Validate all components of a Matrix message.

    Args:
        message: The message content
        sender: The sender ID
        event_id: The event ID
        room_id: The room ID (optional)

    Raises:
        ValidationError: If any component fails validation
    """
    validate_message(message)
    validate_sender(sender)
    validate_event_id(event_id)
    if room_id:
        validate_room_id(room_id)

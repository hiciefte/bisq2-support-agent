"""Centralized error messages for the Bisq support agent.

All user-facing error strings live here so they maintain a consistent
voice aligned with the soul personality layer.  No "I apologize" —
direct, honest, and helpful.
"""

INSUFFICIENT_INFO: str = (
    "I don't have the info to answer that. "
    "Your question has been queued for FAQ creation. "
    "A Bisq human support agent can help you in the meantime."
)

NOT_INITIALIZED: str = "Still warming up. Give it a moment and try again."

QUERY_ERROR: str = "Hit an error processing your question. Try again in a bit."

NO_QUESTION: str = "Didn't catch a question there. What can I help you with on Bisq?"

GENERATION_FAILED: str = (
    "Couldn't put together a solid answer from what I have. "
    "Try rephrasing, or ask a human support agent."
)

TECHNICAL_ERROR: str = "Running into technical difficulties. Try again later."

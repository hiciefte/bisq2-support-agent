"""Shared web-channel identity derivation.

Extracts a stable, privacy-preserving user/session identifier from
an incoming HTTP request.  Used by both ``chat.py`` (query endpoint)
and ``feedback_routes.py`` (reaction endpoint).
"""

import hashlib
import uuid

from fastapi import Request


def derive_web_user_context(request: Request) -> tuple[str, str]:
    """Derive a stable, privacy-preserving user/session identifier for web traffic.

    Returns:
        Tuple of (user_id, session_id).
    """
    session_cookie = request.cookies.get("session_id") or request.cookies.get(
        "bisq_session_id"
    )
    if session_cookie:
        token = session_cookie.strip()
    else:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        client_host = request.client.host if request.client else ""
        user_agent = request.headers.get("user-agent", "")
        token = "|".join([forwarded_for, client_host, user_agent]).strip()
        if not token or token.replace("|", "").strip() == "":
            token = str(uuid.uuid4())

    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session_id = f"web_{digest[:32]}"
    user_id = f"user_{digest[:24]}"
    return user_id, session_id

"""Signed token utilities for trusted staff-answer rating flow."""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Optional


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(body: str, signing_key: str) -> str:
    mac = hmac.new(signing_key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256)
    return _b64url(mac.digest())


@dataclass(frozen=True)
class RatingTokenPayload:
    message_id: str
    rater_id: str
    purpose: str
    jti: str
    iat: int
    exp: int


def generate_rating_token(
    message_id: str,
    rater_id: str,
    signing_key: str,
    ttl_seconds: int,
) -> str:
    now = int(time.time())
    payload = {
        "message_id": message_id,
        "rater_id": rater_id,
        "purpose": "staff_rating",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + max(0, ttl_seconds),
        "nonce": secrets.token_hex(6),
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body, signing_key)}"


def verify_rating_token(
    token: str,
    message_id: str,
    rater_id: str,
    signing_key: str,
) -> Optional[RatingTokenPayload]:
    try:
        body, signature = token.split(".", 1)
        expected = _sign(body, signing_key)
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64url_decode(body))
        if payload.get("purpose") != "staff_rating":
            return None
        if payload.get("message_id") != message_id:
            return None
        if payload.get("rater_id") != rater_id:
            return None
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return RatingTokenPayload(
            message_id=str(payload["message_id"]),
            rater_id=str(payload["rater_id"]),
            purpose="staff_rating",
            jti=str(payload["jti"]),
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
        )
    except Exception:
        return None

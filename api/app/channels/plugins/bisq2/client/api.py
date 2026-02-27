import asyncio
import base64
import json
import logging
import os
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import ParseResult, urlparse, urlunparse

import aiohttp
from app.core.config import Settings

logger = logging.getLogger(__name__)

PAIRING_PROTOCOL_VERSION = 1
CLIENT_ID_HEADER = "Bisq-Client-Id"
SESSION_ID_HEADER = "Bisq-Session-Id"


def _record_bisq2_api_health(is_healthy: bool, response_time: Optional[float] = None):
    """Record Bisq2 API health metric (import lazily to avoid circular imports)."""
    try:
        from app.metrics.task_metrics import record_bisq2_api_health

        record_bisq2_api_health(is_healthy, response_time)
    except Exception as e:
        logger.debug(f"Could not record bisq2 API health metric: {e}")


class Bisq2API:
    """Integration with Bisq2 API for support chat export functionality."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_urls = self._build_base_url_candidates(settings.BISQ_API_URL)
        self.base_url = self.base_urls[0]
        self._session: Optional[aiohttp.ClientSession] = None
        self._auth_lock = asyncio.Lock()
        self._auth_enabled = self._setting_bool("BISQ_API_AUTH_ENABLED", False)
        self._client_id = self._setting_str("BISQ_API_CLIENT_ID")
        self._client_secret = self._setting_str("BISQ_API_CLIENT_SECRET")
        self._session_id = self._setting_str("BISQ_API_SESSION_ID")
        self._pairing_client_name = self._setting_str(
            "BISQ_API_PAIRING_CLIENT_NAME", "bisq-support-agent"
        )
        self._pairing_code_id = self._setting_str("BISQ_API_PAIRING_CODE_ID")
        self._auth_state_file = self._resolve_path(
            "BISQ_API_AUTH_STATE_PATH", "BISQ_API_AUTH_STATE_FILE"
        )
        self._pairing_qr_file = self._resolve_path(
            "BISQ_API_PAIRING_QR_PATH", "BISQ_API_PAIRING_QR_FILE"
        )
        if self._auth_enabled and not self._client_id:
            self._load_auth_state()
        if self._auth_enabled and not self._pairing_code_id:
            self._pairing_code_id = self._load_pairing_code_id_from_qr_file()

    @staticmethod
    def _replace_host(parsed: ParseResult, host: str) -> str:
        auth_prefix = ""
        if parsed.username:
            auth_prefix = parsed.username
            if parsed.password:
                auth_prefix += f":{parsed.password}"
            auth_prefix += "@"
        port_suffix = f":{parsed.port}" if parsed.port is not None else ""
        netloc = f"{auth_prefix}{host}{port_suffix}"
        return urlunparse(parsed._replace(netloc=netloc))

    @classmethod
    def _build_base_url_candidates(cls, configured_url: str) -> list[str]:
        primary = configured_url.rstrip("/")
        candidates = [primary]
        parsed = urlparse(primary)
        host = parsed.hostname or ""
        if host in {"bisq2-api", "localhost", "127.0.0.1"}:
            fallback = cls._replace_host(parsed, "host.docker.internal")
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates

    def _setting_str(self, name: str, default: str = "") -> str:
        value = getattr(self.settings, name, default)
        if isinstance(value, str):
            return value.strip()
        return default

    def _setting_bool(self, name: str, default: bool = False) -> bool:
        value = getattr(self.settings, name, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    def _resolve_path(self, preferred_name: str, fallback_name: str) -> str:
        candidate = self._setting_str(preferred_name)
        if candidate:
            return candidate
        fallback = self._setting_str(fallback_name)
        if not fallback:
            return ""
        if os.path.isabs(fallback):
            return fallback
        data_dir = self._setting_str("DATA_DIR", "api/data")
        return os.path.join(data_dir, fallback)

    @staticmethod
    def _parse_len_prefixed_bytes(payload: bytes, offset: int) -> tuple[bytes, int]:
        if offset + 2 > len(payload):
            raise ValueError("Length prefix out of bounds")
        length = struct.unpack(">H", payload[offset : offset + 2])[0]
        offset += 2
        end = offset + length
        if end > len(payload):
            raise ValueError("Length-prefixed value out of bounds")
        return payload[offset:end], end

    @classmethod
    def _decode_pairing_code_id_from_qr(cls, qr_payload: str) -> str:
        if not qr_payload:
            return ""
        padded = qr_payload.strip()
        if not padded:
            return ""

        # Java emits URL-safe base64 without padding; restore as needed.
        padded += "=" * (-len(padded) % 4)
        raw = base64.urlsafe_b64decode(padded)

        offset = 0
        if len(raw) < 1:
            return ""
        qr_version = raw[offset]
        offset += 1
        if qr_version != PAIRING_PROTOCOL_VERSION:
            raise ValueError(f"Unsupported pairing QR version: {qr_version}")

        pairing_bytes, offset = cls._parse_len_prefixed_bytes(raw, offset)
        # Skip websocket URL + flags; only pairing code ID is needed.
        _unused_ws, offset = cls._parse_len_prefixed_bytes(raw, offset)
        if offset < len(raw):
            offset += 1

        poffset = 0
        if len(pairing_bytes) < 1:
            return ""
        pairing_version = pairing_bytes[poffset]
        poffset += 1
        if pairing_version != PAIRING_PROTOCOL_VERSION:
            raise ValueError(f"Unsupported pairing code version: {pairing_version}")
        pairing_id_bytes, poffset = cls._parse_len_prefixed_bytes(
            pairing_bytes, poffset
        )
        return pairing_id_bytes.decode("utf-8").strip()

    def _load_pairing_code_id_from_qr_file(self) -> str:
        if not self._pairing_qr_file:
            return ""
        path = Path(self._pairing_qr_file)
        if not path.exists():
            return ""
        try:
            payload = path.read_text(encoding="utf-8").strip()
            pairing_code_id = self._decode_pairing_code_id_from_qr(payload)
            if pairing_code_id:
                logger.info("Loaded Bisq pairing code ID from QR file")
            return pairing_code_id
        except Exception:
            logger.exception(
                "Failed to parse Bisq pairing QR payload from %s",
                path,
            )
            return ""

    def _load_auth_state(self) -> None:
        if not self._auth_state_file:
            return
        path = Path(self._auth_state_file)
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            client_id = str(payload.get("client_id", "")).strip()
            if client_id:
                self._client_id = client_id
            if client_id:
                logger.info("Loaded Bisq API auth state from %s", path)
        except Exception:
            logger.exception("Failed to load Bisq API auth state from %s", path)

    def _save_auth_state(self) -> None:
        if not self._auth_state_file:
            return
        if not self._client_id:
            return

        path = Path(self._auth_state_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        try:
            payload = {
                "client_id": self._client_id,
            }
            temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp_path.replace(path)
        except Exception:
            logger.exception("Failed to persist Bisq API auth state to %s", path)
            if temp_path.exists():
                temp_path.unlink()

    async def setup(self):
        """Initialize the API client with timeouts."""
        if not self._session:
            timeout = aiohttp.ClientTimeout(total=10, connect=3, sock_read=10)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def cleanup(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()
            self._session = None

    @staticmethod
    def _is_access_endpoint(endpoint: str) -> bool:
        return endpoint.lstrip("/").startswith("api/v1/access/")

    def _build_authenticated_headers(
        self, existing: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        headers = dict(existing or {})
        if self._auth_enabled and self._client_id and self._session_id:
            headers[CLIENT_ID_HEADER] = self._client_id
            headers[SESSION_ID_HEADER] = self._session_id
        return headers

    async def _request_access(
        self,
        base_url: str,
        endpoint: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not self._session:
            await self.setup()

        url = f"{base_url}/{endpoint.lstrip('/')}"
        async with self._session.request("POST", url, **kwargs) as response:
            response.raise_for_status()
            if "application/json" in response.headers.get("content-type", ""):
                return await response.json()
            return {}

    async def _create_session(self, base_url: str) -> None:
        if not self._client_id or not self._client_secret:
            return
        payload = await self._request_access(
            base_url,
            "/api/v1/access/session",
            json={
                "clientId": self._client_id,
                "clientSecret": self._client_secret,
            },
            headers={"Accept": "application/json"},
        )
        session_id = str(payload.get("sessionId", "")).strip()
        if session_id:
            self._session_id = session_id
            self._save_auth_state()
            logger.info("Created Bisq API session")

    async def _pair_client(self, base_url: str) -> None:
        if not self._pairing_code_id:
            return
        payload = await self._request_access(
            base_url,
            "/api/v1/access/pairing",
            json={
                "version": PAIRING_PROTOCOL_VERSION,
                "pairingCodeId": self._pairing_code_id,
                "clientName": self._pairing_client_name,
            },
            headers={"Accept": "application/json"},
        )
        client_id = str(payload.get("clientId", "")).strip()
        client_secret = str(payload.get("clientSecret", "")).strip()
        session_id = str(payload.get("sessionId", "")).strip()
        if client_id and client_secret:
            self._client_id = client_id
            self._client_secret = client_secret
            self._save_auth_state()
            logger.info("Paired Bisq API client successfully")
        if session_id:
            self._session_id = session_id
            self._save_auth_state()

    async def _ensure_authenticated(self, base_url: str) -> None:
        if not self._auth_enabled:
            return

        if self._client_id and self._session_id:
            return

        async with self._auth_lock:
            if self._client_id and self._session_id:
                return

            if not self._client_id or not self._session_id:
                self._load_auth_state()

            if self._client_id and self._session_id:
                return

            if not self._pairing_code_id:
                self._pairing_code_id = self._load_pairing_code_id_from_qr_file()

            if (
                not self._client_id or not self._client_secret
            ) and self._pairing_code_id:
                await self._pair_client(base_url)

            if not self._client_id or not self._client_secret:
                raise RuntimeError(
                    "Bisq API auth is enabled but client credentials are missing. "
                    "Provide BISQ_API_CLIENT_ID/BISQ_API_CLIENT_SECRET or a pairing code ID/QR file."
                )

            if not self._session_id:
                await self._create_session(base_url)

            if not self._session_id:
                raise RuntimeError(
                    "Bisq API auth is enabled but session creation failed."
                )

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make an HTTP request to the Bisq2 API."""
        if not self._session:
            await self.setup()

        last_connection_error: Optional[aiohttp.ClientConnectionError] = None
        is_access_endpoint = self._is_access_endpoint(endpoint)
        saw_not_found = False
        for index, base_url in enumerate(self.base_urls):
            url = f"{base_url}/{endpoint.lstrip('/')}"
            try:
                if self._auth_enabled and not is_access_endpoint:
                    await self._ensure_authenticated(base_url)

                request_kwargs = dict(kwargs)
                headers = request_kwargs.get("headers")
                request_kwargs["headers"] = self._build_authenticated_headers(headers)

                for attempt in range(2):
                    async with self._session.request(
                        method, url, **request_kwargs
                    ) as response:
                        if response.status == 404:
                            saw_not_found = True
                            if index < len(self.base_urls) - 1:
                                logger.warning(
                                    "Bisq2 API returned 404 at %s; trying next candidate",
                                    base_url,
                                )
                            break
                        if (
                            self._auth_enabled
                            and not is_access_endpoint
                            and response.status in {401, 403}
                            and attempt == 0
                        ):
                            self._session_id = ""
                            await self._ensure_authenticated(base_url)
                            request_kwargs["headers"] = (
                                self._build_authenticated_headers(headers)
                            )
                            continue
                        response.raise_for_status()
                        if "application/json" in response.headers.get(
                            "content-type", ""
                        ):
                            return await response.json()
                        return {"content": await response.text()}
            except aiohttp.ClientConnectionError as e:
                last_connection_error = e
                logger.warning(
                    "Connection to Bisq2 API failed at %s; trying next candidate if available: %s",
                    base_url,
                    e,
                )
                continue
            except aiohttp.ClientError as e:
                logger.error(f"Error making request to Bisq2 API: {e}", exc_info=True)
                raise

        if last_connection_error:
            logger.error(
                "All Bisq2 API URL candidates failed: %s",
                ", ".join(self.base_urls),
                exc_info=True,
            )
            raise last_connection_error
        if saw_not_found:
            return {}
        return {}

    async def export_chat_messages(
        self,
        since: Optional[datetime] = None,
        max_retries: int = 3,
        retry_delay: int = 2,
    ) -> Dict:
        """Export chat messages from Bisq API with retries.

        Returns:
            Dictionary containing export data with structure:
            {
                "exportDate": "2025-10-14T15:30:00Z",
                "exportMetadata": {
                    "channelCount": 2,
                    "messageCount": 100,
                    "dataRetentionDays": 10,
                    "timezone": "UTC"
                },
                "messages": [...]
            }
        """
        if not self._session:
            await self.setup()

        for attempt in range(max_retries):
            start_time = time.time()
            try:
                params = {}
                if since:
                    # Ensure timezone-aware UTC, seconds precision, RFC3339 "Z"
                    if since.tzinfo is None:
                        since = since.replace(tzinfo=timezone.utc)
                    since_utc = (
                        since.astimezone(timezone.utc)
                        .replace(microsecond=0)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
                    params["since"] = since_utc

                result = await self._make_request(
                    "GET",
                    "/api/v1/support/export",
                    params=params,
                    headers={"Accept": "application/json"},
                )
                response_time = time.time() - start_time
                _record_bisq2_api_health(bool(result), response_time)
                return result

            except aiohttp.ClientError as e:
                response_time = time.time() - start_time
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries}: Failed to export chat messages: {str(e)}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                logger.error(
                    f"Failed to export chat messages after {max_retries} attempts: {str(e)}",
                    exc_info=True,
                )
                # Final attempt failed - record unhealthy
                _record_bisq2_api_health(False, response_time)
                return {}
            except Exception as e:
                response_time = time.time() - start_time
                logger.error(
                    "Failed to export chat messages due to non-HTTP error: %s",
                    e,
                    exc_info=True,
                )
                _record_bisq2_api_health(False, response_time)
                return {}

        # Unreachable: loop always returns on success or terminal failure
        return {}

    async def send_support_message(
        self,
        channel_id: str,
        text: str,
        citation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a support message to a Bisq2 channel.

        Args:
            channel_id: Bisq2 channel ID (e.g. "support.support").
            text: Message text to send.
            citation: Optional citation text (original question).

        Returns:
            Response dict with messageId and timestamp, or empty dict on 404.

        Raises:
            aiohttp.ClientError: On connection/HTTP errors.
        """
        endpoint = f"/api/v1/support/channels/{channel_id}/messages"
        body: Dict[str, Any] = {"text": text}
        if citation is not None:
            body["citation"] = citation

        response = await self._make_request("POST", endpoint, json=body)
        if self._has_message_id(response):
            return response

        # Local Bisq2 instances can reject support sends with 404 when no chat
        # identity is selected yet. Attempt bootstrap/select once and retry.
        if response == {}:
            ensured_identity = await self._ensure_selected_user_identity()
            if ensured_identity:
                retry_response = await self._make_request("POST", endpoint, json=body)
                if self._has_message_id(retry_response):
                    logger.info(
                        "Support send succeeded after selecting/bootstrapping user identity"
                    )
                return retry_response

        return response

    @staticmethod
    def _has_message_id(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        value = payload.get("messageId")
        return isinstance(value, str) and bool(value.strip())

    async def _ensure_selected_user_identity(self) -> bool:
        """Ensure Bisq2 has an active chat user identity selected."""
        headers = {"Accept": "application/json"}
        try:
            selected = await self._make_request(
                "GET",
                "/api/v1/user-identities/selected/user-profile",
                headers=headers,
            )
            if selected:
                return True

            identity_ids = await self._make_request(
                "GET",
                "/api/v1/user-identities/ids",
                headers=headers,
            )
            primary_identity_id = ""
            if isinstance(identity_ids, list) and identity_ids:
                candidate = identity_ids[0]
                if isinstance(candidate, str):
                    primary_identity_id = candidate.strip()

            if primary_identity_id:
                selected_profile = await self._make_request(
                    "POST",
                    "/api/v1/user-identities/select",
                    json={"userProfileId": primary_identity_id},
                    headers=headers,
                )
                if selected_profile:
                    logger.info(
                        "Selected existing Bisq2 user identity: %s",
                        primary_identity_id,
                    )
                    return True

            key_material = await self._make_request(
                "GET",
                "/api/v1/user-identities/key-material",
                headers=headers,
            )
            if not isinstance(key_material, dict) or not key_material:
                logger.warning(
                    "Could not bootstrap Bisq2 user identity: missing key material response"
                )
                return False

            created = await self._make_request(
                "POST",
                "/api/v1/user-identities",
                json={
                    "nickName": "Bisq Support Agent",
                    "terms": "",
                    "statement": "",
                    "keyMaterialResponse": key_material,
                },
                headers=headers,
            )
            if not created:
                logger.warning(
                    "Could not bootstrap Bisq2 user identity: create endpoint returned empty response"
                )
                return False

            selected_after_create = await self._make_request(
                "GET",
                "/api/v1/user-identities/selected/user-profile",
                headers=headers,
            )
            if selected_after_create:
                logger.info("Bootstrapped and selected new Bisq2 user identity")
                return True

            # Fallback: select first known identity if create did not auto-select.
            identity_ids_after_create = await self._make_request(
                "GET",
                "/api/v1/user-identities/ids",
                headers=headers,
            )
            if (
                isinstance(identity_ids_after_create, list)
                and identity_ids_after_create
            ):
                fallback_id = identity_ids_after_create[0]
                if isinstance(fallback_id, str) and fallback_id.strip():
                    selected_profile = await self._make_request(
                        "POST",
                        "/api/v1/user-identities/select",
                        json={"userProfileId": fallback_id.strip()},
                        headers=headers,
                    )
                    if selected_profile:
                        logger.info(
                            "Selected fallback Bisq2 user identity after bootstrap: %s",
                            fallback_id.strip(),
                        )
                        return True

            logger.warning("Failed to ensure selected Bisq2 user identity")
            return False
        except Exception:
            logger.exception("Failed to ensure selected Bisq2 user identity")
            return False

    async def send_reaction(
        self,
        channel_id: str,
        message_id: str,
        reaction_id: int,
        is_removed: bool = False,
    ) -> Dict[str, Any]:
        """Send a reaction to a message in a Bisq2 channel.

        Args:
            channel_id: Bisq2 channel ID.
            message_id: ID of the message to react to.
            reaction_id: Bisq2 Reaction enum ordinal (0=THUMBS_UP, etc.).
            is_removed: Whether to remove the reaction.

        Returns:
            Response dict (usually empty on 204).

        Raises:
            aiohttp.ClientError: On connection/HTTP errors.
        """
        endpoint = f"/api/v1/support/channels/{channel_id}/{message_id}/reactions"
        body: Dict[str, Any] = {
            "reactionId": reaction_id,
            "isRemoved": is_removed,
        }
        return await self._make_request("POST", endpoint, json=body)

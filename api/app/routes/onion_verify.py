"""
Onion service verification endpoint.

Provides cryptographic proof of .onion address ownership.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Union

from app.core.config import get_settings
from app.core.tor_metrics import record_verification_request
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/.well-known/onion-verify", tags=["Onion Verification"])

# Static timestamp generated at module load time (timezone-aware UTC)
# This ensures consistent hash verification across requests
VERIFICATION_TIMESTAMP = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Compute verification data and hash once at module load
def _get_verification_data() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Precompute verification data and hash at module load time.

    Returns:
        Tuple of (onion_address, verification_data, data_hash) or (None, None, None) if not configured
    """
    settings = get_settings()  # Get settings at function level, not module level
    onion_address = settings.TOR_HIDDEN_SERVICE
    if not onion_address:
        return None, None, None
    verification_data = (
        f"onion-address={onion_address}\ntimestamp={VERIFICATION_TIMESTAMP}"
    )
    data_hash = hashlib.sha256(verification_data.encode()).hexdigest()
    return onion_address, verification_data, data_hash


# Initialize verification data at module load, with fallback for testing
try:
    ONION_ADDRESS, VERIFICATION_DATA, VERIFICATION_HASH = _get_verification_data()
except (ValueError, KeyError) as e:
    # If settings fail to load (e.g., missing ADMIN_API_KEY during testing),
    # initialize with None values. The endpoint handlers check for None.
    logger.warning(f"Failed to initialize onion verification data: {e}")
    ONION_ADDRESS = None
    VERIFICATION_DATA = None
    VERIFICATION_HASH = None


@router.get("/bisq-support.txt")
async def onion_verification() -> Response:
    """Return .onion verification file.

    This endpoint provides cryptographic proof that the clearnet site
    controls the .onion address. The verification file contains:
    - The .onion address
    - Static timestamp (generated at module load, consistent across requests)
    - SHA256 hash of the verification data
    - Human-readable verification instructions

    Returns:
        Response: Plain text verification file
    """
    if not ONION_ADDRESS:
        record_verification_request("bisq-support.txt", 503)
        return Response(
            content="# Onion service not configured\n",
            media_type="text/plain",
            status_code=503,
        )

    # Use precomputed values from module load
    onion_address = ONION_ADDRESS
    timestamp = VERIFICATION_TIMESTAMP
    verification_data = VERIFICATION_DATA
    data_hash = VERIFICATION_HASH

    # Complete verification file
    content = f"""# Bisq Support Agent - Onion Service Verification
# This file cryptographically proves that this clearnet site controls the .onion address

# Onion Address
onion-address={onion_address}

# Verification Timestamp (UTC)
timestamp={timestamp}

# SHA256 Hash of Verification Data
hash={data_hash}

# Verification Instructions
# 1. Visit this same URL on both clearnet and .onion
# 2. Verify that the onion-address matches on both versions
# 3. Verify that the hash matches: sha256sum of "onion-address=<addr>\\ntimestamp=<time>"
# 4. The timestamp is static (set at service start) to ensure consistent hash verification

# How to Verify
# echo -n "{verification_data}" | sha256sum
# Should output: {data_hash}

# Security Notice
# This verification proves that whoever controls this clearnet site also controls
# the .onion address. It does NOT prove the identity of the site operator.
# For additional verification, check:
# - Official Bisq communication channels
# - Community forums and documentation
# - PGP-signed announcements from Bisq developers
"""

    record_verification_request("bisq-support.txt", 200)
    return Response(content=content, media_type="text/plain")


@router.get("/verification-info", response_model=None)
async def verification_info() -> Union[Dict[str, str], JSONResponse]:
    """Return JSON verification information.

    Provides structured verification data for programmatic access.

    Returns:
        Union[Dict, JSONResponse]: JSON object with verification details or error response
    """
    if not ONION_ADDRESS:
        record_verification_request("verification-info", 503)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "message": "Onion service not configured",
            },
        )

    # Use precomputed values from module load
    # These are guaranteed to be non-None because ONION_ADDRESS is checked above
    onion_address = ONION_ADDRESS
    timestamp = VERIFICATION_TIMESTAMP
    verification_data = VERIFICATION_DATA
    data_hash = VERIFICATION_HASH

    # Type assertions for mypy - these are guaranteed non-None at this point
    assert onion_address is not None
    assert verification_data is not None
    assert data_hash is not None

    record_verification_request("verification-info", 200)
    return {
        "status": "available",
        "onion_address": onion_address,
        "timestamp": timestamp,
        "verification_hash": data_hash,
        "verification_command": f'echo -n "{verification_data}" | sha256sum',
        "instructions": "Visit /.well-known/onion-verify/bisq-support.txt on both clearnet and .onion to verify",
    }

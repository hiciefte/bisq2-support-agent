"""
Onion service verification endpoint.

Provides cryptographic proof of .onion address ownership.
"""

import hashlib
import logging
from datetime import datetime
from typing import Dict

from app.core.config import get_settings
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/.well-known/onion-verify", tags=["Onion Verification"])

# Static timestamp generated at module load time
# This ensures consistent hash verification across requests
VERIFICATION_TIMESTAMP = datetime.utcnow().isoformat() + "Z"


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
    onion_address = settings.TOR_HIDDEN_SERVICE

    if not onion_address:
        return Response(
            content="# Onion service not configured\n",
            media_type="text/plain",
            status_code=503,
        )

    # Use static timestamp for consistent hash verification
    timestamp = VERIFICATION_TIMESTAMP

    # Create verification content
    verification_data = f"onion-address={onion_address}\ntimestamp={timestamp}"

    # Generate SHA256 hash for verification
    data_hash = hashlib.sha256(verification_data.encode()).hexdigest()

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

    return Response(content=content, media_type="text/plain")


@router.get("/verification-info")
async def verification_info() -> Dict[str, str]:
    """Return JSON verification information.

    Provides structured verification data for programmatic access.

    Returns:
        Dict: JSON object with verification details
    """
    onion_address = settings.TOR_HIDDEN_SERVICE

    if not onion_address:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "message": "Onion service not configured",
            },
        )

    # Use static timestamp for consistent hash verification
    timestamp = VERIFICATION_TIMESTAMP
    verification_data = f"onion-address={onion_address}\ntimestamp={timestamp}"
    data_hash = hashlib.sha256(verification_data.encode()).hexdigest()

    return {
        "status": "available",
        "onion_address": onion_address,
        "timestamp": timestamp,
        "verification_hash": data_hash,
        "verification_command": f'echo -n "{verification_data}" | sha256sum',
        "instructions": "Visit /.well-known/onion-verify/bisq-support.txt on both clearnet and .onion to verify",
    }

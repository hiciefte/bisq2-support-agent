import re


def redact_pii(text: str) -> str:
    """
    Redact potential Personally Identifiable Information (PII) from text.

    This function redacts common PII patterns including:
    - Email addresses
    - IP addresses
    - Bitcoin addresses (Legacy P2PKH, P2SH, and Bech32)
    - Matrix IDs (@user:server.com)
    - Bisq profile IDs (UUID format)
    - API keys and passwords
    - Phone numbers
    - Long numeric sequences
    """
    # Bitcoin addresses - Legacy P2PKH (starts with 1)
    text = re.sub(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b", "[BTC_ADDRESS]", text)

    # Bitcoin addresses - Bech32 (starts with bc1)
    text = re.sub(r"\bbc1[a-z0-9]{39,59}\b", "[BTC_ADDRESS]", text, flags=re.IGNORECASE)

    # Matrix IDs (@username:server.domain)
    text = re.sub(r"@[a-zA-Z0-9._-]+:[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[MATRIX_ID]", text)

    # Bisq profile IDs (UUID format)
    text = re.sub(
        r"\b[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\b",
        "[PROFILE_ID]",
        text,
    )

    # Email addresses
    text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)

    # IP addresses
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", text)

    # Long numeric sequences that might be IDs
    text = re.sub(r"\b\d{8,}\b", "[ID]", text)

    # Alphanumeric strings that look like API keys or passwords
    text = re.sub(r"\b[a-zA-Z0-9]{32,}\b", "[KEY]", text)

    # Phone numbers in various formats
    text = re.sub(
        r"\b(?:\+\d{1,3}[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b", "[PHONE]", text
    )

    # Partial numeric sequences that might be sensitive
    text = re.sub(r"\b\d{4,}\b", "[NUMBER]", text)

    return text

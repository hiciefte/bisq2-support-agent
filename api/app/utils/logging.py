import re


def redact_pii(text: str) -> str:
    """
    Redact potential Personally Identifiable Information (PII) from text.
    """
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

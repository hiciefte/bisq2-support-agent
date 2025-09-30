"""
PII Detection and Monitoring Utility

This module provides utilities for detecting Personally Identifiable Information (PII)
in logs and application output to ensure GDPR compliance and privacy protection.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PIIDetector:
    """Detector for identifying PII patterns in text."""

    # PII pattern definitions
    PATTERNS = {
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "bitcoin_legacy": r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b",
        # Match specific segwit (bc1q) and taproot (bc1p) addresses
        "bitcoin_bech32": r"\bbc1[qp][a-z0-9]{38,58}\b",
        "matrix_id": r"@[a-zA-Z0-9._-]+:[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "uuid": r"\b[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\b",
        "phone": r"\b(?:\+\d{1,3}[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b",
        # Match API keys with common prefixes to reduce false positives
        "api_key": r"\b(?:sk-|pk-|Bearer\s+)?[a-zA-Z0-9_-]{32,}\b",
        # Match credit card numbers and SSNs specifically instead of generic long numbers
        "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    }

    def __init__(self):
        """Initialize the PII detector with compiled patterns."""
        self.compiled_patterns = {
            name: re.compile(pattern, re.IGNORECASE if name == "bitcoin_bech32" else 0)
            for name, pattern in self.PATTERNS.items()
        }

    def detect_pii(self, text: str) -> Dict[str, List[str]]:
        """Detect all PII patterns in the given text.

        Args:
            text: The text to scan for PII

        Returns:
            Dictionary mapping PII type to list of detected instances
        """
        detections = {}

        for pii_type, pattern in self.compiled_patterns.items():
            matches = pattern.findall(text)
            if matches:
                # Store unique matches only
                detections[pii_type] = list(set(matches))

        return detections

    def contains_pii(self, text: str) -> bool:
        """Check if text contains any PII.

        Args:
            text: The text to check

        Returns:
            True if any PII pattern is detected, False otherwise
        """
        for pattern in self.compiled_patterns.values():
            if pattern.search(text):
                return True
        return False

    def scan_text_with_context(
        self, text: str, context_chars: int = 20
    ) -> List[Tuple[str, str, str]]:
        """Scan text for PII and return matches with surrounding context.

        Args:
            text: The text to scan
            context_chars: Number of characters to include before/after match

        Returns:
            List of tuples: (pii_type, matched_text, context)
        """
        results = []

        for pii_type, pattern in self.compiled_patterns.items():
            for match in pattern.finditer(text):
                start = max(0, match.start() - context_chars)
                end = min(len(text), match.end() + context_chars)
                context = text[start:end]
                results.append((pii_type, match.group(), context))

        return results


class PIIMonitor:
    """Monitor and alert on PII detection in application output."""

    def __init__(self, alert_threshold: int = 5):
        """Initialize the PII monitor.

        Args:
            alert_threshold: Number of PII detections before alerting
        """
        self.detector = PIIDetector()
        self.alert_threshold = alert_threshold
        self.detection_count = 0

    def check_and_alert(self, text: str, source: str = "unknown") -> Optional[Dict]:
        """Check text for PII and alert if threshold is exceeded.

        Args:
            text: The text to check
            source: Source identifier for the text (e.g., log file, API response)

        Returns:
            Detection report if PII found, None otherwise
        """
        detections = self.detector.detect_pii(text)

        if detections:
            self.detection_count += sum(len(matches) for matches in detections.values())

            # Log warning for each detection
            logger.warning(
                f"PII detected in {source}",
                extra={
                    "event": "pii_detected",
                    "source": source,
                    "pii_types": list(detections.keys()),
                    "total_detections": sum(len(m) for m in detections.values()),
                },
            )

            # Alert if threshold exceeded
            if self.detection_count >= self.alert_threshold:
                alert_msg = (
                    f"PII detection threshold exceeded: {self.detection_count} "
                    f"instances detected (threshold: {self.alert_threshold})"
                )
                logger.error(
                    alert_msg,
                    extra={
                        "event": "pii_threshold_exceeded",
                        "detection_count": self.detection_count,
                        "threshold": self.alert_threshold,
                    },
                )

                # Reset counter after alert
                self.detection_count = 0

            return {
                "source": source,
                "detections": detections,
                "total_count": sum(len(m) for m in detections.values()),
            }

        return None

    def scan_file(self, file_path: str) -> Dict:
        """Scan a file for PII.

        Args:
            file_path: Path to file to scan

        Returns:
            Scan report with detections
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            detections = self.detector.detect_pii(content)
            total_detections = sum(len(matches) for matches in detections.values())

            if detections:
                logger.warning(
                    f"PII found in file: {file_path}",
                    extra={
                        "event": "pii_in_file",
                        "file_path": file_path,
                        "pii_types": list(detections.keys()),
                        "total_detections": total_detections,
                    },
                )

            return {
                "file_path": file_path,
                "detections": detections,
                "total_count": total_detections,
            }

        except Exception:
            logger.exception(f"Error scanning file {file_path}")
            return {"file_path": file_path, "error": "Scan failed"}


def scan_logs_for_pii(log_dir: str, pattern: str = "*.log") -> List[Dict]:
    """Scan log files for PII exposure.

    Args:
        log_dir: Directory containing log files
        pattern: Glob pattern for log files

    Returns:
        List of scan reports for files containing PII
    """
    import glob
    from pathlib import Path

    monitor = PIIMonitor()
    results = []

    log_files = glob.glob(str(Path(log_dir) / pattern))

    for log_file in log_files:
        report = monitor.scan_file(log_file)
        if report.get("total_count", 0) > 0:
            results.append(report)

    return results


# Global detector instance for convenience
_detector = PIIDetector()


def detect_pii(text: str) -> Dict[str, List[str]]:
    """Convenience function to detect PII in text.

    Args:
        text: The text to scan

    Returns:
        Dictionary of detected PII by type
    """
    return _detector.detect_pii(text)


def contains_pii(text: str) -> bool:
    """Convenience function to check if text contains PII.

    Args:
        text: The text to check

    Returns:
        True if PII detected, False otherwise
    """
    return _detector.contains_pii(text)

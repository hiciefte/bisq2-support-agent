"""
Migration script to convert bisq_version to protocol field in existing FAQs.

This script converts old bisq_version values to the new protocol field:
- "Bisq 1" -> "multisig_v1"
- "Bisq 2" -> "bisq_easy"
- "General" -> None (all protocols)

Usage:
    # Dry run (preview changes without modifying file)
    python -m app.scripts.migrate_faq_version --dry-run

    # Execute migration
    python -m app.scripts.migrate_faq_version

    # Use custom default protocol
    python -m app.scripts.migrate_faq_version --default-protocol "bisq_easy"
"""

import argparse
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def backup_faq_file(faq_file_path: Path) -> Path:
    """Create a timestamped backup of the FAQ file.

    Args:
        faq_file_path: Path to the FAQ JSONL file

    Returns:
        Path to the backup file
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = faq_file_path.with_suffix(f".backup_{timestamp}.jsonl")

    shutil.copy2(faq_file_path, backup_path)
    logger.info(f"Created backup: {backup_path}")

    return backup_path


def load_faqs(faq_file_path: Path) -> List[Dict]:
    """Load all FAQs from the JSONL file.

    Args:
        faq_file_path: Path to the FAQ JSONL file

    Returns:
        List of FAQ dictionaries
    """
    faqs: List[Dict] = []

    if not faq_file_path.exists():
        logger.error(f"FAQ file not found: {faq_file_path}")
        return faqs

    with open(faq_file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                faq = json.loads(line)
                faqs.append(faq)
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing line {line_num}: {e}")
                logger.error(f"Line content: {line[:100]}...")

    logger.info(f"Loaded {len(faqs)} FAQs from {faq_file_path}")
    return faqs


def migrate_faqs(
    faqs: List[Dict], default_protocol: str = "bisq_easy"
) -> tuple[List[Dict], int]:
    """Convert bisq_version to protocol field in FAQs.

    Args:
        faqs: List of FAQ dictionaries
        default_protocol: Default protocol to assign (default: "bisq_easy")

    Returns:
        Tuple of (updated_faqs, count_updated)
    """
    valid_protocols = {"multisig_v1", "bisq_easy", "musig", "all", None}

    # Mapping from old bisq_version to new protocol
    bisq_version_to_protocol = {
        "Bisq 1": "multisig_v1",
        "Bisq 2": "bisq_easy",
        "General": None,
        "Both": None,  # "Both" maps to None (all protocols)
    }

    if default_protocol not in valid_protocols:
        logger.warning(
            f"Invalid default_protocol '{default_protocol}', using 'bisq_easy'"
        )
        default_protocol = "bisq_easy"

    updated_count = 0

    for faq in faqs:
        # If protocol already exists and is valid, keep it
        if "protocol" in faq and faq["protocol"] in valid_protocols:
            continue

        # Convert old bisq_version to protocol
        if "bisq_version" in faq:
            old_version = faq["bisq_version"]
            new_protocol = bisq_version_to_protocol.get(old_version, default_protocol)
            faq["protocol"] = new_protocol
            # Remove old bisq_version field
            del faq["bisq_version"]
            updated_count += 1
            logger.debug(
                f"Converted FAQ: bisq_version='{old_version}' -> protocol='{new_protocol}'"
            )
        else:
            # No bisq_version or protocol, use default
            faq["protocol"] = default_protocol
            updated_count += 1

    return faqs, updated_count


def save_faqs(faq_file_path: Path, faqs: List[Dict]) -> None:
    """Save FAQs back to the JSONL file.

    Args:
        faq_file_path: Path to the FAQ JSONL file
        faqs: List of FAQ dictionaries
    """
    with open(faq_file_path, "w", encoding="utf-8") as f:
        for faq in faqs:
            f.write(json.dumps(faq, ensure_ascii=False) + "\n")

    logger.info(f"Saved {len(faqs)} FAQs to {faq_file_path}")


def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(
        description="Migrate FAQ entries from bisq_version to protocol field"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying the file",
    )
    parser.add_argument(
        "--default-protocol",
        type=str,
        default="bisq_easy",
        choices=["multisig_v1", "bisq_easy", "musig", "all"],
        help="Default protocol to assign (default: bisq_easy)",
    )
    parser.add_argument(
        "--faq-file", type=str, help="Path to FAQ file (default: from settings)"
    )

    args = parser.parse_args()

    # Determine FAQ file path
    if args.faq_file:
        faq_file_path = Path(args.faq_file)
    else:
        from app.core.config import get_settings

        settings = get_settings()
        faq_file_path = Path(settings.DATA_DIR) / "extracted_faq.jsonl"

    logger.info(f"Using FAQ file: {faq_file_path}")

    # Load FAQs
    faqs = load_faqs(faq_file_path)

    if not faqs:
        logger.warning("No FAQs to migrate")
        return

    # Migrate FAQs
    updated_faqs, updated_count = migrate_faqs(faqs, args.default_protocol)

    logger.info(f"Migration summary: {updated_count} FAQs converted to protocol field")

    # Show sample of changes
    if updated_count > 0:
        logger.info("Sample of updated FAQs:")
        sample_size = min(3, updated_count)
        sample_count = 0
        for faq in updated_faqs:
            if sample_count >= sample_size:
                break
            if "protocol" in faq:
                logger.info(f"  - Question: {faq.get('question', 'N/A')[:60]}...")
                logger.info(f"    Protocol: {faq.get('protocol')}")
                sample_count += 1

    # Dry run mode - don't save
    if args.dry_run:
        logger.info("Dry run complete - no changes written to disk")
        return

    # Create backup before saving
    backup_path = backup_faq_file(faq_file_path)
    logger.info(f"Backup created at: {backup_path}")

    # Save migrated FAQs
    try:
        save_faqs(faq_file_path, updated_faqs)
        logger.info("Migration completed successfully")
    except Exception as e:
        logger.error(f"Error saving migrated FAQs: {e}")
        logger.error(f"Backup is available at: {backup_path}")
        raise


if __name__ == "__main__":
    main()

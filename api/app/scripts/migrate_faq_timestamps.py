#!/usr/bin/env python3
"""
Migration script to add timestamp fields to existing FAQs.

This script:
1. Reads all existing FAQs from extracted_faq.jsonl
2. Adds created_at, updated_at, and verified_at fields
3. Writes back to the file with timestamps
4. Creates a backup before modification

Usage:
    python -m app.scripts.migrate_faq_timestamps [--dry-run]
"""

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# Add project root to path - must be before app imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# noqa comments needed because imports must come after sys.path modification
from app.core.config import get_settings  # noqa: E402
from app.models.faq import FAQItem  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def migrate_faq_timestamps(dry_run: bool = False) -> dict:
    """
    Migrate existing FAQs to include timestamp fields.

    Args:
        dry_run: If True, only simulate the migration without writing changes

    Returns:
        Dictionary with migration statistics
    """
    settings = get_settings()
    faq_file_path = Path(settings.DATA_DIR) / "extracted_faq.jsonl"

    if not faq_file_path.exists():
        logger.error(f"FAQ file not found at {faq_file_path}")
        return {"status": "error", "message": "FAQ file not found"}

    # Create backup
    if not dry_run:
        backup_path = faq_file_path.with_suffix(".jsonl.backup")
        shutil.copy2(faq_file_path, backup_path)
        logger.info(f"Created backup at {backup_path}")

    # Read existing FAQs
    faqs: List[dict] = []
    with open(faq_file_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            if line.strip():
                try:
                    faq_data = json.loads(line)
                    faqs.append(faq_data)
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Skipping malformed line {line_num} in FAQ file: {e}"
                    )

    logger.info(f"Read {len(faqs)} FAQs from file")

    # Migration timestamp - use current time as default for all existing FAQs
    migration_timestamp = datetime.now(timezone.utc)

    # Process each FAQ
    migrated_count = 0
    skipped_count = 0

    for faq_data in faqs:
        # Check if timestamps already exist
        if "created_at" in faq_data and faq_data["created_at"]:
            logger.debug(
                f"FAQ already has timestamps, skipping: {faq_data.get('question', 'Unknown')[:50]}"
            )
            skipped_count += 1
            continue

        # Add timestamp fields
        faq_data["created_at"] = migration_timestamp.isoformat()
        faq_data["updated_at"] = migration_timestamp.isoformat()

        # Add verified_at only if FAQ is already verified
        if faq_data.get("verified", False):
            faq_data["verified_at"] = migration_timestamp.isoformat()
        else:
            faq_data["verified_at"] = None

        migrated_count += 1
        logger.debug(f"Migrated FAQ: {faq_data.get('question', 'Unknown')[:50]}")

    # Write back to file
    if not dry_run:
        with open(faq_file_path, "w") as f:
            for faq in faqs:
                f.write(json.dumps(faq) + "\n")
        logger.info(f"Wrote {len(faqs)} FAQs back to file")
    else:
        logger.info("[DRY RUN] Would have written changes to file")

    # Validate migration by reading back
    if not dry_run:
        with open(faq_file_path, "r") as f:
            validated_count = 0
            for line in f:
                if line.strip():
                    try:
                        faq_data = json.loads(line)
                        # Validate using Pydantic model
                        FAQItem(**faq_data)
                        validated_count += 1
                    except Exception as e:
                        logger.error(f"Validation failed for FAQ: {e}")
                        return {
                            "status": "error",
                            "message": f"Validation failed: {e}",
                        }

        logger.info(f"Validated {validated_count} FAQs successfully")

    return {
        "status": "success",
        "total_faqs": len(faqs),
        "migrated": migrated_count,
        "skipped": skipped_count,
        "migration_timestamp": migration_timestamp.isoformat(),
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Migrate FAQ data to include timestamp fields"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without writing changes",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("FAQ Timestamp Migration Script")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("Running in DRY RUN mode - no changes will be written")

    result = migrate_faq_timestamps(dry_run=args.dry_run)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Migration Results:")
    logger.info(f"  Status: {result['status']}")

    if result["status"] == "success":
        logger.info(f"  Total FAQs: {result['total_faqs']}")
        logger.info(f"  Migrated: {result['migrated']}")
        logger.info(f"  Skipped (already migrated): {result['skipped']}")
        logger.info(f"  Migration timestamp: {result['migration_timestamp']}")
        if result["dry_run"]:
            logger.info("  ** DRY RUN - No changes written **")
        else:
            logger.info("  ✅ Migration completed successfully")
            logger.info(
                "  Note: Backup created with .backup extension in data directory"
            )
    else:
        logger.error(f"  Message: {result.get('message', 'Unknown error')}")

    logger.info("=" * 60)

    # Exit code
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()

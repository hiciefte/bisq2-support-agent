"""
Production migration script: JSONL → SQLite

This script:
1. Creates backup of JSONL file
2. Migrates all FAQs to SQLite
3. Verifies migration integrity
4. Optionally switches FAQService to use SQLite

Usage:
    python -m app.scripts.migrate_to_sqlite [--verify-only] [--dry-run] [--rollback]

Options:
    --verify-only    Verify existing migration without performing new migration
    --dry-run        Test migration without committing changes
    --rollback       Rollback from SQLite to JSONL (disaster recovery)
"""

import argparse
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

import portalocker
from app.core.config import get_settings
from app.services.faq.faq_migration import (
    migrate_jsonl_to_sqlite,
    rollback_sqlite_to_jsonl,
    verify_migration,
)
from app.services.faq.faq_repository import FAQRepository
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_backup(jsonl_path: Path) -> Path:
    """
    Create timestamped backup of JSONL file.

    Args:
        jsonl_path: Path to JSONL file

    Returns:
        Path: Backup file path

    Raises:
        FileNotFoundError: If JSONL file doesn't exist
    """
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = jsonl_path.parent / f"extracted_faq_{timestamp}.jsonl.backup"

    logger.info(f"Creating backup: {backup_path}")
    shutil.copy2(jsonl_path, backup_path)

    # Verify backup
    if not backup_path.exists():
        raise RuntimeError(f"Backup creation failed: {backup_path}")

    backup_size = backup_path.stat().st_size
    original_size = jsonl_path.stat().st_size

    if backup_size != original_size:
        raise RuntimeError(
            f"Backup size mismatch: backup={backup_size}, original={original_size}"
        )

    logger.info(f"Backup created successfully: {backup_path} ({backup_size} bytes)")
    return backup_path


def main():
    """Main migration script entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate FAQ data from JSONL to SQLite"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify existing migration without performing new migration",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test migration without committing changes",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback from SQLite to JSONL (disaster recovery)",
    )

    args = parser.parse_args()

    # Get application settings
    settings = get_settings()

    # Define paths
    jsonl_path = Path(settings.DATA_DIR) / "extracted_faq.jsonl"
    db_path = Path(settings.DATA_DIR) / "faqs.db"

    logger.info("=" * 80)
    logger.info("FAQ Migration: JSONL → SQLite")
    logger.info("=" * 80)
    logger.info(f"JSONL file: {jsonl_path}")
    logger.info(f"SQLite DB: {db_path}")
    logger.info(
        f"Mode: {'VERIFY ONLY' if args.verify_only else 'DRY RUN' if args.dry_run else 'ROLLBACK' if args.rollback else 'PRODUCTION'}"
    )
    logger.info("=" * 80)

    try:
        # Create JSONL repository (always needed)
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))

        # Only create SQLite repository if not in dry-run mode
        # (dry-run should not create or modify the database)
        if args.dry_run:
            logger.info("DRY RUN: Skipping database creation and migration")
            logger.info(f"Would read from: {jsonl_path}")
            logger.info(f"Would write to: {db_path}")

            # Read JSONL to show what would be migrated
            all_faqs = list(jsonl_repo.get_all_faqs())
            logger.info(f"Found {len(all_faqs)} FAQs that would be migrated")

            logger.info("=" * 80)
            logger.info("DRY RUN COMPLETE - No changes made")
            logger.info("=" * 80)
            sys.exit(0)

        # Create SQLite repository (creates/opens database)
        sqlite_repo = FAQRepositorySQLite(str(db_path))

        if args.rollback:
            # ROLLBACK MODE: SQLite → JSONL
            logger.warning("=" * 80)
            logger.warning("DISASTER RECOVERY: Rolling back from SQLite to JSONL")
            logger.warning("This will OVERWRITE the JSONL file!")
            logger.warning("=" * 80)

            response = input("Are you sure you want to proceed? (yes/NO): ")
            if response.lower() != "yes":
                logger.info("Rollback cancelled by user")
                sys.exit(0)

            # Create backup before rollback
            backup_path = create_backup(jsonl_path)

            # Perform rollback
            stats = rollback_sqlite_to_jsonl(sqlite_repo, jsonl_repo)

            logger.info("=" * 80)
            logger.info("ROLLBACK COMPLETE")
            logger.info(f"Total FAQs: {stats['total']}")
            logger.info(f"Rolled back: {stats['rolled_back']}")
            logger.info(f"Errors: {stats['errors']}")
            logger.info(f"Duration: {stats['duration_seconds']}s")
            logger.info(f"Backup: {backup_path}")
            logger.info("=" * 80)

            sys.exit(0)

        if args.verify_only:
            # VERIFY MODE: Check migration integrity
            logger.info("Verifying migration integrity...")
            success = verify_migration(jsonl_repo, sqlite_repo)

            if success:
                logger.info("=" * 80)
                logger.info("VERIFICATION PASSED")
                logger.info("=" * 80)
                sys.exit(0)
            else:
                logger.error("=" * 80)
                logger.error("VERIFICATION FAILED")
                logger.error("=" * 80)
                sys.exit(1)

        # MIGRATION MODE
        # Create backup before migration
        backup_path = create_backup(jsonl_path)

        # Perform migration
        logger.info("Starting migration...")
        stats = migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)

        logger.info("=" * 80)
        logger.info("MIGRATION COMPLETE")
        logger.info(f"Total FAQs: {stats['total']}")
        logger.info(f"Migrated: {stats['migrated']}")
        logger.info(f"Errors: {stats['errors']}")
        logger.info(f"Duration: {stats['duration_seconds']}s")
        logger.info("=" * 80)

        # Verify migration
        logger.info("Verifying migration integrity...")
        success = verify_migration(jsonl_repo, sqlite_repo)

        if not success:
            logger.error("Migration verification failed!")
            sys.exit(1)

        logger.info("=" * 80)
        logger.info("VERIFICATION PASSED")
        logger.info("=" * 80)

        if args.dry_run:
            logger.info("DRY RUN COMPLETE - No changes committed")
        else:
            logger.info(f"Backup created: {backup_path}")
            logger.info("")
            logger.info("Next steps:")
            logger.info("1. Update .env to set USE_SQLITE_FAQ_STORAGE=true")
            logger.info("2. Restart API service")
            logger.info("3. Test FAQ operations via admin interface")
            logger.info("4. Monitor for errors in production logs")
            logger.info("")
            logger.info(
                "To rollback: python -m app.scripts.migrate_to_sqlite --rollback"
            )

        sys.exit(0)

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Script to migrate legacy feedback files to the current month-based convention.

This script:
1. Reads all feedback from legacy files (day-based and root feedback.jsonl)
2. Sorts them by timestamp
3. Writes them to appropriate month-based files (feedback_YYYY-MM.jsonl)
4. Backs up original files to a subdirectory

Usage:
    python migrate_feedback_files.py
"""

import asyncio
import logging
import os
import sys
from pprint import pprint

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import get_settings
from app.services.simplified_rag_service import SimplifiedRAGService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Main function to migrate feedback files."""
    logger.info("Starting feedback file migration")

    try:
        # Initialize settings and RAG service
        settings = get_settings()
        service = SimplifiedRAGService(settings)

        # Run the migration
        logger.info("Migrating legacy feedback files to month-based convention")
        stats = service.migrate_legacy_feedback()

        # Print migration statistics
        logger.info("Migration complete!")
        logger.info(f"Total entries migrated: {stats['total_entries_migrated']}")
        logger.info(f"Legacy files processed: {stats['legacy_files_processed']}")
        
        if stats['entries_by_month']:
            logger.info("Entries by month:")
            for month, count in sorted(stats['entries_by_month'].items()):
                logger.info(f"  {month}: {count} entries")
        
        if stats['backed_up_files']:
            logger.info("Backed up files:")
            for file in stats['backed_up_files']:
                logger.info(f"  {file}")
        
        # Get data directory for informational purposes
        feedback_dir = os.path.join(settings.DATA_DIR, 'feedback')
        backup_dir = os.path.join(feedback_dir, 'legacy_backup')
        
        logger.info(f"Legacy files backed up to: {backup_dir}")
        logger.info(f"New month-based files stored in: {feedback_dir}")
        logger.info("Migration process completed successfully")
    except Exception as e:
        logger.error(f"Error migrating feedback files: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 
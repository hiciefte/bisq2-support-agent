"""
Migration script to import JSONL feedback data into SQLite database.

This script:
1. Creates the SQLite database with schema
2. Imports all JSONL feedback files
3. Preserves conversation history and metadata
4. Handles deduplication (skips existing message_ids)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.db.database import get_database  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class FeedbackMigration:
    """Handles migration of feedback from JSONL to SQLite."""

    def __init__(self, db_path: str, feedback_dir: str):
        """
        Initialize migration.

        Args:
            db_path: Path to SQLite database file
            feedback_dir: Directory containing JSONL feedback files
        """
        self.db = get_database()
        self.db.initialize(db_path)
        self.feedback_dir = Path(feedback_dir)
        self.stats = {
            "total_files": 0,
            "total_entries": 0,
            "imported": 0,
            "skipped_duplicates": 0,
            "errors": 0,
        }

    def migrate(self, dry_run: bool = False) -> Dict[str, int]:
        """
        Run the migration.

        Args:
            dry_run: If True, only simulate migration without writing to database

        Returns:
            Dictionary with migration statistics
        """
        if not self.feedback_dir.exists():
            logger.error(f"Feedback directory not found: {self.feedback_dir}")
            return self.stats

        # Find all feedback JSONL files
        feedback_files = sorted(self.feedback_dir.glob("feedback_*.jsonl"))
        self.stats["total_files"] = len(feedback_files)

        logger.info(f"Found {len(feedback_files)} feedback files")

        for feedback_file in feedback_files:
            logger.info(f"Processing: {feedback_file.name}")
            self._process_file(feedback_file, dry_run)

        logger.info("Migration complete!")
        logger.info(f"Statistics: {self.stats}")
        return self.stats

    def _process_file(self, file_path: Path, dry_run: bool) -> None:
        """
        Process a single JSONL feedback file.

        Args:
            file_path: Path to JSONL file
            dry_run: If True, simulate without writing
        """
        try:
            with open(file_path, "r") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    self.stats["total_entries"] += 1

                    try:
                        entry = json.loads(line)
                        self._import_entry(entry, dry_run)
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"JSON parse error in {file_path.name} line {line_num}: {e}"
                        )
                        self.stats["errors"] += 1
                    except Exception as e:
                        logger.error(
                            f"Error processing entry in {file_path.name} line {line_num}: {e}"
                        )
                        self.stats["errors"] += 1

        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            self.stats["errors"] += 1

    def _import_entry(self, entry: Dict[str, Any], dry_run: bool) -> None:
        """
        Import a single feedback entry into SQLite.

        Args:
            entry: Feedback entry dictionary
            dry_run: If True, simulate without writing
        """
        message_id = entry.get("message_id")
        if not message_id:
            logger.warning("Feedback entry missing message_id, skipping")
            self.stats["errors"] += 1
            return

        if dry_run:
            logger.info(f"[DRY RUN] Would import message_id: {message_id}")
            self.stats["imported"] += 1
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Check if entry already exists
            cursor.execute(
                "SELECT id FROM feedback WHERE message_id = ?", (message_id,)
            )
            existing = cursor.fetchone()

            if existing:
                logger.debug(f"Skipping duplicate message_id: {message_id}")
                self.stats["skipped_duplicates"] += 1
                return

            # Insert main feedback entry
            cursor.execute(
                """
                INSERT INTO feedback (message_id, question, answer, rating, explanation, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    entry.get("question", ""),
                    entry.get("answer", ""),
                    entry.get("rating", 0),
                    entry.get("explanation"),
                    entry.get("timestamp", datetime.now().isoformat()),
                ),
            )
            feedback_id = cursor.lastrowid

            # Insert conversation history
            conversation_history = entry.get("conversation_history", [])
            for position, message in enumerate(conversation_history):
                cursor.execute(
                    """
                    INSERT INTO conversation_messages (feedback_id, role, content, position)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        feedback_id,
                        message.get("role", "user"),
                        message.get("content", ""),
                        position,
                    ),
                )

            # Insert metadata
            metadata = entry.get("metadata", {})
            if isinstance(metadata, dict):
                for key, value in metadata.items():
                    # Convert complex values to JSON strings
                    if not isinstance(value, str):
                        value = json.dumps(value)

                    cursor.execute(
                        """
                        INSERT INTO feedback_metadata (feedback_id, key, value)
                        VALUES (?, ?, ?)
                        """,
                        (feedback_id, key, value),
                    )

                # Extract issues from metadata
                issues = metadata.get("issues", [])
                if isinstance(issues, list):
                    for issue in issues:
                        if issue:  # Skip empty strings
                            cursor.execute(
                                """
                                INSERT INTO feedback_issues (feedback_id, issue_type)
                                VALUES (?, ?)
                                """,
                                (feedback_id, issue),
                            )

            conn.commit()
            self.stats["imported"] += 1
            logger.debug(f"Imported message_id: {message_id}")


def main():
    """Main entry point for migration script."""
    # Get default paths from environment or use container defaults
    data_dir = os.environ.get("DATA_DIR", "/data")
    default_db_path = os.path.join(data_dir, "feedback.db")
    default_feedback_dir = os.path.join(data_dir, "feedback")

    parser = argparse.ArgumentParser(
        description="Migrate feedback from JSONL to SQLite"
    )
    parser.add_argument(
        "--db-path",
        default=default_db_path,
        help=f"Path to SQLite database file (default: {default_db_path})",
    )
    parser.add_argument(
        "--feedback-dir",
        default=default_feedback_dir,
        help=f"Directory containing JSONL feedback files (default: {default_feedback_dir})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without writing to database",
    )

    args = parser.parse_args()

    logger.info("Starting feedback migration to SQLite")
    logger.info(f"Database path: {args.db_path}")
    logger.info(f"Feedback directory: {args.feedback_dir}")
    logger.info(f"Dry run: {args.dry_run}")

    migration = FeedbackMigration(args.db_path, args.feedback_dir)
    stats = migration.migrate(dry_run=args.dry_run)

    print("\n" + "=" * 50)
    print("Migration Statistics:")
    print("=" * 50)
    for key, value in stats.items():
        print(f"{key:25}: {value}")
    print("=" * 50)

    if stats["errors"] > 0:
        logger.warning(f"Migration completed with {stats['errors']} errors")
        sys.exit(1)
    else:
        logger.info("Migration completed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()

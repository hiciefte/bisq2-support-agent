"""
Database migration runner for applying schema updates.

This script applies SQL migrations from the migrations/ directory
to the feedback database, tracking which migrations have been applied.
"""

import logging
import sqlite3
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def get_applied_migrations(conn: sqlite3.Connection) -> List[str]:
    """Get list of already applied migrations."""
    cursor = conn.cursor()

    # Create migrations table if it doesn't exist
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name TEXT UNIQUE NOT NULL,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    # Get applied migrations
    cursor.execute("SELECT migration_name FROM schema_migrations ORDER BY id")
    return [row[0] for row in cursor.fetchall()]


def apply_migration(conn: sqlite3.Connection, migration_name: str, sql: str) -> None:
    """Apply a single migration to the database."""
    cursor = conn.cursor()

    try:
        # Apply the migration SQL
        cursor.executescript(sql)

        # Record migration as applied
        cursor.execute(
            "INSERT INTO schema_migrations (migration_name) VALUES (?)",
            (migration_name,),
        )

        conn.commit()
        logger.info(f"Successfully applied migration: {migration_name}")

    except Exception as e:
        conn.rollback()
        logger.exception(f"Failed to apply migration {migration_name}")
        raise


def run_migrations(db_path: str) -> None:
    """Run all pending migrations on the database."""
    db_file = Path(db_path)

    if not db_file.exists():
        logger.info(f"Database does not exist at {db_path}, skipping migrations")
        return

    logger.info(f"Running migrations on database: {db_path}")

    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        logger.info("No migrations directory found, skipping")
        return

    # Get all migration files
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        logger.info("No migration files found")
        return

    # Connect to database
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        # Get already applied migrations
        applied = get_applied_migrations(conn)
        logger.info(f"Already applied migrations: {applied}")

        # Apply pending migrations
        pending_count = 0
        for migration_file in migration_files:
            migration_name = migration_file.name

            if migration_name in applied:
                logger.debug(f"Skipping already applied migration: {migration_name}")
                continue

            logger.info(f"Applying migration: {migration_name}")

            # Read migration SQL
            with open(migration_file, "r") as f:
                migration_sql = f.read()

            # Apply the migration
            apply_migration(conn, migration_name, migration_sql)
            pending_count += 1

        if pending_count == 0:
            logger.info("No pending migrations to apply")
        else:
            logger.info(f"Successfully applied {pending_count} migration(s)")

    finally:
        conn.close()


if __name__ == "__main__":
    # Run migrations on default database path
    import os

    data_dir = os.environ.get("DATA_DIR", "api/data")
    db_path = os.path.join(data_dir, "feedback.db")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    run_migrations(db_path)

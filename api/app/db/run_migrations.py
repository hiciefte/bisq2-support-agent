"""
Database migration runner for applying schema updates.

This script applies SQL migrations from the migrations/ directory
to the feedback database, tracking which migrations have been applied.

Features:
- Migration tracking with metadata (checksum, duration, status)
- Validation before applying migrations
- Rollback support for failed migrations
- Idempotent execution
"""

import hashlib
import logging
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

from app.db.migration_validator import MigrationValidationError, validate_migration_sql

logger = logging.getLogger(__name__)


def calculate_checksum(file_path: Path) -> str:
    """
    Calculate SHA256 checksum of migration file.

    Args:
        file_path: Path to migration file

    Returns:
        Hexadecimal checksum string
    """
    with open(file_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _upgrade_schema_migrations_table(conn: sqlite3.Connection) -> None:
    """
    Upgrade schema_migrations table to include new metadata columns.

    This is safe to run multiple times (uses ALTER TABLE IF NOT EXISTS pattern).

    Args:
        conn: Database connection
    """
    cursor = conn.cursor()

    # Check what columns exist
    cursor.execute("PRAGMA table_info(schema_migrations)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    # Add new columns if they don't exist
    new_columns = [
        ("checksum", "TEXT"),
        ("execution_time_ms", "INTEGER"),
        ("status", "TEXT DEFAULT 'success'"),
        ("error_message", "TEXT"),
        ("down_sql", "TEXT"),
    ]

    for column_name, column_def in new_columns:
        if column_name not in existing_columns:
            try:
                cursor.execute(
                    f"ALTER TABLE schema_migrations ADD COLUMN {column_name} {column_def}"
                )
                logger.info(f"Added column {column_name} to schema_migrations table")
            except sqlite3.OperationalError as e:
                logger.debug(f"Column {column_name} may already exist: {e}")

    conn.commit()


def get_applied_migrations(conn: sqlite3.Connection) -> List[str]:
    """
    Get list of already applied migrations.

    Args:
        conn: Database connection

    Returns:
        List of applied migration names
    """
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

    # Upgrade table to include metadata columns
    _upgrade_schema_migrations_table(conn)

    # Get applied migrations
    cursor.execute("SELECT migration_name FROM schema_migrations ORDER BY id")
    return [row[0] for row in cursor.fetchall()]


def validate_checksum(
    conn: sqlite3.Connection, migration_name: str, current_checksum: str
) -> None:
    """
    Validate that migration file hasn't been modified after deployment.

    Args:
        conn: Database connection
        migration_name: Name of migration
        current_checksum: Current file checksum

    Raises:
        ValueError: If checksums don't match
    """
    cursor = conn.cursor()

    cursor.execute(
        "SELECT checksum FROM schema_migrations WHERE migration_name = ?",
        (migration_name,),
    )
    row = cursor.fetchone()

    if row and row[0]:
        stored_checksum = row[0]
        if stored_checksum != current_checksum:
            raise ValueError(
                f"Migration {migration_name} has been modified after deployment!\n"
                f"Expected checksum: {stored_checksum}\n"
                f"Current checksum: {current_checksum}\n"
                f"This is a security concern - migrations should never be modified after application."
            )


def apply_migration(
    conn: sqlite3.Connection,
    migration_name: str,
    up_sql: str,
    down_sql: Optional[str],
    checksum: str,
) -> None:
    """
    Apply a single migration to the database.

    Args:
        conn: Database connection
        migration_name: Name of migration file
        up_sql: SQL to apply (up migration)
        down_sql: SQL for rollback (down migration), if available
        checksum: SHA256 checksum of migration file

    Raises:
        Exception: If migration fails
    """
    cursor = conn.cursor()
    start_time = time.time()

    try:
        # Validate migration SQL before applying
        logger.info(f"Validating migration: {migration_name}")
        try:
            validate_migration_sql(up_sql, conn)
        except MigrationValidationError as e:
            logger.error(f"Migration validation failed: {e}")
            raise

        # Apply the migration SQL
        logger.info(f"Applying migration: {migration_name}")
        cursor.executescript(up_sql)

        # Calculate execution time
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Record migration as applied with metadata
        cursor.execute(
            """
            INSERT INTO schema_migrations
            (migration_name, checksum, execution_time_ms, status, down_sql)
            VALUES (?, ?, ?, ?, ?)
            """,
            (migration_name, checksum, execution_time_ms, "success", down_sql),
        )

        conn.commit()
        logger.info(
            f"Successfully applied migration: {migration_name} ({execution_time_ms}ms)"
        )

    except Exception as e:
        conn.rollback()

        # Record failed migration
        try:
            execution_time_ms = int((time.time() - start_time) * 1000)
            cursor.execute(
                """
                INSERT OR REPLACE INTO schema_migrations
                (migration_name, checksum, execution_time_ms, status, error_message, down_sql)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    migration_name,
                    checksum,
                    execution_time_ms,
                    "failed",
                    str(e),
                    down_sql,
                ),
            )
            conn.commit()
        except Exception as log_error:
            logger.error(f"Failed to log migration failure: {log_error}")

        logger.exception(f"Failed to apply migration {migration_name}")
        raise


def rollback_migration(db_path: str, migration_name: str, force: bool = False) -> None:
    """
    Rollback a specific migration.

    Args:
        db_path: Path to database file
        migration_name: Name of migration to roll back
        force: If True, remove from tracking even if down SQL unavailable

    Raises:
        ValueError: If migration not found or no rollback SQL available
        Exception: If rollback fails
    """
    db_file = Path(db_path)

    if not db_file.exists():
        raise ValueError(f"Database does not exist: {db_path}")

    logger.info(f"Rolling back migration: {migration_name}")

    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        cursor = conn.cursor()

        # Get down SQL from schema_migrations
        cursor.execute(
            "SELECT down_sql, status FROM schema_migrations WHERE migration_name = ?",
            (migration_name,),
        )
        row = cursor.fetchone()

        if not row:
            raise ValueError(f"Migration {migration_name} not found in tracking table")

        down_sql, status = row

        if not down_sql:
            if force:
                logger.warning(
                    f"No down SQL for {migration_name}, removing from tracking (--force)"
                )
                cursor.execute(
                    "DELETE FROM schema_migrations WHERE migration_name = ?",
                    (migration_name,),
                )
                conn.commit()
                return
            else:
                raise ValueError(
                    f"No rollback SQL available for {migration_name}. "
                    f"Check {migration_name}_down.sql file. "
                    f"Use --force to remove from tracking without executing rollback."
                )

        # Execute down migration
        logger.info(f"Executing rollback SQL for {migration_name}")
        cursor.executescript(down_sql)

        # Remove from applied migrations
        cursor.execute(
            "DELETE FROM schema_migrations WHERE migration_name = ?",
            (migration_name,),
        )

        conn.commit()
        logger.info(f"Successfully rolled back migration: {migration_name}")

    except Exception:
        conn.rollback()
        logger.exception(f"Failed to rollback migration: {migration_name}")
        raise
    finally:
        conn.close()


def run_migrations(db_path: str, validate_only: bool = False) -> None:
    """
    Run all pending migrations on the database.

    Args:
        db_path: Path to database file
        validate_only: If True, only validate migrations without applying

    Raises:
        Exception: If any migration fails
    """
    db_file = Path(db_path)

    if not db_file.exists():
        logger.info(f"Database does not exist at {db_path}, skipping migrations")
        return

    logger.info(
        f"{'Validating' if validate_only else 'Running'} migrations on database: {db_path}"
    )

    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        logger.info("No migrations directory found, skipping")
        return

    # Get all migration files (exclude _down.sql files)
    migration_files = sorted(
        [f for f in migrations_dir.glob("*.sql") if not f.name.endswith("_down.sql")]
    )

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

            # Skip _down.sql files
            if migration_name.endswith("_down.sql"):
                continue

            # Calculate checksum
            checksum = calculate_checksum(migration_file)

            # If already applied, validate checksum
            if migration_name in applied:
                logger.debug(f"Checking migration: {migration_name}")
                validate_checksum(conn, migration_name, checksum)
                continue

            logger.info(f"Found pending migration: {migration_name}")

            # Read up migration SQL
            with open(migration_file, "r") as f:
                up_sql = f.read()

            # Look for corresponding down migration
            down_file = migration_file.parent / f"{migration_file.stem}_down.sql"
            down_sql = None
            if down_file.exists():
                with open(down_file, "r") as f:
                    down_sql = f.read()
                logger.debug(f"Found down migration: {down_file.name}")
            else:
                logger.warning(f"No down migration found for {migration_name}")

            if validate_only:
                # Just validate without applying
                logger.info(f"Validating: {migration_name}")
                try:
                    validate_migration_sql(up_sql, conn)
                    logger.info(f"✓ Validation passed: {migration_name}")
                except MigrationValidationError as e:
                    logger.error(f"✗ Validation failed: {migration_name} - {e}")
                    raise
            else:
                # Apply the migration
                apply_migration(conn, migration_name, up_sql, down_sql, checksum)
                pending_count += 1

        if validate_only:
            logger.info("All migrations validated successfully")
        elif pending_count == 0:
            logger.info("No pending migrations to apply")
        else:
            logger.info(f"Successfully applied {pending_count} migration(s)")

    finally:
        conn.close()


if __name__ == "__main__":
    # Run migrations on default database path
    import os
    import sys

    data_dir = os.environ.get("DATA_DIR", "api/data")
    db_path = os.path.join(data_dir, "feedback.db")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Support command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "validate":
            run_migrations(db_path, validate_only=True)
        elif command == "rollback" and len(sys.argv) > 2:
            migration_name = sys.argv[2]
            force = "--force" in sys.argv
            rollback_migration(db_path, migration_name, force=force)
        else:
            print("Usage:")
            print("  python run_migrations.py              # Apply pending migrations")
            print("  python run_migrations.py validate     # Validate without applying")
            print(
                "  python run_migrations.py rollback <name> [--force]  # Rollback migration"
            )
            sys.exit(1)
    else:
        run_migrations(db_path)

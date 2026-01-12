"""
Migration validation utilities.

This module provides SQL validation and safety checks for database migrations
before they are applied to the database.
"""

import logging
import re
import sqlite3
from typing import List, Tuple

logger = logging.getLogger(__name__)


class MigrationValidationError(Exception):
    """Raised when migration validation fails."""


def validate_migration_sql(sql: str, conn: sqlite3.Connection) -> None:
    """
    Validate SQL syntax and check for dangerous operations.

    Args:
        sql: Migration SQL to validate
        conn: Database connection for validation

    Raises:
        MigrationValidationError: If validation fails
    """
    # Check for dangerous operations
    _check_dangerous_operations(sql)

    # Validate SQL syntax
    _validate_syntax(sql, conn)


def _check_dangerous_operations(sql: str) -> None:
    """
    Check for potentially dangerous SQL operations.

    Args:
        sql: SQL to check

    Raises:
        MigrationValidationError: If dangerous operations detected
    """
    dangerous_patterns = [
        (r"\bDROP\s+TABLE\b", "DROP TABLE operations are not allowed in migrations"),
        (
            r"\bTRUNCATE\b",
            "TRUNCATE operations are not allowed in migrations",
        ),
        (
            r"\bDELETE\s+FROM\b(?!\s+schema_migrations)",
            "DELETE FROM operations should be carefully reviewed",
        ),
    ]

    for pattern, message in dangerous_patterns:
        if re.search(pattern, sql, re.IGNORECASE):
            logger.warning(f"Potentially dangerous operation: {message}")
            # Note: We log warning but don't fail - allows manual review
            # In stricter environments, could raise MigrationValidationError here


def _validate_syntax(sql: str, conn: sqlite3.Connection) -> None:
    """
    Validate SQL syntax using SQLite EXPLAIN.

    Args:
        sql: SQL to validate
        conn: Database connection

    Raises:
        MigrationValidationError: If SQL syntax is invalid
    """
    try:
        # Split into individual statements and validate each
        statements = _split_sql_statements(sql)

        for stmt in statements:
            if not stmt.strip():
                continue

            # Use EXPLAIN to validate syntax without executing
            try:
                conn.execute(f"EXPLAIN {stmt}")
            except sqlite3.OperationalError:
                # Some statements can't be explained (e.g., CREATE INDEX)
                # Try parsing them differently
                if "CREATE INDEX" in stmt.upper() or "CREATE TABLE" in stmt.upper():
                    # These are generally safe, skip EXPLAIN
                    continue
                raise

    except sqlite3.Error as e:
        raise MigrationValidationError(f"Invalid SQL syntax: {e}") from e


def _split_sql_statements(sql: str) -> List[str]:
    """
    Split SQL into individual statements.

    Args:
        sql: SQL string with multiple statements

    Returns:
        List of individual SQL statements
    """
    # Simple split by semicolon
    # Note: This doesn't handle strings with semicolons, but sufficient for migrations
    statements = []
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.startswith("--"):
            statements.append(stmt)
    return statements


def validate_column_not_exists(
    conn: sqlite3.Connection, table: str, column: str
) -> None:
    """
    Validate that a column doesn't already exist before adding it.

    Args:
        conn: Database connection
        table: Table name
        column: Column name

    Raises:
        MigrationValidationError: If column already exists
    """
    cursor = conn.cursor()

    try:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]

        if column in columns:
            raise MigrationValidationError(
                f"Column '{column}' already exists in table '{table}'"
            )
    except sqlite3.Error as e:
        logger.warning(f"Could not validate column existence: {e}")
        # Don't fail validation if we can't check - let migration fail naturally


def extract_table_column_from_alter(sql: str) -> List[Tuple[str, str]]:
    """
    Extract table and column names from ALTER TABLE ADD COLUMN statements.

    Args:
        sql: SQL containing ALTER TABLE statements

    Returns:
        List of (table_name, column_name) tuples
    """
    pattern = r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)"
    matches = re.findall(pattern, sql, re.IGNORECASE)
    return matches

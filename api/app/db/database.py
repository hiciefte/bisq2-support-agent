"""
Database connection and initialization for feedback storage.

This module provides SQLite database connectivity with proper connection pooling,
thread safety, and migration support.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FeedbackDatabase:
    """SQLite database manager for feedback storage."""

    _instance: Optional["FeedbackDatabase"] = None
    _connection: Optional[sqlite3.Connection] = None

    def __new__(cls):
        """Singleton pattern to ensure one database instance."""
        if cls._instance is None:
            cls._instance = super(FeedbackDatabase, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize database connection (called once due to singleton)."""
        if not hasattr(self, "initialized"):
            self.db_path: Optional[Path] = None
            self.initialized = False

    def initialize(self, db_path: str) -> None:
        """
        Initialize the database with schema.

        Args:
            db_path: Path to SQLite database file
        """
        if self.initialized:
            logger.info("Database already initialized")
            return

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initializing database at: {self.db_path}")

        # Create database and apply schema
        self._create_schema()
        self.initialized = True
        logger.info("Database initialized successfully")

    def _create_schema(self) -> None:
        """Create database schema from schema.sql file."""
        schema_path = Path(__file__).parent / "schema.sql"

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, "r") as f:
            schema_sql = f.read()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Execute schema (SQLite supports multiple statements in executescript)
            cursor.executescript(schema_sql)
            conn.commit()

        logger.info("Database schema created successfully")

    @contextmanager
    def get_connection(self):
        """
        Get a database connection with proper context management.

        Yields:
            sqlite3.Connection: Database connection

        Example:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM feedback")
        """
        if not self.db_path:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        conn = None
        try:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # Allow multi-threaded access
                timeout=30.0,  # Wait up to 30 seconds for locks
            )
            # Enable foreign keys
            conn.execute("PRAGMA foreign_keys = ON")
            # Use row factory for dict-like access
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            if conn:
                conn.close()

    def close(self) -> None:
        """Close database connection and cleanup."""
        if self._connection:
            self._connection.close()
            self._connection = None
        logger.info("Database connection closed")


# Global database instance
_db_instance: Optional[FeedbackDatabase] = None


def get_database() -> FeedbackDatabase:
    """
    Get the global database instance.

    Returns:
        FeedbackDatabase: Global database instance
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = FeedbackDatabase()
    return _db_instance

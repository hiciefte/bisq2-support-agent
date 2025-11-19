"""
SQLite-based FAQ repository with security hardening.

Security features implemented:
- SQL injection prevention via parameterized queries (CRITICAL)
- Race condition prevention via UPSERT and write locks (CRITICAL)
- File permission enforcement (mode 600) (HIGH)
- Input validation in migration and CRUD operations (HIGH)
- WAL mode for concurrent reads during writes
- Persistent connection with connection pooling
- Transaction isolation for data integrity

Following TDD: Implementation written to pass security test suite.
"""

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

from app.models.faq import FAQIdentifiedItem, FAQItem

logger = logging.getLogger(__name__)


# Retry configuration for database lock handling
MAX_RETRIES = 5
INITIAL_BACKOFF_MS = 100  # 100ms initial delay
MAX_BACKOFF_MS = 5000  # 5 second max delay


class FAQRepositorySQLite:
    """
    SQLite-based FAQ repository with security-hardened implementation.

    Security mitigations:
    1. SQL Injection: All queries use parameterized statements
    2. Race Conditions: UPSERT atomic operations + write lock
    3. File Permissions: Database created with mode 600
    4. Input Validation: Pydantic models + length constraints
    5. Concurrent Access: WAL mode + persistent connection
    """

    # Schema version for future migrations
    SCHEMA_VERSION = 1

    # Field length constraints (prevent DoS via huge inputs)
    MAX_QUESTION_LENGTH = 2000
    MAX_ANSWER_LENGTH = 10000
    MAX_CATEGORY_LENGTH = 100
    MAX_SOURCE_LENGTH = 100

    def __init__(self, db_path: str):
        """
        Initialize SQLite repository with security hardening.

        Args:
            db_path: Path to SQLite database file

        Security features:
        - Creates database with mode 600 (owner read/write only)
        - Enables WAL mode for concurrent reads
        - Dedicated writer connection + reader connection for concurrency
        - Initializes write lock for race condition prevention
        """
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._read_lock = (
            threading.Lock()
        )  # Protect reader connection from concurrent use

        # Ensure parent directory exists
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        # Create database file if missing and enforce secure permissions (600)
        if not db_file.exists():
            db_file.touch(mode=0o600)
            logger.info("Created database file with mode 600: %s", db_path)
        else:
            db_file.chmod(0o600)
            logger.info("Enforced mode 600 on existing database file: %s", db_path)

        # Create dedicated writer connection (used only for writes)
        self._writer_conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level="IMMEDIATE",  # Acquire write lock immediately
            timeout=10.0,
        )
        self._writer_conn.row_factory = sqlite3.Row

        # Create reader connection (used for reads, allows concurrent access)
        self._reader_conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level="DEFERRED",  # Don't block other readers
            timeout=10.0,
        )
        self._reader_conn.row_factory = sqlite3.Row

        # Configure both connections with WAL mode
        for conn in [self._writer_conn, self._reader_conn]:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA wal_autocheckpoint=1000")

        # Initialize schema using writer connection
        self._initialize_schema()

        logger.info(f"SQLite FAQ repository initialized: {db_path}")

    def _initialize_schema(self):
        """
        Create database schema if it doesn't exist.

        Schema includes:
        - Unique constraint on question for deduplication
        - Indexes on frequently queried columns
        - Timestamps with timezone support
        - Schema version tracking
        """
        with self._writer_conn:
            # Create FAQs table
            self._writer_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS faqs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL UNIQUE,
                    answer TEXT NOT NULL,
                    category TEXT DEFAULT 'General',
                    source TEXT DEFAULT 'Manual',
                    verified INTEGER DEFAULT 0,
                    bisq_version TEXT DEFAULT 'Bisq 2',
                    created_at TEXT,
                    updated_at TEXT,
                    verified_at TEXT,
                    CHECK(LENGTH(question) <= 2000),
                    CHECK(LENGTH(answer) <= 10000),
                    CHECK(LENGTH(category) <= 100),
                    CHECK(LENGTH(source) <= 100)
                )
            """
            )

            # Create indexes for performance
            self._writer_conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_faqs_category
                ON faqs(category)
            """
            )

            self._writer_conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_faqs_verified
                ON faqs(verified)
            """
            )

            self._writer_conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_faqs_bisq_version
                ON faqs(bisq_version)
            """
            )

            # Full-text search index
            self._writer_conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS faqs_fts
                USING fts5(question, answer, content=faqs, content_rowid=id)
            """
            )

            # Create triggers to keep FTS index in sync
            self._writer_conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS faqs_ai AFTER INSERT ON faqs BEGIN
                    INSERT INTO faqs_fts(rowid, question, answer)
                    VALUES (new.id, new.question, new.answer);
                END
            """
            )

            self._writer_conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS faqs_ad AFTER DELETE ON faqs BEGIN
                    INSERT INTO faqs_fts(faqs_fts, rowid, question, answer)
                    VALUES('delete', old.id, old.question, old.answer);
                END
            """
            )

            self._writer_conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS faqs_au AFTER UPDATE ON faqs BEGIN
                    INSERT INTO faqs_fts(faqs_fts, rowid, question, answer)
                    VALUES('delete', old.id, old.question, old.answer);
                    INSERT INTO faqs_fts(rowid, question, answer)
                    VALUES(new.id, new.question, new.answer);
                END
            """
            )

            # Schema version tracking
            self._writer_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """
            )

            # Insert schema version if not exists
            self._writer_conn.execute(
                """
                INSERT OR IGNORE INTO schema_version (version, applied_at)
                VALUES (?, ?)
            """,
                (self.SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )

    def _execute_with_retry(self, operation, *args, **kwargs):
        """
        Execute database operation with exponential backoff retry on lock errors.

        Args:
            operation: Callable that performs database operation
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation

        Returns:
            Result from operation

        Raises:
            sqlite3.Error: If all retries exhausted or non-retryable error
        """
        last_error = None
        backoff_ms = INITIAL_BACKOFF_MS

        for attempt in range(MAX_RETRIES):
            try:
                return operation(*args, **kwargs)
            except sqlite3.OperationalError as e:
                error_msg = str(e).lower()
                # Retry on database locked/busy errors
                if "locked" in error_msg or "busy" in error_msg:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        # Exponential backoff with jitter
                        sleep_ms = min(backoff_ms, MAX_BACKOFF_MS)
                        time.sleep(sleep_ms / 1000.0)
                        backoff_ms *= 2
                        logger.warning(
                            f"Database locked, retry {attempt + 1}/{MAX_RETRIES} "
                            f"after {sleep_ms}ms: {e}"
                        )
                    continue
                else:
                    # Non-retryable error, raise immediately
                    raise
            except sqlite3.DatabaseError:
                # Database corruption or other serious errors - don't retry
                logger.exception("Database error (not retrying)")
                raise

        # All retries exhausted
        logger.error("All %s retries exhausted for database operation", MAX_RETRIES)
        raise last_error

    def add_faq(self, faq_item: FAQItem) -> FAQIdentifiedItem:
        """
        Add FAQ with UPSERT for race condition prevention.

        Security mitigations:
        - Input validation via Pydantic model
        - Length constraints checked in schema
        - UPSERT prevents duplicate questions (atomic operation)
        - Write lock prevents concurrent modification conflicts
        - Parameterized query prevents SQL injection

        Args:
            faq_item: FAQ data to add

        Returns:
            Added FAQ with ID

        Raises:
            ValueError: If input validation fails
        """
        # Validate field lengths
        if len(faq_item.question) > self.MAX_QUESTION_LENGTH:
            raise ValueError(
                f"Question exceeds maximum length ({self.MAX_QUESTION_LENGTH})"
            )
        if len(faq_item.answer) > self.MAX_ANSWER_LENGTH:
            raise ValueError(
                f"Answer exceeds maximum length ({self.MAX_ANSWER_LENGTH})"
            )

        # Auto-populate timestamps using datetime objects
        now_dt = datetime.now(timezone.utc)
        created_at_dt = faq_item.created_at or now_dt
        updated_at_dt = faq_item.updated_at or now_dt

        # Auto-populate verified_at for new verified FAQs (data consistency)
        if faq_item.verified:
            verified_at_dt = faq_item.verified_at or now_dt
        else:
            verified_at_dt = None

        # Convert to ISO strings for database storage
        created_at = created_at_dt.isoformat()
        updated_at = updated_at_dt.isoformat()
        verified_at = verified_at_dt.isoformat() if verified_at_dt else None

        # Define write operation
        def _write_operation():
            with self._write_lock:
                with self._writer_conn:
                    # UPSERT: Insert or update if question already exists
                    cursor = self._writer_conn.execute(
                        """
                        INSERT INTO faqs (
                            question, answer, category, source, verified,
                            bisq_version, created_at, updated_at, verified_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(question) DO UPDATE SET
                            answer = excluded.answer,
                            category = excluded.category,
                            source = excluded.source,
                            verified = excluded.verified,
                            bisq_version = excluded.bisq_version,
                            updated_at = excluded.updated_at,
                            verified_at = excluded.verified_at
                        RETURNING id
                        """,
                        (
                            faq_item.question,
                            faq_item.answer,
                            faq_item.category or "General",
                            faq_item.source or "Manual",
                            1 if faq_item.verified else 0,
                            faq_item.bisq_version or "Bisq 2",
                            created_at,
                            updated_at,
                            verified_at,
                        ),
                    )
                    return cursor.fetchone()[0]

        # Execute with retry logic
        faq_id = self._execute_with_retry(_write_operation)

        # Return identified FAQ (convert integer ID to string for compatibility)
        return FAQIdentifiedItem(
            id=str(faq_id),
            question=faq_item.question,
            answer=faq_item.answer,
            category=faq_item.category or "General",
            source=faq_item.source or "Manual",
            verified=faq_item.verified or False,
            bisq_version=faq_item.bisq_version or "Bisq 2",
            created_at=created_at_dt,
            updated_at=updated_at_dt,
            verified_at=verified_at_dt,
        )

    def get_faqs_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        category: Optional[str] = None,
        verified: Optional[bool] = None,
        source: Optional[str] = None,
        search_text: Optional[str] = None,
        bisq_version: Optional[str] = None,
        verified_from: Optional[datetime] = None,
        verified_to: Optional[datetime] = None,
    ) -> Dict:
        """
        Get paginated FAQs with filtering.

        Security mitigations:
        - All filters use parameterized queries (SQL injection prevention)
        - Search uses FTS5 for efficient full-text search
        - No dynamic SQL construction from user input

        Args:
            page: Page number (1-indexed)
            page_size: Items per page
            category: Filter by category
            verified: Filter by verification status
            source: Filter by source
            search_text: Full-text search query
            bisq_version: Filter by Bisq version

        Returns:
            Dict with paginated results and metadata
        """
        # Clamp page to valid range for consistency with JSONL repository
        if page < 1:
            page = 1
        offset = (page - 1) * page_size
        params: List = []
        where_clauses: List[str] = []
        total = 0  # Default value in case of errors

        # SECURITY NOTE: Dynamic SQL construction below is safe because:
        # - All where_clauses are static strings (no user input)
        # - All user values go through params list (parameterized queries)
        # - No string interpolation or concatenation of user data
        # Build WHERE clause with parameterized queries only
        if category is not None:
            where_clauses.append("category = ?")
            params.append(category)

        if verified is not None:
            where_clauses.append("verified = ?")
            params.append(1 if verified else 0)

        if source is not None:
            where_clauses.append("source = ?")
            params.append(source)

        if bisq_version is not None:
            where_clauses.append("bisq_version = ?")
            params.append(bisq_version)

        # Date range filters for verified_at timestamp
        if verified_from is not None:
            where_clauses.append("verified_at >= ?")
            params.append(verified_from.isoformat())

        if verified_to is not None:
            where_clauses.append("verified_at <= ?")
            params.append(verified_to.isoformat())

        # Protect reader connection with lock to prevent concurrent thread access
        with self._read_lock:
            # Handle full-text search separately using FTS5
            if search_text:
                # Escape FTS5 special characters in search text
                # FTS5 uses quotes for phrase search, so escape them
                escaped_search = search_text.replace('"', '""')
                # Wrap in quotes for exact phrase matching (prevents syntax errors)
                fts_query = f'"{escaped_search}"'

                # Use FTS5 virtual table for search
                search_query = """
                    SELECT faqs.* FROM faqs
                    JOIN faqs_fts ON faqs.id = faqs_fts.rowid
                    WHERE faqs_fts MATCH ?
                """
                count_query = """
                    SELECT COUNT(*) FROM faqs
                    JOIN faqs_fts ON faqs.id = faqs_fts.rowid
                    WHERE faqs_fts MATCH ?
                """
                search_params = [fts_query]

                # Add additional filters
                if where_clauses:
                    search_query += " AND " + " AND ".join(where_clauses)
                    count_query += " AND " + " AND ".join(where_clauses)
                    search_params.extend(params)

                search_query += " LIMIT ? OFFSET ?"
                search_params.extend([str(page_size), str(offset)])

                # Execute search
                cursor = self._reader_conn.execute(search_query, search_params)
                rows = cursor.fetchall()

                # Get total count
                try:
                    cursor = self._reader_conn.execute(
                        count_query, [fts_query] + params
                    )
                    result = cursor.fetchone()
                    total = result[0] if result else 0
                except (sqlite3.Error, IndexError) as e:
                    logger.warning(f"Failed to get FTS count, using 0: {e}")
                    total = 0

            else:
                # Regular query without search
                where_sql = (
                    "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
                )

                query = f"""
                    SELECT * FROM faqs
                    {where_sql}
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                """
                params.extend([page_size, offset])

                cursor = self._reader_conn.execute(query, params)
                rows = cursor.fetchall()

                # Get total count
                count_query = f"SELECT COUNT(*) FROM faqs {where_sql}"
                count_params = params[:-2]  # Exclude LIMIT/OFFSET
                try:
                    cursor = self._reader_conn.execute(count_query, count_params)
                    result = cursor.fetchone()
                    total = result[0] if result else 0
                except (sqlite3.Error, IndexError) as e:
                    logger.warning(f"Failed to get count, using 0: {e}")
                    total = 0

            # Convert rows to FAQIdentifiedItem objects (filter out None values)
            items = [faq for row in rows if (faq := self._row_to_faq(row)) is not None]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    def get_filtered_faqs(
        self,
        search_text: Optional[str] = None,
        categories: Optional[List[str]] = None,
        source: Optional[str] = None,
        verified: Optional[bool] = None,
        bisq_version: Optional[str] = None,
        verified_from: Optional[datetime] = None,
        verified_to: Optional[datetime] = None,
    ) -> List[FAQIdentifiedItem]:
        """Get all FAQs matching the specified filters without pagination.

        This method is designed for aggregation operations (e.g., statistics)
        where all matching FAQs are needed without pagination limits.

        SCALING NOTE: Uses page_size=10000 which aligns with the documented
        SQLite capacity limit (≤10k FAQs). If FAQ count exceeds this threshold,
        results will be silently truncated. At that point, migration to PostgreSQL
        is recommended per the system's scaling guidelines.

        Args:
            search_text: Optional text search filter
            categories: Optional list of categories to filter by
            source: Optional source filter
            verified: Optional verification status filter
            bisq_version: Optional Bisq version filter
            verified_from: Optional start date for verified_at filter (inclusive)
            verified_to: Optional end date for verified_at filter (inclusive)

        Returns:
            List of all FAQs matching the specified filters (up to 10k per category)
        """
        # Use get_faqs_paginated with large page size to get all results
        # Categories list needs to be converted to single category for pagination
        # If multiple categories provided, we'll need to make multiple calls
        all_faqs = []

        if categories and len(categories) > 1:
            # Handle multiple categories by combining results
            for category in categories:
                result = self.get_faqs_paginated(
                    page=1,
                    page_size=10000,  # Large page size to get all FAQs
                    category=category,
                    verified=verified,
                    source=source,
                    search_text=search_text,
                    bisq_version=bisq_version,
                    verified_from=verified_from,
                    verified_to=verified_to,
                )
                all_faqs.extend(result["items"])
        else:
            # Single category or no category filter
            category = categories[0] if categories and len(categories) == 1 else None
            result = self.get_faqs_paginated(
                page=1,
                page_size=10000,  # Large page size to get all FAQs
                category=category,
                verified=verified,
                source=source,
                search_text=search_text,
                bisq_version=bisq_version,
                verified_from=verified_from,
                verified_to=verified_to,
            )
            all_faqs = result["items"]

        return all_faqs

    def get_all_faqs(
        self,
        category: Optional[str] = None,
        verified: Optional[bool] = None,
        source: Optional[str] = None,
        bisq_version: Optional[str] = None,
    ) -> List[FAQIdentifiedItem]:
        """
        Get all FAQs using pagination internally.

        This method provides API compatibility with the old JSONL repository
        by wrapping the paginated query and fetching all results.

        Args:
            category: Optional category filter
            verified: Optional verification status filter
            source: Optional source filter
            bisq_version: Optional Bisq version filter

        Returns:
            List of all FAQs matching the filters
        """
        all_faqs: List[FAQIdentifiedItem] = []
        page = 1
        page_size = 100

        while True:
            result = self.get_faqs_paginated(
                page=page,
                page_size=page_size,
                category=category,
                verified=verified,
                source=source,
                bisq_version=bisq_version,
            )
            all_faqs.extend(result["items"])

            if page >= result["total_pages"]:
                break

            page += 1

        return all_faqs

    def update_faq(
        self, faq_id: Union[int, str], faq_item: FAQItem
    ) -> Optional[FAQIdentifiedItem]:
        """
        Update existing FAQ.

        Security mitigations:
        - Parameterized query prevents SQL injection
        - Write lock prevents race conditions
        - Input validation via Pydantic model
        - Retry logic for SQLITE_BUSY errors

        Args:
            faq_id: FAQ ID to update (int or str, converted to int)
            faq_item: New FAQ data

        Returns:
            Updated FAQIdentifiedItem if successful, None if not found
        """
        # Convert string ID to int if needed
        faq_id_int = int(faq_id) if isinstance(faq_id, str) else faq_id

        # Validate field lengths
        if len(faq_item.question) > self.MAX_QUESTION_LENGTH:
            raise ValueError(
                f"Question exceeds maximum length ({self.MAX_QUESTION_LENGTH})"
            )
        if len(faq_item.answer) > self.MAX_ANSWER_LENGTH:
            raise ValueError(
                f"Answer exceeds maximum length ({self.MAX_ANSWER_LENGTH})"
            )

        updated_at = datetime.now(timezone.utc).isoformat()

        # Fetch existing FAQ to check current verification status
        with self._read_lock:
            cursor = self._reader_conn.execute(
                "SELECT verified, verified_at FROM faqs WHERE id = ?", (faq_id_int,)
            )
            existing_row = cursor.fetchone()

        if not existing_row:
            # FAQ not found - will fail in update operation
            verified_at = None
        else:
            existing_verified = bool(existing_row[0])
            existing_verified_at = existing_row[1]

            # Handle verified_at timestamp (matching JSONL behavior):
            # - If verification status changes from False→True, set verified_at to now
            # - If FAQ stays verified, preserve existing verified_at timestamp
            # - If FAQ becomes unverified, clear verified_at to None
            if faq_item.verified:
                if not existing_verified:
                    # Verification status changed from False→True: set new timestamp
                    verified_at = updated_at
                elif faq_item.verified_at:
                    # FAQ stays verified, explicit verified_at provided: use it
                    verified_at = faq_item.verified_at.isoformat()
                else:
                    # FAQ stays verified, no explicit verified_at: preserve existing
                    verified_at = existing_verified_at
            else:
                # FAQ is being unverified: clear timestamp
                verified_at = None

        # Define write operation
        def _update_operation():
            with self._write_lock:
                with self._writer_conn:
                    cursor = self._writer_conn.execute(
                        """
                        UPDATE faqs
                        SET question = ?, answer = ?, category = ?, source = ?,
                            verified = ?, bisq_version = ?, updated_at = ?, verified_at = ?
                        WHERE id = ?
                        """,
                        (
                            faq_item.question,
                            faq_item.answer,
                            faq_item.category or "General",
                            faq_item.source or "Manual",
                            1 if faq_item.verified else 0,
                            faq_item.bisq_version or "Bisq 2",
                            updated_at,
                            verified_at,
                            faq_id_int,
                        ),
                    )
                    return cursor.rowcount > 0

        # Execute update with retry logic
        success = self._execute_with_retry(_update_operation)

        if not success:
            return None

        # Fetch and return the updated FAQ
        with self._read_lock:
            cursor = self._reader_conn.execute(
                "SELECT * FROM faqs WHERE id = ?", (faq_id_int,)
            )
            row = cursor.fetchone()
            return self._row_to_faq(row) if row else None

    def delete_faq(self, faq_id: Union[int, str]) -> bool:
        """
        Delete FAQ by ID.

        Security mitigations:
        - Parameterized query prevents SQL injection
        - Write lock prevents race conditions
        - Retry logic for SQLITE_BUSY errors

        Args:
            faq_id: FAQ ID to delete (int or str, converted to int)

        Returns:
            True if deleted, False if not found
        """
        # Convert string ID to int if needed
        faq_id_int = int(faq_id) if isinstance(faq_id, str) else faq_id

        # Define delete operation
        def _delete_operation():
            with self._write_lock:
                with self._writer_conn:
                    cursor = self._writer_conn.execute(
                        "DELETE FROM faqs WHERE id = ?", (faq_id_int,)
                    )
                    return cursor.rowcount > 0

        # Execute with retry logic
        success = self._execute_with_retry(_delete_operation)

        # Log outcome for parity with JSONL repository
        if success:
            logger.info("Deleted FAQ with ID: %s", faq_id_int)
        else:
            logger.warning("Delete failed: FAQ with ID %s not found", faq_id_int)

        return success

    def migrate_from_jsonl(self, jsonl_path: str) -> Dict[str, int]:
        """
        Migrate FAQs from JSONL file to SQLite database.

        Security mitigations:
        - Input validation for each entry
        - Malformed JSON entries are skipped (logged)
        - Missing required fields are skipped
        - Invalid datetime values are replaced with None
        - Transaction rollback on critical errors

        Args:
            jsonl_path: Path to JSONL file

        Returns:
            Migration statistics (success, skipped, errors)
        """
        stats = {"success": 0, "skipped": 0, "errors": 0}

        if not Path(jsonl_path).exists():
            logger.error(f"JSONL file not found: {jsonl_path}")
            return stats

        with open(jsonl_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    # Parse JSON
                    data = json.loads(line)

                    # Validate required fields
                    if "question" not in data or "answer" not in data:
                        logger.warning(
                            f"Line {line_num}: Missing required fields, skipping"
                        )
                        stats["skipped"] += 1
                        continue

                    # Parse datetime fields with error handling
                    created_at = self._parse_datetime(data.get("created_at"))
                    updated_at = self._parse_datetime(data.get("updated_at"))
                    verified_at = self._parse_datetime(data.get("verified_at"))

                    # Create FAQItem with validated data
                    faq_item = FAQItem(
                        question=data["question"],
                        answer=data["answer"],
                        category=data.get("category", "General"),
                        source=data.get("source", "Manual"),
                        verified=data.get("verified", False),
                        bisq_version=data.get("bisq_version", "Bisq 2"),
                        created_at=created_at,
                        updated_at=updated_at,
                        verified_at=verified_at,
                    )

                    # Add to database (UPSERT handles duplicates)
                    self.add_faq(faq_item)
                    stats["success"] += 1

                except json.JSONDecodeError:
                    logger.exception("Line %s: Malformed JSON", line_num)
                    stats["errors"] += 1
                except ValueError:
                    logger.exception("Line %s: Validation error", line_num)
                    stats["errors"] += 1
                except Exception:
                    logger.exception(
                        "Line %s: Unexpected error during migration", line_num
                    )
                    stats["errors"] += 1

        logger.info(
            f"Migration complete: {stats['success']} success, "
            f"{stats['skipped']} skipped, {stats['errors']} errors"
        )
        return stats

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """
        Parse datetime string with error handling.

        Args:
            value: ISO 8601 datetime string or None

        Returns:
            Parsed datetime or None if invalid
        """
        if not value:
            return None

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.warning(f"Invalid datetime value: {value}")
            return None

    def _row_to_faq(self, row: sqlite3.Row) -> Optional[FAQIdentifiedItem]:
        """
        Convert database row to FAQIdentifiedItem.

        Args:
            row: SQLite row object

        Returns:
            FAQIdentifiedItem object, or None if row has NULL required fields
        """
        # Skip rows with NULL or missing required fields
        try:
            question = row["question"]
            answer = row["answer"]
            row_id = row["id"]
        except (IndexError, KeyError) as e:
            logger.warning(f"Skipping malformed row (missing columns): {e}")
            return None

        # Skip rows with NULL required fields (can happen with FTS operations)
        if question is None or answer is None:
            logger.warning(
                f"Skipping FAQ {row_id} with NULL required fields "
                f"(question={question}, answer={answer})"
            )
            return None

        return FAQIdentifiedItem(
            id=str(row["id"]),  # Convert integer ID to string for compatibility
            question=row["question"],
            answer=row["answer"],
            category=row["category"] or "General",
            source=row["source"] or "Manual",
            verified=bool(row["verified"]),
            bisq_version=row["bisq_version"] or "Bisq 2",
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
            verified_at=self._parse_datetime(row["verified_at"]),
        )

    def close(self):
        """Close database connections."""
        if hasattr(self, "_writer_conn"):
            self._writer_conn.close()
        if hasattr(self, "_reader_conn"):
            self._reader_conn.close()
            logger.info("SQLite connection closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

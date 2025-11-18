"""
FAQ migration utilities for JSONL to SQLite transition.

This module provides functions to:
1. Migrate FAQs from JSONL to SQLite
2. Rollback from SQLite to JSONL (disaster recovery)
3. Track migration statistics and progress
"""

import logging
import time
from typing import Any, Dict

from app.models.faq import FAQItem
from app.services.faq.faq_repository import FAQRepository
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

logger = logging.getLogger(__name__)


def _get_all_faqs_from_sqlite(sqlite_repo: FAQRepositorySQLite) -> list:
    """
    Helper to get all FAQs from SQLite repository using pagination.

    Args:
        sqlite_repo: SQLite repository

    Returns:
        list: All FAQs from the repository
    """
    all_faqs = []
    page = 1
    page_size = 100

    while True:
        result = sqlite_repo.get_faqs_paginated(page=page, page_size=page_size)
        all_faqs.extend(result["items"])

        if page >= result["total_pages"]:
            break

        page += 1

    return all_faqs


def migrate_jsonl_to_sqlite(
    jsonl_repo: FAQRepository, sqlite_repo: FAQRepositorySQLite
) -> Dict[str, Any]:
    """
    Migrate all FAQs from JSONL repository to SQLite repository.

    This function:
    - Reads all FAQs from JSONL file
    - Adds each FAQ to SQLite database (UPSERT handles duplicates)
    - Tracks migration statistics
    - Is idempotent (can be run multiple times safely)

    Args:
        jsonl_repo: Source JSONL repository
        sqlite_repo: Target SQLite repository

    Returns:
        dict: Migration statistics containing:
            - total: Total FAQs in JSONL
            - migrated: Successfully migrated FAQs
            - errors: Number of errors encountered
            - duration_seconds: Migration duration
    """
    logger.info("Starting JSONL to SQLite migration")
    start_time = time.time()

    stats: Dict[str, Any] = {"total": 0, "migrated": 0, "errors": 0}

    try:
        # Read all FAQs from JSONL
        faqs = jsonl_repo.get_all_faqs()
        stats["total"] = len(faqs)

        logger.info(f"Found {stats['total']} FAQs to migrate")

        # Migrate each FAQ to SQLite
        for faq in faqs:
            try:
                # Convert FAQIdentifiedItem to FAQItem (remove id for SQLite auto-generation)
                faq_item = FAQItem(
                    question=faq.question,
                    answer=faq.answer,
                    category=faq.category,
                    source=faq.source,
                    verified=faq.verified,
                    bisq_version=faq.bisq_version,
                    created_at=faq.created_at,
                    updated_at=faq.updated_at,
                    verified_at=faq.verified_at,
                )

                # Add to SQLite (UPSERT will handle duplicates)
                sqlite_repo.add_faq(faq_item)
                stats["migrated"] += 1

                if stats["migrated"] % 10 == 0:
                    logger.info(f"Migrated {stats['migrated']}/{stats['total']} FAQs")

            except Exception:
                logger.exception(f"Error migrating FAQ '{faq.question}'")
                stats["errors"] += 1
                continue

        duration = time.time() - start_time
        stats["duration_seconds"] = float(round(duration, 2))

        logger.info(
            f"Migration complete: {stats['migrated']}/{stats['total']} FAQs migrated "
            f"in {stats['duration_seconds']}s ({stats['errors']} errors)"
        )

    except Exception:
        logger.exception("Migration failed")
        duration = time.time() - start_time
        stats["duration_seconds"] = float(round(duration, 2))
        raise
    else:
        return stats


def rollback_sqlite_to_jsonl(
    sqlite_repo: FAQRepositorySQLite, jsonl_repo: FAQRepository
) -> Dict[str, Any]:
    """
    Rollback FAQs from SQLite repository to JSONL repository.

    This is a disaster recovery function that:
    - Reads all FAQs from SQLite database
    - Writes each FAQ back to JSONL file
    - Tracks rollback statistics

    WARNING: This will overwrite the existing JSONL file!

    Args:
        sqlite_repo: Source SQLite repository
        jsonl_repo: Target JSONL repository

    Returns:
        dict: Rollback statistics containing:
            - total: Total FAQs in SQLite
            - rolled_back: Successfully rolled back FAQs
            - errors: Number of errors encountered
            - duration_seconds: Rollback duration
    """
    logger.warning("Starting SQLite to JSONL rollback (disaster recovery)")
    start_time = time.time()

    stats: Dict[str, Any] = {"total": 0, "rolled_back": 0, "errors": 0}

    try:
        # Read all FAQs from SQLite using pagination helper
        faqs = _get_all_faqs_from_sqlite(sqlite_repo)
        stats["total"] = len(faqs)

        logger.info(f"Found {stats['total']} FAQs to rollback")

        # Clear existing JSONL file (we're doing a full restore from SQLite)
        # This ensures we don't append to existing data, but completely replace it
        jsonl_repo._clear_file()

        # Rollback each FAQ to JSONL
        for faq in faqs:
            try:
                # Convert FAQIdentifiedItem to FAQItem for JSONL storage
                faq_item = FAQItem(
                    question=faq.question,
                    answer=faq.answer,
                    category=faq.category,
                    source=faq.source,
                    verified=faq.verified,
                    bisq_version=faq.bisq_version,
                    created_at=faq.created_at,
                    updated_at=faq.updated_at,
                    verified_at=faq.verified_at,
                )

                # Add to JSONL repository
                jsonl_repo.add_faq(faq_item)
                stats["rolled_back"] += 1

                if stats["rolled_back"] % 10 == 0:
                    logger.info(
                        f"Rolled back {stats['rolled_back']}/{stats['total']} FAQs"
                    )

            except Exception:
                logger.exception(f"Error rolling back FAQ '{faq.question}'")
                stats["errors"] += 1
                continue

        duration = time.time() - start_time
        stats["duration_seconds"] = float(round(duration, 2))

        logger.info(
            f"Rollback complete: {stats['rolled_back']}/{stats['total']} FAQs restored "
            f"in {stats['duration_seconds']}s ({stats['errors']} errors)"
        )

    except Exception:
        logger.exception("Rollback failed")
        duration = time.time() - start_time
        stats["duration_seconds"] = float(round(duration, 2))
        raise
    else:
        return stats


def verify_migration(
    jsonl_repo: FAQRepository, sqlite_repo: FAQRepositorySQLite
) -> bool:
    """
    Verify that SQLite migration matches JSONL content.

    Compares:
    - Total FAQ count
    - Sample of questions exist in both repositories
    - Verified status matches

    Args:
        jsonl_repo: Source JSONL repository
        sqlite_repo: Target SQLite repository

    Returns:
        bool: True if verification passes, False otherwise
    """
    logger.info("Verifying migration integrity")

    try:
        # Get all FAQs from both repositories
        jsonl_faqs = jsonl_repo.get_all_faqs()
        sqlite_faqs = _get_all_faqs_from_sqlite(sqlite_repo)

        # Check 1: Count should be close (duplicates in JSONL may reduce count in SQLite)
        jsonl_count = len(jsonl_faqs)
        sqlite_count = len(sqlite_faqs)

        if sqlite_count > jsonl_count:
            logger.error(
                f"Verification failed: SQLite has more FAQs ({sqlite_count}) than JSONL ({jsonl_count})"
            )
            return False

        logger.info(f"Count check: JSONL={jsonl_count}, SQLite={sqlite_count}")

        # Check 2: All questions from JSONL should exist in SQLite
        jsonl_questions = {faq.question for faq in jsonl_faqs}
        sqlite_questions = {faq.question for faq in sqlite_faqs}

        missing_questions = jsonl_questions - sqlite_questions
        if missing_questions:
            logger.error(
                f"Verification failed: {len(missing_questions)} questions missing from SQLite: "
                f"{list(missing_questions)[:5]}"
            )
            return False

        logger.info("All questions verified in SQLite")

        # Check 3: Verified status should match for sample of FAQs
        sample_size = min(10, jsonl_count)
        if sample_size > 0:
            jsonl_sample = jsonl_faqs[:sample_size]
            for jsonl_faq in jsonl_sample:
                # Find matching FAQ in SQLite
                sqlite_matches = [
                    f for f in sqlite_faqs if f.question == jsonl_faq.question
                ]
                if not sqlite_matches:
                    logger.error(
                        f"Verification failed: Question not found in SQLite: {jsonl_faq.question}"
                    )
                    return False

                sqlite_faq = sqlite_matches[0]
                if jsonl_faq.verified != sqlite_faq.verified:
                    logger.warning(
                        f"Verified status mismatch for '{jsonl_faq.question}': "
                        f"JSONL={jsonl_faq.verified}, SQLite={sqlite_faq.verified}"
                    )

        logger.info("Migration verification passed")
        return True

    except Exception as e:
        logger.error(f"Verification failed with error: {e}")
        return False

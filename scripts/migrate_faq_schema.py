#!/usr/bin/env python3
"""
FAQ Schema Migration Script

Adds missing fields to FAQ data while preserving all existing content.
Run this during deployments when FAQ schema changes.

Usage:
    python migrate_faq_schema.py [--dry-run]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

FAQ_FILE = Path("/opt/bisq-support/api/data/extracted_faq.jsonl")
FAQ_BACKUP = Path("/opt/bisq-support/api/data/extracted_faq.jsonl.backup")


def migrate_faq_entry(faq: Dict[str, Any]) -> Dict[str, Any]:
    """Add missing fields to FAQ entry with appropriate defaults."""
    # Add verified field if missing
    if "verified" not in faq:
        faq["verified"] = False

    # Future schema changes can be added here
    # Example:
    # if "priority" not in faq:
    #     faq["priority"] = 0

    return faq


def migrate_faq_file(dry_run: bool = False) -> int:
    """
    Migrate FAQ file by adding missing fields.

    Args:
        dry_run: If True, only report changes without modifying file

    Returns:
        Number of FAQs migrated
    """
    if not FAQ_FILE.exists():
        print(f"❌ FAQ file not found: {FAQ_FILE}", file=sys.stderr)
        return -1

    # Read all FAQs
    faqs = []
    migrated_count = 0

    try:
        with open(FAQ_FILE, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    faq = json.loads(line)
                    original_faq = faq.copy()
                    migrated_faq = migrate_faq_entry(faq)

                    # Check if migration changed anything
                    if migrated_faq != original_faq:
                        migrated_count += 1
                        if dry_run:
                            print(
                                f"Would migrate FAQ {line_num}: {faq.get('question', 'N/A')[:50]}..."
                            )

                    faqs.append(migrated_faq)

                except json.JSONDecodeError as e:
                    print(
                        f"⚠️  Skipping invalid JSON on line {line_num}: {e}",
                        file=sys.stderr,
                    )
                    continue

    except Exception as e:
        print(f"❌ Error reading FAQ file: {e}", file=sys.stderr)
        return -1

    if migrated_count == 0:
        print("✅ No migrations needed - all FAQs up to date")
        return 0

    if dry_run:
        print(f"\n📋 Dry run complete: {migrated_count} FAQs would be migrated")
        return migrated_count

    # Create backup before writing
    try:
        import shutil

        shutil.copy2(FAQ_FILE, FAQ_BACKUP)
        print(f"📦 Created backup: {FAQ_BACKUP}")
    except Exception as e:
        print(f"⚠️  Warning: Could not create backup: {e}", file=sys.stderr)

    # Write migrated FAQs
    try:
        with open(FAQ_FILE, "w", encoding="utf-8") as f:
            for faq in faqs:
                f.write(json.dumps(faq, ensure_ascii=False) + "\n")

        print(f"✅ Successfully migrated {migrated_count} FAQs")
        print(f"📊 Total FAQs: {len(faqs)}")
        return migrated_count

    except Exception as e:
        print(f"❌ Error writing FAQ file: {e}", file=sys.stderr)
        if FAQ_BACKUP.exists():
            print(f"💡 Restore backup with: cp {FAQ_BACKUP} {FAQ_FILE}")
        return -1


def main():
    parser = argparse.ArgumentParser(description="Migrate FAQ schema")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )

    args = parser.parse_args()

    result = migrate_faq_file(dry_run=args.dry_run)
    sys.exit(0 if result >= 0 else 1)


if __name__ == "__main__":
    main()

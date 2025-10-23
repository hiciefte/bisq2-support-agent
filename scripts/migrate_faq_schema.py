#!/usr/bin/env python3
"""
FAQ Schema Migration Script

Adds missing fields to FAQ data while preserving all existing content.
Run this during deployments when FAQ schema changes.

Usage:
    python migrate_faq_schema.py [--dry-run] [--data-dir PATH]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

# Default data directory for production
DEFAULT_DATA_DIR = Path("/opt/bisq-support/api/data")


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


def migrate_faq_file(data_dir: Path, dry_run: bool = False) -> int:
    """
    Migrate FAQ file by adding missing fields.

    Args:
        data_dir: Directory containing FAQ data
        dry_run: If True, only report changes without modifying file

    Returns:
        Number of FAQs migrated
    """
    faq_file = data_dir / "extracted_faq.jsonl"
    faq_backup = data_dir / "extracted_faq.jsonl.backup"

    if not faq_file.exists():
        print(f"❌ FAQ file not found: {faq_file}", file=sys.stderr)
        return -1

    # Read all FAQs
    faqs = []
    migrated_count = 0

    try:
        with open(faq_file, "r", encoding="utf-8") as f:
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

        shutil.copy2(faq_file, faq_backup)
        print(f"📦 Created backup: {faq_backup}")
    except Exception as e:
        print(f"⚠️  Warning: Could not create backup: {e}", file=sys.stderr)

    # Write migrated FAQs
    try:
        with open(faq_file, "w", encoding="utf-8") as f:
            for faq in faqs:
                f.write(json.dumps(faq, ensure_ascii=False) + "\n")

        print(f"✅ Successfully migrated {migrated_count} FAQs")
        print(f"📊 Total FAQs: {len(faqs)}")
        return migrated_count

    except Exception as e:
        print(f"❌ Error writing FAQ file: {e}", file=sys.stderr)
        if faq_backup.exists():
            print(f"💡 Restore backup with: cp {faq_backup} {faq_file}")
        return -1


def main():
    parser = argparse.ArgumentParser(description="Migrate FAQ schema")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Data directory containing FAQ files (default: {DEFAULT_DATA_DIR})",
    )

    args = parser.parse_args()

    # SECURITY: Validate data directory exists and is absolute
    try:
        data_dir = args.data_dir.resolve(strict=True)
    except (OSError, RuntimeError) as e:
        print(f"❌ Invalid data directory: {args.data_dir} ({e})", file=sys.stderr)
        sys.exit(1)

    # SECURITY: Validate path contains expected patterns
    data_dir_str = str(data_dir)
    allowed_patterns = ["bisq-support", "bisq-faq-test", "bisq2-support-agent"]
    if not any(pattern in data_dir_str for pattern in allowed_patterns):
        print(f"❌ Invalid data directory path: {data_dir}", file=sys.stderr)
        print("   Data directory must be within bisq-support project", file=sys.stderr)
        sys.exit(1)

    result = migrate_faq_file(data_dir=data_dir, dry_run=args.dry_run)
    sys.exit(0 if result >= 0 else 1)


if __name__ == "__main__":
    main()

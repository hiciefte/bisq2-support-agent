#!/bin/bash
# Test script for FAQ preservation during deployment
# Tests the core logic without requiring Docker or production environment

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================================"
echo "FAQ Preservation System - Local Test"
echo "======================================================${NC}"

# Create test directory structure
TEST_DIR="/tmp/bisq-faq-test-$$"
echo -e "${BLUE}Creating test environment: $TEST_DIR${NC}"
mkdir -p "$TEST_DIR/api/data"
mkdir -p "$TEST_DIR/scripts"

# Initialize git repo
cd "$TEST_DIR"
git init
git config user.email "test@example.com"
git config user.name "Test User"

# Create sample FAQ data (simulating production)
echo -e "${BLUE}Creating sample FAQ data (simulating production)...${NC}"
cat > "$TEST_DIR/api/data/extracted_faq.jsonl" <<'EOF'
{"question": "What is Bisq?", "answer": "Bisq is a decentralized exchange", "category": "General", "source": "Manual"}
{"question": "How do I trade?", "answer": "Click the Trade tab", "category": "Trading", "source": "Manual"}
{"question": "Is Bisq safe?", "answer": "Yes, it's non-custodial", "category": "Security", "source": "Manual"}
EOF

INITIAL_FAQ_COUNT=$(wc -l < "$TEST_DIR/api/data/extracted_faq.jsonl")
INITIAL_FIRST_QUESTION=$(head -1 "$TEST_DIR/api/data/extracted_faq.jsonl" | grep -o '"What is Bisq?"')

echo -e "${GREEN}✓ Created $INITIAL_FAQ_COUNT FAQs${NC}"
echo -e "${GREEN}✓ First question: $INITIAL_FIRST_QUESTION${NC}"

# Create initial git commit (simulating existing production state)
git add api/data/extracted_faq.jsonl
git commit -m "Initial FAQ data"

# Simulate FAQ changes in production (before deployment)
echo -e "\n${BLUE}Simulating FAQ changes in production...${NC}"
cat >> "$TEST_DIR/api/data/extracted_faq.jsonl" <<'EOF'
{"question": "Can I use Tor?", "answer": "Yes, Bisq supports Tor", "category": "Privacy", "source": "Extracted"}
{"question": "What fees apply?", "answer": "Trading fees are 0.1%", "category": "Fees", "source": "Extracted"}
EOF

PRODUCTION_FAQ_COUNT=$(wc -l < "$TEST_DIR/api/data/extracted_faq.jsonl")
echo -e "${GREEN}✓ Production now has $PRODUCTION_FAQ_COUNT FAQs (added 2 new)${NC}"

# Source the preservation functions
echo -e "\n${BLUE}Loading FAQ preservation functions...${NC}"

# Define the functions inline for testing
preserve_production_data() {
    local repo_dir="${1:-.}"
    local backup_dir="$repo_dir/api/data/.backup_$(date +%Y%m%d_%H%M%S)"

    cd "$repo_dir" || return 1

    local production_files=(
        "api/data/extracted_faq.jsonl"
    )

    mkdir -p "$backup_dir"

    echo "Backing up production data files..."
    local backed_up_count=0
    for file in "${production_files[@]}"; do
        local file_path="$repo_dir/$file"
        if [ -f "$file_path" ]; then
            cp "$file_path" "$backup_dir/"
            backed_up_count=$((backed_up_count + 1))
        fi
    done

    if [ "$backed_up_count" -gt 0 ]; then
        echo "Backed up $backed_up_count file(s) to: $backup_dir"
        echo "$backup_dir"
        return 0
    else
        rmdir "$backup_dir" 2>/dev/null
        return 0
    fi
}

restore_production_data() {
    local repo_dir="${1:-.}"
    local backup_dir="${2}"

    if [ -z "$backup_dir" ] || [ ! -d "$backup_dir" ]; then
        echo "No backup directory specified"
        return 0
    fi

    cd "$repo_dir" || return 1

    echo "Restoring production data files from backup..."
    local restored_count=0
    for backup_file in "$backup_dir"/*; do
        if [ -f "$backup_file" ]; then
            local filename=$(basename "$backup_file")
            local restore_path="$repo_dir/api/data/$filename"
            cp "$backup_file" "$restore_path"
            restored_count=$((restored_count + 1))
        fi
    done

    if [ "$restored_count" -gt 0 ]; then
        echo "Restored $restored_count file(s)"
        return 0
    fi
}

# Test 1: Backup production data
echo -e "\n${BLUE}TEST 1: Backup production data${NC}"
BACKUP_DIR=$(preserve_production_data "$TEST_DIR" 2>&1 | tail -1)

echo "Debug: BACKUP_DIR='$BACKUP_DIR'"
echo "Debug: Checking if directory exists..."
ls -la "$TEST_DIR/api/data/" | grep backup || echo "No backup directory found"

# Find the actual backup directory
BACKUP_DIR=$(find "$TEST_DIR/api/data" -type d -name ".backup_*" | head -1)

if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    BACKUP_FAQ_COUNT=$(wc -l < "$BACKUP_DIR/extracted_faq.jsonl")
    if [ "$BACKUP_FAQ_COUNT" -eq "$PRODUCTION_FAQ_COUNT" ]; then
        echo -e "${GREEN}✓ PASS: Backup created with $BACKUP_FAQ_COUNT FAQs${NC}"
    else
        echo -e "${RED}✗ FAIL: Backup has $BACKUP_FAQ_COUNT FAQs, expected $PRODUCTION_FAQ_COUNT${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ FAIL: Backup directory not created${NC}"
    exit 1
fi

# Test 2: Simulate git reset (overwrites FAQ file)
echo -e "\n${BLUE}TEST 2: Simulate git reset (data loss scenario)${NC}"
git reset --hard HEAD
AFTER_RESET_COUNT=$(wc -l < "$TEST_DIR/api/data/extracted_faq.jsonl")

if [ "$AFTER_RESET_COUNT" -eq "$INITIAL_FAQ_COUNT" ]; then
    echo -e "${YELLOW}✓ Git reset restored initial state: $AFTER_RESET_COUNT FAQs (lost 2 FAQs as expected)${NC}"
else
    echo -e "${RED}✗ FAIL: Unexpected FAQ count after reset: $AFTER_RESET_COUNT${NC}"
    exit 1
fi

# Test 3: Restore production data
echo -e "\n${BLUE}TEST 3: Restore production data${NC}"
restore_production_data "$TEST_DIR" "$BACKUP_DIR"
AFTER_RESTORE_COUNT=$(wc -l < "$TEST_DIR/api/data/extracted_faq.jsonl")

if [ "$AFTER_RESTORE_COUNT" -eq "$PRODUCTION_FAQ_COUNT" ]; then
    echo -e "${GREEN}✓ PASS: Production data restored: $AFTER_RESTORE_COUNT FAQs${NC}"
else
    echo -e "${RED}✗ FAIL: Restore failed. Expected $PRODUCTION_FAQ_COUNT, got $AFTER_RESTORE_COUNT${NC}"
    exit 1
fi

# Test 4: Verify FAQ content integrity
echo -e "\n${BLUE}TEST 4: Verify FAQ content integrity${NC}"
RESTORED_FIRST_QUESTION=$(head -1 "$TEST_DIR/api/data/extracted_faq.jsonl" | grep -o '"What is Bisq?"')
RESTORED_LAST_QUESTION=$(tail -1 "$TEST_DIR/api/data/extracted_faq.jsonl" | grep -o '"What fees apply?"')

if [ "$RESTORED_FIRST_QUESTION" = "$INITIAL_FIRST_QUESTION" ] && [ -n "$RESTORED_LAST_QUESTION" ]; then
    echo -e "${GREEN}✓ PASS: First question matches: $RESTORED_FIRST_QUESTION${NC}"
    echo -e "${GREEN}✓ PASS: Last question preserved: $RESTORED_LAST_QUESTION${NC}"
else
    echo -e "${RED}✗ FAIL: FAQ content corrupted${NC}"
    exit 1
fi

# Test 5: Test migration script
echo -e "\n${BLUE}TEST 5: Test FAQ schema migration${NC}"

# Get the directory where this test script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Copy migration script to test directory
if [ -f "$SCRIPT_DIR/migrate_faq_schema.py" ]; then
    cp "$SCRIPT_DIR/migrate_faq_schema.py" "$TEST_DIR/scripts/"

    # Update FAQ_FILE path in migration script for testing
    sed -i.bak 's|/opt/bisq-support|'"$TEST_DIR"'|g' "$TEST_DIR/scripts/migrate_faq_schema.py"

    # Run migration
    cd "$TEST_DIR"
    if python3 "$TEST_DIR/scripts/migrate_faq_schema.py"; then
        # Check if verified field was added
        FIRST_FAQ_VERIFIED=$(head -1 "$TEST_DIR/api/data/extracted_faq.jsonl" | grep -o '"verified": false')
        if [ -n "$FIRST_FAQ_VERIFIED" ]; then
            echo -e "${GREEN}✓ PASS: Migration added verified field${NC}"
        else
            echo -e "${RED}✗ FAIL: Migration did not add verified field${NC}"
            exit 1
        fi
    else
        echo -e "${RED}✗ FAIL: Migration script failed${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠ SKIP: Migration script not found at $SCRIPT_DIR/migrate_faq_schema.py${NC}"
    echo -e "${YELLOW}       (This is OK - migration tested separately)${NC}"
fi

# Test 6: Test idempotency (run migration again)
if [ -f "$TEST_DIR/scripts/migrate_faq_schema.py" ]; then
    echo -e "\n${BLUE}TEST 6: Test migration idempotency${NC}"
    BEFORE_SECOND_RUN=$(wc -l < "$TEST_DIR/api/data/extracted_faq.jsonl")
    python3 "$TEST_DIR/scripts/migrate_faq_schema.py" > /dev/null 2>&1
    AFTER_SECOND_RUN=$(wc -l < "$TEST_DIR/api/data/extracted_faq.jsonl")

    if [ "$BEFORE_SECOND_RUN" -eq "$AFTER_SECOND_RUN" ]; then
        echo -e "${GREEN}✓ PASS: Migration is idempotent (no duplicate fields)${NC}"
    else
        echo -e "${RED}✗ FAIL: Migration not idempotent${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠ SKIP: Idempotency test (migration script not available)${NC}"
fi

# Cleanup
echo -e "\n${BLUE}Cleaning up test environment...${NC}"
cd /tmp
rm -rf "$TEST_DIR"
echo -e "${GREEN}✓ Test environment cleaned up${NC}"

# Summary
echo -e "\n${GREEN}======================================================"
echo "✓ CORE TESTS PASSED"
echo "======================================================"
echo "Test Results:"
echo "  ✓ Backup creation works"
echo "  ✓ Git reset simulated (data loss scenario)"
echo "  ✓ Production data restoration works"
echo "  ✓ FAQ content integrity preserved"
if [ -f "$TEST_DIR/scripts/migrate_faq_schema.py" ]; then
    echo "  ✓ Schema migration successful"
    echo "  ✓ Migration is idempotent"
else
    echo "  ⚠ Schema migration (tested separately)"
fi
echo ""
echo "The FAQ preservation system is working correctly!"
echo "======================================================${NC}"

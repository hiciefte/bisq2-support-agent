#!/bin/bash
# scripts/generate-vanity-onion.sh
# Generate vanity .onion address locally and prepare for server deployment

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
PREFIX="${1:-bisq}"
THREADS="${2:-$(nproc)}"
OUTPUT_DIR="./onion-keys-$(date +%Y%m%d-%H%M%S)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Vanity .onion Address Generator${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}Prefix:${NC} $PREFIX"
echo -e "${GREEN}Threads:${NC} $THREADS"
echo -e "${GREEN}Output:${NC} $OUTPUT_DIR"
echo ""

# Check for mkp224o
if ! command -v mkp224o &> /dev/null; then
    echo -e "${RED}Error: mkp224o not found${NC}"
    echo ""
    echo "Install mkp224o:"
    echo ""
    echo "macOS:"
    echo "  brew install mkp224o"
    echo ""
    echo "Ubuntu/Debian:"
    echo "  git clone https://github.com/cathugger/mkp224o.git"
    echo "  cd mkp224o && ./autogen.sh && ./configure && make"
    echo ""
    exit 1
fi

# Estimate difficulty
PREFIX_LEN=${#PREFIX}
case $PREFIX_LEN in
    1-3)
        ESTIMATE="< 1 second"
        DIFFICULTY="Trivial"
        ;;
    4)
        ESTIMATE="5-30 seconds"
        DIFFICULTY="Easy"
        ;;
    5)
        ESTIMATE="2-10 minutes"
        DIFFICULTY="Easy"
        ;;
    6)
        ESTIMATE="30-60 minutes"
        DIFFICULTY="Medium"
        ;;
    7)
        ESTIMATE="8-24 hours"
        DIFFICULTY="Hard"
        ;;
    8)
        ESTIMATE="10-30 days"
        DIFFICULTY="Very Hard"
        ;;
    *)
        ESTIMATE="Months/Years"
        DIFFICULTY="Impractical"
        ;;
esac

echo -e "${YELLOW}Estimated time: $ESTIMATE (Difficulty: $DIFFICULTY)${NC}"
echo ""

# Warn if difficulty is high
if [ "$PREFIX_LEN" -gt 6 ]; then
    echo -e "${RED}Warning: This may take a very long time!${NC}"
    echo -e "${YELLOW}Consider using a shorter prefix (4-6 characters recommended)${NC}"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

echo -e "${GREEN}Starting generation...${NC}"
echo ""

# Generate vanity address
mkdir -p "$OUTPUT_DIR"

mkp224o "$PREFIX" -d "$OUTPUT_DIR" -n 1 -t "$THREADS" -v

# Find generated directory
ONION_DIR=$(find "$OUTPUT_DIR" -type d -name "${PREFIX}*.onion" | head -1)

if [ -z "$ONION_DIR" ]; then
    echo -e "${RED}Error: No address generated${NC}"
    exit 1
fi

ONION_ADDR=$(cat "$ONION_DIR/hostname")

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Generation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Generated Address:${NC}"
echo -e "${GREEN}$ONION_ADDR${NC}"
echo ""
echo -e "${BLUE}Key Location:${NC}"
echo "$ONION_DIR"
echo ""

# Create encrypted backup
BACKUP_FILE="bisq-onion-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
echo -e "${YELLOW}Creating encrypted backup...${NC}"

tar czf "$BACKUP_FILE" -C "$OUTPUT_DIR" "$(basename "$ONION_DIR")"

if command -v gpg &> /dev/null; then
    gpg --symmetric --cipher-algo AES256 "$BACKUP_FILE"
    rm "$BACKUP_FILE"
    BACKUP_FILE="${BACKUP_FILE}.gpg"
    echo -e "${GREEN}✓ Encrypted backup created: $BACKUP_FILE${NC}"
else
    echo -e "${YELLOW}⚠ GPG not found - backup is NOT encrypted${NC}"
    echo -e "${YELLOW}  Install GPG to create encrypted backups${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Next Steps${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "1. Transfer keys to server:"
echo ""
echo "   scp -r $ONION_DIR root@YOUR_SERVER:/tmp/bisq-onion/"
echo ""
echo "2. On the server, install keys:"
echo ""
echo "   sudo systemctl stop tor"
echo "   sudo rm -rf /var/lib/tor/bisq-support"
echo "   sudo mv /tmp/bisq-onion /var/lib/tor/bisq-support"
echo "   sudo chown -R debian-tor:debian-tor /var/lib/tor/bisq-support"
echo "   sudo chmod 700 /var/lib/tor/bisq-support"
echo "   sudo chmod 600 /var/lib/tor/bisq-support/*"
echo "   sudo systemctl start tor"
echo ""
echo "3. Update application environment:"
echo ""
echo "   Edit /opt/bisq-support/docker/.env:"
echo "   TOR_HIDDEN_SERVICE=$ONION_ADDR"
echo ""
echo "4. Restart services:"
echo ""
echo "   cd /opt/bisq-support/scripts && ./restart.sh"
echo ""
echo "5. Securely delete local keys:"
echo ""
echo "   shred -vfz -n 10 $ONION_DIR/hs_ed25519_secret_key"
echo "   rm -rf $OUTPUT_DIR"
echo ""
echo -e "${YELLOW}⚠ IMPORTANT: Store encrypted backup in a secure location!${NC}"
echo -e "${YELLOW}  Backup file: $BACKUP_FILE${NC}"
echo ""

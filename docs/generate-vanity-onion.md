# Generate Custom Vanity .onion Address Locally

This guide shows how to generate a custom vanity .onion address on your local machine and transfer it to the production server.

## Why Generate Locally?

- **Faster generation**: Your local machine may have more CPU cores
- **No server downtime**: Generate offline without affecting production
- **Better branding**: Custom prefix makes the address memorable (e.g., `bisq...onion`)

## Prerequisites

- Local machine with multiple CPU cores (for faster generation)
- `mkp224o` tool (fastest v3 onion generator)
- OR `eschalot` (alternative tool)

## Method 1: Using mkp224o (Recommended - Fastest)

### Step 1: Install mkp224o

```bash
# macOS
brew install mkp224o

# Ubuntu/Debian
sudo apt update
sudo apt install -y git gcc libc6-dev libsodium-dev make autoconf
git clone https://github.com/cathugger/mkp224o.git
cd mkp224o
./autogen.sh
./configure
make
```

### Step 2: Generate Vanity Address

```bash
# Generate address starting with "bisq"
./mkp224o bisq -d ./onion-keys -n 1

# Options:
# -d ./onion-keys    = Output directory for keys
# -n 1               = Stop after finding 1 match
# -t 8               = Use 8 threads (adjust for your CPU)
# -v                 = Verbose output

# For multi-thread generation (faster):
./mkp224o bisq -d ./onion-keys -n 1 -t 8 -v
```

**Expected patterns and difficulty**:
- `bisq` prefix (4 chars): ~5-30 seconds on modern CPU
- `bisq2` prefix (5 chars): ~2-10 minutes
- `bisqai` prefix (6 chars): ~30-60 minutes
- `bisqsupport` (11 chars): Days/weeks (not recommended)

### Step 3: Verify Generated Keys

```bash
# List generated addresses
ls -la ./onion-keys/

# Example output:
# drwx------  bisq7abc123def456.onion/
#   ├── hostname (contains the .onion address)
#   ├── hs_ed25519_public_key
#   └── hs_ed25519_secret_key

# View the generated address
cat ./onion-keys/bisq*/hostname
# Output: bisq7abc123def456ghi789jkl012mno345pqr678stu901vwx234yz.onion
```

## Method 2: Using eschalot (Alternative)

### Step 1: Install eschalot

```bash
# macOS
brew install eschalot

# Ubuntu/Debian
sudo apt install -y eschalot
```

### Step 2: Generate Vanity Address

```bash
# Generate address starting with "bisq"
eschalot -v -t 8 -r ^bisq

# Options:
# -v         = Verbose mode
# -t 8       = Use 8 threads
# -r ^bisq   = Regex pattern (must start with bisq)

# Save output to file
eschalot -t 8 -r ^bisq > bisq-onion.txt
```

**Note**: eschalot generates v2 addresses by default. For v3 addresses, use `mkp224o`.

## Method 3: Using Tor's built-in tool (No vanity)

If you don't need a custom prefix, Tor can generate a random v3 address:

```bash
# Generate random v3 address
tor --hash-password "$(openssl rand -base64 16)" --Address-map 127.0.0.1:80

# Or use Python
python3 << 'EOF'
import hashlib
import base64
from nacl.signing import SigningKey
from nacl.encoding import Base32Encoder

# Generate key pair
key = SigningKey.generate()
public_key = key.verify_key.encode()

# Calculate .onion address (v3 format)
version = b'\x03'
checksum = hashlib.sha3_256(b'.onion checksum' + public_key + version).digest()[:2]
onion_address = base64.b32encode(public_key + checksum + version).decode().lower()

print(f"Generated address: {onion_address}.onion")
print(f"Public key (base32): {base64.b32encode(public_key).decode()}")
print(f"Private key (base32): {base64.b32encode(key.encode()).decode()}")
EOF
```

## Step 4: Transfer Keys to Production Server

### Option A: Secure Copy (scp)

```bash
# From your local machine
cd ./onion-keys

# Find the generated directory
ONION_DIR=$(ls -d bisq*/)
ONION_ADDR=$(cat $ONION_DIR/hostname)

echo "Generated address: $ONION_ADDR"

# Copy keys to server (replace with your server IP)
scp -r $ONION_DIR root@YOUR_SERVER_IP:/tmp/bisq-onion-keys/

# On the server, move keys to Tor directory
ssh root@YOUR_SERVER_IP << 'EOF'
sudo systemctl stop tor
sudo rm -rf /var/lib/tor/bisq-support
sudo mv /tmp/bisq-onion-keys /var/lib/tor/bisq-support
sudo chown -R debian-tor:debian-tor /var/lib/tor/bisq-support
sudo chmod 700 /var/lib/tor/bisq-support
sudo systemctl start tor
EOF
```

### Option B: Manual Transfer (More Secure)

```bash
# 1. On local machine, display the keys
cd ./onion-keys/bisq*/
echo "=== HOSTNAME ==="
cat hostname
echo ""
echo "=== PUBLIC KEY (base64) ==="
base64 hs_ed25519_public_key
echo ""
echo "=== SECRET KEY (base64) ==="
base64 hs_ed25519_secret_key

# 2. Copy the output to a secure location

# 3. On the server, recreate the keys
ssh root@YOUR_SERVER_IP

# Stop Tor
sudo systemctl stop tor

# Create directory
sudo mkdir -p /var/lib/tor/bisq-support

# Recreate files (paste your base64 values)
echo "your-base64-public-key" | base64 -d | sudo tee /var/lib/tor/bisq-support/hs_ed25519_public_key > /dev/null
echo "your-base64-secret-key" | base64 -d | sudo tee /var/lib/tor/bisq-support/hs_ed25519_secret_key > /dev/null
echo "bisqXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX.onion" | sudo tee /var/lib/tor/bisq-support/hostname > /dev/null

# Set correct permissions
sudo chown -R debian-tor:debian-tor /var/lib/tor/bisq-support
sudo chmod 700 /var/lib/tor/bisq-support
sudo chmod 600 /var/lib/tor/bisq-support/*

# Start Tor
sudo systemctl start tor
```

## Step 5: Verify on Server

```bash
# Check Tor logs
sudo journalctl -u tor -f

# Verify hostname file
sudo cat /var/lib/tor/bisq-support/hostname

# Test the service
torsocks curl http://$(sudo cat /var/lib/tor/bisq-support/hostname)
```

## Security Best Practices

### Secure Key Storage

1. **Backup the keys immediately**:
   ```bash
   # On local machine
   tar czf bisq-onion-backup-$(date +%Y%m%d).tar.gz ./onion-keys/bisq*/

   # Encrypt the backup
   gpg --symmetric --cipher-algo AES256 bisq-onion-backup-*.tar.gz

   # Store encrypted backup in multiple secure locations
   ```

2. **Delete local copies after transfer**:
   ```bash
   # Securely delete local keys
   shred -vfz -n 10 ./onion-keys/bisq*/hs_ed25519_secret_key
   rm -rf ./onion-keys/
   ```

3. **Never commit keys to git**:
   - The `.onion` private keys are cryptographic secrets
   - If leaked, someone can impersonate your service
   - Keys should only exist on the server and in encrypted backups

### Key Rotation

If you suspect key compromise:

1. Generate new vanity address locally
2. Transfer new keys to server
3. Update `TOR_HIDDEN_SERVICE` environment variable
4. Restart services
5. Announce new address through official channels

## Difficulty Estimates

**For mkp224o with 8 CPU cores**:

| Prefix Length | Pattern | Time Estimate | Difficulty |
|---------------|---------|---------------|------------|
| 4 chars | `bisq` | 5-30 seconds | Easy |
| 5 chars | `bisq2` | 2-10 minutes | Easy |
| 6 chars | `bisqai` | 30-60 minutes | Medium |
| 7 chars | `bisqsup` | 8-24 hours | Hard |
| 8 chars | `bisqsupp` | 10-30 days | Very Hard |
| 9+ chars | `bisqsupport` | Months/Years | Impractical |

**Note**: Each additional character increases difficulty by ~32x (for base32 charset)

## Recommended Patterns

For Bisq Support Agent, consider these patterns:

1. **`bisq` prefix** (4 chars) - Simple, recognizable, fast to generate
2. **`bisq2` prefix** (5 chars) - Version-specific, still fast
3. **`bisqai` prefix** (6 chars) - Indicates AI assistant, reasonable time
4. **`bisqhelp` prefix** (8 chars) - Descriptive but takes days

**Recommended**: Start with `bisq` (4 chars) - generates in seconds and is memorable.

## Example: Complete Workflow

```bash
# 1. Generate vanity address locally
mkp224o bisq -d ./onion-keys -n 1 -t 8 -v

# 2. View generated address
ONION_ADDR=$(cat ./onion-keys/bisq*/hostname)
echo "Generated: $ONION_ADDR"

# 3. Create encrypted backup
tar czf bisq-onion-backup.tar.gz ./onion-keys/bisq*/
gpg --symmetric --cipher-algo AES256 bisq-onion-backup.tar.gz

# 4. Transfer to server
scp -r ./onion-keys/bisq*/ root@YOUR_SERVER:/tmp/bisq-onion/

# 5. On server, install keys
ssh root@YOUR_SERVER << 'EOF'
sudo systemctl stop tor
sudo rm -rf /var/lib/tor/bisq-support
sudo mv /tmp/bisq-onion /var/lib/tor/bisq-support
sudo chown -R debian-tor:debian-tor /var/lib/tor/bisq-support
sudo chmod 700 /var/lib/tor/bisq-support
sudo chmod 600 /var/lib/tor/bisq-support/*
sudo systemctl start tor
sudo journalctl -u tor -f
EOF

# 6. Securely delete local keys
shred -vfz -n 10 ./onion-keys/bisq*/hs_ed25519_secret_key
rm -rf ./onion-keys/

# 7. Store encrypted backup in secure location
mv bisq-onion-backup.tar.gz.gpg ~/secure-backups/
```

## Troubleshooting

### mkp224o Not Finding Matches

```bash
# Increase verbosity to see progress
./mkp224o bisq -v -d ./onion-keys -n 1

# Use more threads
./mkp224o bisq -t $(nproc) -d ./onion-keys -n 1

# Try shorter prefix
./mkp224o bis -t 8 -d ./onion-keys -n 1
```

### Permission Errors on Server

```bash
# Fix ownership
sudo chown -R debian-tor:debian-tor /var/lib/tor/bisq-support

# Fix permissions
sudo chmod 700 /var/lib/tor/bisq-support
sudo chmod 600 /var/lib/tor/bisq-support/*

# Verify
sudo ls -la /var/lib/tor/bisq-support/
```

### Tor Won't Start

```bash
# Check configuration
sudo tor --verify-config

# Check logs
sudo journalctl -u tor --no-pager -n 50

# Test manually
sudo -u debian-tor tor -f /etc/tor/torrc
```

## References

- [mkp224o GitHub](https://github.com/cathugger/mkp224o) - Fast v3 vanity generator
- [Tor Onion Services](https://community.torproject.org/onion-services/) - Official docs
- [Tor Rendezvous Specification](https://gitweb.torproject.org/torspec.git/tree/rend-spec-v3.txt) - v3 onion technical spec

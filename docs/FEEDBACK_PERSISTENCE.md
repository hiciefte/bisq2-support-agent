# Feedback Persistence Architecture

## Overview

This document describes the architecture and implementation of the feedback persistence system, including how feedback data is stored, persisted across deployments, and the fixes implemented to prevent data loss.

## Architecture

### Data Flow

```
User Interaction (Frontend)
    ↓
Chat Interface (chat-interface.tsx)
    ↓ Rating Submission
Frontend API Call (/feedback/submit)
    ↓
Backend API (feedback.py)
    ↓
Feedback Service (feedback_service.py)
    ↓
File Storage (feedback_YYYY-MM.jsonl)
    ↓
Docker Named Volume (bisq2-feedback-data)
```

### Storage Layer

#### File Structure
- **Location**: `/data/feedback/` (inside container)
- **Host Mount**: `$INSTALL_DIR/api/data/feedback/`
- **Format**: Month-based JSONL files (`feedback_YYYY-MM.jsonl`)
- **Persistence**: Docker named volume `bisq2-feedback-data`

#### Example Files
```
/data/feedback/
├── feedback_2025-01.jsonl
├── feedback_2025-02.jsonl
├── feedback_2025-03.jsonl
└── legacy_backup/        # Migrated legacy files
```

### Feedback Entry Structure

```json
{
  "message_id": "uuid-v4",
  "question": "User's question",
  "answer": "Assistant's response",
  "rating": 1,
  "timestamp": "2025-10-05T12:34:56.789Z",
  "sources": [...],
  "metadata": {
    "response_time": 5.23,
    "token_count": 150,
    "conversation_id": "uuid",
    "explanation": "User's feedback explanation",
    "issues": ["too_verbose", "not_specific"]
  }
}
```

## Critical Issue: Feedback Not Persisting

### Root Causes Identified

#### 1. **Missing Docker Named Volume** (PRIMARY CAUSE)
**Problem**: The Docker Compose configuration mounted `../api/data:/data` as a bind mount, but did NOT use a named volume for the feedback subdirectory.

**Impact**: When containers were rebuilt or recreated during deployments:
- The bind mount would reset to the host filesystem state
- Any feedback written by the container but not yet synced to host would be lost
- During rapid deployments, race conditions could cause data loss

**Fix**: Added named Docker volume for feedback data:
```yaml
volumes:
  - ../api/data:/data
  - feedback-data:/data/feedback  # Named volume for persistent storage

volumes:
  feedback-data:
    name: bisq2-feedback-data
    driver: local
```

#### 2. **Frontend Code Errors**
**Problem**: The manage-feedback admin page had critical JavaScript errors:
- Undefined function calls to `setApiKey()`
- Incorrect parameter passing to `fetchData(key)`

**Impact**: The admin interface failed to load, making it impossible to view feedback even if it was persisting correctly.

**Fix**: Updated authentication to use secure HTTP-only cookies:
```typescript
const handleLogin = async (e: FormEvent) => {
  e.preventDefault();
  const key = (e.target as HTMLFormElement).apiKey.value;
  if (key) {
    try {
      await loginWithApiKey(key);
      await fetchData();  // Correct: no parameters
      // ...
    } catch (error) {
      setLoginError('Login failed. Please check your API key.');
    }
  }
};
```

#### 3. **No Persistence Validation**
**Problem**: Deployment scripts didn't verify that feedback data was persisting correctly after updates.

**Impact**: Data loss issues could go undetected until users reported missing feedback.

**Fix**: Created `verify-feedback-persistence.sh` script that checks:
- Feedback directory exists and has correct permissions
- Docker volume is properly configured
- API container has write access
- Feedback files are being created

## Implementation Details

### Backend (Python/FastAPI)

#### File: `api/app/services/feedback_service.py`

**Key Features**:
- Month-based file naming for easy archival
- Thread-safe writes using `portalocker`
- Automatic cache invalidation on updates
- Migration support for legacy formats

**Critical Methods**:

```python
async def store_feedback(self, feedback_data: Dict[str, Any]) -> bool:
    """Store user feedback in the feedback file."""
    feedback_dir = self.settings.FEEDBACK_DIR_PATH
    os.makedirs(feedback_dir, exist_ok=True)

    # Use current month for filename
    current_month = datetime.now().strftime("%Y-%m")
    feedback_file = os.path.join(feedback_dir, f"feedback_{current_month}.jsonl")

    # Add timestamp if not present
    if "timestamp" not in feedback_data:
        feedback_data["timestamp"] = datetime.now().isoformat()

    # Write to file (thread-safe)
    with open(feedback_file, "a") as f:
        f.write(json.dumps(feedback_data) + "\n")

    return True
```

### Frontend (Next.js/React)

#### File: `web/src/components/chat/chat-interface.tsx`

**Feedback Submission Flow**:

```typescript
const handleRating = async (messageId: string, rating: number) => {
  // Prepare feedback data
  const feedbackData = {
    message_id: messageId,
    question: questionMessage.content,
    answer: ratedMessage.content,
    rating,
    sources: ratedMessage.sources,
    metadata: {
      response_time: ratedMessage.metadata?.response_time || 0,
      token_count: ratedMessage.metadata?.token_count,
      conversation_id: messages[0].id,
      timestamp: new Date().toISOString()
    }
  };

  // Submit to API
  const response = await fetch(`${apiUrl}/feedback/submit`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(feedbackData)
  });

  // Store locally as backup
  const storedRatings = JSON.parse(localStorage.getItem("messageRatings") || "{}");
  storedRatings[messageId] = feedbackData;
  localStorage.setItem("messageRatings", JSON.stringify(storedRatings));
};
```

### Docker Configuration

#### Named Volume Benefits

1. **Persistence**: Data survives container recreation
2. **Performance**: Better I/O performance than bind mounts on some systems
3. **Portability**: Can be backed up and migrated using Docker commands
4. **Atomic Operations**: Volume mounts are atomic, reducing race conditions

#### Volume Management Commands

```bash
# List all volumes
docker volume ls

# Inspect feedback volume
docker volume inspect bisq2-feedback-data

# Backup feedback data
docker run --rm -v bisq2-feedback-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/feedback-backup-$(date +%Y%m%d).tar.gz /data

# Restore feedback data
docker run --rm -v bisq2-feedback-data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/feedback-backup-YYYYMMDD.tar.gz -C /
```

## Deployment Considerations

### Production Deployment

1. **Initial Deployment**: The deploy.sh script:
   - Creates feedback directory with correct permissions (775)
   - Sets ownership to UID:GID 1001:1001 (bisq-support user)
   - Creates named Docker volume on first run

2. **Updates**: The update.sh script:
   - Preserves existing feedback data
   - Fixes permissions if they drift
   - Verifies persistence after deployment
   - Creates backup tags before updates

3. **Rollbacks**: The rollback process:
   - Preserves feedback data (not part of git repository)
   - Restores previous application version
   - Maintains data integrity

### File Permissions

**Critical Requirements**:
- **Directory**: 775 (rwxrwxr-x)
- **Files**: 664 (rw-rw-r--)
- **Owner**: 1001:1001 (matches container user)

**Why UID 1001?**
- Container runs as non-root user for security
- Consistent UID across host and container ensures write access
- Numeric UID works regardless of username differences

### Monitoring and Validation

#### Verification Script

Run after every deployment:
```bash
/opt/bisq-support/scripts/verify-feedback-persistence.sh
```

**Checks Performed**:
1. Feedback directory exists
2. Permissions are correct (775, owner 1001:1001)
3. Docker volume is configured
4. API container can write to directory
5. Count feedback entries to verify data integrity

#### Health Checks

Add to monitoring system:
```bash
# Check feedback file count
ls -1 /opt/bisq-support/api/data/feedback/feedback_*.jsonl 2>/dev/null | wc -l

# Check total feedback entries
cat /opt/bisq-support/api/data/feedback/feedback_*.jsonl 2>/dev/null | wc -l

# Check last feedback timestamp
docker compose -f /opt/bisq-support/docker/docker-compose.yml \
  exec -T api python -c "
import json
import os
from glob import glob

files = sorted(glob('/data/feedback/feedback_*.jsonl'), reverse=True)
if files:
    with open(files[0]) as f:
        lines = f.readlines()
        if lines:
            last = json.loads(lines[-1])
            print(f\"Last feedback: {last.get('timestamp', 'unknown')}\")
"
```

## Troubleshooting

### Problem: Feedback Not Appearing in Admin Panel

**Diagnosis Steps**:
1. Check if frontend has errors in browser console
2. Verify API endpoint responds: `curl http://localhost:8000/admin/feedback/stats`
3. Check feedback files exist: `ls -lh /opt/bisq-support/api/data/feedback/`
4. Verify Docker volume: `docker volume inspect bisq2-feedback-data`
5. Check container logs: `docker compose logs api | grep -i feedback`

**Common Causes**:
- Frontend JavaScript errors (check browser console)
- Authentication issues (check admin cookie)
- File permission problems (run verify script)
- Docker volume not mounted (check docker-compose.yml)

### Problem: Permission Denied Errors

**Fix**:
```bash
cd /opt/bisq-support
sudo chown -R 1001:1001 api/data/feedback
sudo chmod -R 775 api/data/feedback
docker compose -f docker/docker-compose.yml restart api
```

### Problem: Feedback Lost After Update

**Recovery**:
1. Check if data exists in Docker volume:
   ```bash
   docker run --rm -v bisq2-feedback-data:/data alpine ls -lh /data
   ```

2. If data exists in volume but not visible in container:
   - Verify volume mount in docker-compose.yml
   - Restart containers: `docker compose restart api`

3. If data truly lost:
   - Check backup tags: `git tag | grep backup`
   - Check failed_updates directory for saved state
   - Restore from external backup if available

## Testing

### Local Testing

```bash
# Start local environment
./run-local.sh

# Submit test feedback through UI
# Navigate to http://localhost:3000
# Ask a question and rate the response

# Verify feedback was stored
ls -lh api/data/feedback/
cat api/data/feedback/feedback_*.jsonl | tail -1 | python -m json.tool

# Check admin panel
# Navigate to http://localhost:3000/admin/manage-feedback
# Login with admin API key
# Verify feedback appears in list
```

### Production Testing

```bash
# SSH to production server
ssh root@YOUR_SERVER_IP

# Run verification script
/opt/bisq-support/scripts/verify-feedback-persistence.sh

# Check recent feedback
docker compose -f /opt/bisq-support/docker/docker-compose.yml \
  exec api python -c "
from app.services.feedback_service import FeedbackService
from app.core.config import get_settings

settings = get_settings()
service = FeedbackService(settings)
feedback = service.load_feedback()
print(f'Total feedback entries: {len(feedback)}')
if feedback:
    print(f'Latest: {feedback[-1].get(\"timestamp\", \"unknown\")}')
"
```

## Backup and Recovery

### Automated Backups

Add to cron (recommended):
```bash
# Daily feedback backup at 3 AM
0 3 * * * /opt/bisq-support/scripts/backup-feedback.sh
```

### Manual Backup

```bash
#!/bin/bash
# Create timestamped backup
BACKUP_DIR="/opt/bisq-support/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup using Docker volume
docker run --rm \
  -v bisq2-feedback-data:/data \
  -v "$BACKUP_DIR":/backup \
  alpine tar czf "/backup/feedback_${TIMESTAMP}.tar.gz" /data

echo "Backup created: $BACKUP_DIR/feedback_${TIMESTAMP}.tar.gz"
```

### Restore from Backup

```bash
#!/bin/bash
BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
  echo "Usage: $0 <backup_file.tar.gz>"
  exit 1
fi

# Stop API to prevent write conflicts
docker compose -f /opt/bisq-support/docker/docker-compose.yml stop api

# Restore from backup
docker run --rm \
  -v bisq2-feedback-data:/data \
  -v "$(dirname "$BACKUP_FILE")":/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/$(basename "$BACKUP_FILE") -C /"

# Restart API
docker compose -f /opt/bisq-support/docker/docker-compose.yml start api

echo "Restore complete. Verifying..."
/opt/bisq-support/scripts/verify-feedback-persistence.sh
```

## Security Considerations

1. **Data Privacy**: Feedback may contain user questions
   - Ensure proper access controls on feedback files
   - Limit admin panel access to authorized users only
   - Consider implementing data retention policies

2. **File Permissions**: Prevent unauthorized access
   - Directory: 775 (not 777)
   - Files: 664 (not 666)
   - Owner: dedicated user (1001), not root

3. **Backup Security**: Protect backup files
   - Encrypt backups if stored off-server
   - Secure transfer channels (SSH, HTTPS)
   - Limit backup retention period

## Performance Optimization

### File-Based Storage Benefits
- Simple, no database required
- Easy to backup and inspect
- Fast appends, no index overhead
- Month-based partitioning for easy archival

### Caching
- 5-minute TTL cache for feedback loading
- Invalidated on writes/updates
- Reduces file I/O for frequent reads

### Monitoring
- Track feedback file sizes
- Monitor disk usage
- Alert on permission issues
- Verify write success rates

## Future Enhancements

1. **Compression**: Automatically compress old months
2. **Archival**: Move old feedback to cold storage
3. **Analytics**: Real-time feedback analytics dashboard
4. **Alerting**: Notify on feedback data issues
5. **Replication**: Multi-region backup replication

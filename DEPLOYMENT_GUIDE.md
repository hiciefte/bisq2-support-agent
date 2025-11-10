# Deployment Guide for PR #95: FAQ Animation Fix & Bulk Actions UI

This guide provides step-by-step instructions for deploying the changes from PR #95 to production.

## Overview

**PR #95** includes:
- Fix for FAQ animation stutter when collapsing expanded FAQs
- Refined bulk actions UI from three merged feature branches
- Bisq version field for FAQs
- Inline FAQ editing with keyboard navigation
- Manual vector store rebuild system

## Pre-Deployment Checklist

Before deploying, ensure:
- [ ] All GitHub Actions CI/CD checks pass (green checkmarks)
- [ ] CodeRabbitAI review comments have been addressed
- [ ] Local testing completed successfully
- [ ] Database backups are current (if applicable)
- [ ] Server access credentials are available

## Deployment Steps

### 1. Connect to Production Server

```bash
# Replace with actual server credentials
ssh root@production-server-ip
cd /opt/bisq-support
```

### 2. Backup Current State

```bash
# Create backup of current deployment
./scripts/backup.sh

# Or manually backup FAQ data (CRITICAL)
cp api/data/extracted_faq.jsonl api/data/extracted_faq.jsonl.backup.$(date +%Y%m%d_%H%M%S)
```

### 3. Deploy Using Automated Script

```bash
# The update.sh script handles everything automatically:
# - Git pull with FAQ data preservation
# - Requirements detection and rebuild
# - Service restart with zero downtime
# - Health checks and rollback on failure

./scripts/update.sh
```

**What the script does:**
- Pulls latest changes from `main` branch
- Backs up and restores `extracted_faq.jsonl` (prevents data loss)
- Detects changed files and determines rebuild requirements
- Rebuilds only changed containers (nginx, api, web, bisq2-api)
- Keeps nginx running during backend updates (shows maintenance page)
- Waits for health checks before completing
- Rolls back automatically if deployment fails

### 4. Manual Deployment (If Automated Script Unavailable)

If you need to deploy manually:

```bash
# Stop backend services (keep nginx running for maintenance page)
docker compose -f docker/docker-compose.yml stop api web bisq2-api

# Backup FAQ data
cp api/data/extracted_faq.jsonl /tmp/faq_backup.jsonl

# Pull latest changes
git pull origin main

# Restore FAQ data
cp /tmp/faq_backup.jsonl api/data/extracted_faq.jsonl

# Check for requirements changes
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml run --build --rm api pip-compile api/requirements.in -o api/requirements.txt --upgrade --no-strip-extras

# Rebuild and restart backend containers
docker compose -f docker/docker-compose.yml up -d --build api web bisq2-api

# Wait for services to become healthy
sleep 30
docker compose -f docker/docker-compose.yml ps

# Verify health
curl -f http://localhost/health || echo "Health check failed!"
```

### 5. Post-Deployment Verification

```bash
# Check service status
docker compose -f docker/docker-compose.yml ps

# Check logs for errors
docker compose -f docker/docker-compose.yml logs --tail=50 api
docker compose -f docker/docker-compose.yml logs --tail=50 web

# Verify FAQ system is working
curl -X GET http://localhost/api/admin/faqs -H "X-API-Key: $ADMIN_API_KEY"

# Test vector store rebuild (optional)
curl -X POST http://localhost/api/admin/vectorstore/rebuild -H "X-API-Key: $ADMIN_API_KEY"
```

### 6. Test Critical Functionality

Access the admin interface and verify:

1. **FAQ Management Page** (`/admin/manage-faqs`):
   - FAQs load correctly with pagination
   - Clicking expanded FAQ selects it without collapsing ✓
   - Arrow icon collapses expanded FAQs smoothly ✓
   - Keyboard shortcuts work (j/k navigation, e/d/v actions, a for select all)
   - Inline editing works correctly
   - Bisq version filtering functions properly

2. **Vector Store Status**:
   - Status banner shows current rebuild state
   - Manual rebuild trigger works
   - Pending changes counter is accurate

3. **Bulk Actions**:
   - Bulk selection mode activates correctly
   - Bulk operations (delete, verify) work
   - Selection state persists correctly

## Rollback Procedure

If issues arise after deployment:

```bash
# Option 1: Use automated rollback
./scripts/rollback.sh

# Option 2: Manual rollback
git log --oneline -5  # Find previous commit hash
git checkout <previous-commit-hash>
docker compose -f docker/docker-compose.yml up -d --build

# Restore FAQ data from backup if needed
cp api/data/extracted_faq.jsonl.backup.YYYYMMDD_HHMMSS api/data/extracted_faq.jsonl
docker compose -f docker/docker-compose.yml restart api
```

## Configuration Changes

This PR does not require environment variable changes, but verify:

```bash
# Check .env file has required variables
cat docker/.env | grep -E "ADMIN_API_KEY|CORS_ORIGINS|COOKIE_SECURE"
```

If accessing from a new IP/domain, update CORS settings:

```bash
# Edit docker/.env
CORS_ORIGINS=http://localhost:3000,http://production-ip,https://yourdomain.com

# Restart services
./scripts/restart.sh
```

## Database Migrations

No database migrations required for this PR.

## Known Issues & Considerations

1. **Node Modules Volume**:
   - New npm dependencies added (framer-motion)
   - Docker volume rebuild handled automatically by update.sh
   - Local dev: Run `docker volume rm docker_web_node_modules && docker compose up -d --build web`

2. **FAQ Data Protection**:
   - `extracted_faq.jsonl` is NOT tracked by git (prevents production data loss)
   - Always use backup/restore during git operations
   - The `update.sh` script handles this automatically

3. **Requirements.txt Updates**:
   - Several Python dependencies were updated (black, fastapi, langchain-core, etc.)
   - Requirements are automatically compiled and applied by update.sh
   - Manual check: `docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml run --rm api pip-compile api/requirements.in -o api/requirements.txt --upgrade --no-strip-extras`

## Monitoring After Deployment

Monitor these metrics for 24 hours post-deployment:

```bash
# Check error rates in logs
docker compose -f docker/docker-compose.yml logs -f api | grep -i error

# Monitor resource usage
docker stats

# Check Grafana dashboard (if configured)
# Navigate to http://production-ip:3001
```

## Support Contacts

- **GitHub PR**: https://github.com/hiciefte/bisq2-support-agent/pull/95
- **Documentation**: See CLAUDE.md for development workflow
- **Logs**: `docker/logs/` directory on production server

## Success Criteria

Deployment is successful when:
- [ ] All Docker containers are running and healthy
- [ ] FAQ management page loads without errors
- [ ] FAQ animation is smooth (no stutter on collapse)
- [ ] Keyboard shortcuts work correctly
- [ ] Vector store rebuild functions properly
- [ ] No error logs in API or web containers
- [ ] Response times are within acceptable range

## Appendix: Technical Details

### Changes Summary

**Frontend** (`web/src/app/admin/manage-faqs/page.tsx`):
- Modified CollapsibleTrigger onClick handler (lines 2174-2194)
- Added arrow click detection using `closest('svg')`
- Conditional state updates to prevent animation conflicts

**Backend**:
- Added Bisq version field to FAQ model
- Vector store rebuild endpoints and status tracking
- Inline editing support

**Infrastructure**:
- Docker entrypoint script for web container node_modules
- Updated Python dependencies

### Animation Fix Technical Explanation

The animation stutter occurred because two animation systems were running simultaneously:
1. **Framer Motion's layout animation** (triggered by `selectedIndex` state change)
2. **Collapsible's internal collapse animation**

**Solution**: Skip the `setSelectedIndex()` call when clicking the arrow icon on an expanded FAQ, preventing the layout animation from triggering during collapse. Only the Collapsible animation runs, eliminating the conflict.

### Deployment Automation

The `scripts/update.sh` script provides:
- **Zero downtime**: Nginx stays running, shows maintenance page during updates
- **Selective rebuilds**: Only rebuilds changed containers (api, web, bisq2-api, nginx)
- **Data protection**: Automatic FAQ data backup/restore
- **Health checks**: Verifies services before completion
- **Auto-rollback**: Reverts on failure

Excluded from rebuilds: prometheus, grafana, node-exporter, scheduler (monitoring stack stays running).

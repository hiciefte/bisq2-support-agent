# AISuite Migration - Production Deployment Plan

**PR**: https://github.com/hiciefte/bisq2-support-agent/pull/78
**Date Prepared**: 2025-10-14
**Prepared For**: deployment-engineer subagent
**Critical Level**: MEDIUM - Configuration change, no breaking API changes

## Overview

This deployment migrates the application from the old multi-provider LLM system (with LLM_PROVIDER setting) to AISuite for unified LLM interface. The migration removes the XAI provider support and simplifies to OpenAI-only via AISuite, while enabling future multi-provider support through AISuite's interface.

**Key Changes**:
- Removes `LLM_PROVIDER` setting (no longer needed)
- Removes XAI provider support (`XAI_API_KEY`, `XAI_MODEL` settings removed)
- Migrates to AISuite for OpenAI access
- Updates OPENAI_MODEL format to include provider prefix
- Adds LLM_TEMPERATURE configuration
- Major dependency cleanup (removes langchain-community, langchain-huggingface, langchain-xai)

## Pre-Deployment Checklist

### 1. Verify Environment File Exists
```bash
# Check production .env file exists
if [ ! -f /opt/bisq-support/docker/.env ]; then
    echo "ERROR: Production .env file not found"
    exit 1
fi
```

### 2. Backup Current Configuration
```bash
# Create backup of current .env
cd /opt/bisq-support/docker
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
```

## Required Configuration Changes

### 1. Update OPENAI_MODEL Format

**Current Format** (will cause startup failure):
```bash
OPENAI_MODEL=gpt-4o-mini
```

**New Format** (required):
```bash
# Model ID with provider prefix for AISuite (format: "provider:model")
# Examples: openai:gpt-4o-mini, openai:gpt-4o, anthropic:claude-3-5-sonnet
OPENAI_MODEL=openai:gpt-4o-mini
```

**Action Required**:
```bash
cd /opt/bisq-support/docker

# Check current value
grep "^OPENAI_MODEL=" .env

# Update to provider-prefixed format
# If using gpt-4o-mini, change to: openai:gpt-4o-mini
# If using gpt-4o, change to: openai:gpt-4o
# If using o3-mini, change to: openai:o3-mini

# Example sed command (adjust model name as needed):
sed -i 's/^OPENAI_MODEL=gpt-4o-mini$/OPENAI_MODEL=openai:gpt-4o-mini/' .env
```

### 2. Add LLM_TEMPERATURE (Optional, has default)

**New Setting**:
```bash
# Temperature for LLM responses (0.0-2.0, default: 0.7)
LLM_TEMPERATURE=0.7
```

**Action**:
```bash
# Check if LLM_TEMPERATURE exists
if ! grep -q "^LLM_TEMPERATURE=" .env; then
    echo "# Temperature for LLM responses (0.0-2.0, default: 0.7)" >> .env
    echo "LLM_TEMPERATURE=0.7" >> .env
fi
```

### 3. Remove Deprecated Settings (Critical)

**Settings to Remove** (will cause errors if left in .env):
```bash
cd /opt/bisq-support/docker

# Remove old multi-provider settings
sed -i '/^LLM_PROVIDER=/d' .env
sed -i '/^XAI_API_KEY=/d' .env
sed -i '/^XAI_MODEL=/d' .env

# Verify removal
echo "=== Verifying deprecated settings removed ==="
if grep -q "^LLM_PROVIDER=" .env; then
    echo "ERROR: LLM_PROVIDER still present"
    exit 1
fi
if grep -q "^XAI_API_KEY=" .env; then
    echo "ERROR: XAI_API_KEY still present"
    exit 1
fi
echo "✓ All deprecated settings removed"
```

### 4. Verify Other Settings (No Changes Required)

These settings remain unchanged:
- `OPENAI_API_KEY` - No change (still required)
- `OPENAI_EMBEDDING_MODEL` - No change (still uses OpenAI embeddings directly)
- `MAX_TOKENS` - No change
- `ADMIN_API_KEY` - No change
- `CORS_ORIGINS` - No change
- All other environment variables - No change

## Code Changes Summary

### Files Modified

**Configuration Changes**:
1. `api/app/core/config.py` - Removed LLM_PROVIDER, XAI settings; fixed CORS type; added LLM_TEMPERATURE; updated model format
2. `docker/.env.example` - Updated model format documentation, removed XAI settings
3. `api/.env.example` - Updated model format documentation, removed XAI settings

**Service Changes**:
4. `api/app/services/faq_service.py` - Migrated to modular architecture with AISuite
5. `api/app/services/faq/faq_extractor.py` - New modular component using AISuite client
6. `api/app/services/simplified_rag_service.py` - Migrated to modular architecture
7. `api/app/services/rag/llm_provider.py` - New modular component with AISuite and temperature support
8. `api/app/services/feedback_service.py` - Migrated to modular architecture

**Dependencies**:
9. `api/requirements.in` - Added aisuite, removed langchain-community, langchain-huggingface, langchain-xai
10. `api/requirements.txt` - Generated from requirements.in with new dependencies

**Testing Infrastructure** (development only, no production impact):
11. Pre-commit hooks configuration
12. Pytest test suite (58 test cases)
13. Test fixtures and documentation

### Critical Fixes
- **CORS_ORIGINS type** - Changed from `list[str]` to `str` with validator to handle Pydantic parsing
- **Deprecated settings removal** - LLM_PROVIDER, XAI_API_KEY, XAI_MODEL must be removed from production .env
- **Model format change** - OPENAI_MODEL must use provider prefix (e.g., `openai:gpt-4o-mini`)

## Deployment Steps

### 1. Pull Latest Code
```bash
cd /opt/bisq-support
git fetch origin
git pull origin main
```

### 2. Update Environment Configuration
```bash
cd /opt/bisq-support/docker

# Step 1: Remove deprecated settings (critical)
echo "=== Removing deprecated settings ==="
sed -i '/^LLM_PROVIDER=/d' .env
sed -i '/^XAI_API_KEY=/d' .env
sed -i '/^XAI_MODEL=/d' .env

# Verify removal
if grep -qE "^(LLM_PROVIDER|XAI_API_KEY|XAI_MODEL)=" .env; then
    echo "ERROR: Failed to remove deprecated settings"
    grep -E "^(LLM_PROVIDER|XAI_API_KEY|XAI_MODEL)=" .env
    exit 1
fi
echo "✓ Deprecated settings removed"

# Step 2: Update OPENAI_MODEL format
echo "=== Updating OPENAI_MODEL format ==="
CURRENT_MODEL=$(grep "^OPENAI_MODEL=" .env | cut -d'=' -f2-)
echo "Current OPENAI_MODEL: $CURRENT_MODEL"

# Check if already in correct format (contains colon)
if echo "$CURRENT_MODEL" | grep -q ":"; then
    echo "✓ OPENAI_MODEL already in correct format"
else
    echo "Migrating to provider-prefixed format..."

    # Update based on current model
    case "$CURRENT_MODEL" in
        "gpt-4o-mini")
            sed -i 's/^OPENAI_MODEL=gpt-4o-mini$/OPENAI_MODEL=openai:gpt-4o-mini/' .env
            echo "✓ Updated to openai:gpt-4o-mini"
            ;;
        "gpt-4o")
            sed -i 's/^OPENAI_MODEL=gpt-4o$/OPENAI_MODEL=openai:gpt-4o/' .env
            echo "✓ Updated to openai:gpt-4o"
            ;;
        "o3-mini")
            sed -i 's/^OPENAI_MODEL=o3-mini$/OPENAI_MODEL=openai:o3-mini/' .env
            echo "✓ Updated to openai:o3-mini"
            ;;
        *)
            echo "WARNING: Unrecognized model '$CURRENT_MODEL'"
            echo "Please manually update to format: openai:$CURRENT_MODEL"
            exit 1
            ;;
    esac
fi

# Step 3: Add LLM_TEMPERATURE if missing
echo "=== Adding LLM_TEMPERATURE ==="
if ! grep -q "^LLM_TEMPERATURE=" .env; then
    echo "" >> .env
    echo "# Temperature for LLM responses (0.0-2.0, default: 0.7)" >> .env
    echo "LLM_TEMPERATURE=0.7" >> .env
    echo "✓ Added LLM_TEMPERATURE=0.7"
else
    echo "✓ LLM_TEMPERATURE already present"
fi

# Step 4: Verify final configuration
echo ""
echo "=== Final Configuration ==="
grep "^OPENAI_MODEL=" .env
grep "^LLM_TEMPERATURE=" .env
grep "^OPENAI_API_KEY=" .env | sed 's/=.*/=<redacted>/'
echo ""
echo "✓ Configuration update complete"
```

### 3. Run Automated Update Script
```bash
cd /opt/bisq-support/scripts
./update.sh
```

The `update.sh` script will:
- Create backup reference tag
- Pull latest code
- Detect changes (Python dependencies changed → rebuild required)
- Stop containers (nginx stays running, shows maintenance page)
- Rebuild API container with new code
- Restart all services
- Run health checks
- Test chat endpoint functionality
- Automatically rollback if anything fails

### 4. Monitor Deployment
```bash
# Watch service status
watch -n 2 'docker compose -f /opt/bisq-support/docker/docker-compose.yml ps'

# Follow API logs
docker compose -f /opt/bisq-support/docker/docker-compose.yml logs -f api
```

## Verification Steps

### 1. Check Service Health
```bash
cd /opt/bisq-support/docker

# Check all services are healthy
docker compose ps

# Expected output: All services should show (healthy) status
# If API shows (unhealthy), check logs immediately
```

### 2. Verify Configuration Loading
```bash
# Check API logs for successful startup
docker compose logs api --tail=50 | grep -i "aisuite\|temperature\|model"

# Should see:
# - "LLM provider initialized with AISuite client"
# - "LLM initialized with model: openai:gpt-4o-mini" (or your model)
# - No "SettingsError" or "error parsing" messages
```

### 3. Test Chat Endpoint
```bash
# Test chat functionality
ADMIN_KEY=$(cat /opt/bisq-support/runtime_secrets/prometheus_admin_key)

curl -X POST http://localhost/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is Bisq?", "conversation_id": "test-deploy"}'

# Should return JSON response with "answer" field
# No errors or 500 status
```

### 4. Test FAQ Extraction (Optional)
```bash
# Test FAQ service initialization
docker compose exec api python -c "
from app.services.faq_service import FAQService
from app.core.config import get_settings
settings = get_settings()
faq_service = FAQService.get_instance(settings)
print('FAQ service initialized successfully')
"

# Should print: "FAQ service initialized successfully"
# No ImportError or initialization errors
```

### 5. Check Admin Interface
```bash
# Access admin interface at: http://<your-server-ip>/admin
# Login with ADMIN_API_KEY
# Verify FAQs page loads
# Verify feedback page loads
```

## Rollback Plan

If deployment fails, the `update.sh` script automatically rolls back. Manual rollback if needed:

### Automatic Rollback
The `update.sh` script handles rollback automatically on:
- Build failures
- Health check failures
- Chat endpoint test failures

Failed state is saved to `/opt/bisq-support/failed_updates/<timestamp>/` for debugging.

### Manual Rollback Steps
```bash
cd /opt/bisq-support

# Find previous working version
git log --oneline -20

# Reset to previous commit (replace COMMIT_HASH)
git reset --hard COMMIT_HASH

# Restore previous .env
cd docker
cp .env.backup.<timestamp> .env

# Rebuild and restart
cd /opt/bisq-support/docker
docker compose down
docker compose up -d --build

# Wait for services to be healthy
sleep 30
docker compose ps
```

## Troubleshooting

### Issue 1: API Container Fails to Start

**Symptoms**:
```
SettingsError: error parsing value for field "CORS_ORIGINS"
```

**Cause**: String CORS_ORIGINS not being converted to list

**Fix**: Already implemented in `config.py` with `mode="before"` validator

### Issue 2: Model Not Found Error

**Symptoms**:
```
Error: Model "gpt-4o-mini" not found
```

**Cause**: Missing provider prefix in OPENAI_MODEL

**Fix**:
```bash
cd /opt/bisq-support/docker
# Add provider prefix
sed -i 's/^OPENAI_MODEL=\(.*\)$/OPENAI_MODEL=openai:\1/' .env
docker compose restart api
```

### Issue 3: AISuite Import Error

**Symptoms**:
```
ModuleNotFoundError: No module named 'aisuite'
```

**Cause**: Requirements not installed (shouldn't happen with rebuild)

**Fix**:
```bash
cd /opt/bisq-support/docker
docker compose up -d --build api
```

### Issue 4: Temperature Not Applied

**Symptoms**: LLM responses seem deterministic or off

**Check**:
```bash
cd /opt/bisq-support/docker
grep "^LLM_TEMPERATURE=" .env

# If missing, add it:
echo "LLM_TEMPERATURE=0.7" >> .env
docker compose restart api
```

## Post-Deployment Verification

### 1. Monitor for 15 Minutes
```bash
# Watch logs for errors
docker compose -f /opt/bisq-support/docker/docker-compose.yml logs -f api | grep -i error

# Monitor resource usage
docker stats docker-api-1 --no-stream
```

### 2. Test All Endpoints
```bash
# Health check
curl http://localhost/health

# Chat endpoint
curl -X POST http://localhost/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Test", "conversation_id": "test"}'

# Admin endpoints (with authentication)
curl http://localhost/api/admin/faqs

# Feedback endpoint
curl -X POST http://localhost/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"test","message_id":"test","feedback":"positive"}'
```

### 3. Check Prometheus Metrics
```bash
# Check metrics are being collected
curl http://localhost/metrics | grep -i "chat\|faq\|rag"
```

### 4. Verify Grafana Dashboard
- Access Grafana at `http://<server-ip>:3001`
- Check "Bisq Support Agent" dashboard
- Verify metrics are updating
- Check for any alerts

## Dependencies

### Python Packages

**Added**:
- `aisuite==0.1.12` - Unified LLM interface
- `pre-commit` - Development dependency (no production impact)
- `flake8` - Development dependency (no production impact)

**Removed**:
- `langchain-community` - Replaced by AISuite for LLM providers
- `langchain-huggingface` - No longer needed
- `langchain-xai` - XAI provider removed

**Unchanged**:
- `openai<2.0.0` - Still used for embeddings (pinned to 1.x)
- `langchain-openai` - Still used for embeddings only
- `langchain-core` - Core LangChain functionality
- `langchain-chroma` - Vector store integration
- `httpx==0.27.2` - Pinned for aisuite compatibility
- All other dependencies unchanged

**Version Updates**:
- Various dependency updates from pip-compile (patch versions)
- See requirements.txt diff in PR #78 for complete list

### Environment Variables

**Required**:
- `OPENAI_API_KEY` - **REQUIRED** (no change)
- `OPENAI_MODEL` - **REQUIRED** (format changed to provider-prefixed)
- `ADMIN_API_KEY` - **REQUIRED** (no change)

**Optional**:
- `LLM_TEMPERATURE` - Optional (default: 0.7)

**Removed** (critical - must delete from .env):
- `LLM_PROVIDER` - No longer used
- `XAI_API_KEY` - XAI provider removed
- `XAI_MODEL` - XAI provider removed

## Performance Impact

- **Expected**: None - AISuite is a thin wrapper
- **API Response Time**: No change expected
- **Memory Usage**: Negligible increase (~1-2MB)
- **CPU Usage**: No change
- **Startup Time**: May increase by 1-2 seconds during initialization

## Security Considerations

- **API Keys**: No changes to key handling
- **Authentication**: No changes to authentication flow
- **Secrets Management**: No new secrets required
- **Network**: No changes to network configuration

## Future Enhancements Enabled

This migration enables:
1. Multi-provider support (Anthropic, Cohere, etc.)
2. Provider failover and load balancing
3. Model comparison and A/B testing
4. Cost optimization by provider selection
5. Rate limit management across providers

## Documentation Updates

Updated files:
- `docker/.env.example` - Model format documentation, removed XAI settings
- `api/.env.example` - Model format documentation, removed XAI settings
- `CLAUDE.md` - Deployment instructions reference
- This file - Complete deployment guide

## Additional Changes in PR #78 (No Production Impact)

The following changes are included in PR #78 but do not affect production deployment:

**Testing Infrastructure** (development only):
- Pre-commit hooks for code quality (.pre-commit-config.yaml)
- Pytest test suite (58 test cases for FAQService, FeedbackService, RAGService)
- Test fixtures and documentation (api/tests/)
- Playwright E2E testing setup

**Code Quality** (development only):
- CI/CD pipeline enhancements (black, isort, mypy checks)
- Modular service architecture (43.9% complexity reduction)
- Type safety improvements

**Documentation** (informational):
- Test documentation (api/tests/README.md)
- Pre-commit setup guide (.pre-commit-setup.md)

These changes improve code quality and developer experience but require no production configuration or deployment actions.

## Success Criteria

Deployment is successful when:
- ✅ All Docker containers healthy
- ✅ API responds to `/health` endpoint
- ✅ Chat endpoint returns valid responses
- ✅ Admin interface accessible and functional
- ✅ FAQ extraction works (if scheduled job runs)
- ✅ Feedback submission works
- ✅ Prometheus metrics updating
- ✅ Grafana dashboard showing data
- ✅ No errors in application logs for 15 minutes

## Timeline

- **Preparation**: 5 minutes (backup, environment updates)
- **Deployment**: 10-15 minutes (pull, rebuild, restart, health checks)
- **Verification**: 15 minutes (endpoint tests, monitoring)
- **Total**: 30-35 minutes

## Support Contact

If issues arise:
1. Check logs: `docker compose logs api`
2. Check this troubleshooting section
3. Review failed deployment details in `/opt/bisq-support/failed_updates/`
4. Rollback if necessary (automatic or manual)

## Appendix A: Complete Configuration Example

**Production `.env` After Migration**:
```bash
# OpenAI API Configuration
OPENAI_API_KEY=sk-proj-...
# Model ID with provider prefix for AISuite (format: "provider:model")
OPENAI_MODEL=openai:gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
MAX_TOKENS=4096
# Temperature for LLM responses (0.0-2.0, default: 0.7)
LLM_TEMPERATURE=0.7

# Admin Configuration
ADMIN_API_KEY=<from /opt/bisq-support/runtime_secrets/prometheus_admin_key>
COOKIE_SECURE=false

# CORS Configuration
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://<your-server-ip>

# Bisq2 API Configuration
BISQ_API_URL=http://bisq2-api:8090

# (All other settings unchanged)
```

## Appendix B: Quick Reference Commands

```bash
# Navigate to installation
cd /opt/bisq-support

# Pull latest code
git pull origin main

# Edit environment
cd docker
nano .env

# Update with script
cd /opt/bisq-support/scripts
./update.sh

# Manual rebuild if needed
cd /opt/bisq-support/docker
docker compose down
docker compose up -d --build

# Check status
docker compose ps

# View logs
docker compose logs -f api

# Test endpoint
curl -X POST http://localhost/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Test"}'

# Rollback
git reset --hard COMMIT_HASH
docker compose down && docker compose up -d --build
```

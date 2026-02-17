# Alertmanager Configuration

This directory contains Alertmanager configuration for routing Prometheus alerts to Matrix.

## Architecture

Alerts flow through the following path:

```
Prometheus → Alertmanager → API (/alertmanager/alerts) → Matrix Room
```

The API service handles Matrix notifications using password-based authentication with:
- Session persistence (no token timeouts)
- Automatic token refresh on auth failures
- Circuit breaker protection to prevent account lockout
- Unified auth system with Matrix Shadow Mode polling

## Matrix Integration Setup

### Prerequisites

1. **Matrix Account**: Create a Matrix account (e.g., on matrix.org or your own homeserver)
2. **Matrix Room**: Create a room for alerts (e.g., "#bisq-alerts:matrix.org")
3. **Matrix Bot User**: Recommended to create a dedicated bot user for sending alerts

### Environment Variables

Add the following to your `.env` file in `/docker/.env` (production) or `/docker/.env` (local):

```bash
# Matrix Configuration for Alert Notifications
# These variables are used by both Shadow Mode polling AND alert notifications
MATRIX_HOMESERVER_URL=https://matrix.org
MATRIX_USER=@bisq-alerts:matrix.org
MATRIX_PASSWORD=your_secure_password
MATRIX_ALERT_ROOM=!RoomIdHere:matrix.org
MATRIX_ALERT_SESSION_FILE=/data/matrix_alert_session.json
```

**Note**: The same Matrix credentials are used for both:
- Shadow Mode (polling staff answers for FAQ extraction)
- Alert notifications (forwarding Prometheus alerts)

**Finding Room ID**:
1. In Element (Matrix client), go to Room Settings → Advanced
2. Copy the "Internal Room ID" (starts with `!`)

### Alert Severity Levels

Alerts are grouped by severity:

- **Critical** (`severity: critical`): Immediate action required
  - RAG error rate > 5%
  - RAG latency > 5 seconds
  - Containers down or unhealthy
  - Notifications sent immediately, repeated every 30 minutes

- **Warning** (`severity: warning`): Review within hours
  - FAQ/Wiki extraction failures or stale data
  - Low user satisfaction
  - High RAG costs
  - Notifications grouped for 1 minute, repeated every 12 hours

### Alert Configuration

#### Alert Rules (`docker/prometheus/alert_rules.yml`)

- Contains 10 alert rules (4 critical, 6 warning)
- Configured thresholds and evaluation periods
- Add custom alerts as needed

#### Alertmanager Config (`docker/alertmanager/alertmanager.yml`)


- Routing rules by severity
- Notification grouping and timing
- Inhibition rules to prevent notification spam
- Webhook URL: `http://api:8000/alertmanager/alerts`

### Testing Alerts

To test the Matrix integration:

1. **Start services**:

   ```bash
   docker compose up -d alertmanager api
   ```

2. **Check API alertmanager health**:

   ```bash
   curl http://localhost:8000/alertmanager/health
   # Expected: {"status":"healthy"}
   ```

3. **Send a test alert directly to API**:

   ```bash
   curl -X POST http://localhost:8000/alertmanager/alerts \
     -H "Content-Type: application/json" \
     -d '{
       "receiver": "matrix-notifications",
       "status": "firing",
       "alerts": [{
         "status": "firing",
         "labels": {
           "alertname": "TestAlert",
           "severity": "warning"
         },
         "annotations": {
           "summary": "Test alert from manual trigger",
           "description": "This is a test notification"
         }
       }]
     }'
   ```

4. **Trigger a test alert via Prometheus**:

   ```bash
   # Access Alertmanager UI
   # Visit http://localhost:9093 (if exposed)

   # Or send test alert via Alertmanager API
   curl -X POST http://localhost:9093/api/v1/alerts \
     -H "Content-Type: application/json" \
     -d '[{
       "labels": {
         "alertname": "TestAlert",
         "severity": "warning"
       },
       "annotations": {
         "summary": "Test alert from Alertmanager",
         "description": "This is a test notification"
       }
     }]'
   ```

5. **Verify alert appears in Matrix room**

### Troubleshooting

#### Alerts not appearing in Matrix

1. **Check API logs for alert processing**:

   ```bash
   docker compose logs api | grep -i "alert"
   ```

2. **Check alertmanager health endpoint**:

   ```bash
   curl http://localhost:8000/alertmanager/health
   ```

3. **Verify Matrix Shadow Mode is enabled**:

   ```bash
   docker compose logs api | grep -i "matrix"
   ```

4. **Test Matrix login manually**:

   ```bash
   curl -X POST https://matrix.org/_matrix/client/r0/login \
     -H "Content-Type: application/json" \
     -d '{
       "type": "m.login.password",
       "user": "bisq-alerts",
       "password": "your_password"
     }'
   ```

5. **Check Alertmanager connectivity to API**:

   ```bash
   # From Alertmanager container
   docker compose exec alertmanager wget -O- http://api:8000/alertmanager/health
   ```

6. **Send test alert and check response**:

   ```bash
   curl -v -X POST http://localhost:8000/alertmanager/alerts \
     -H "Content-Type: application/json" \
     -d '{
       "receiver": "test",
       "status": "firing",
       "alerts": [{
         "status": "firing",
         "labels": {"alertname": "Test", "severity": "info"},
         "annotations": {"summary": "Debug test"}
       }]
     }'
   ```

#### Alert rule not firing

1. **Check Prometheus targets**:

   - Visit [http://localhost:9090/targets](http://localhost:9090/targets) (if exposed)
   - Verify all targets are "UP"

2. **Test alert expression in Prometheus UI**:

   - Visit [http://localhost:9090/graph](http://localhost:9090/graph)
   - Run your alert expression manually
   - Check if condition evaluates to true

3. **Check alert rules status**:

   - Visit [http://localhost:9090/alerts](http://localhost:9090/alerts)
   - Verify rule is loaded and evaluating

4. **Review Prometheus logs**:

   ```bash
   docker compose logs prometheus | grep -i "alert"
   ```

#### Matrix service unavailable warning

If you see `"warning": "matrix_service_unavailable"` in alert responses:

1. **Check Matrix Shadow Mode is enabled**:
   - Verify `MATRIX_HOMESERVER_URL`, `MATRIX_USER`, `MATRIX_PASSWORD`, `MATRIX_ALERT_ROOM` are set
   - Check API startup logs for Matrix initialization

2. **Check Matrix connection**:
   ```bash
   docker compose logs api | grep -i "shadow"
   ```

3. **Restart API to reinitialize Matrix connection**:
   ```bash
   docker compose restart api
   ```

### Alert Notification Examples

#### Critical Alert (RAG High Error Rate)

```markdown
🔥 **CRITICAL**: RAGHighErrorRate (rag)
RAG error rate above 5%

Error rate is 7.2%. Immediate investigation required.
```

#### Warning Alert (High RAG Cost)

```markdown
🔥 **WARNING**: HighRAGCost (rag)
RAG cost per request above $0.02

Current average cost: $0.025. Consider optimizing token usage.
```

#### Resolved Alert

```markdown
✅ **WARNING**: HighRAGCost (rag)
RAG cost per request above $0.02

Alert resolved - cost is now within acceptable range.
```

### Security Best Practices

1. **Use Bot Account**: Create dedicated Matrix bot user for alerts, not your personal account
2. **Secure Password**: Use strong, unique password for Matrix bot
3. **Private Room**: Make alert room private/invite-only
4. **Environment Variables**: Never commit Matrix credentials to git
5. **Access Control**: Limit who can view/modify alertmanager configuration

### API Endpoint Reference

#### Health Check

```
GET /alertmanager/health
Response: {"status": "healthy"}
```

#### Receive Alerts

```
POST /alertmanager/alerts
Content-Type: application/json

Request Body (Alertmanager webhook format):
{
  "receiver": "matrix-notifications",
  "status": "firing" | "resolved",
  "alerts": [
    {
      "status": "firing" | "resolved",
      "labels": {
        "alertname": "AlertName",
        "severity": "critical" | "warning" | "info"
      },
      "annotations": {
        "summary": "Brief description",
        "description": "Detailed description"
      }
    }
  ]
}

Response:
{
  "status": "ok",
  "alerts_processed": 1
}
```

### Additional Resources

- [Prometheus Alerting](https://prometheus.io/docs/alerting/latest/overview/)
- [Alertmanager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Matrix Protocol](https://matrix.org/docs/guides/)

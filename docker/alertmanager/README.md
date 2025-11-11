# Alertmanager Configuration

This directory contains Alertmanager configuration for routing Prometheus alerts to Matrix.

## Matrix Integration Setup

### Prerequisites

1. **Matrix Account**: Create a Matrix account (e.g., on matrix.org or your own homeserver)
2. **Matrix Room**: Create a room for alerts (e.g., "#bisq-alerts:matrix.org")
3. **Matrix Bot User**: Recommended to create a dedicated bot user for sending alerts

### Environment Variables

Add the following to your `.env` file in `/docker/.env` (production) or `/docker/.env` (local):

```bash
# Matrix Configuration for Alert Notifications
MATRIX_HOMESERVER=https://matrix.org
MATRIX_USER=@bisq-alerts:matrix.org
MATRIX_PASSWORD=your_secure_password
MATRIX_ROOM=!RoomIdHere:matrix.org
```

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

### Testing Alerts

To test the Matrix integration:

1. **Start services**:

   ```bash
   docker compose up -d alertmanager matrix-alertmanager-webhook
   ```

2. **Check Matrix webhook logs**:

   ```bash
   docker compose logs -f matrix-alertmanager-webhook
   ```

3. **Trigger a test alert via Prometheus**:

   ```bash
   # Access Alertmanager UI
   # Visit http://localhost:9093 (if exposed)

   # Or send test alert via API
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

4. **Verify alert appears in Matrix room**

### Troubleshooting

#### Alerts not appearing in Matrix

1. **Check Matrix webhook logs**:

   ```bash
   docker compose logs matrix-alertmanager-webhook
   ```

2. **Verify environment variables**:

   ```bash
   docker compose exec matrix-alertmanager-webhook env | grep MATRIX
   ```

3. **Test Matrix login manually**:

   ```bash
   curl -X POST https://matrix.org/_matrix/client/r0/login \
     -H "Content-Type: application/json" \
     -d '{
       "type": "m.login.password",
       "user": "bisq-alerts",
       "password": "your_password"
     }'
   ```

4. **Check Alertmanager connectivity**:

   ```bash
   # From Alertmanager container
   docker compose exec alertmanager wget -O- http://matrix-alertmanager-webhook:3000/health
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

### Alert Notification Examples

#### Critical Alert (RAG High Error Rate)

```markdown
🚨 **CRITICAL ALERT**
**RAG error rate above 5%**
Error rate is 7.2%
Immediate investigation required.

Labels:
- alertname: RAGHighErrorRate
- severity: critical
- component: rag

[View in Grafana](http://localhost:3001/d/rag-health)
```

#### Warning Alert (High RAG Cost)

```markdown
⚠️ **WARNING**
**RAG cost per request above $0.02**
Current average cost: $0.025
Consider optimizing token usage.

Labels:
- alertname: HighRAGCost
- severity: warning
- component: rag
```

### Security Best Practices

1. **Use Bot Account**: Create dedicated Matrix bot user for alerts, not your personal account
2. **Secure Password**: Use strong, unique password for Matrix bot
3. **Private Room**: Make alert room private/invite-only
4. **Environment Variables**: Never commit Matrix credentials to git
5. **Access Control**: Limit who can view/modify alertmanager configuration

### Additional Resources

- [Prometheus Alerting](https://prometheus.io/docs/alerting/latest/overview/)
- [Alertmanager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Matrix Protocol](https://matrix.org/docs/guides/)
- [matrix-alertmanager Docker Image](https://github.com/jaywink/matrix-alertmanager)

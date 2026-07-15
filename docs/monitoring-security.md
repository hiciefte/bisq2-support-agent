# Securing Monitoring Services

This document explains how to secure the monitoring services (Grafana and Prometheus) in the Bisq 2 Support Agent.

## Grafana Security

Grafana has been configured with basic authentication. Production deployments
must set generated credentials in `docker/.env`:

```
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<generated-secret>
GRAFANA_DATASOURCE_API_KEY=<generated-read-only-datasource-key>
```

### Important Security Notes for Grafana:

1. **Use Generated Credentials**: `scripts/deploy.sh` generates the Grafana admin password and dedicated read-only datasource key. Do not commit or reuse local development values.

2. **Restrict Network Access**: The direct Grafana port is bound to `127.0.0.1`; public access through `/grafana/` is limited by nginx IP allow/deny rules.

3. **Access Control**: After logging in, you can set up additional users with different permission levels:
   - Go to Configuration > Users
   - Add new users with appropriate roles (Admin, Editor, Viewer)

4. **Organization Management**: You can create separate organizations for different teams:
   - Go to Configuration > Organizations
   - Create new organizations and manage users within each

5. **API Keys**: Grafana's provisioned Admin API datasource must use `GRAFANA_DATASOURCE_API_KEY`, not the master `ADMIN_API_KEY`.

### Accessing Grafana in Production

Production intentionally does not expose Grafana's raw container port on a
public interface. Keep this binding:

```yaml
127.0.0.1:${EXPOSE_GRAFANA_PORT:-3001}:3000
```

Use one of these access paths instead:

1. **Browser through nginx**: use `/grafana/` on the production web origin. This
   path is subject to nginx allow/deny rules, rate limits, and security headers.

2. **SSH tunnel for maintainers and Grafana MCP**:

   ```bash
   scripts/grafana-tunnel.sh <ssh-target>
   ```

   Then open:

   ```text
   http://127.0.0.1:3001/grafana/
   ```

   For tools that call the Grafana HTTP API directly, including the Grafana MCP
   server, use this base URL while the tunnel is running:

   ```text
   http://127.0.0.1:3001
   ```

3. **VPN or access proxy**: if browser access must work without SSH tunnels, put
   `/grafana/` behind a private network, SSO/access proxy, or explicit trusted
   IP allowlist. Do not reopen public `:3001` just for convenience.

## Prometheus Security

Prometheus doesn't have built-in authentication. To secure Prometheus, you have several options:

### Option 1: Use a Reverse Proxy (Recommended)

1. Set up Nginx or Traefik as a reverse proxy in front of Prometheus
2. Configure basic authentication in the proxy
3. Add TLS/SSL for encrypted connections

Example Nginx configuration:

```nginx
server {
    listen 443 ssl;
    server_name prometheus.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        auth_basic "Prometheus";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://localhost:9090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Option 2: Use Prometheus's web.config.file Option

1. Create a web.config.yml file with TLS and basic auth configuration
2. Update the Prometheus Docker configuration to use this file

Example web.config.yml:

```yaml
tls_server_config:
  cert_file: /etc/prometheus/certs/prometheus.crt
  key_file: /etc/prometheus/certs/prometheus.key

basic_auth_users:
  admin: $2y$10$...  # bcrypt hash of password
```

Update docker-compose.yml:

```yaml
prometheus:
  image: prom/prometheus:latest
  command:
    - '--config.file=/etc/prometheus/prometheus.yml'
    - '--web.config.file=/etc/prometheus/web.config.yml'
  # ... other configuration ...
```

### Option 3: Network-Level Security

1. Don't expose Prometheus publicly
2. Use a VPN or SSH tunneling to access Prometheus
3. Configure firewall rules to restrict access

### Option 4: Environment Variable Configuration

Set `ADMIN_API_KEY` in `docker/.env` to secure application admin endpoints:

```
# Admin API key for protected endpoints
ADMIN_API_KEY=your_secure_admin_key
```

This key is consumed by the API, not by Prometheus or the scheduler. Scheduled
application jobs use a separate, narrowly scoped runtime credential generated
inside an isolated Compose volume; it must not be copied into `docker/.env` or
reused as an admin key.

## Additional Security Recommendations

1. **Regular Updates**: Keep Grafana and Prometheus updated to the latest versions
2. **Audit Logging**: Enable audit logging in both services
3. **HTTPS**: Always use HTTPS in production environments
4. **Least Privilege**: Follow the principle of least privilege for all users and services
5. **Monitoring**: Monitor access to your monitoring services (yes, monitor your monitoring!)
6. **Port Exposure**: Configure exposed ports in the `docker/.env` file:
   ```
   EXPOSE_PROMETHEUS_PORT=9090
   EXPOSE_GRAFANA_PORT=3001
   ```

## Privacy and Data Protection

### User Data Handling

The Bisq Support Agent stores local support data needed to answer, review, and
improve responses:

**What We Collect:**
- Chat questions and AI responses
- User feedback ratings (thumbs up/down)
- Optional feedback explanations
- Timestamps and message IDs
- Channel user/room identifiers, escalation records, and reviewer identifiers

Standard application access logs can contain network and request metadata.
Matrix session credentials and local crypto state are operational artifacts and
are rotated as a complete generation at the configured retention boundary.

### Data Retention

**Automated Cleanup:**
- `DATA_RETENTION_DAYS` is validated between 1 and 30 days and rendered in the
  public privacy surfaces at runtime.
- SQLite records, translation entries, processed identifiers, structured
  exports, local sessions, and bind-mounted logs are handled by the scheduled
  retention job. Old parents are anonymized only when a newer child still
  requires their key.
- Malformed or untimestamped legacy rows are preserved for manual migration;
  their store-age metric exposes overdue artifacts instead of silently
  deleting data whose age cannot be proven.
- Reviewed FAQ/support-playbook text and aggregate operational metrics may
  remain; the knowledge stores omit structured source identifiers and links.
- Docker runtime-log age retention is installed and verified by a human using
  the checked-in host script.
- See `docs/runbooks/privacy-retention.md` for the complete store inventory.

**Privacy Compliance:**
- Data minimization: Only collect what's necessary
- Purpose limitation: Data used only for service improvement
- Transparency: Users are informed via privacy policy (see `/privacy` page)

### Third-Party Data Sharing

**OpenAI Integration:**
- User questions are sent to OpenAI for AI response generation
- OpenAI does not use API data for training (per their API usage policy)
- Users are warned not to share sensitive information

**Security Warning:**
Users are prominently warned NOT to share:
- Private keys or seed phrases
- Personal identifying information
- Financial account details
- Trading partner information

### Privacy Policy Implementation

For detailed privacy implementation requirements, see:
- `/privacy` page - User-facing privacy policy
- Privacy warning modal on first visit to chat interface
- `docs/environment-configuration.md` - Privacy-related environment controls

## References

- [Grafana Security Documentation](https://grafana.com/docs/grafana/latest/administration/security/)
- [Prometheus Security Documentation](https://prometheus.io/docs/operating/security/)
- [OpenAI API Data Usage Policy](https://openai.com/policies/api-data-usage-policies)

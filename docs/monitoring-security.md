# Securing Monitoring Services

This document explains how to secure the monitoring services (Grafana and Prometheus) in the Bisq 2 Support Agent.

## Grafana Security

Grafana has been configured with basic authentication. The default credentials are set in the `docker/.env` file:

```
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=securepassword
```

### Important Security Notes for Grafana:

1. **Change Default Credentials**: Always change the default credentials in the `docker/.env` file before deploying to production.

2. **Access Control**: After logging in, you can set up additional users with different permission levels:
   - Go to Configuration > Users
   - Add new users with appropriate roles (Admin, Editor, Viewer)

3. **Organization Management**: You can create separate organizations for different teams:
   - Go to Configuration > Organizations
   - Create new organizations and manage users within each

4. **API Keys**: For automated access, use API keys instead of user credentials:
   - Go to Configuration > API Keys
   - Create keys with appropriate permissions and expiration dates

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

You can set the Admin API key in the `docker/.env` file, which is used by Prometheus to secure admin endpoints:

```
# Admin API key for protected endpoints
ADMIN_API_KEY=your_secure_admin_key
```

This key will be passed to Prometheus as an environment variable in the docker-compose.yml configuration.

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

The Bisq Support Agent collects minimal user data for service improvement:

**What We Collect:**
- Chat questions and AI responses
- User feedback ratings (thumbs up/down)
- Optional feedback explanations
- Timestamps and message IDs

**What We DON'T Collect:**
- Personal identifiers (names, emails)
- IP addresses (beyond standard server logs)
- User accounts or authentication data

### Data Retention

**Automated Cleanup:**
- Personal data is automatically deleted after **30 days** (configurable via `DATA_RETENTION_DAYS`)
- Only anonymized FAQs are kept permanently for the knowledge base
- See `scripts/cleanup_old_data.sh` for implementation

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
- `docs/requirements/privacy-implementation-spec.md` - Technical specification
- `/privacy` page - User-facing privacy policy
- Privacy warning modal on first visit to chat interface

## References

- [Grafana Security Documentation](https://grafana.com/docs/grafana/latest/administration/security/)
- [Prometheus Security Documentation](https://prometheus.io/docs/operating/security/)
- [OpenAI API Data Usage Policy](https://openai.com/policies/api-data-usage-policies) 
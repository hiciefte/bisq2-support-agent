# Environment Configuration

This document details the environment variables used by the Bisq Support Agent project. These variables are used by the deployment/update scripts and within the Docker containers.

## Deployment/Update Script Variables

These variables are typically set in the shell or sourced from `/etc/bisq-support/deploy.env` before running `scripts/deploy.sh` or `scripts/update.sh`.

### Required Script Variables

*   **`BISQ_SUPPORT_REPO_URL`**
    *   Description: The Git repository URL for the Bisq Support Agent project.
    *   Example: `git@github.com:user/bisq2-support-agent.git`
*   **`BISQ_SUPPORT_INSTALL_DIR`**
    *   Description: The absolute path on the server where the Bisq Support Agent code will be cloned/installed.
    *   Example: `/opt/bisq-support`

### Optional Script Variables

*   **`BISQ_SUPPORT_SECRETS_DIR`**
    *   Description: The absolute path to store generated secrets (like API keys, passwords).
    *   Default: `$BISQ_SUPPORT_INSTALL_DIR/secrets`
*   **`BISQ_SUPPORT_LOG_DIR`**
    *   Description: The absolute path for storing host-level logs (like deployment script logs, *not* application logs inside Docker).
    *   Default: `$BISQ_SUPPORT_INSTALL_DIR/logs`
*   **`BISQ_SUPPORT_SSH_KEY_PATH`**
    *   Description: The absolute path to the private SSH key used for authenticating with Git repositories.
    *   Default: `$HOME/.ssh/bisq2_support_agent` (Note: `$HOME` resolves to the home directory of the user running the script, typically `/root` when using `sudo`)

## Docker Container Variables (`docker/.env`)

These variables configure the application services running inside Docker containers. They are primarily set in the `docker/.env` file located within the installation directory (`$BISQ_SUPPORT_INSTALL_DIR/docker/.env`). The deployment script copies `docker/.env.example` if `.env` doesn't exist and injects some secrets.

*   **`OPENAI_API_KEY`**
    *   Description: (Required) Your API key from OpenAI, used for LLM operations via AISuite and embeddings.
*   **`OPENAI_MODEL`**
    *   Description: The OpenAI model ID to use for generating chat responses via AISuite.
  *   Default: `gpt-4o-mini`
*   **`OPENAI_EMBEDDING_MODEL`**
    *   Description: The OpenAI model ID to use for creating text embeddings.
    *   Default: `text-embedding-3-small`
*   **`MAX_TOKENS`**
    *   Description: The maximum number of tokens to generate in LLM completions.
    *   Default: `4096`
*   **`ADMIN_API_KEY`**
    *   Description: A secret key required to access administrative API endpoints (e.g., feedback processing). The deployment script generates a random key and stores it in `$BISQ_SUPPORT_SECRETS_DIR/admin_api_key`, then injects it into `.env`.
    *   Default in `.env.example`: `dev_admin_key`
*   **`DEBUG`**
    *   Description: Set to `true` to enable debug mode for the API (provides more verbose error output). Should be `false` in production.
    *   Default: `false`
*   **`CORS_ORIGINS`**
    *   Description: A comma-separated list of origins (URLs) allowed to make requests to the API. Use `*` for wide-open access (not recommended for production).
    *   Default: `http://localhost:3000,http://127.0.0.1:3000`
*   **`DATA_DIR`**
    *   Description: The path *inside the API container* where persistent data (wiki, FAQs, vectorstore, feedback) is stored/mounted. **IMPORTANT**: This must match the volume mount destination in `docker-compose.yml` to ensure data persistence across container restarts.
    *   Default: `/data` (maps to `$BISQ_SUPPORT_INSTALL_DIR/api/data` on the host via Docker volume mounts in `docker-compose.yml`)
*   **`EXPOSE_API_PORT`**
    *   Description: Internal port used by the API container.
    *   Default: `8000`
*   **`EXPOSE_PROMETHEUS_PORT`**
    *   Description: Internal port used by the Prometheus container.
    *   Default: `9090`
*   **`EXPOSE_GRAFANA_PORT`**
    *   Description: Internal port used by the Grafana container. (Note: The *external* port is configured in `docker-compose.yml`).
    *   Default: `3001`
*   **`GRAFANA_ADMIN_USER`**
    *   Description: The username for the initial Grafana admin user.
    *   Default: `admin`
*   **`GRAFANA_ADMIN_PASSWORD`**
    *   Description: The password for the initial Grafana admin user. The deployment script generates a random password and stores it in `$BISQ_SUPPORT_SECRETS_DIR/grafana_admin_password`, then injects it into `.env`.
    *   Default in `.env.example`: `securepassword`
*   **`PROMETHEUS_BASIC_AUTH_USERNAME`**
    *   Description: Username for basic authentication if configured for Prometheus (current setup might not use it).
    *   Default: `admin`
*   **`PROMETHEUS_BASIC_AUTH_PASSWORD`**
    *   Description: Password for basic authentication if configured for Prometheus.
    *   Default: `prometheuspassword`
*   **`NEXT_PUBLIC_PROJECT_NAME`**
    *   Description: A name for the project, potentially used in the UI.
    *   Default: `Bisq 2 Support Agent`
*   **`HEALTHCHECK_URL`**
    *   Description: (Optional) Healthchecks.io ping URL for external health monitoring. The scheduler container pings this URL every 5 minutes to confirm the system is operational. If not configured, external alerting will not be available (local monitoring via Prometheus/Grafana will still function).
    *   Example: `https://hc-ping.com/YOUR-UUID-HERE`
    *   Default: None (feature disabled if not set)

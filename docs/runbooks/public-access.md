# Public Access: Clearnet TLS or Tor-Only

Production supports two public-access modes. An operator must choose one before
launch; the application does not select a mode or provision certificates.

Never commit certificate material, private keys, public names, addresses, or
deployment-specific paths. Store those values only in the deployment
environment and operator-managed secret storage.

## Human launch decisions

Before enabling public traffic, a human operator must decide:

- clearnet TLS or Tor-only exposure;
- the host bind and firewall policy;
- the public name and, for clearnet, its DNS configuration;
- certificate issuer, provisioning, renewal, and reload procedure; and
- whether a later HSTS policy should include subdomains or preload.

This runbook implements and validates both exposure modes without selecting any
of those deployment-specific values.

Run the Compose commands below from the repository's `docker/` directory.

## TLS activation behavior

The nginx startup hook reads these container settings:

- `NGINX_TLS_CERTIFICATE`: mounted certificate-chain file.
- `NGINX_TLS_PRIVATE_KEY`: mounted private-key file.
- `NGINX_TLS_REDIRECT_HTTP`: explicit HTTP-to-HTTPS redirect toggle.

The base Compose file publishes only HTTP and defaults its host bind to
loopback. The optional `docker-compose.tls.yml` overlay mounts the
operator-selected certificate directory read-only and publishes HTTPS. It
requires the certificate directory, certificate filename, private-key
filename, and HTTPS bind to be set explicitly.

TLS remains disabled when both files are absent. Nginx refuses to start if only
one file exists, either file is empty, or HTTP redirection is requested without
a complete pair. A complete pair enables the TLS listener; it does not enable
HTTP redirection unless `NGINX_TLS_REDIRECT_HTTP=true` is also set.

HSTS is emitted only by HTTPS responses. The initial policy is one year without
`includeSubDomains` or `preload`; either expansion requires a separate review
of every affected public name.

### Persisting the selected mode

For clearnet TLS, set this deploy-only value in the operator-managed
`deploy.env` before activating the listener:

```bash
BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=docker-compose.tls.yml
```

The production deploy, update, rollback, start, stop, and health-repair paths
then invoke Compose with both the base file and this overlay. The shared helper
accepts no other override name and fails closed if the selected file is absent,
so an update or rollback cannot silently recreate nginx from the base file
alone. As an independent guard, base mode also refuses TLS-only inputs,
HTTPS redirection, or a non-loopback HTTP bind. Losing `deploy.env` therefore
cannot silently convert a selected clearnet deployment to public HTTP.

For Tor-only mode, leave the setting empty or absent. This preserves the legacy
base-only Compose behavior. Changing either mode is a human exposure decision;
edit the operator-managed deployment environment deliberately and validate the
resolved configuration before restarting services.

When upgrading an installation that predates this helper, first update the
code while the override setting is absent. After that update succeeds, persist
the reviewed overlay and run the validation steps below. Older updater code
does not know how to carry the selection forward.

## Option A: Clearnet with TLS

The operator must:

1. Select the public name and configure DNS and firewall policy.
2. Provision and renew a trusted certificate and private key outside the
   repository.
3. Mount the certificate directory read-only into nginx and set both container
   file paths.
4. Persist `BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=docker-compose.tls.yml` in the
   deploy environment.
5. Set `NGINX_HTTP_BIND_ADDRESS` and `NGINX_HTTPS_BIND_ADDRESS` to the reviewed
   public interface.
6. Set `NGINX_TLS_REDIRECT_HTTP=true` and enable secure cookies.
7. Recreate nginx so the startup hook reads the current files.

Validate configuration before shifting traffic:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.tls.yml \
  run --rm --no-deps nginx nginx -t
docker compose -f docker-compose.yml -f docker-compose.tls.yml \
  up -d --force-recreate nginx
docker compose -f docker-compose.yml -f docker-compose.tls.yml \
  exec nginx nginx -T | grep -E 'listen 443 ssl|ssl_certificate'
```

Set `PUBLIC_HTTPS_URL` and `PUBLIC_HTTP_URL` in the operator shell, then verify
the live boundary without writing either value to the repository:

```bash
curl --fail --silent --show-error --head "$PUBLIC_HTTPS_URL"
http_headers="$(curl --silent --show-error --head "$PUBLIC_HTTP_URL")"
printf '%s\n' "$http_headers" | grep -Eq '^HTTP/[0-9.]+ (301|308)( |$)'
printf '%s\n' "$http_headers" | grep -Eiq '^Location:[[:space:]]*https://'
curl --fail --silent --show-error --head "$PUBLIC_HTTPS_URL" \
  | grep -i '^Strict-Transport-Security:'
```

The HTTP response must redirect permanently to HTTPS. The HTTPS response must
present the expected certificate and include HSTS.

Certificate renewal remains an operator responsibility. Replace files
atomically, run `nginx -t`, then recreate or reload nginx. Keep the previous
pair available until the renewed listener has been verified.

The Tor rollback script performs the same checks before it changes Tor state:
it rejects missing, empty, malformed, expired, encrypted, or mismatched TLS
material and requires an ephemeral nginx config test to produce a TLS listener.

## Option B: Tor-only

The operator must:

1. Leave both nginx TLS file paths unmounted or absent.
2. Set `NGINX_TLS_REDIRECT_HTTP=false`.
3. Remove or leave empty `BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE` in the deploy
   environment.
4. Set `NGINX_HTTP_BIND_ADDRESS` to the loopback interface consumed by the Tor
   hidden service and use only the base Compose file. Do not use the TLS
   overlay or publish an HTTPS listener.
5. Block direct clearnet ingress with the host firewall.
6. Disable secure cookies for the onion service.

After recreating nginx, verify that no TLS server was generated:

```bash
docker compose -f docker-compose.yml up -d --force-recreate nginx
if docker compose -f docker-compose.yml exec nginx nginx -T \
  | grep -q 'listen 443 ssl'; then
  echo "unexpected TLS listener" >&2
  exit 1
fi
```

Set `ONION_SERVICE_URL` only in the operator shell and verify access through a
Tor-enabled client. Also verify from outside the host that no clearnet listener
is reachable.

## Failure recovery

- **Partial or empty pair:** restore both valid files or remove both, then
  recreate nginx. Do not bypass the startup check.
- **Invalid or mismatched pair:** nginx configuration validation fails. Restore
  the last known-good pair and rerun `nginx -t`.
- **Redirect enabled before TLS:** disable the redirect until a complete pair is
  mounted and validated.
- **Unexpected clearnet exposure in Tor-only mode:** remove public port
  publishing or correct the bind and firewall policy before restarting nginx.
- **Rollback target lacks the selected overlay:** do not clear the persisted
  selection merely to make the rollback proceed. Choose a target containing
  the reviewed overlay or make an explicit human decision to change exposure
  mode first.

Do not change production files directly from this repository workflow. The
commands above are human-run deployment and verification steps.

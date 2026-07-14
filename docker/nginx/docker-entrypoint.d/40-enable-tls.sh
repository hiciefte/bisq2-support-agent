#!/bin/sh

set -eu

certificate=${NGINX_TLS_CERTIFICATE:-/etc/nginx/tls/certificate.pem}
private_key=${NGINX_TLS_PRIVATE_KEY:-/etc/nginx/tls/private-key.pem}
redirect_http=${NGINX_TLS_REDIRECT_HTTP:-false}
runtime_dir=${NGINX_TLS_RUNTIME_DIR:-/etc/nginx/runtime}

case "$redirect_http" in
    1|true|yes|on)
        redirect_http=true
        ;;
    0|false|no|off)
        redirect_http=false
        ;;
    *)
        echo "40-enable-tls.sh: NGINX_TLS_REDIRECT_HTTP must be true or false" >&2
        exit 1
        ;;
esac

case "$certificate:$private_key" in
    *[!A-Za-z0-9_./:-]*)
        echo "40-enable-tls.sh: TLS file paths contain unsupported characters" >&2
        exit 1
        ;;
esac

certificate_present=false
private_key_present=false
[ -e "$certificate" ] && certificate_present=true
[ -e "$private_key" ] && private_key_present=true

tls_enabled=false
if [ "$certificate_present" = true ] || [ "$private_key_present" = true ]; then
    if [ ! -f "$certificate" ] || [ ! -s "$certificate" ] || \
        [ ! -f "$private_key" ] || [ ! -s "$private_key" ]; then
        echo "40-enable-tls.sh: partial TLS configuration; refusing to start" >&2
        exit 1
    fi
    tls_enabled=true
fi

if [ "$redirect_http" = true ] && [ "$tls_enabled" = false ]; then
    echo "40-enable-tls.sh: HTTP redirection requires a complete TLS certificate pair" >&2
    exit 1
fi

mkdir -p "$runtime_dir"
runtime_config="$runtime_dir/tls.conf"
temporary_config=$(mktemp "$runtime_dir/tls.conf.XXXXXX")
trap 'rm -f "$temporary_config"' EXIT HUP INT TERM

if [ "$redirect_http" = true ]; then
    cat >"$temporary_config" <<'EOF'
map $scheme $redirect_to_https {
    default 0;
    http 1;
}
EOF
else
    cat >"$temporary_config" <<'EOF'
map $scheme $redirect_to_https {
    default 0;
}
EOF
fi

if [ "$tls_enabled" = true ]; then
    cat >>"$temporary_config" <<EOF

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate $certificate;
    ssl_certificate_key $private_key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:TLS:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    set \$strict_transport_security "max-age=31536000";
    include /etc/nginx/conf.d/snippets/transport-security.conf;
    include /etc/nginx/conf.d/snippets/application-routes.prod.conf;
}
EOF
    echo "40-enable-tls.sh: complete certificate pair detected; TLS enabled"
else
    echo "40-enable-tls.sh: certificate pair absent; TLS remains disabled"
fi

chmod 644 "$temporary_config"
mv "$temporary_config" "$runtime_config"
trap - EXIT HUP INT TERM

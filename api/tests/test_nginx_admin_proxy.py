"""Admin proxy contracts, with opt-in real nginx/Docker routing coverage."""

import json
import os
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = [
    ROOT / "docker/nginx/conf.d/default.conf",
    ROOT / "docker/nginx/conf.d/snippets/application-routes.prod.conf",
]
IMAGE = "nginx:alpine@sha256:54f2a904c251d5a34adf545a72d32515a15e08418dae0266e23be2e18c66fefa"


def admin_block(path):
    text = path.read_text()
    start = text.index("    location ~ ^/api/admin/")
    end = text.index("\n    }", start) + len("\n    }")
    return text[start:end]


@pytest.mark.parametrize("config", CONFIGS, ids=lambda p: p.name)
def test_admin_proxy_does_not_depend_on_late_regex_captures(config):
    block = admin_block(config)
    assert "rewrite ^/api/(.*)$ /$1 break;" in block
    assert "proxy_pass http://api:8000;" in block
    assert "proxy_pass http://api:8000/admin/$1$2" not in block


@pytest.fixture(scope="module", params=CONFIGS, ids=lambda p: p.name)
def live_proxy(request, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("nginx-admin")
    if os.environ.get("NGINX_ROUTING_DOCKER") != "1":
        pytest.skip("Set NGINX_ROUTING_DOCKER=1 to run the real nginx regression")

    class EchoHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            length = int(self.headers.get("Content-Length", "0"))
            response = json.dumps(
                {
                    "path": self.path,
                    "method": self.command,
                    "body": self.rfile.read(length).decode(),
                }
            ).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(response)

        do_POST = do_GET

        def log_message(self, *args):
            pass

    backend = ThreadingHTTPServer(("0.0.0.0", 0), EchoHandler)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    host_ip = subprocess.check_output(
        ["docker", "run", "--rm", IMAGE, "getent", "ahostsv4", "host.docker.internal"],
        text=True,
    ).split()[0]
    block = admin_block(request.param)
    # Exercise the actual route, rate limits, and shared cookie map. Only the
    # backend address and unrelated response-header/maintenance includes differ.
    block = "\n".join(
        line
        for line in block.splitlines()
        if "include " not in line and "error_page " not in line
    ).replace("api:8000", f"{host_ip}:{backend.server_port}")
    http_config = (ROOT / "docker/nginx/nginx.conf").read_text()
    map_start = http_config.index("    map $cookie_session_id $rate_limit_key {")
    map_end = http_config.index("\n    }", map_start) + len("\n    }")
    config = tmp_path / "nginx.conf"
    config.write_text(
        "events {}\nhttp {\n"
        + http_config[map_start:map_end]
        + "\nlimit_req_zone $rate_limit_key zone=admin:1m rate=100r/s;\n"
        + "limit_conn_zone $binary_remote_addr zone=addr:1m;\n"
        + "server { listen 8080; resolver 127.0.0.11;\n"
        + block
        + "\n}\n}\n"
    )
    container = None
    try:
        container = subprocess.check_output(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--stop-timeout=1",
                "-p",
                "127.0.0.1::8080",
                "-v",
                f"{config}:/etc/nginx/nginx.conf:ro",
                IMAGE,
            ],
            text=True,
        ).strip()
        port = (
            subprocess.check_output(["docker", "port", container, "8080"], text=True)
            .strip()
            .rsplit(":", 1)[1]
        )
        url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(
                    url + "/api/admin/auth/status", timeout=2
                ).close()
                break
            except OSError:
                time.sleep(0.1)
        yield url
    finally:
        if container:
            subprocess.run(
                ["docker", "stop", container], check=True, capture_output=True
            )
        backend.shutdown()
        backend.server_close()
        thread.join()


@pytest.mark.integration
@pytest.mark.parametrize("cookie", [None, "session_id=" + "a" * 32])
@pytest.mark.parametrize(
    "path,body",
    [
        ("auth/status", None),
        ("auth/login", '{"api_key":"fixture-only-key"}'),
        ("training/candidates?status=pending&limit=7", None),
    ],
)
def test_admin_proxy_preserves_upstream_request(live_proxy, cookie, path, body):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(
        live_proxy + "/api/admin/" + path,
        data=body.encode() if body is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        actual = json.load(response)
    assert actual == {
        "path": "/admin/" + path,
        "method": "POST" if body is not None else "GET",
        "body": body or "",
    }

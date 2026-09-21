#!/usr/bin/env python3
"""Configure nginx + Let's Encrypt pour geotax.ittechmed.com sur le VPS."""
from __future__ import annotations

import os
import sys

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "76.13.36.246")
USER = os.environ.get("DEPLOY_SSH_USER", "root")
PASSWORD = os.environ.get("DEPLOY_SSH_PASS", "")
DOMAIN = "geotax.ittechmed.com"
APP_DIR = "/opt/paiement-fisc"
NGINX_AVAILABLE = f"/etc/nginx/sites-available/{DOMAIN}"
NGINX_ENABLED = f"/etc/nginx/sites-enabled/{DOMAIN}"

NGINX_HTTP_BOOTSTRAP = f"""server {{
    listen 80;
    listen [::]:80;
    server_name {DOMAIN};

    location ^~ /.well-known/acme-challenge/ {{
        root /var/www/certbot;
        default_type text/plain;
        try_files $uri =404;
    }}

    location / {{
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 180) -> tuple[int, str, str]:
    print(f"\n$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    code = stdout.channel.recv_exit_status()
    if out:
        print(out.rstrip())
    if err:
        print(err.rstrip())
    return code, out, err


def main() -> int:
    if not PASSWORD:
        print("Définir DEPLOY_SSH_PASS", file=sys.stderr)
        return 1

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    nginx_conf_local = os.path.join(repo_root, "deploy", "hostinger", "nginx-geotax.conf")
    with open(nginx_conf_local, encoding="utf-8") as f:
        nginx_conf_full = f.read()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=60, allow_agent=False, look_for_keys=False)

    run(client, "mkdir -p /var/www/certbot")

    # Phase 1 : HTTP temporaire pour Certbot
    sftp = client.open_sftp()
    with sftp.file(NGINX_AVAILABLE, "w") as remote:
        remote.write(NGINX_HTTP_BOOTSTRAP)
    sftp.close()

    run(client, f"ln -sf {NGINX_AVAILABLE} {NGINX_ENABLED}")
    code, _, _ = run(client, "nginx -t")
    if code != 0:
        return code
    run(client, "systemctl reload nginx")

    cert_cmd = (
        f"certbot certonly --webroot -w /var/www/certbot -d {DOMAIN} "
        "--agree-tos --non-interactive --register-unsafely-without-email"
    )
    code, out, err = run(client, cert_cmd, timeout=300)
    if code != 0 and "Certificate not yet due for renewal" not in (out + err):
        print("Échec certbot", file=sys.stderr)
        return code

    # Phase 2 : config HTTPS finale
    sftp = client.open_sftp()
    with sftp.file(NGINX_AVAILABLE, "w") as remote:
        remote.write(nginx_conf_full)
    sftp.close()

    code, _, _ = run(client, "nginx -t")
    if code != 0:
        return code
    run(client, "systemctl reload nginx")

    run(
        client,
        f"cd {APP_DIR} && sed -i 's/^SESSION_COOKIE_SECURE=.*/SESSION_COOKIE_SECURE=true/' .env "
        "&& docker compose --env-file .env up -d app",
    )

    code, out, _ = run(client, f"curl -sI https://{DOMAIN}/login | head -12")
    client.close()
    return 0 if "200 OK" in out or "302" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())

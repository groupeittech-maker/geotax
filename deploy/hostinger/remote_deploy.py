"""Upload + remote deploy via SSH (password from env DEPLOY_SSH_PASS only)."""
from __future__ import annotations

import os
import subprocess
import sys

import paramiko

HOST = os.environ.get("DEPLOY_SSH_HOST", "76.13.36.246")
USER = os.environ.get("DEPLOY_SSH_USER", "root")
PASSWORD = os.environ.get("DEPLOY_SSH_PASS")
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/paiement-fisc")
ARCHIVE = os.environ.get("DEPLOY_ARCHIVE")
DUMP_LOCAL = os.environ.get("DEPLOY_DUMP_LOCAL")
SKIP_RESTORE = os.environ.get("DEPLOY_SKIP_RESTORE", "").lower() in ("1", "true", "yes")


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 900) -> int:
    print(f"\n$ {cmd[:240]}{'...' if len(cmd) > 240 else ''}")
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("STDERR:", err.rstrip())
    if code != 0:
        print(f"Exit code: {code}")
    return code


def build_archive_if_needed() -> str:
    global ARCHIVE
    if ARCHIVE and os.path.isfile(ARCHIVE):
        return ARCHIVE
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    archive = os.path.join(os.environ.get("TEMP", "/tmp"), "paiement-fisc-deploy.tar.gz")
    excludes = [
        "--exclude=.env", "--exclude=.git", "--exclude=instance",
        "--exclude=venv", "--exclude=__pycache__", "--exclude=qr_codes",
    ]
    cmd = ["tar", "-czf", archive, *excludes, "-C", repo_root, "."]
    print("Création archive :", " ".join(cmd))
    subprocess.check_call(cmd)
    ARCHIVE = archive
    return archive


def main() -> int:
    if not PASSWORD:
        print("DEPLOY_SSH_PASS non défini.", file=sys.stderr)
        return 2

    archive = build_archive_if_needed()
    if not os.path.isfile(archive):
        print("DEPLOY_ARCHIVE invalide.", file=sys.stderr)
        return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print(f"Connexion SSH {USER}@{HOST}...")
        client.connect(
            HOST,
            username=USER,
            password=PASSWORD,
            timeout=60,
            allow_agent=False,
            look_for_keys=False,
        )
    except paramiko.AuthenticationException:
        print(
            "Échec authentification SSH. "
            "Réinitialisez le mot de passe root dans hPanel → VPS → SSH access.",
            file=sys.stderr,
        )
        return 1

    run(client, f"mkdir -p {REMOTE_DIR}/deploy/hostinger")
    sftp = client.open_sftp()
    print(f"Upload archive ({os.path.getsize(archive)} octets)...")
    sftp.put(archive, f"{REMOTE_DIR}/app.tar.gz")
    if DUMP_LOCAL and os.path.isfile(DUMP_LOCAL):
        print("Upload backup.dump...")
        sftp.put(DUMP_LOCAL, f"{REMOTE_DIR}/deploy/hostinger/backup.dump")
    sftp.close()

    if run(client, f"cd {REMOTE_DIR} && tar -xzf app.tar.gz && rm -f app.tar.gz") != 0:
        client.close()
        return 1

    restore = ""
    if not SKIP_RESTORE and DUMP_LOCAL and os.path.isfile(DUMP_LOCAL):
        restore = """
if [ -f deploy/hostinger/backup.dump ]; then
  cat deploy/hostinger/backup.dump | docker compose --env-file .env exec -T db \\
    pg_restore -U paiement_fisc -d paiement_fisc --clean --if-exists --no-owner --no-acl 2>/dev/null || true
fi
"""

    remote = f"""set -euo pipefail
cd {REMOTE_DIR}
if [ ! -f .env ]; then
  cp .env.docker.example .env
  SECRET=$(openssl rand -hex 32)
  PASS=$(openssl rand -hex 16)
  sed -i "s/changez-cette-cle-secrete-longue/$SECRET/" .env
  sed -i "s/changez-ce-mot-de-passe-fort/$PASS/" .env
  chmod 600 .env
fi
grep -q '^HTTP_PORT=' .env && sed -i 's/^HTTP_PORT=.*/HTTP_PORT=8080/' .env || echo 'HTTP_PORT=8080' >> .env
sed -i 's/^SESSION_COOKIE_SECURE=.*/SESSION_COOKIE_SECURE=false/' .env || echo 'SESSION_COOKIE_SECURE=false' >> .env
grep -q '^LOG_FORMAT=' .env || echo 'LOG_FORMAT=json' >> .env
bash deploy/hostinger/install-docker.sh
bash deploy/hostinger/deploy.sh
{restore}
docker compose --env-file .env restart app worker
sleep 5
docker compose --env-file .env ps
curl -s http://127.0.0.1:8080/health/ready || true
docker compose --env-file .env exec -T app python deploy/verify_migration_status.py || true
"""
    code = run(client, remote, timeout=900)
    client.close()
    if code == 0:
        print(f"\n✓ Déploiement OK — http://{HOST}:8080")
        print(f"  HTTPS (si configuré) : https://geotax.ittechmed.com")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

"""Import backup.sql on VPS. Password via DEPLOY_SSH_PASS."""
import os
import sys
import paramiko

HOST = os.environ.get("DEPLOY_SSH_HOST", "76.13.36.246")
USER = os.environ.get("DEPLOY_SSH_USER", "root")
PASSWORD = os.environ.get("DEPLOY_SSH_PASS")
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/paiement-fisc")
SQL_LOCAL = os.environ.get("DEPLOY_SQL_LOCAL", os.path.join(os.path.dirname(__file__), "backup.sql"))

if not PASSWORD:
    sys.exit("DEPLOY_SSH_PASS requis")
if not os.path.isfile(SQL_LOCAL):
    sys.exit(f"Fichier introuvable : {SQL_LOCAL}")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=60, allow_agent=False, look_for_keys=False)

sftp = client.open_sftp()
print("Upload backup.sql...")
sftp.put(SQL_LOCAL, f"{REMOTE_DIR}/deploy/hostinger/backup.sql")
sftp.close()

# Upload updated docker-compose.yml for postgres 17
compose_local = os.path.join(os.path.dirname(__file__), "..", "..", "docker-compose.yml")
if os.path.isfile(compose_local):
    sftp = client.open_sftp()
    sftp.put(compose_local, f"{REMOTE_DIR}/docker-compose.yml")
    sftp.close()

cmd = f"""set -e
cd {REMOTE_DIR}
docker compose --env-file .env down -v || true
docker compose --env-file .env pull db
docker compose --env-file .env up -d db
echo 'Attente PostgreSQL...'
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  docker compose --env-file .env exec -T db pg_isready -U paiement_fisc && break
  sleep 3
done
docker compose --env-file .env exec -T db psql -U paiement_fisc -d paiement_fisc -c 'SELECT 1' 
cat deploy/hostinger/backup.sql | docker compose --env-file .env exec -T db psql -U paiement_fisc -d paiement_fisc -v ON_ERROR_STOP=1
docker compose --env-file .env up -d
sleep 8
docker compose --env-file .env exec -T db psql -U paiement_fisc -d paiement_fisc -c "SELECT 'boutiques' t, count(*) FROM boutiques UNION ALL SELECT 'paiements', count(*) FROM paiements UNION ALL SELECT 'users', count(*) FROM users;"
docker compose --env-file .env exec -T app python deploy/verify_migration_status.py
curl -s -o /dev/null -w 'login HTTP %{{http_code}}\\n' http://127.0.0.1:8080/login
"""
_, stdout, stderr = client.exec_command(cmd, timeout=600)
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("STDERR:", err[-3000:])
print("exit", stdout.channel.recv_exit_status())
client.close()

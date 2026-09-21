#!/usr/bin/env bash
# Installe Docker (script officiel, compatible Ubuntu/Debian Hostinger)
# Usage : sudo bash deploy/hostinger/install-docker.sh
set -eu

if command -v docker >/dev/null 2>&1; then
    echo "Docker déjà installé : $(docker --version)"
else
    echo "==> Installation Docker (get.docker.com)"
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

docker compose version
echo "Installation terminée."

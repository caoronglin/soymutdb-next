#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Linux Installation Script (docker compose 主路径)
# =====================================================================
# Usage: sudo bash deploy/linux/install.sh
# 说明：生产部署以 docker compose 为主路径（容器化，systemd 仅编排
# compose 项目）。历史 conda 裸进程部署（deploy/conda）已废弃，非主路径。
# =====================================================================
set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTALL_DIR="/opt/soymutdb"
SERVICE_USER="soymutdb"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Linux Installation (compose)${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Check root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}[ERROR] This script must be run as root (use sudo).${NC}"
    exit 1
fi

# ---------------------------------------------------------------------
# Step 1: Check Docker dependency
# ---------------------------------------------------------------------
echo -e "${CYAN}[1/7] Checking Docker dependency...${NC}"
if ! command -v docker &>/dev/null; then
    echo -e "${RED}[ERROR] docker not found. Install Docker Engine first (https://docs.docker.com/engine/install/).${NC}"
    exit 1
fi
if ! docker compose version &>/dev/null; then
    echo -e "${RED}[ERROR] docker compose plugin not found. Install docker-compose-plugin.${NC}"
    exit 1
fi
echo -e "${GREEN}  Docker found: $(docker --version)${NC}"

# ---------------------------------------------------------------------
# Step 2: Create service user and directory structure
# ---------------------------------------------------------------------
echo -e "${CYAN}[2/7] Creating service user '${SERVICE_USER}'...${NC}"
if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    echo -e "${YELLOW}  User '${SERVICE_USER}' already exists, skipping.${NC}"
else
    useradd --system --shell /bin/bash --home-dir "${INSTALL_DIR}" --create-home "${SERVICE_USER}"
    echo -e "${GREEN}  User '${SERVICE_USER}' created.${NC}"
fi

mkdir -p "${INSTALL_DIR}"/{apps,data,logs,config}
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
chmod 750 "${INSTALL_DIR}/data"
echo -e "${GREEN}  Directories created at ${INSTALL_DIR}.${NC}"

# ---------------------------------------------------------------------
# Step 3: Copy application files (compose project)
# ---------------------------------------------------------------------
echo -e "${CYAN}[3/7] Copying application files...${NC}"
cp -r "${PROJECT_ROOT}/apps/api" "${INSTALL_DIR}/apps/"
cp -r "${PROJECT_ROOT}/apps/worker" "${INSTALL_DIR}/apps/"
cp -r "${PROJECT_ROOT}/packages" "${INSTALL_DIR}/"
cp -r "${PROJECT_ROOT}/infra" "${INSTALL_DIR}/"
cp -r "${PROJECT_ROOT}/deploy/scripts" "${INSTALL_DIR}/"
cp "${PROJECT_ROOT}/docker-compose.yml" "${INSTALL_DIR}/"
echo -e "${GREEN}  Application files copied (incl. docker-compose.yml, deploy/scripts).${NC}"

# ---------------------------------------------------------------------
# Step 4: Create environment file from template
# ---------------------------------------------------------------------
echo -e "${CYAN}[4/7] Creating environment file...${NC}"
if [[ -f "${INSTALL_DIR}/.env" ]]; then
    echo -e "${YELLOW}  ${INSTALL_DIR}/.env already exists, keeping it.${NC}"
elif [[ -f "${PROJECT_ROOT}/deploy/.env.example" ]]; then
    cp "${PROJECT_ROOT}/deploy/.env.example" "${INSTALL_DIR}/.env"
    echo -e "${YELLOW}  Copied deploy/.env.example to .env - EDIT IT with production values:${NC}"
    echo -e "${YELLOW}    - *_IMAGE_REF (CI 发布合同中的 image@sha256)${NC}"
    echo -e "${YELLOW}    - SOYMUTDB_JWT_SECRET / SOYMUTDB_CORS_ORIGINS (API fail-fast 必填)${NC}"
    echo -e "${YELLOW}    - POSTGRES_PASSWORD / CLICKHOUSE_PASSWORD / REDIS_PASSWORD / MINIO_*${NC}"
fi
chmod 600 "${INSTALL_DIR}/.env"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
echo -e "${GREEN}  Environment file ready at ${INSTALL_DIR}/.env.${NC}"

# ---------------------------------------------------------------------
# Step 5: Install systemd service files
# ---------------------------------------------------------------------
echo -e "${CYAN}[5/7] Installing systemd service files...${NC}"
cp "${SCRIPT_DIR}/soymutdb-api.service" /etc/systemd/system/
cp "${SCRIPT_DIR}/soymutdb.target" /etc/systemd/system/
rm -f /etc/systemd/system/soymutdb-worker.service /etc/systemd/system/soymutdb-beat.service

systemctl daemon-reload
echo -e "${GREEN}  Service files installed and daemon reloaded.${NC}"

# ---------------------------------------------------------------------
# Step 6: Enable services
# ---------------------------------------------------------------------
echo -e "${CYAN}[6/7] Enabling services...${NC}"
systemctl enable soymutdb-api.service soymutdb.target
echo -e "${GREEN}  Enabled soymutdb-api.service + soymutdb.target.${NC}"

# ---------------------------------------------------------------------
# Step 7: Verify compose configuration
# ---------------------------------------------------------------------
echo -e "${CYAN}[7/7] Verifying compose configuration...${NC}"
if (cd "${INSTALL_DIR}" && docker compose -f docker-compose.yml config -q); then
    echo -e "${GREEN}  docker compose config OK.${NC}"
else
    echo -e "${YELLOW}  Compose validation failed (missing env vars?). Fill ${INSTALL_DIR}/.env first.${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit ${INSTALL_DIR}/.env with production values (镜像 digest refs / 密钥 / 密码)"
echo "  2. Start stack:  sudo systemctl start soymutdb.target"
echo "  3. Upgrade:      sudo bash ${INSTALL_DIR}/deploy/scripts/upgrade.sh"
echo "  4. Check status: sudo systemctl status soymutdb.target"
echo "  5. View logs:    cd ${INSTALL_DIR} && docker compose logs -f api"
echo ""

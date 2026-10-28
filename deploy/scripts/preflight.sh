#!/usr/bin/env bash
# =============================================================================
# Stocknomist Deployment Preflight Script (ADR-014 Shared-Host Guarded)
# Validates host resources, docker engine, port non-collision, and permissions.
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================================================"
echo "          Stocknomist Preflight Host Audit (ADR-014 Guarded)            "
echo "========================================================================"

# 1. Docker Engine Verification
echo -n "[1/6] Checking Docker Engine availability... "
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    DOCKER_VER=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "detected")
    echo -e "${GREEN}OK${NC} (${DOCKER_VER})"
else
    echo -e "${RED}FAILED${NC}"
    echo "ERROR: Docker engine is not installed or not running." >&2
    exit 1
fi

# 2. Docker Compose Verification
echo -n "[2/6] Checking Docker Compose availability... "
if docker compose version >/dev/null 2>&1; then
    COMPOSE_VER=$(docker compose version --short 2>/dev/null || echo "detected")
    echo -e "${GREEN}OK${NC} (${COMPOSE_VER})"
else
    echo -e "${RED}FAILED${NC}"
    echo "ERROR: Docker Compose is not available." >&2
    exit 1
fi

# 3. Dedicated Loopback Port Non-Collision Check (Port 18800)
echo -n "[3/6] Checking loopback port 127.0.0.1:18800 availability... "
PORT_LISTENER=$(ss -tulpn 2>/dev/null | grep -E ':18800\s' || true)
if [ -z "$PORT_LISTENER" ]; then
    echo -e "${GREEN}OK${NC} (Port 18800 is completely free)"
else
    # Port is in use - check if it is our own stocknomist container for idempotent redeploy
    if echo "$PORT_LISTENER" | grep -q "docker-proxy"; then
        RUNNING_CONTAINER=$(docker ps --filter "publish=18800" --format '{{.Names}}' 2>/dev/null || true)
        if [ "$RUNNING_CONTAINER" = "stocknomist" ] || [ "$RUNNING_CONTAINER" = "stocknomist-app" ]; then
            echo -e "${YELLOW}REDEPLOY${NC} (Bound by active container '$RUNNING_CONTAINER'; will be refreshed)"
        else
            echo -e "${RED}CONFLICT${NC}"
            echo "ERROR: Port 18800 is bound by another container: $RUNNING_CONTAINER" >&2
            exit 1
        fi
    else
        echo -e "${RED}CONFLICT${NC}"
        echo "ERROR: Port 18800 is bound by a non-docker process: $PORT_LISTENER" >&2
        exit 1
    fi
fi

# 4. Host Available Memory Check (ADR-014 requires >= 1024 MB free)
echo -n "[4/6] Checking host available RAM (min 1024 MB)... "
MEM_AVAILABLE_KB=$(awk '/MemAvailable/ {print $2}' /proc/meminfo 2>/dev/null || echo "0")
MEM_AVAILABLE_MB=$((MEM_AVAILABLE_KB / 1024))
if [ "$MEM_AVAILABLE_MB" -ge 1024 ]; then
    echo -e "${GREEN}OK${NC} (${MEM_AVAILABLE_MB} MB available, >= 1024 MB required)"
else
    echo -e "${RED}INSUFFICIENT${NC}"
    echo "ERROR: Available RAM is ${MEM_AVAILABLE_MB} MB, below required 1024 MB." >&2
    exit 1
fi

# 5. Host Root Filesystem Space Check (ADR-014 requires >= 5120 MB free)
echo -n "[5/6] Checking root disk headroom (min 5120 MB / 5 GiB)... "
DISK_AVAIL_MB=$(df -m / 2>/dev/null | awk 'NR==2 {print $4}')
if [ "$DISK_AVAIL_MB" -ge 5120 ]; then
    echo -e "${GREEN}OK${NC} (${DISK_AVAIL_MB} MB free, >= 5120 MB required)"
else
    echo -e "${RED}INSUFFICIENT${NC}"
    echo "ERROR: Root disk free space is ${DISK_AVAIL_MB} MB, below 5120 MB reserve." >&2
    exit 1
fi

# 6. Persistent Data Directory & Ownership Check
echo -n "[6/6] Checking data directory permissions (UID 10001:10001)... "
TARGET_DATA_DIR="/opt/stocknomist/data"
mkdir -p "$TARGET_DATA_DIR" "$TARGET_DATA_DIR/cache"
chown -R 10001:10001 "$TARGET_DATA_DIR"
chmod 0755 "$TARGET_DATA_DIR"
echo -e "${GREEN}OK${NC} (Directory ready: $TARGET_DATA_DIR)"

echo "------------------------------------------------------------------------"
echo -e "${GREEN}All Preflight checks PASSED successfully! Ready for deployment.${NC}"
echo "========================================================================"
exit 0

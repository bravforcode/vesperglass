#!/usr/bin/env bash
# =============================================================================
# Stocknomist Automated Deployment Orchestrator (ADR-014 Guarded)
# Handles preflight, multi-stage build, container startup, Caddy reverse-proxy
# configuration with TLS and Basic Auth, and post-deployment smoke verification.
# =============================================================================
set -euo pipefail

DEPLOY_DIR="/opt/stocknomist"
cd "$DEPLOY_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================================================${NC}"
echo -e "${BLUE}       Stocknomist Deployment Orchestrator (ADR-014 Shared-Host)       ${NC}"
echo -e "${BLUE}========================================================================${NC}"

# -----------------------------------------------------------------------------
# Step 1: Preflight Host Audit
# -----------------------------------------------------------------------------
echo -e "\n${YELLOW}==> [1/6] Executing Host Preflight Audit...${NC}"
bash deploy/scripts/preflight.sh

# -----------------------------------------------------------------------------
# Step 2: Clean Existing Legacy / Running Containers
# -----------------------------------------------------------------------------
echo -e "\n${YELLOW}==> [2/6] Preparing Docker Service Environment...${NC}"
# Gracefully stop existing instances to release loopback port 18800
docker compose down --remove-orphans 2>/dev/null || true
if docker ps -a --format '{{.Names}}' | grep -E '^(stocknomist|stocknomist-app)$' >/dev/null 2>&1; then
    docker rm -f stocknomist stocknomist-app 2>/dev/null || true
fi

# -----------------------------------------------------------------------------
# Step 3: Build Container Image (Multi-Stage Node + Python)
# -----------------------------------------------------------------------------
echo -e "\n${YELLOW}==> [3/6] Building Production Container (Multi-Stage Node + Python)...${NC}"
docker compose build

# -----------------------------------------------------------------------------
# Step 4: Launch Container Service
# -----------------------------------------------------------------------------
echo -e "\n${YELLOW}==> [4/6] Starting Container Service (stocknomist-app)...${NC}"
docker compose up -d

echo -e "\n${YELLOW}==> [4.1] Polling Local Loopback Health Endpoint (http://127.0.0.1:18800/health)...${NC}"
HEALTHY=false
for i in {1..20}; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18800/health 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}✓ Container is healthy (HTTP 200 received on attempt $i)${NC}"
        HEALTHY=true
        break
    fi
    echo "  Attempt $i: status=$HTTP_CODE. Waiting 2s..."
    sleep 2
done

if [ "$HEALTHY" != "true" ]; then
    echo -e "${RED}ERROR: Container healthcheck failed to respond with HTTP 200!${NC}" >&2
    echo "Recent container logs:" >&2
    docker compose logs --tail 60 >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# Step 5: Configure Host Caddy Reverse Proxy & Basic Auth
# -----------------------------------------------------------------------------
echo -e "\n${YELLOW}==> [5/6] Configuring Host Caddy Reverse Proxy & Security...${NC}"

# 5.1 Install Caddy modular snippet
echo "  Installing /etc/caddy/stocknomist.caddy..."
cp deploy/caddy/stocknomist.caddy /etc/caddy/stocknomist.caddy
chown root:caddy /etc/caddy/stocknomist.caddy
chmod 0640 /etc/caddy/stocknomist.caddy

# 5.2 Configure Basic Auth password hash (admin:stocknomist2026)
echo "  Setting up Basic Auth credential hash (/etc/caddy/stocknomist-password.hash)..."
cat << 'EOF' > /etc/caddy/stocknomist-password.hash
admin $2a$14$UG2YPfqN/mBy7u8nlNUbLucLSbgcMm45YZGwSf3ECSENU61r5PbKO
EOF
chown root:caddy /etc/caddy/stocknomist-password.hash
chmod 0640 /etc/caddy/stocknomist-password.hash

# 5.3 Ensure snippet is imported into /etc/caddy/Caddyfile
if ! grep -q "import /etc/caddy/stocknomist.caddy" /etc/caddy/Caddyfile; then
    echo "  Adding modular import to /etc/caddy/Caddyfile..."
    cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak-$(date +%Y%m%d%H%M%S)"
    echo -e "\nimport /etc/caddy/stocknomist.caddy" >> /etc/caddy/Caddyfile
fi

# 5.4 Validate Caddy configuration before reloading
echo "  Validating Caddy configuration..."
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# 5.5 Reload Caddy with zero downtime
echo "  Reloading Caddy web server..."
systemctl reload caddy

# -----------------------------------------------------------------------------
# Step 6: Post-Deployment Smoke Verification
# -----------------------------------------------------------------------------
echo -e "\n${YELLOW}==> [6/6] Executing Live Smoke Verification...${NC}"

# Check loopback
LOOPBACK_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18800/health)
echo "  [Test 1/4] Loopback Probe (http://127.0.0.1:18800/health): HTTP $LOOPBACK_CODE"
if [ "$LOOPBACK_CODE" != "200" ]; then
    echo -e "${RED}FAILED: Loopback probe did not return 200${NC}" >&2
    exit 1
fi

# Check public health bypass (no auth required)
PUBLIC_HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" https://stocknomist.168-222-27-36.sslip.io/health)
echo "  [Test 2/4] Public Health Bypass (https://stocknomist.168-222-27-36.sslip.io/health): HTTP $PUBLIC_HEALTH_CODE"
if [ "$PUBLIC_HEALTH_CODE" != "200" ]; then
    echo -e "${RED}FAILED: Public health check bypass did not return 200${NC}" >&2
    exit 1
fi

# Check unauthenticated public access challenged with HTTP 401
UNAUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" https://stocknomist.168-222-27-36.sslip.io/)
echo "  [Test 3/4] Unauthenticated Root Challenge (https://stocknomist.168-222-27-36.sslip.io/): HTTP $UNAUTH_CODE"
if [ "$UNAUTH_CODE" != "401" ]; then
    echo -e "${RED}FAILED: Expected HTTP 401 Unauthorized for unauthenticated request, got $UNAUTH_CODE${NC}" >&2
    exit 1
fi

# Check authenticated access with admin credentials returns HTTP 200
AUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u admin:stocknomist2026 https://stocknomist.168-222-27-36.sslip.io/)
echo "  [Test 4/4] Authenticated App Ingress (admin:stocknomist2026): HTTP $AUTH_CODE"
if [ "$AUTH_CODE" != "200" ]; then
    echo -e "${RED}FAILED: Expected HTTP 200 OK for authenticated request, got $AUTH_CODE${NC}" >&2
    exit 1
fi

echo -e "\n${GREEN}========================================================================${NC}"
echo -e "${GREEN}✓ DEPLOYMENT COMPLETE & VERIFIED SUCCESSFULLY!${NC}"
echo -e "${GREEN}  Endpoint:    https://stocknomist.168-222-27-36.sslip.io${NC}"
echo -e "${GREEN}  Health:      https://stocknomist.168-222-27-36.sslip.io/health${NC}"
echo -e "${GREEN}  Auth:        admin / stocknomist2026${NC}"
echo -e "${GREEN}========================================================================${NC}"
exit 0

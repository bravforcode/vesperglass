"""
Stocknomist Final Milestone Security, Penetration & VPS Challenger Suite
Author: challenger_final_2
Role: Empirical Challenger (Adversarial Security & Infrastructure Audit)
Target: https://stocknomist.168-222-27-36.sslip.io and host 168.222.27.36
"""

import base64
import json
import os
import socket
import subprocess
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest
import requests
import urllib3

# Suppress unverified HTTPS warnings for tests
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://stocknomist.168-222-27-36.sslip.io"
VPS_HOST = "168.222.27.36"
VPS_PORT = 18800
SSH_KEY = "C:/Users/menum/.ssh/graxia-vps-1682222736"
SSH_USER = "root"
VALID_AUTH = ("admin", "stocknomist2026")


def run_ssh_command(cmd: str) -> str:
    """Run an SSH command against the VPS and return output."""
    ssh_cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{SSH_USER}@{VPS_HOST}",
        cmd
    ]
    res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        raise RuntimeError(f"SSH command failed (code {res.returncode}): {res.stderr}\nOutput: {res.stdout}")
    return res.stdout.strip()


# =========================================================================
# Module 1: Authentication Barrier Verification
# =========================================================================

class TestAuthenticationBarrier:
    """Verify that unauthenticated requests cannot access any protected routes."""

    @pytest.mark.parametrize("path", [
        "/",
        "/api/screen",
        "/api/market-pulse",
        "/api/stock/AAPL",
        "/api/stock/MSFT",
        "/assets/index-DKXbTtiX.js",
        "/vite.svg",
        "/nonexistent-secret-file",
    ])
    def test_unauthenticated_request_rejected(self, path):
        url = f"{BASE_URL}{path}"
        r = requests.get(url, verify=False, timeout=10)
        assert r.status_code == 401, f"Expected 401 for unauth GET {path}, got {r.status_code}"
        assert "Basic" in r.headers.get("Www-Authenticate", ""), f"Missing Www-Authenticate header for {path}"

    def test_health_endpoint_publicly_accessible(self):
        url = f"{BASE_URL}/health"
        r = requests.get(url, verify=False, timeout=10)
        assert r.status_code == 200, f"Expected 200 for public /health, got {r.status_code}"
        data = r.json()
        assert data.get("status") == "ok", f"Unexpected health payload: {data}"

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    def test_unauthenticated_verbs_rejected(self, method):
        url = f"{BASE_URL}/api/screen"
        r = requests.request(method, url, verify=False, timeout=10)
        assert r.status_code == 401, f"Expected 401 for unauth {method} /api/screen, got {r.status_code}"


# =========================================================================
# Module 2: Hostile Path Traversal & Injection Fuzzing
# =========================================================================

class TestHostilePathTraversalFuzzing:
    """Fuzz endpoints with traversal sequences, null bytes, and malicious payloads."""

    TRAVERSAL_PAYLOADS = [
        "../etc/passwd",
        "..%2Fetc%2Fpasswd",
        "%2e%2e%2fetc%2fpasswd",
        "%2e%2e/%2e%2e/%2e%2e/etc/passwd",
        "%252e%252e%252fetc%252fpasswd",
        "..;/..;/etc/passwd",
        "....//....//etc/passwd",
        "..%5c..%5cwindows%5cwin.ini",
        "/%2e%2e/health",
        "/health/../api/screen",
        "/health/%2e%2e/api/screen",
        "/assets/..%2f..%2fapp/main.py",
        "/assets/%2e%2e%2findex.html",
        "/assets/%20/..%2Fmain.py",
        "/api/stock/..%2F..%2Fetc%2Fpasswd",
        "/api/stock/AAPL%00.json",
        "/api/stock/AAPL%0Acat",
        "/api/stock/'%20OR%201=1--",
        "/api/screen?strategy=../../etc/passwd",
        "/api/screen?strategy=<script>alert(1)</script>",
        "/api/screen?min_return=-999999999",
        "/api/screen?market_cap=INVALID_CAP_TIER_PAYLOAD",
    ]

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_hostile_traversal_payloads(self, payload):
        # Test without credentials: MUST be 400, 401, 404, or 422 (never 200 or 500)
        url = f"{BASE_URL}{payload if payload.startswith('/') else '/' + payload}"
        r = requests.get(url, verify=False, timeout=10)
        assert r.status_code in [400, 401, 404, 422], (
            f"Hostile payload {payload} produced unsafe status {r.status_code} (Unauthenticated)"
        )
        assert "root:x:0:0" not in r.text, "Arbitrary file leak (/etc/passwd) detected!"

        # Test WITH valid credentials: MUST be 200 (if safe query param fallback), 400, 404, or 422 (never leak arbitrary files or 500 crash)
        r_auth = requests.get(url, auth=VALID_AUTH, verify=False, timeout=10)
        assert r_auth.status_code in [200, 400, 404, 422], (
            f"Hostile payload {payload} produced unsafe status {r_auth.status_code} (Authenticated)"
        )
        assert r_auth.status_code != 500, f"Hostile payload caused HTTP 500 internal crash: {payload}"
        assert "root:x:0:0" not in r_auth.text, "Arbitrary file leak (/etc/passwd) detected with auth!"


# =========================================================================
# Module 3: Basic Auth Brute-Force & Malformed Header Fuzzing
# =========================================================================

class TestBasicAuthFuzzing:
    """Stress test authentication parsing with dictionary attacks and malformed headers."""

    DICTIONARY_ATTEMPTS = [
        ("admin", "admin"),
        ("admin", "123456"),
        ("admin", "password"),
        ("admin", "root"),
        ("root", "root"),
        ("guest", "guest"),
        ("stocknomist", "stocknomist"),
        ("admin", "stocknomist"),
        ("admin", "Stocknomist2026"),  # case sensitivity check
        ("administrator", "stocknomist2026"),
        ("admin' OR '1'='1", "stocknomist2026"),
        ("admin; DROP TABLE users;--", "stocknomist2026"),
    ]

    @pytest.mark.parametrize("username,password", DICTIONARY_ATTEMPTS)
    def test_credential_dictionary_rejection(self, username, password):
        r = requests.get(f"{BASE_URL}/api/screen", auth=(username, password), verify=False, timeout=10)
        assert r.status_code == 401, f"Failed to reject invalid credentials: {username}:{password}"

    def test_malformed_auth_headers(self):
        cases = [
            ("Empty", ""),
            ("Invalid Scheme Bearer", "Bearer some_jwt_token_here"),
            ("Non-Base64", "Basic !@#$%^&*()_+"),
            ("No Colon In Payload", f"Basic {base64.b64encode(b'adminonly').decode()}"),
            ("Empty User Empty Pass", f"Basic {base64.b64encode(b':').decode()}"),
            ("Giant Header 8KB", "Basic " + "A" * 8192),
            ("Giant Header 16KB", "Basic " + "B" * 16384),
        ]
        for name, header_val in cases:
            headers = {"Authorization": header_val} if header_val else {}
            r = requests.get(f"{BASE_URL}/api/screen", headers=headers, verify=False, timeout=10)
            assert r.status_code in [400, 401, 431], (
                f"Malformed auth header '{name}' produced unexpected code {r.status_code}"
            )

    def test_valid_auth_success(self):
        endpoints = ["/", "/api/screen", "/api/market-pulse", "/api/stock/AAPL"]
        for ep in endpoints:
            r = requests.get(f"{BASE_URL}{ep}", auth=VALID_AUTH, verify=False, timeout=10)
            assert r.status_code == 200, f"Valid auth failed for {ep}: got {r.status_code}"
            # Verify security headers
            assert "Strict-Transport-Security" in r.headers, f"Missing HSTS on {ep}"
            assert "X-Frame-Options" in r.headers, f"Missing X-Frame-Options on {ep}"
            assert "Content-Security-Policy" in r.headers, f"Missing CSP on {ep}"


# =========================================================================
# Module 4: Direct Port Reachability (Loopback Confinement)
# =========================================================================

class TestDirectPortReachability:
    """Verify that port 18800 is bound strictly to loopback and blocked externally."""

    def test_external_port_18800_unreachable(self):
        """TCP connect to public IP:18800 MUST time out or be refused."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(4.0)
        reachable = False
        try:
            s.connect((VPS_HOST, VPS_PORT))
            reachable = True
        except (socket.timeout, ConnectionRefusedError, OSError):
            reachable = False
        finally:
            s.close()
        assert not reachable, f"SECURITY VIOLATION: Port {VPS_PORT} on {VPS_HOST} is directly reachable from public internet!"

    def test_vps_loopback_socket_binding(self):
        """Verify on VPS host that docker-proxy binds to 127.0.0.1:18800 ONLY."""
        ss_out = run_ssh_command("ss -tulpn | grep 18800")
        assert "127.0.0.1:18800" in ss_out, f"Expected 127.0.0.1:18800 in socket listeners, got: {ss_out}"
        assert "0.0.0.0:18800" not in ss_out, f"Dangerous binding to 0.0.0.0 detected: {ss_out}"
        assert ":::18800" not in ss_out, f"Dangerous IPv6 wildcard binding detected: {ss_out}"

        port_out = run_ssh_command("docker port stocknomist-app")
        assert "127.0.0.1:18800" in port_out, f"Docker port binding not loopback: {port_out}"


# =========================================================================
# Module 5: Cgroup Resource Limits & Live Load Stress Audit
# =========================================================================

class TestContainerResourceLimitsAndLoad:
    """Inspect kernel cgroup limits and verify container memory remains bounded under load."""

    def test_cgroup_limits_enforced(self):
        out = run_ssh_command(
            'CID=$(docker inspect -f "{{.Id}}" stocknomist-app); '
            'echo "CID:$CID"; '
            'echo "MEM_MAX:$(cat /sys/fs/cgroup/system.slice/docker-${CID}.scope/memory.max)"; '
            'echo "PIDS_MAX:$(cat /sys/fs/cgroup/system.slice/docker-${CID}.scope/pids.max)"; '
            'echo "CPU_MAX:$(cat /sys/fs/cgroup/system.slice/docker-${CID}.scope/cpu.max)"; '
            'echo "MEM_CURR:$(cat /sys/fs/cgroup/system.slice/docker-${CID}.scope/memory.current)"'
        )
        lines = dict(item.split(":", 1) for item in out.splitlines() if ":" in item)

        mem_max = int(lines.get("MEM_MAX", 0))
        pids_max = int(lines.get("PIDS_MAX", 0))
        cpu_max = lines.get("CPU_MAX", "")
        mem_curr_bytes = int(lines.get("MEM_CURR", 0))
        mem_curr_mb = mem_curr_bytes / (1024 * 1024)

        assert mem_max == 1073741824, f"memory.max mismatch: expected 1073741824 (1GiB), got {mem_max}"
        assert pids_max == 128, f"pids.max mismatch: expected 128, got {pids_max}"
        assert cpu_max.strip() == "50000 100000", f"cpu.max mismatch: expected '50000 100000', got '{cpu_max}'"
        assert mem_curr_mb < 150.0, f"Memory exceeded 150MB: {mem_curr_mb:.2f} MB"

    def test_concurrent_load_and_memory_stability(self):
        """Fire 30 parallel requests using pooled session and confirm memory stays well below 1GiB and 0 OOM kills."""
        initial_mem_out = run_ssh_command(
            'CID=$(docker inspect -f "{{.Id}}" stocknomist-app); '
            'cat /sys/fs/cgroup/system.slice/docker-${CID}.scope/memory.current'
        )
        initial_mem_mb = int(initial_mem_out) / (1024 * 1024)

        session = requests.Session()
        session.auth = VALID_AUTH
        session.verify = False

        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=2)
        session.mount("https://", adapter)

        def make_req(idx):
            url = f"{BASE_URL}/api/screen" if idx % 2 == 0 else f"{BASE_URL}/api/stock/AAPL"
            r = session.get(url, timeout=25)
            return r.status_code

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_req, i) for i in range(30)]
            results = [f.result() for f in as_completed(futures)]

        assert all(code == 200 for code in results), f"Non-200 responses under load: {set(results)}"

        # Measure memory and OOM status after load
        post_out = run_ssh_command(
            'CID=$(docker inspect -f "{{.Id}}" stocknomist-app); '
            'echo "MEM:$(cat /sys/fs/cgroup/system.slice/docker-${CID}.scope/memory.current)"; '
            'echo "OOM:$(docker inspect -f \'{{.State.OOMKilled}}\' stocknomist-app)"'
        )
        post_lines = dict(item.split(":", 1) for item in post_out.splitlines() if ":" in item)
        post_mem_mb = int(post_lines.get("MEM", 0)) / (1024 * 1024)
        oom_killed = post_lines.get("OOM", "false").lower() == "true"

        assert not oom_killed, "CONTAINER EXPERIENCED OOM KILL!"
        # Verify memory remains strictly well under 1GiB ceiling (and within expected ~100-120MB range)
        assert post_mem_mb < 150.0, f"Memory under load exceeded 150MB: {post_mem_mb:.2f} MB (initial: {initial_mem_mb:.2f} MB)"


# =========================================================================
# Module 6: Neighbor Containers & Host Service Health Check
# =========================================================================

class TestNeighborContainersHealth:
    """Verify Graxia, Sanso, Windmill, and Caddy remain fully healthy on the host."""

    def test_neighbor_containers_operational(self):
        ps_out = run_ssh_command("docker ps --format '{{.Names}}|{{.Status}}'")
        containers = {}
        for line in ps_out.splitlines():
            if "|" in line:
                name, status = line.split("|", 1)
                containers[name.strip()] = status.strip()

        # Check required neighbor containers
        graxia_services = [
            "graxia_prod_backend",
            "graxia_prod_celery",
            "graxia_prod_beat",
            "graxia_prod_frontend",
            "graxia_prod_redis",
            "graxia_prod_postgres",
        ]
        sanso_services = [
            "sanso-prod-web-1",
            "sanso-prod-worker-1",
            "sanso-prod-postgres-1",
            "sanso-prod-redis-1",
        ]
        windmill_services = [
            "windmill-windmill_server-1",
            "windmill-db-1",
            "windmill-windmill_worker-1",
        ]

        for s in graxia_services:
            assert s in containers, f"Graxia container missing: {s}"
            assert "Up" in containers[s], f"Graxia container not Up: {s} -> {containers[s]}"
            assert "unhealthy" not in containers[s], f"Graxia container unhealthy: {s} -> {containers[s]}"

        for s in sanso_services:
            assert s in containers, f"Sanso container missing: {s}"
            assert "Up" in containers[s], f"Sanso container not Up: {s} -> {containers[s]}"
            assert "unhealthy" not in containers[s], f"Sanso container unhealthy: {s} -> {containers[s]}"

        for s in windmill_services:
            assert s in containers, f"Windmill container missing: {s}"
            assert "Up" in containers[s], f"Windmill container not Up: {s} -> {containers[s]}"
            assert "unhealthy" not in containers[s], f"Windmill container unhealthy: {s} -> {containers[s]}"

    def test_caddy_service_status(self):
        caddy_status = run_ssh_command("systemctl is-active caddy")
        assert caddy_status == "active", f"Host Caddy service not active: {caddy_status}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(["-v", "-s", __file__]))

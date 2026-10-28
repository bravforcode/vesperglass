"""
Milestone 3 Remediation Challenger Test Suite (Challenger 3).
Empirically challenges:
1. Complete neutralization of CWE-22 Path Traversal in serve_spa.
2. System file probes (Linux & Windows) blocked with HTTP 404 JSON.
3. Obfuscated, encoded, double-encoded, backslash, null-byte, and UNC path traversal attempts.
4. Correct SPA HTML5 client route fallback (HTTP 200 without caching headers).
5. Immutable caching headers for static assets in dist/assets.
6. Absolute isolation of /api/* routes from SPA catch-all.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app) as test_client:
        yield test_client


# =============================================================================
# 1. CWE-22 Path Traversal Neutralization & Exfiltration Tests
# =============================================================================

class TestCwe22TraversalNeutralization:
    """Verifies that arbitrary file exfiltration outside dist_dir is completely blocked."""

    @pytest.mark.parametrize("payload,target_desc", [
        ("/..%2F..%2Fbackend%2Fapp%2Fconfig.py", "backend config.py"),
        ("/..%2F..%2Fbackend%2Fapp%2Fmain.py", "backend main.py"),
        ("/..%2F..%2Fdata%2Fstocknomist.db", "SQLite stocknomist.db"),
        ("/..%2F..%2Fdata%2Fmarket_data.duckdb", "DuckDB market_data.duckdb"),
        ("/..%2F..%2Fpackage.json", "root package.json"),
        ("/..%2F..%2Fdeploy%2FDockerfile", "Dockerfile"),
        ("/..%2F..%2Fbackend%2Fapp%2Fdata_seeds%2Fsp500.json", "sp500.json seed"),
    ])
    def test_url_encoded_traversal_blocked(self, client, payload, target_desc):
        """URL-encoded traversal must return 404 JSON and never leak file contents."""
        res = client.get(payload)
        assert res.status_code == 404, (
            f"Expected 404 for {target_desc} ({payload}), got {res.status_code}"
        )
        assert res.headers.get("content-type", "").startswith("application/json")
        data = res.json()
        assert data.get("detail") == "Not found"
        # Confirm no file content leaked
        assert "AppConfig" not in res.text
        assert "SQLite format" not in res.text
        assert "DUCK" not in res.text

    @pytest.mark.parametrize("payload", [
        "/..%5C..%5Cbackend%5Capp%5Cconfig.py",
        "/..%5c..%5cdata%5cstocknomist.db",
        "/%2e%2e/%2e%2e/backend/app/config.py",
        "/%2e%2e%2f%2e%2e%2fbackend/app/config.py",
        "/%2e%2e%5c%2e%2e%5cbackend/app/config.py",
        "/....//backend/app/config.py",
        "/..//..//backend/app/config.py",
        "/assets/..%2f..%2fbackend/app/config.py",
        "/assets/..%5c..%5cbackend/app/config.py",
        "/assets/..%2F..%2Fdata%2Fstocknomist.db",
        "/%252e%252e%252f%252e%252e%252fbackend%252fapp%252fconfig.py",
    ])
    def test_diverse_traversal_encodings_blocked(self, client, payload):
        """Diverse traversal encodings and prefix tricks must return 404 JSON."""
        res = client.get(payload)
        assert res.status_code == 404, f"Expected 404 for payload {payload}, got {res.status_code}"
        assert res.headers.get("content-type", "").startswith("application/json")
        assert "AppConfig" not in res.text
        assert "SQLite format" not in res.text


# =============================================================================
# 2. System Probes & OS Path Probing Tests
# =============================================================================

class TestSystemProbes:
    """Verifies that OS probes (Linux / Windows) return 404 JSON."""

    @pytest.mark.parametrize("probe", [
        "/etc/passwd",
        "/etc/shadow",
        "/etc/hosts",
        "/ETC/PASSWD",
        "/proc/self/cmdline",
        "/proc/self/environ",
        "/proc/cpuinfo",
        "/sys/class/net",
        "/sys/devices",
        "/windows/system32/cmd.exe",
        "/windows/win.ini",
        "/WINDOWS/SYSTEM32/CALC.EXE",
        "/Windows/System32/drivers/etc/hosts",
    ])
    def test_sensitive_os_probes_return_404_json(self, client, probe):
        """OS probe paths must be intercepted and return HTTP 404 JSON, not HTML."""
        res = client.get(probe)
        assert res.status_code == 404, f"Expected 404 for probe {probe}, got {res.status_code}"
        assert res.headers.get("content-type", "").startswith("application/json")
        data = res.json()
        assert data.get("detail") == "Not found"
        assert "<!doctype html>" not in res.text.lower()

    @pytest.mark.parametrize("payload", [
        "/C:/Windows/win.ini",
        "/c:/backend/app/config.py",
        "/D:/data/stocknomist.db",
        "/index.html::$DATA",
        "/vite.svg::$DATA",
        "/%00",
        "/assets%00",
        "/index.html%00.txt",
    ])
    def test_windows_ntfs_and_null_probes(self, client, payload):
        """NTFS alternate data streams, drive letters, and null bytes must return 404 JSON."""
        res = client.get(payload)
        assert res.status_code == 404, f"Expected 404 for {payload}, got {res.status_code}"
        assert res.headers.get("content-type", "").startswith("application/json")


# =============================================================================
# 3. Legitimate SPA Client Route Fallback & Header Verification
# =============================================================================

class TestSpaLegitimateRouting:
    """Verifies that legitimate SPA client-side routes properly serve index.html."""

    @pytest.mark.parametrize("route", [
        "/",
        "/screener",
        "/stock/AAPL",
        "/stock/NVDA",
        "/stock/MSFT",
        "/stock/BRK-B",
        "/portfolio",
        "/dashboard/analytics",
        "/watchlist",
        "/settings/general",
        "/deeply/nested/spa/client/view/state",
    ])
    def test_client_routes_serve_index_html(self, client, route):
        """Client-side routes must return HTTP 200 with text/html and index.html content."""
        res = client.get(route)
        assert res.status_code == 200, f"Expected 200 for client route {route}, got {res.status_code}"
        assert "text/html" in res.headers.get("content-type", "")
        # Must contain HTML root shell
        assert '<div id="root">' in res.text or "<!doctype html>" in res.text.lower()

        # Must NOT contain aggressive caching headers that poison SPA navigation
        cache_control = res.headers.get("cache-control", "")
        assert "immutable" not in cache_control.lower()
        assert "max-age=31536000" not in cache_control.lower()


# =============================================================================
# 4. Static Dist Asset Resolution & Caching Headers
# =============================================================================

class TestStaticDistAssets:
    """Verifies direct file serving from dist_dir."""

    def test_root_index_html_direct_access(self, client):
        """Direct access to /index.html returns 200 OK text/html."""
        res = client.get("/index.html")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert '<div id="root">' in res.text

    def test_root_vite_svg_direct_access(self, client):
        """Direct access to /vite.svg returns 200 OK image/svg+xml."""
        res = client.get("/vite.svg")
        assert res.status_code == 200
        assert "image/svg+xml" in res.headers.get("content-type", "")
        assert "<svg" in res.text

    def test_assets_immutable_headers(self, client):
        """Static bundled assets in /assets/ must have immutable Cache-Control headers."""
        for asset in [
            "/assets/index-DKXbTtiX.js",
            "/assets/index-DSOH8dwQ.css",
            "/assets/vendor-charts-BAEAfuc8.js",
            "/assets/vendor-react-l0sNRNKZ.js",
            "/assets/vendor-table-smynQQcU.js",
        ]:
            res = client.get(asset)
            assert res.status_code == 200, f"Failed to fetch asset {asset}"
            assert res.headers.get("cache-control") == "public, max-age=31536000, immutable"
            assert len(res.content) > 0


# =============================================================================
# 5. API Route Isolation
# =============================================================================

class TestApiRouteIsolation:
    """Ensures /api/* and /health are never hijacked by SPA catch-all."""

    @pytest.mark.parametrize("api_route", [
        "/health",
        "/api/market-pulse",
        "/api/screen",
        "/api/universe",
        "/api/stock/AAPL",
    ])
    def test_valid_api_routes_return_200_json(self, client, api_route):
        """Valid API endpoints return 200 JSON."""
        res = client.get(api_route)
        assert res.status_code == 200
        assert "application/json" in res.headers.get("content-type", "")

    @pytest.mark.parametrize("missing_api_route", [
        "/api/nonexistent",
        "/api/v1/unknown",
        "/api/screen/deep/invalid",
        "/api/stock/AAPL/invalid_subresource",
        "/health/extra",
    ])
    def test_missing_api_routes_return_404_json(self, client, missing_api_route):
        """Invalid API endpoints must return 404 JSON, NOT 200 HTML."""
        res = client.get(missing_api_route)
        assert res.status_code == 404, f"Expected 404 for {missing_api_route}, got {res.status_code}"
        assert "application/json" in res.headers.get("content-type", "")
        assert "<!doctype html>" not in res.text.lower()
        assert '<div id="root">' not in res.text

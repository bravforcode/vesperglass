"""
Empirical Challenger 1 Test Suite for Milestone 3 (Tokenomist Dark UI & FastAPI Service).
Executed by Challenger 1 (Roles: critic, specialist).

Adversarially stress-tests:
1. Hostile Query Inputs on /api/screen (SQL/DuckDB injections, extreme limits, negative values, unknown strategies/sectors).
2. Degenerate & Non-Existent Tickers on /api/stock/{ticker} (unknown symbols, path traversal normalization).
3. Concurrency & Thread Safety (multithreaded concurrent requests against SQLite WAL and DuckDB cache).
4. JSON RFC 8259 Compliance (strict absence of NaN / Inf, header integrity).
5. Static SPA Fallback & API Isolation (HTML5 fallback for client routes, 404 JSON preservation for /api/*).
6. Security Vulnerability Reproduction: Arbitrary File Read / Path Traversal in serve_spa.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app) as test_client:
        yield test_client


# =============================================================================
# 1. Hostile Query Inputs on /api/screen
# =============================================================================

class TestScreenHostileInputs:
    """Stress tests for /api/screen input sanitization, boundaries, and SQL injection safety."""

    def test_screen_sql_injection_payloads(self, client):
        """
        Adversarially injects classic and DuckDB/SQLite SQL injection payloads into
        query parameters: strategy, sector, search, market_cap, sort_by, sort_dir.
        Verifies: No SQL execution, no database corruption, no unhandled 500 error.
        """
        injection_payloads = [
            "'; DROP TABLE screener_signals; --",
            "' OR '1'='1",
            "1' UNION SELECT 1, 'HACK', 'HACK', 100, 100, 10, 200, 50, 10, 1, 50, 1, 100, 100, 100, 'injected' --",
            "'; UPDATE company_fundamentals SET roe = -9999; --",
            "admin'--",
            "\" OR \"\"=\"",
            "' OR 1=1; ATTACH DATABASE 'hacked.db' AS hacked; --",
            "<script>alert('xss')</script>",
            "../../../../etc/passwd",
            "%00%27%20OR%201=1",
        ]

        for payload in injection_payloads:
            # Test in strategy
            res = client.get(f"/api/screen?strategy={payload}")
            assert res.status_code == 200, f"Failed on strategy injection '{payload}': {res.status_code}"
            assert isinstance(res.json(), list)

            # Test in sector
            res = client.get(f"/api/screen?sector={payload}")
            assert res.status_code == 200, f"Failed on sector injection '{payload}': {res.status_code}"
            assert isinstance(res.json(), list)

            # Test in search
            res = client.get(f"/api/screen?search={payload}")
            assert res.status_code == 200, f"Failed on search injection '{payload}': {res.status_code}"
            assert isinstance(res.json(), list)

            # Test in sort_by
            res = client.get(f"/api/screen?sort_by={payload}")
            assert res.status_code == 200, f"Failed on sort_by injection '{payload}': {res.status_code}"
            assert isinstance(res.json(), list)

            # Test in sort_dir
            res = client.get(f"/api/screen?sort_dir={payload}")
            assert res.status_code == 200, f"Failed on sort_dir injection '{payload}': {res.status_code}"
            assert isinstance(res.json(), list)

    def test_screen_extreme_limit_boundaries(self, client):
        """
        FastAPI specifies limit: int = Query(50, ge=1, le=200).
        Verifies that out-of-range limits are rejected with HTTP 422 Unprocessable Entity
        and in-range boundaries return valid results.
        """
        # Negative limits must be rejected with 422
        res_neg = client.get("/api/screen?limit=-1")
        assert res_neg.status_code == 422, f"Expected 422 for limit=-1, got {res_neg.status_code}"

        res_zero = client.get("/api/screen?limit=0")
        assert res_zero.status_code == 422, f"Expected 422 for limit=0, got {res_zero.status_code}"

        # Excessive limits must be rejected with 422
        res_excess = client.get("/api/screen?limit=201")
        assert res_excess.status_code == 422, f"Expected 422 for limit=201, got {res_excess.status_code}"

        res_huge = client.get("/api/screen?limit=100000")
        assert res_huge.status_code == 422, f"Expected 422 for limit=100000, got {res_huge.status_code}"

        # Non-integer limits
        res_str = client.get("/api/screen?limit=abc")
        assert res_str.status_code == 422, f"Expected 422 for limit=abc, got {res_str.status_code}"

        # Valid boundaries (1 and 200)
        res_one = client.get("/api/screen?limit=1")
        assert res_one.status_code == 200
        assert len(res_one.json()) <= 1

        res_max = client.get("/api/screen?limit=200")
        assert res_max.status_code == 200
        assert len(res_max.json()) <= 200

    def test_screen_negative_and_extreme_numeric_filters(self, client):
        """
        Tests handling of negative and extreme numeric values for min_return and min_rr.
        """
        # Negative min_return should succeed and return all qualifying candidates
        res_neg_ret = client.get("/api/screen?min_return=-10.0")
        assert res_neg_ret.status_code == 200
        assert isinstance(res_neg_ret.json(), list)

        # Extremely high min_return should return empty list gracefully
        res_high_ret = client.get("/api/screen?min_return=999999.0")
        assert res_high_ret.status_code == 200
        assert len(res_high_ret.json()) == 0

        # Extremely high min_rr (e.g. 100.0) should return empty list gracefully
        res_high_rr = client.get("/api/screen?min_rr=100.0")
        assert res_high_rr.status_code == 200
        assert len(res_high_rr.json()) == 0

        # Negative min_rr
        res_neg_rr = client.get("/api/screen?min_rr=-50.0")
        assert res_neg_rr.status_code == 200
        assert isinstance(res_neg_rr.json(), list)

    def test_screen_unknown_and_nonexistent_filters(self, client):
        """
        Tests filtering by non-existent strategies, sectors, and market cap tiers.
        """
        # Unknown strategy
        res_strat = client.get("/api/screen?strategy=non_existent_crypto_quant_strategy")
        assert res_strat.status_code == 200
        assert len(res_strat.json()) == 0

        # Unknown sector
        res_sec = client.get("/api/screen?sector=CryptocurrencyAndMining")
        assert res_sec.status_code == 200
        assert len(res_sec.json()) == 0

        # Unknown market cap tier
        res_mcap = client.get("/api/screen?market_cap=NanoMicroUnknown")
        assert res_mcap.status_code == 200
        assert len(res_mcap.json()) == 0

        # Non-matching search query
        res_search = client.get("/api/screen?search=XYZNONEXISTENTTICKER12345")
        assert res_search.status_code == 200
        assert len(res_search.json()) == 0


# =============================================================================
# 2. Degenerate & Non-Existent Tickers on /api/stock/{ticker}
# =============================================================================

class TestStockDetailEdgeInputs:
    """Stress tests for /api/stock/{ticker} symbol normalization and 404 contracts."""

    def test_stock_nonexistent_ticker(self, client):
        """Non-existent tickers must return 404 with structured JSON detail."""
        for sym in ["NONEXISTENT", "UNKNOWN_XYZ", "BOGUS99", "FAKE"]:
            res = client.get(f"/api/stock/{sym}")
            assert res.status_code == 404, f"Expected 404 for {sym}, got {res.status_code}"
            data = res.json()
            assert "detail" in data
            assert sym in data["detail"].upper()

    def test_stock_encoded_traversal_returns_404(self, client):
        """Encoded traversal strings in ticker path parameter must return 404."""
        traversal_attempts = [
            "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "%2e%2e%5c%2e%2e%5cwindows%5csystem32",
        ]
        for trav in traversal_attempts:
            res = client.get(f"/api/stock/{trav}")
            assert res.status_code == 404, f"Expected 404 for traversal '{trav}', got {res.status_code}"
            assert res.headers.get("content-type", "").startswith("application/json")

    def test_stock_special_characters_and_sql(self, client):
        """Special characters and SQL injection in ticker path parameter return 404."""
        hostile_symbols = [
            "AAPL'; DROP TABLE screener_signals; --",
            "AAPL<script>",
            "AAPL' OR '1'='1",
            "$$$INVALID$$$",
        ]
        for sym in hostile_symbols:
            res = client.get(f"/api/stock/{sym}")
            assert res.status_code == 404, f"Expected 404 for '{sym}', got {res.status_code}"
            assert res.headers.get("content-type", "").startswith("application/json")

    def test_stock_ticker_normalization(self, client):
        """Case-insensitivity and dot-to-hyphen conversion (e.g. aapl -> AAPL, BRK.B -> BRK-B)."""
        # Lowercase ticker lookup
        res_lower = client.get("/api/stock/aapl")
        assert res_lower.status_code == 200
        assert res_lower.json()["ticker"] == "AAPL"

        # Dot ticker lookup
        res_dot = client.get("/api/stock/BRK.B")
        assert res_dot.status_code == 200
        assert res_dot.json()["ticker"] == "BRK-B"


# =============================================================================
# 3. Concurrency & Thread Safety Stress Test
# =============================================================================

class TestConcurrencyAndThreadSafety:
    """Stress tests DuckDB and SQLite connection pooling under multithreaded load."""

    def test_concurrent_api_requests(self, client):
        """
        Executes 50 concurrent requests across multiple threads to /api/market-pulse,
        /api/screen, /api/stock/NVDA, /api/stock/AAPL, /api/universe, and /health.
        Verifies:
        - Zero 'database is locked' errors
        - Zero DuckDB thread collisions
        - Zero HTTP 500 errors
        - 100% of requests return HTTP 200
        """
        endpoints = [
            "/health",
            "/api/market-pulse",
            "/api/screen",
            "/api/screen?strategy=momentum_breakout",
            "/api/screen?min_return=5.0",
            "/api/stock/NVDA",
            "/api/stock/AAPL",
            "/api/stock/MSFT",
            "/api/universe",
        ]

        # 50 total tasks distributed across 10 worker threads
        tasks = [endpoints[i % len(endpoints)] for i in range(50)]

        def worker_fetch(path: str):
            res = client.get(path)
            return path, res.status_code, res.headers.get("content-type")

        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_fetch, p) for p in tasks]
            for future in as_completed(futures):
                path, status, ctype = future.result()
                results.append((path, status, ctype))

        assert len(results) == 50
        for path, status, ctype in results:
            assert status == 200, f"Concurrent request to {path} failed with status {status}"
            assert "application/json" in ctype


# =============================================================================
# 4. JSON RFC 8259 Compliance & Header Integrity
# =============================================================================

class TestJsonComplianceAndHeaders:
    """Verifies that all API outputs adhere to strict RFC 8259 JSON (no NaN / Inf)."""

    @staticmethod
    def _assert_no_nan_or_inf(data, path="root"):
        """Recursively checks that no float values are NaN, Inf, or -Inf."""
        if isinstance(data, dict):
            for k, v in data.items():
                TestJsonComplianceAndHeaders._assert_no_nan_or_inf(v, f"{path}.{k}")
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                TestJsonComplianceAndHeaders._assert_no_nan_or_inf(item, f"{path}[{idx}]")
        elif isinstance(data, float):
            assert math.isfinite(data), f"Non-finite float value found at {path}: {data}"
            assert not math.isnan(data), f"NaN float value found at {path}: {data}"

    def test_health_json_compliance(self, client):
        """Verifies /health response JSON compliance."""
        res = client.get("/health")
        assert res.status_code == 200
        raw_text = res.text
        parsed = json.loads(raw_text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Illegal constant {x}")))
        self._assert_no_nan_or_inf(parsed)

    def test_market_pulse_json_compliance(self, client):
        """Verifies /api/market-pulse response has no NaN or Inf in telemetry metrics."""
        res = client.get("/api/market-pulse")
        assert res.status_code == 200
        raw_text = res.text
        parsed = json.loads(raw_text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Illegal constant {x}")))
        self._assert_no_nan_or_inf(parsed)

    def test_screen_json_compliance(self, client):
        """Verifies /api/screen candidate objects contain zero NaN or Inf values."""
        res = client.get("/api/screen?limit=100")
        assert res.status_code == 200
        raw_text = res.text
        parsed = json.loads(raw_text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Illegal constant {x}")))
        self._assert_no_nan_or_inf(parsed)

    def test_stock_detail_json_compliance(self, client):
        """Verifies /api/stock/{ticker} profile contains zero NaN or Inf in indicators and candles."""
        for ticker in ["NVDA", "AAPL", "MSFT", "TSLA"]:
            res = client.get(f"/api/stock/{ticker}")
            assert res.status_code == 200
            raw_text = res.text
            parsed = json.loads(raw_text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Illegal constant {x}")))
            self._assert_no_nan_or_inf(parsed)


# =============================================================================
# 5. Static SPA Fallback & API Isolation
# =============================================================================

class TestSpaFallbackRouting:
    """Verifies SPA routing fallback logic and API 404 isolation."""

    def test_spa_arbitrary_client_routes_return_index(self, client):
        """Client-side paths should return index.html with 200 OK."""
        routes = [
            "/stocks/AAPL",
            "/dashboard",
            "/screener/momentum",
            "/settings/account",
            "/nonexistent/client/view",
        ]
        for route in routes:
            res = client.get(route)
            assert res.status_code == 200, f"Expected 200 for SPA route {route}, got {res.status_code}"
            assert "text/html" in res.headers.get("content-type", "")
            assert '<div id="root">' in res.text or "<!doctype html>" in res.text.lower()

    def test_api_routes_never_fallback_to_html(self, client):
        """
        Invalid /api routes must return HTTP 404 JSON, NOT HTTP 200 index.html.
        Catch-all SPA fallback must never mask missing API endpoints.
        """
        invalid_api_paths = [
            "/api/nonexistent",
            "/api/v1/invalid",
            "/api/screen/unknown",
            "/api/stocks/invalid/route",
        ]
        for path in invalid_api_paths:
            res = client.get(path)
            assert res.status_code == 404, f"Expected 404 for {path}, got {res.status_code}"
            assert "application/json" in res.headers.get("content-type", "")
            assert "<!doctype html>" not in res.text.lower()
            assert '<div id="root">' not in res.text

    def test_scan_refresh_endpoint(self, client):
        """Verifies POST /api/scan/refresh completes successfully."""
        res = client.post("/api/scan/refresh")
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "success"
        assert "pulse" in data


# =============================================================================
# 6. Empirical Vulnerability Reproduction: Arbitrary File Read via serve_spa
# =============================================================================

class TestVulnerabilityDemonstration:
    """
    Demonstrates confirmed security failure modes discovered during adversarial review.
    """

    def test_vuln_arbitrary_file_read_via_spa_catchall(self, client):
        """
        CONFIRMED VULNERABILITY (CWE-22):
        backend/app/main.py lines 99-105 does not validate that target_file.resolve()
        is within dist_dir.resolve().
        An attacker can traverse directories using encoded slashes (..%2F) and download
        source code or databases (e.g. backend/app/config.py, data/stocknomist.db).
        """
        # Attempt to read backend/app/config.py
        res = client.get("/..%2F..%2Fbackend%2Fapp%2Fconfig.py")

        # If vulnerable, status is 200 and source code is exposed
        # This test documents the empirical vulnerability:
        is_vulnerable = (res.status_code == 200 and "AppConfig" in res.text)
        print(f"\n[VULN PROOF] Arbitrary file read vulnerability present: {is_vulnerable}")
        if is_vulnerable:
            pytest.fail(
                "CRITICAL SECURITY VULNERABILITY (CWE-22): Path traversal in serve_spa allows "
                "reading arbitrary server files outside frontend/dist! "
                "Fetched backend/app/config.py with HTTP 200!"
            )

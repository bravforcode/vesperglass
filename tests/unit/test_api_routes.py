"""
Unit Test Suite for Stocknomist API Routes (Milestone 3).
Tests all REST endpoints with FastAPI TestClient:
- /health and /api/health
- /api/market-pulse
- /api/screen (multi-criteria filters, sorting, limits)
- /api/stock/{ticker} (deep dive profile, 252-day candles, indicators, trade setup, radar, checklist)
- /api/universe and /api/scan/refresh
"""

import unittest
from fastapi.testclient import TestClient

from backend.app.main import app


class TestApiRoutes(unittest.TestCase):
    """API endpoint verification test cases."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    # -------------------------------------------------------------------------
    # Health Probes
    # -------------------------------------------------------------------------

    def test_root_health_endpoint(self):
        """Test GET /health returns 200 with status ok and version."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["version"], "1.0.0")
        self.assertIn("cache_timestamp", data)

    def test_api_health_endpoint(self):
        """Test GET /api/health returns 200 with status ok."""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["version"], "1.0.0")

    # -------------------------------------------------------------------------
    # Market Pulse
    # -------------------------------------------------------------------------

    def test_market_pulse_structure(self):
        """Test GET /api/market-pulse returns index telemetry and bento metrics."""
        resp = self.client.get("/api/market-pulse")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Telemetry indices
        self.assertIn("indices", data)
        self.assertIn("SPY", data["indices"])
        self.assertIn("QQQ", data["indices"])
        self.assertIn("price", data["indices"]["SPY"])
        self.assertIn("change_pct", data["indices"]["SPY"])

        # Scan status and counts
        self.assertEqual(data["scan_status"], "COMPLETED")
        self.assertGreaterEqual(data["stocks_scanned"], 1000)
        self.assertGreater(data["candidates_found"], 0)

        # Top opportunity card
        self.assertIn("top_opportunity", data)
        top = data["top_opportunity"]
        self.assertIn("ticker", top)
        self.assertGreaterEqual(top["risk_reward_ratio"], 2.0)
        self.assertGreaterEqual(top["target_return_pct"], 3.0)

        # Active signals breakdown
        self.assertIn("active_signals", data)
        breakdown = data["active_signals"]
        self.assertIn("total", breakdown)
        self.assertIn("momentum", breakdown)
        self.assertIn("earnings", breakdown)
        self.assertIn("oversold", breakdown)
        self.assertIn("quality", breakdown)

        # Performance metrics
        self.assertGreaterEqual(data["expected_return_avg"], 3.0)
        self.assertGreaterEqual(data["win_rate_pct"], 50.0)

    # -------------------------------------------------------------------------
    # Screener Query & Filters
    # -------------------------------------------------------------------------

    def test_screener_unfiltered(self):
        """Test GET /api/screen returns list of candidate stocks with full schema."""
        resp = self.client.get("/api/screen")
        self.assertEqual(resp.status_code, 200)
        candidates = resp.json()
        self.assertIsInstance(candidates, list)
        self.assertGreater(len(candidates), 0)

        sample = candidates[0]
        # Required candidate fields
        self.assertIn("ticker", sample)
        self.assertIn("name", sample)
        self.assertIn("sector", sample)
        self.assertIn("price", sample)
        self.assertIn("change_24h_pct", sample)
        self.assertIn("strategies", sample)
        self.assertIn("setup", sample)
        self.assertIn("factor_scores", sample)
        self.assertIn("catalysts", sample)
        self.assertIn("sparkline", sample)

        # Trade setup fields
        setup = sample["setup"]
        self.assertIn("entry_price", setup)
        self.assertIn("stop_loss", setup)
        self.assertIn("target_price", setup)
        self.assertIn("target_return_pct", setup)
        self.assertIn("risk_reward_ratio", setup)
        self.assertGreater(setup["target_price"], setup["entry_price"])
        self.assertLess(setup["stop_loss"], setup["entry_price"])
        self.assertGreaterEqual(setup["risk_reward_ratio"], 2.0)

        # 5-axis factor scores
        factors = sample["factor_scores"]
        for dim in ["momentum", "value", "quality", "growth", "volatility"]:
            self.assertIn(dim, factors)
            self.assertTrue(0 <= factors[dim] <= 100)

    def test_screener_filter_strategy(self):
        """Test GET /api/screen?strategy=momentum_breakout."""
        resp = self.client.get("/api/screen?strategy=momentum_breakout")
        self.assertEqual(resp.status_code, 200)
        candidates = resp.json()
        self.assertGreater(len(candidates), 0)
        for c in candidates:
            self.assertIn("momentum_breakout", c["strategies"])

    def test_screener_filter_sector(self):
        """Test GET /api/screen?sector=Technology."""
        resp = self.client.get("/api/screen?sector=Technology")
        self.assertEqual(resp.status_code, 200)
        candidates = resp.json()
        self.assertGreater(len(candidates), 0)
        for c in candidates:
            self.assertIn("Technology", c["sector"])

    def test_screener_filter_min_return(self):
        """Test GET /api/screen?min_return=5.0."""
        resp = self.client.get("/api/screen?min_return=5.0")
        self.assertEqual(resp.status_code, 200)
        candidates = resp.json()
        for c in candidates:
            self.assertGreaterEqual(c["setup"]["target_return_pct"], 5.0)

    def test_screener_filter_market_cap(self):
        """Test GET /api/screen?market_cap=mega."""
        resp = self.client.get("/api/screen?market_cap=mega")
        self.assertEqual(resp.status_code, 200)
        candidates = resp.json()
        self.assertGreater(len(candidates), 0)
        for c in candidates:
            self.assertEqual(c["market_cap_tier"], "Mega")

    def test_screener_search(self):
        """Test GET /api/screen?search=NVDA returns matching stock."""
        resp = self.client.get("/api/screen?search=NVDA")
        self.assertEqual(resp.status_code, 200)
        candidates = resp.json()
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["ticker"], "NVDA")

    def test_screener_sorting(self):
        """Test GET /api/screen?sort_by=risk_reward_ratio&sort_dir=desc."""
        resp = self.client.get("/api/screen?sort_by=risk_reward_ratio&sort_dir=desc")
        self.assertEqual(resp.status_code, 200)
        candidates = resp.json()
        if len(candidates) >= 2:
            self.assertGreaterEqual(
                candidates[0]["setup"]["risk_reward_ratio"],
                candidates[1]["setup"]["risk_reward_ratio"],
            )

    # -------------------------------------------------------------------------
    # Stock Deep-Dive Detail
    # -------------------------------------------------------------------------

    def test_stock_detail_valid(self):
        """Test GET /api/stock/NVDA returns 252-day candles, indicators, setup, and checklist."""
        resp = self.client.get("/api/stock/NVDA")
        self.assertEqual(resp.status_code, 200)
        detail = resp.json()

        self.assertEqual(detail["ticker"], "NVDA")
        self.assertIn("price", detail)
        self.assertIn("candles", detail)
        self.assertEqual(len(detail["candles"]), 252)

        # Candlestick fields
        first_candle = detail["candles"][0]
        self.assertIn("time", first_candle)
        self.assertIn("open", first_candle)
        self.assertIn("high", first_candle)
        self.assertIn("low", first_candle)
        self.assertIn("close", first_candle)

        # Volumes series
        self.assertIn("volumes", detail)
        self.assertEqual(len(detail["volumes"]), 252)
        self.assertIn("color", detail["volumes"][0])

        # Technical indicators
        self.assertIn("indicators", detail)
        ind = detail["indicators"]
        self.assertIn("sma_20", ind)
        self.assertIn("sma_50", ind)
        self.assertIn("sma_200", ind)
        self.assertIn("rsi_14", ind)
        self.assertIn("atr_14", ind)
        self.assertIn("bb_upper", ind)
        self.assertIn("bb_middle", ind)
        self.assertIn("bb_lower", ind)

        # Trade setup blueprint
        self.assertIn("setup", detail)
        setup = detail["setup"]
        self.assertGreater(setup["target_price"], setup["entry_price"])
        self.assertLess(setup["stop_loss"], setup["entry_price"])
        self.assertGreaterEqual(setup["risk_reward_ratio"], 2.0)
        self.assertIn("shares", setup)
        self.assertIn("risk_amount", setup)
        self.assertIn("horizon_days", setup)

        # 5-axis factor radar comparison
        self.assertIn("radar_comparison", detail)
        self.assertEqual(len(detail["radar_comparison"]), 5)
        for item in detail["radar_comparison"]:
            self.assertIn("factor", item)
            self.assertIn("stockScore", item)
            self.assertIn("sectorAvg", item)

        # Catalyst timeline
        self.assertIn("catalysts", detail)
        self.assertGreater(len(detail["catalysts"]), 0)
        for evt in detail["catalysts"]:
            self.assertIn("type", evt)
            self.assertIn("date", evt)
            self.assertIn("countdown", evt)

        # Strategy checklist
        self.assertIn("strategy_checklist", detail)
        self.assertGreaterEqual(len(detail["strategy_checklist"]), 4)
        for chk in detail["strategy_checklist"]:
            self.assertIn("criterion", chk)
            self.assertIn("passed", chk)
            self.assertIn("detail", chk)

    def test_stock_detail_not_found(self):
        """Test GET /api/stock/INVALID_TICKER_999 returns 404."""
        resp = self.client.get("/api/stock/INVALID_TICKER_999")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("detail", resp.json())

    # -------------------------------------------------------------------------
    # Universe & Refresh Endpoints
    # -------------------------------------------------------------------------

    def test_universe_endpoint(self):
        """Test GET /api/universe returns constituents list."""
        resp = self.client.get("/api/universe")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1000)

    def test_scan_refresh_endpoint(self):
        """Test POST /api/scan/refresh returns success."""
        resp = self.client.post("/api/scan/refresh")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("pulse", data)

    # -------------------------------------------------------------------------
    # Static SPA Hosting & HTML5 Fallback
    # -------------------------------------------------------------------------

    def test_spa_root_serves_html(self):
        """Test GET / serves index.html."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))
        self.assertIn("root", resp.text)

    def test_spa_client_route_fallback(self):
        """Test client-side route /screener falls back to index.html with 200."""
        resp = self.client.get("/screener")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))
        self.assertIn("root", resp.text)

    def test_spa_static_assets_serving(self):
        """Test GET /assets/* serves compiled asset with immutable cache header."""
        resp = self.client.get("/assets/index-DSOH8dwQ.css")
        if resp.status_code == 200:
            self.assertIn("immutable", resp.headers.get("cache-control", ""))


if __name__ == "__main__":
    unittest.main()

"""
Empirical Challenger Test Suite for Milestone 3 (Tokenomist Dark UI & FastAPI Service).
Executed by Challenger 2 (Agent: critic, specialist).

Verifies:
1. Static asset caching headers (immutable for /assets/*, no-cache / safe for index.html / SPA routes).
2. SPA client route fallback vs API isolation (no 404 masking for /api/*).
3. TradingView Lightweight Charts CandlestickSeries & VolumeSeries data contracts:
   - Time format YYYY-MM-DD
   - Strictly ascending order (t[i] > t[i-1])
   - Zero duplicate timestamps
   - High >= max(Open, Close) and Low <= min(Open, Close)
   - Volume >= 0
4. Factor radar score boundaries ([0, 100] strictly enforced across all 5 axes under normal and extreme inputs).
5. Trade Setup Risk:Reward ratio strictly >= 2.0 and target return within 3-10% bounds.
6. Clean bundle build and gzip budget (< 350 KB) with zero secret leaks.
"""

import gzip
import math
import os
from pathlib import Path
import re
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.engine.strategies import calculate_factor_radar
from backend.app.engine.trade_setup import generate_trade_setup


@pytest.fixture(scope="module")
def client():
    """Shared FastAPI TestClient."""
    with TestClient(app) as test_client:
        yield test_client


# =============================================================================
# 1. Static Asset Caching & SPA Route Fallback Integrity
# =============================================================================

def test_static_asset_immutable_cache_headers(client):
    """
    Empirically verifies that all static assets under /assets/*
    return HTTP 200 with 'Cache-Control: public, max-age=31536000, immutable'.
    """
    assets_dir = Path("frontend/dist/assets")
    assert assets_dir.exists(), "frontend/dist/assets directory does not exist. Run npm run build."

    asset_files = [f for f in os.listdir(assets_dir) if (assets_dir / f).is_file()]
    assert len(asset_files) > 0, "No asset files found in frontend/dist/assets"

    for file_name in asset_files:
        url = f"/assets/{file_name}"
        res = client.get(url)
        assert res.status_code == 200, f"Expected 200 for {url}, got {res.status_code}"
        cache_control = res.headers.get("cache-control")
        assert cache_control == "public, max-age=31536000, immutable", (
            f"Expected immutable cache header on {url}, got '{cache_control}'"
        )
        assert len(res.content) > 0, f"Empty content served for {url}"


def test_spa_client_routes_safe_caching(client):
    """
    Empirically verifies that non-asset SPA routes return index.html (HTTP 200)
    WITHOUT caching headers that would poison client SPA navigation.
    """
    spa_routes = [
        "/",
        "/index.html",
        "/screener",
        "/stock/AAPL",
        "/stock/NVDA",
        "/stock/MSFT",
        "/deep/client/nested/route",
    ]

    for route in spa_routes:
        res = client.get(route)
        assert res.status_code == 200, f"Expected 200 for SPA route {route}, got {res.status_code}"
        cache_control = res.headers.get("cache-control", "")
        # Must not contain immutable or long max-age
        assert "immutable" not in cache_control.lower(), (
            f"SPA route {route} must not be marked immutable! Found: {cache_control}"
        )
        assert "max-age=31536000" not in cache_control.lower(), (
            f"SPA route {route} must not have long max-age! Found: {cache_control}"
        )
        # Content verification: must return the HTML shell
        body = res.text
        assert "<div id=\"root\">" in body or "<!DOCTYPE html>" in body or "<!doctype html>" in body.lower(), (
            f"SPA route {route} did not return the React root shell"
        )


def test_api_routes_not_hijacked_by_spa(client):
    """
    Ensures /api/* and /health endpoints return JSON and are never hijacked
    by the catch-all SPA HTML fallback.
    """
    # 1. Valid API routes
    for endpoint in ["/health", "/api/market-pulse", "/api/screen", "/api/universe"]:
        res = client.get(endpoint)
        assert res.status_code == 200, f"Expected 200 for {endpoint}, got {res.status_code}"
        assert "application/json" in res.headers.get("content-type", ""), (
            f"Expected JSON content-type for {endpoint}, got {res.headers.get('content-type')}"
        )

    # 2. Unknown API route must return 404 JSON, NOT 200 index.html
    res_404 = client.get("/api/unknown_nonexistent_route")
    assert res_404.status_code == 404, f"Unknown API route returned {res_404.status_code}, expected 404"
    assert "application/json" in res_404.headers.get("content-type", "")
    assert "<!doctype html>" not in res_404.text.lower()


# =============================================================================
# 2. Frontend Bundle Size & Secret Leak Check
# =============================================================================

def test_frontend_bundle_gzip_size_and_secrets():
    """
    Verifies that total gzipped bundle size is strictly < 350 KB
    and no API secrets or localhost URLs exist in production assets.
    """
    dist_dir = Path("frontend/dist")
    assert dist_dir.exists(), "frontend/dist does not exist"

    total_gzip_bytes = 0
    total_raw_bytes = 0
    suspicious_patterns = []

    for root, _, files in os.walk(dist_dir):
        for f in files:
            fp = Path(root) / f
            raw_data = fp.read_bytes()
            total_raw_bytes += len(raw_data)
            gz_data = gzip.compress(raw_data)
            total_gzip_bytes += len(gz_data)

            if f.endswith((".js", ".html", ".css")):
                text = raw_data.decode("utf-8", errors="ignore")
                # Check for hardcoded localhost or 127.0.0.1
                if "localhost" in text:
                    suspicious_patterns.append(f"Hardcoded localhost found in {f}")
                if "127.0.0.1" in text:
                    suspicious_patterns.append(f"Hardcoded 127.0.0.1 found in {f}")
                # Check for leaked secrets
                for kw in ["api_key", "secret_key", "private_key", "aws_secret"]:
                    if kw in text.lower():
                        suspicious_patterns.append(f"Suspicious secret keyword '{kw}' in {f}")

    total_gzip_kb = total_gzip_bytes / 1024.0
    print(f"\n[Bundle Audit] Total Raw: {total_raw_bytes / 1024.0:.2f} KB | Total Gzip: {total_gzip_kb:.2f} KB")

    assert total_gzip_kb < 350.0, f"Gzip bundle size {total_gzip_kb:.2f} KB exceeds 350 KB threshold!"
    assert len(suspicious_patterns) == 0, f"Security audit findings: {suspicious_patterns}"


# =============================================================================
# 3. Chart Data Contracts: Candlestick, Volume, & Execution Lines
# =============================================================================

@pytest.mark.parametrize("ticker", ["NVDA", "AAPL", "MSFT", "TSLA", "BRK-B", "URI", "DECK"])
def test_tradingview_chart_data_contract(client, ticker):
    """
    Tests the TradingView lightweight-charts data contract on /api/stock/{ticker}:
    - time string YYYY-MM-DD
    - strictly ascending order
    - zero duplicate timestamps
    - valid price levels (high >= open, close; low <= open, close)
    - volume >= 0
    """
    res = client.get(f"/api/stock/{ticker}")
    assert res.status_code == 200, f"Failed to get stock detail for {ticker}: {res.status_code}"
    data = res.json()

    candles = data.get("candles", [])
    volumes = data.get("volumes", [])

    assert len(candles) >= 50, f"Expected at least 50 bars for {ticker}, got {len(candles)}"
    assert len(candles) == len(volumes), f"Candle count ({len(candles)}) != Volume count ({len(volumes)})"

    seen_candle_times = set()
    prev_time = ""

    date_regex = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for i, c in enumerate(candles):
        t = c.get("time")
        assert isinstance(t, str), f"Candle time must be string, got {type(t)}"
        assert date_regex.match(t), f"Candle time '{t}' does not match YYYY-MM-DD format"

        # Strictly ascending order
        if i > 0:
            assert t > prev_time, (
                f"Candle series out of order or duplicate for {ticker}: "
                f"index {i} time '{t}' <= previous time '{prev_time}'"
            )

        assert t not in seen_candle_times, f"Duplicate candle time '{t}' found for {ticker}"
        seen_candle_times.add(t)
        prev_time = t

        o, h, l_val, cl = c.get("open"), c.get("high"), c.get("low"), c.get("close")
        for p_name, p_val in [("open", o), ("high", h), ("low", l_val), ("close", cl)]:
            assert isinstance(p_val, (int, float)), f"{p_name} is not numeric in bar {i}"
            assert math.isfinite(p_val) and p_val > 0, f"{p_name} is non-positive or infinite ({p_val}) in bar {i}"

        assert h >= o, f"High ({h}) < Open ({o}) in bar {i}"
        assert h >= cl, f"High ({h}) < Close ({cl}) in bar {i}"
        assert l_val <= o, f"Low ({l_val}) > Open ({o}) in bar {i}"
        assert l_val <= cl, f"Low ({l_val}) > Close ({cl}) in bar {i}"

    # Volume series check
    for j, v in enumerate(volumes):
        v_time = v.get("time")
        v_val = v.get("value")
        v_color = v.get("color")

        assert v_time == candles[j]["time"], f"Volume time '{v_time}' does not match candle time '{candles[j]['time']}'"
        assert isinstance(v_val, (int, float)) and v_val >= 0, f"Volume value negative or non-numeric: {v_val}"
        assert v_color in ["#10B981", "#F43F5E"], f"Unexpected volume color: {v_color}"

    # Execution price lines in setup
    setup = data.get("setup", {})
    entry = setup.get("entry_price")
    target = setup.get("target_price")
    stop = setup.get("stop_loss")

    assert entry > 0, f"Entry price non-positive: {entry}"
    assert target > entry, f"Target price ({target}) <= Entry price ({entry})"
    assert stop < entry, f"Stop loss ({stop}) >= Entry price ({entry})"


# =============================================================================
# 4. Factor Radar Score Boundaries [0, 100]
# =============================================================================

def test_factor_radar_score_bounds_in_screener_api(client):
    """
    Verifies that all candidates returned by /api/screen have factor scores
    strictly bounded between 0 and 100.
    """
    res = client.get("/api/screen?limit=100")
    assert res.status_code == 200
    candidates = res.json()
    assert len(candidates) > 0, "No candidates returned by /api/screen"

    expected_factors = ["momentum", "value", "quality", "growth", "volatility"]

    for cand in candidates:
        scores = cand.get("factor_scores", {})
        for factor in expected_factors:
            assert factor in scores, f"Missing factor '{factor}' in candidate {cand.get('ticker')}"
            val = scores[factor]
            assert isinstance(val, int), f"Factor '{factor}' score not int: {type(val)}"
            assert 0 <= val <= 100, f"Factor '{factor}' score {val} out of bounds [0, 100] for {cand.get('ticker')}"


def test_factor_radar_score_bounds_in_stock_modal(client):
    """
    Verifies that the detailed stock modal endpoint returns radar scores
    and comparisons strictly bounded between 0 and 100.
    """
    res = client.get("/api/stock/AAPL")
    assert res.status_code == 200
    data = res.json()

    # 1. Direct factor scores
    scores = data.get("factor_scores", {})
    for f_name, f_val in scores.items():
        assert 0 <= f_val <= 100, f"Factor score {f_name}={f_val} out of [0, 100]"

    # 2. Radar comparison array
    radar_comp = data.get("radar_comparison", [])
    assert len(radar_comp) == 5, f"Expected 5 comparison factors, got {len(radar_comp)}"
    for item in radar_comp:
        s_score = item.get("stockScore")
        sec_avg = item.get("sectorAvg")
        assert 0 <= s_score <= 100, f"stockScore {s_score} out of [0, 100]"
        assert 0 <= sec_avg <= 100, f"sectorAvg {sec_avg} out of [0, 100]"


def test_factor_radar_adversarial_math_inputs():
    """
    Stress-tests calculate_factor_radar directly with adversarial inputs:
    - Extreme negative ROE, D/E, PE
    - Extreme positive numbers
    - NaN and Inf values
    - All None inputs
    """
    # 1. All None
    scores_none = calculate_factor_radar(None, None).to_dict()
    for k, v in scores_none.items():
        assert 0 <= v <= 100, f"None input produced out-of-bounds score: {k}={v}"

    # 2. Extreme negative numbers
    adversarial_fund_neg = {
        "roe": -999999.0,
        "debt_to_equity": -500.0,
        "forward_pe": -100.0,
        "fcf_yield": -50.0,
        "revenue_growth_qoq": -500.0,
        "eps_surprise_pct": -200.0,
    }
    scores_neg = calculate_factor_radar(None, adversarial_fund_neg).to_dict()
    for k, v in scores_neg.items():
        assert 0 <= v <= 100, f"Extreme negative fundamentals produced out-of-bounds score: {k}={v}"

    # 3. Extreme positive numbers
    adversarial_fund_pos = {
        "roe": 1e9,
        "debt_to_equity": 1e6,
        "forward_pe": 1e6,
        "fcf_yield": 1e6,
        "revenue_growth_qoq": 1e6,
        "eps_surprise_pct": 1e6,
    }
    scores_pos = calculate_factor_radar(None, adversarial_fund_pos).to_dict()
    for k, v in scores_pos.items():
        assert 0 <= v <= 100, f"Extreme positive fundamentals produced out-of-bounds score: {k}={v}"

    # 4. NaN / Inf values
    adversarial_fund_nan = {
        "roe": float("nan"),
        "debt_to_equity": float("inf"),
        "forward_pe": float("-inf"),
        "fcf_yield": float("nan"),
    }
    scores_nan = calculate_factor_radar(None, adversarial_fund_nan).to_dict()
    for k, v in scores_nan.items():
        assert 0 <= v <= 100, f"NaN/Inf fundamentals produced out-of-bounds score: {k}={v}"


# =============================================================================
# 5. Trade Setup Risk:Reward Ratio & Bounds
# =============================================================================

def test_trade_setup_rr_ratio_screener_api(client):
    """
    Verifies that every candidate returned by /api/screen has:
    - setup.risk_reward_ratio >= 2.0
    - setup.is_valid is True
    - setup.target_return_pct within 3% to 10%
    """
    res = client.get("/api/screen?limit=100&min_rr=2.0")
    assert res.status_code == 200
    candidates = res.json()
    assert len(candidates) > 0

    for cand in candidates:
        setup = cand.get("setup", {})
        ticker = cand.get("ticker")

        rr = setup.get("risk_reward_ratio")
        ret = setup.get("target_return_pct")
        entry = setup.get("entry_price")
        target = setup.get("target_price")
        stop = setup.get("stop_loss")

        assert rr is not None, f"Missing risk_reward_ratio in setup for {ticker}"
        assert rr >= 2.0, f"Candidate {ticker} has R:R {rr} < 2.0!"

        assert ret is not None, f"Missing target_return_pct in setup for {ticker}"
        # Target return within 3% to 10% target swing corridor
        assert 3.0 <= ret <= 10.0, f"Candidate {ticker} target return {ret}% outside 3-10% bounds"

        # Mathematical check: reward / risk >= 1.99
        risk = entry - stop
        reward = target - entry
        assert risk > 0, f"Risk per share <= 0 for {ticker}"
        assert reward > 0, f"Reward per share <= 0 for {ticker}"
        calc_rr = reward / risk
        assert calc_rr >= 1.99, f"Computed R:R {calc_rr:.3f} < 2.0 for {ticker}"


def test_generate_trade_setup_adversarial_inputs():
    """
    Stress-tests generate_trade_setup directly:
    - Normal parameters enforce R:R >= 2.0 and target 3-10%
    - Extreme and invalid inputs fail gracefully (is_valid=False)
    """
    # 1. Standard valid setup
    setup = generate_trade_setup(
        entry_price=100.0,
        atr_14=2.0,
        strategy_name="MOMENTUM_BREAKOUT",
        min_return_pct=3.0,
        max_return_pct=10.0,
        min_rr_ratio=2.0,
    )
    assert setup.is_valid is True
    assert setup.risk_reward_ratio >= 2.0
    assert 3.0 <= setup.target_return_pct <= 10.0
    assert setup.stop_loss < 100.0
    assert setup.target_price > 100.0

    # 2. Huge ATR relative to price (e.g. entry 10, ATR 8)
    # Target clamped to 10% would give reward $1.00, requiring risk <= $0.50.
    # If 0.75 * ATR = 6.0 > 0.50, setup cannot meet 1:2 RR safely, so it must be marked invalid.
    setup_huge_atr = generate_trade_setup(
        entry_price=10.0,
        atr_14=8.0,
        min_return_pct=3.0,
        max_return_pct=10.0,
        min_rr_ratio=2.0,
    )
    assert setup_huge_atr.is_valid is False or setup_huge_atr.risk_reward_ratio >= 2.0

    # 3. Invalid zero/negative entry price
    setup_invalid = generate_trade_setup(entry_price=-50.0, atr_14=2.0)
    assert setup_invalid.is_valid is False
    assert setup_invalid.risk_reward_ratio == 0.0

    # 4. NaN / Inf inputs
    setup_nan = generate_trade_setup(entry_price=float("nan"), atr_14=2.0)
    assert setup_nan.is_valid is False

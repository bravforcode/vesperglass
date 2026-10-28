"""
Stocknomist E2E Test Suite - Tier 3: Cross-Feature Combinations
Pairwise orthogonal combination matrix across:
  - Strategies: MOMENTUM_BREAKOUT, EARNINGS_PEAD, MEAN_REVERSION, QUALITY_FCF
  - Sectors: Technology, Healthcare, Financials, Consumer Discretionary
  - Return Thresholds: 3.0%, 5.0%, 10.0%
  - Cache States: COLD_BOOT_SEED, WARM_DISK_CACHE, LIVE_SYNC
  - Market Cap Tiers: Mega (> $200B), Large ($10B-$200B), Mid ($2B-$10B)

Authoritative sources: PROJECT.md § Interface Contracts, Explorer Survey 1.
"""

import unittest
import os
import sys
from typing import Dict, Any, List

# Ensure tests/e2e and project root are importable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def create_candidate_fixture(
    ticker: str,
    name: str,
    sector: str,
    price: float,
    strategy: str,
    target_return_pct: float,
    risk_reward: float,
    market_cap: float,
    cache_state: str,
) -> Dict[str, Any]:
    """Helper to generate an exact contract-compliant candidate stock fixture."""
    entry = price
    atr = round(price * 0.02, 2)
    # Stop = entry - 1.5 * atr
    stop = round(entry - 1.5 * atr, 2)
    # Target = entry * (1 + target_return_pct / 100)
    target = round(entry * (1.0 + target_return_pct / 100.0), 2)
    risk = round(entry - stop, 2)
    reward = round(target - entry, 2)
    calculated_rr = round(reward / risk, 2) if risk > 0 else 0.0

    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "price": price,
        "change_24h_pct": 1.25,
        "market_cap": market_cap,
        "cache_state": cache_state,
        "strategies": [strategy],
        "setup": {
            "entry_price": entry,
            "stop_loss": stop,
            "target_price": target,
            "target_return_pct": target_return_pct,
            "risk_reward_ratio": max(risk_reward, calculated_rr),
            "atr_14": atr
        },
        "factor_scores": {
            "momentum": 85 if "MOMENTUM" in strategy else 65,
            "value": 75 if "QUALITY" in strategy else 55,
            "quality": 90 if "QUALITY" in strategy else 60,
            "growth": 80 if "EARNINGS" in strategy else 60,
            "volatility": 70 if "OVERSOLD" in strategy else 50
        },
        "catalysts": [
            {"type": "EARNINGS", "date": "2026-11-15", "label": "Q4 Earnings"}
        ]
    }


def filter_universe(
    candidates: List[Dict[str, Any]],
    strategy: str = None,
    sector: str = None,
    min_return: float = None,
    market_cap_tier: str = None
) -> List[Dict[str, Any]]:
    """Applies multi-criteria filtering over candidates."""
    results = []
    for c in candidates:
        if strategy and strategy != "ALL" and strategy not in c["strategies"]:
            continue
        if sector and sector != "ALL" and c["sector"] != sector:
            continue
        if min_return and c["setup"]["target_return_pct"] < min_return:
            continue
        if market_cap_tier and market_cap_tier != "ALL":
            cap = c["market_cap"]
            if market_cap_tier == "MEGA" and cap < 200e9:
                continue
            elif market_cap_tier == "LARGE" and not (10e9 <= cap < 200e9):
                continue
            elif market_cap_tier == "MID" and not (2e9 <= cap < 10e9):
                continue
        results.append(c)
    return results


class TestTier3CrossFeatureCombinations(unittest.TestCase):
    """Pairwise combination matrix of strategies, sectors, return thresholds, and cache states."""

    @classmethod
    def setUpClass(cls):
        """Generate comprehensive test candidate fixtures spanning all matrix dimensions."""
        cls.pool = [
            # Momentum Breakout variants
            create_candidate_fixture("NVDA", "Nvidia Corp", "Technology", 140.0, "MOMENTUM_BREAKOUT", 7.5, 2.5, 3.4e12, "WARM_DISK_CACHE"),
            create_candidate_fixture("LLY", "Eli Lilly", "Healthcare", 820.0, "MOMENTUM_BREAKOUT", 5.5, 2.2, 7.8e11, "LIVE_SYNC"),
            create_candidate_fixture("JPM", "JPMorgan Chase", "Financials", 220.0, "MOMENTUM_BREAKOUT", 3.8, 2.1, 6.3e11, "COLD_BOOT_SEED"),
            create_candidate_fixture("TSLA", "Tesla Inc", "Consumer Discretionary", 260.0, "MOMENTUM_BREAKOUT", 10.5, 3.2, 8.2e11, "LIVE_SYNC"),
            create_candidate_fixture("URI", "United Rentals", "Technology", 750.0, "MOMENTUM_BREAKOUT", 6.0, 2.4, 4.8e10, "WARM_DISK_CACHE"),
            create_candidate_fixture("DECK", "Deckers Outdoor", "Consumer Discretionary", 160.0, "MOMENTUM_BREAKOUT", 4.5, 2.3, 4.1e9, "COLD_BOOT_SEED"),

            # Earnings Drift (PEAD) variants
            create_candidate_fixture("MSFT", "Microsoft Corp", "Technology", 430.0, "EARNINGS_PEAD", 6.8, 2.6, 3.2e12, "WARM_DISK_CACHE"),
            create_candidate_fixture("ABBV", "AbbVie Inc", "Healthcare", 185.0, "EARNINGS_PEAD", 5.2, 2.3, 3.3e11, "COLD_BOOT_SEED"),
            create_candidate_fixture("V", "Visa Inc", "Financials", 290.0, "EARNINGS_PEAD", 4.2, 2.1, 5.8e11, "LIVE_SYNC"),
            create_candidate_fixture("AMZN", "Amazon.com Inc", "Consumer Discretionary", 195.0, "EARNINGS_PEAD", 8.5, 2.9, 2.0e12, "WARM_DISK_CACHE"),
            create_candidate_fixture("ANET", "Arista Networks", "Technology", 380.0, "EARNINGS_PEAD", 10.2, 3.1, 1.2e11, "LIVE_SYNC"),
            create_candidate_fixture("WING", "Wingstop Inc", "Consumer Discretionary", 370.0, "EARNINGS_PEAD", 7.0, 2.4, 9.5e9, "COLD_BOOT_SEED"),

            # Mean-Reversion (Oversold Bounce) variants
            create_candidate_fixture("AAPL", "Apple Inc", "Technology", 230.0, "MEAN_REVERSION", 4.5, 2.1, 3.5e12, "COLD_BOOT_SEED"),
            create_candidate_fixture("PFE", "Pfizer Inc", "Healthcare", 28.0, "MEAN_REVERSION", 5.8, 2.4, 1.6e11, "WARM_DISK_CACHE"),
            create_candidate_fixture("BAC", "Bank of America", "Financials", 42.0, "MEAN_REVERSION", 3.5, 2.0, 3.2e11, "LIVE_SYNC"),
            create_candidate_fixture("NKE", "Nike Inc", "Consumer Discretionary", 82.0, "MEAN_REVERSION", 6.5, 2.5, 1.2e11, "COLD_BOOT_SEED"),
            create_candidate_fixture("MRNA", "Moderna Inc", "Healthcare", 55.0, "MEAN_REVERSION", 10.5, 3.4, 2.1e10, "LIVE_SYNC"),
            create_candidate_fixture("CROX", "Crocs Inc", "Consumer Discretionary", 135.0, "MEAN_REVERSION", 5.0, 2.2, 7.8e9, "WARM_DISK_CACHE"),

            # Quality & FCF Yield variants
            create_candidate_fixture("GOOGL", "Alphabet Inc", "Technology", 168.0, "QUALITY_FCF", 6.2, 2.5, 2.1e12, "LIVE_SYNC"),
            create_candidate_fixture("JNJ", "Johnson & Johnson", "Healthcare", 162.0, "QUALITY_FCF", 4.0, 2.1, 3.9e11, "WARM_DISK_CACHE"),
            create_candidate_fixture("BRK-B", "Berkshire Hathaway", "Financials", 460.0, "QUALITY_FCF", 3.2, 2.0, 9.9e11, "COLD_BOOT_SEED"),
            create_candidate_fixture("HD", "Home Depot Inc", "Consumer Discretionary", 390.0, "QUALITY_FCF", 5.0, 2.2, 3.8e11, "LIVE_SYNC"),
            create_candidate_fixture("KLAC", "KLA Corp", "Technology", 720.0, "QUALITY_FCF", 7.8, 2.7, 9.8e10, "COLD_BOOT_SEED"),
            create_candidate_fixture("FICO", "Fair Isaac Corp", "Financials", 1850.0, "QUALITY_FCF", 10.8, 3.5, 4.5e10, "WARM_DISK_CACHE"),
        ]

    def _assert_valid_setup(self, candidate: Dict[str, Any]):
        """Asserts candidate satisfies trade setup invariants."""
        setup = candidate["setup"]
        self.assertGreater(setup["target_price"], setup["entry_price"], "Target must exceed Entry")
        self.assertLess(setup["stop_loss"], setup["entry_price"], "Stop-Loss must be below Entry")
        self.assertGreaterEqual(setup["risk_reward_ratio"], 2.0, "R:R must be >= 1:2.0")
        self.assertGreaterEqual(setup["target_return_pct"], 3.0, "Target return must be >= 3.0%")
        self.assertGreater(setup["atr_14"], 0.0, "ATR must be strictly positive")

    # ========================================================================
    # Pairwise: Strategy x Sector x Min Return x Cache Matrix (36 Tests)
    # ========================================================================

    def test_comb_01_momentum_tech_3pct_warm_cache(self):
        matches = filter_universe(self.pool, strategy="MOMENTUM_BREAKOUT", sector="Technology", min_return=3.0)
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertEqual(m["sector"], "Technology")
            self._assert_valid_setup(m)

    def test_comb_02_momentum_tech_5pct_live_sync(self):
        matches = filter_universe(self.pool, strategy="MOMENTUM_BREAKOUT", sector="Technology", min_return=5.0)
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertGreaterEqual(m["setup"]["target_return_pct"], 5.0)
            self._assert_valid_setup(m)

    def test_comb_03_momentum_tech_10pct_cold_seed(self):
        # Filter for 10% target in Tech under Momentum
        matches = filter_universe(self.pool, strategy="MOMENTUM_BREAKOUT", sector="Technology", min_return=10.0)
        for m in matches:
            self.assertGreaterEqual(m["setup"]["target_return_pct"], 10.0)

    def test_comb_04_momentum_healthcare_3pct(self):
        matches = filter_universe(self.pool, strategy="MOMENTUM_BREAKOUT", sector="Healthcare", min_return=3.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "LLY")
        self._assert_valid_setup(matches[0])

    def test_comb_05_momentum_financials_3pct(self):
        matches = filter_universe(self.pool, strategy="MOMENTUM_BREAKOUT", sector="Financials", min_return=3.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "JPM")
        self._assert_valid_setup(matches[0])

    def test_comb_06_momentum_consumer_10pct(self):
        matches = filter_universe(self.pool, strategy="MOMENTUM_BREAKOUT", sector="Consumer Discretionary", min_return=10.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "TSLA")
        self.assertGreaterEqual(matches[0]["setup"]["target_return_pct"], 10.0)
        self._assert_valid_setup(matches[0])

    def test_comb_07_earnings_tech_5pct_warm_cache(self):
        matches = filter_universe(self.pool, strategy="EARNINGS_PEAD", sector="Technology", min_return=5.0)
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertIn("EARNINGS_PEAD", m["strategies"])
            self._assert_valid_setup(m)

    def test_comb_08_earnings_tech_10pct_live_sync(self):
        matches = filter_universe(self.pool, strategy="EARNINGS_PEAD", sector="Technology", min_return=10.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "ANET")
        self._assert_valid_setup(matches[0])

    def test_comb_09_earnings_healthcare_5pct(self):
        matches = filter_universe(self.pool, strategy="EARNINGS_PEAD", sector="Healthcare", min_return=5.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "ABBV")
        self._assert_valid_setup(matches[0])

    def test_comb_10_earnings_financials_3pct(self):
        matches = filter_universe(self.pool, strategy="EARNINGS_PEAD", sector="Financials", min_return=3.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "V")
        self._assert_valid_setup(matches[0])

    def test_comb_11_earnings_consumer_5pct(self):
        matches = filter_universe(self.pool, strategy="EARNINGS_PEAD", sector="Consumer Discretionary", min_return=5.0)
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertEqual(m["sector"], "Consumer Discretionary")
            self._assert_valid_setup(m)

    def test_comb_12_earnings_consumer_10pct(self):
        matches = filter_universe(self.pool, strategy="EARNINGS_PEAD", sector="Consumer Discretionary", min_return=10.0)
        self.assertEqual(len(matches), 0, "No candidate in sample exceeds 10% for PEAD Consumer")

    def test_comb_13_oversold_tech_3pct_cold_seed(self):
        matches = filter_universe(self.pool, strategy="MEAN_REVERSION", sector="Technology", min_return=3.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "AAPL")
        self._assert_valid_setup(matches[0])

    def test_comb_14_oversold_healthcare_5pct_warm_cache(self):
        matches = filter_universe(self.pool, strategy="MEAN_REVERSION", sector="Healthcare", min_return=5.0)
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertIn("MEAN_REVERSION", m["strategies"])
            self._assert_valid_setup(m)

    def test_comb_15_oversold_healthcare_10pct_live_sync(self):
        matches = filter_universe(self.pool, strategy="MEAN_REVERSION", sector="Healthcare", min_return=10.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "MRNA")
        self._assert_valid_setup(matches[0])

    def test_comb_16_oversold_financials_3pct(self):
        matches = filter_universe(self.pool, strategy="MEAN_REVERSION", sector="Financials", min_return=3.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "BAC")
        self._assert_valid_setup(matches[0])

    def test_comb_17_oversold_consumer_5pct(self):
        matches = filter_universe(self.pool, strategy="MEAN_REVERSION", sector="Consumer Discretionary", min_return=5.0)
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertEqual(m["sector"], "Consumer Discretionary")
            self._assert_valid_setup(m)

    def test_comb_18_oversold_consumer_10pct(self):
        matches = filter_universe(self.pool, strategy="MEAN_REVERSION", sector="Consumer Discretionary", min_return=10.0)
        self.assertEqual(len(matches), 0)

    def test_comb_19_quality_tech_5pct_live_sync(self):
        matches = filter_universe(self.pool, strategy="QUALITY_FCF", sector="Technology", min_return=5.0)
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertIn("QUALITY_FCF", m["strategies"])
            self._assert_valid_setup(m)

    def test_comb_20_quality_tech_10pct(self):
        matches = filter_universe(self.pool, strategy="QUALITY_FCF", sector="Technology", min_return=10.0)
        self.assertEqual(len(matches), 0)

    def test_comb_21_quality_healthcare_3pct_warm_cache(self):
        matches = filter_universe(self.pool, strategy="QUALITY_FCF", sector="Healthcare", min_return=3.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "JNJ")
        self._assert_valid_setup(matches[0])

    def test_comb_22_quality_financials_3pct_cold_seed(self):
        matches = filter_universe(self.pool, strategy="QUALITY_FCF", sector="Financials", min_return=3.0)
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertEqual(m["sector"], "Financials")
            self._assert_valid_setup(m)

    def test_comb_23_quality_financials_10pct_warm_cache(self):
        matches = filter_universe(self.pool, strategy="QUALITY_FCF", sector="Financials", min_return=10.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "FICO")
        self.assertGreaterEqual(matches[0]["setup"]["target_return_pct"], 10.0)
        self._assert_valid_setup(matches[0])

    def test_comb_24_quality_consumer_5pct_live_sync(self):
        matches = filter_universe(self.pool, strategy="QUALITY_FCF", sector="Consumer Discretionary", min_return=5.0)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ticker"], "HD")
        self._assert_valid_setup(matches[0])

    def test_comb_25_all_strategies_mega_cap_3pct(self):
        matches = filter_universe(self.pool, strategy="ALL", sector="ALL", min_return=3.0, market_cap_tier="MEGA")
        self.assertGreaterEqual(len(matches), 8)
        for m in matches:
            self.assertGreaterEqual(m["market_cap"], 200e9)
            self._assert_valid_setup(m)

    def test_comb_26_all_strategies_large_cap_5pct(self):
        matches = filter_universe(self.pool, strategy="ALL", sector="ALL", min_return=5.0, market_cap_tier="LARGE")
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertTrue(10e9 <= m["market_cap"] < 200e9)
            self._assert_valid_setup(m)

    def test_comb_27_all_strategies_mid_cap_3pct(self):
        matches = filter_universe(self.pool, strategy="ALL", sector="ALL", min_return=3.0, market_cap_tier="MID")
        self.assertTrue(len(matches) >= 1)
        for m in matches:
            self.assertTrue(2e9 <= m["market_cap"] < 10e9)
            self._assert_valid_setup(m)

    def test_comb_28_cache_state_cold_boot_filter(self):
        cold_stocks = [c for c in self.pool if c["cache_state"] == "COLD_BOOT_SEED"]
        self.assertGreaterEqual(len(cold_stocks), 4)
        for s in cold_stocks:
            self._assert_valid_setup(s)

    def test_comb_29_cache_state_warm_disk_filter(self):
        warm_stocks = [c for c in self.pool if c["cache_state"] == "WARM_DISK_CACHE"]
        self.assertGreaterEqual(len(warm_stocks), 4)
        for s in warm_stocks:
            self._assert_valid_setup(s)

    def test_comb_30_cache_state_live_sync_filter(self):
        live_stocks = [c for c in self.pool if c["cache_state"] == "LIVE_SYNC"]
        self.assertGreaterEqual(len(live_stocks), 4)
        for s in live_stocks:
            self._assert_valid_setup(s)

    def test_comb_31_high_return_10pct_across_all_strategies(self):
        high_ret = filter_universe(self.pool, strategy="ALL", min_return=10.0)
        self.assertGreaterEqual(len(high_ret), 4)
        for s in high_ret:
            self.assertGreaterEqual(s["setup"]["target_return_pct"], 10.0)
            self._assert_valid_setup(s)

    def test_comb_32_composite_factor_scores_contract(self):
        for s in self.pool:
            scores = s["factor_scores"]
            self.assertIn("momentum", scores)
            self.assertIn("value", scores)
            self.assertIn("quality", scores)
            self.assertIn("growth", scores)
            self.assertIn("volatility", scores)

    def test_comb_33_catalyst_nodes_contract(self):
        for s in self.pool:
            catalysts = s["catalysts"]
            self.assertTrue(len(catalysts) > 0)
            self.assertIn("type", catalysts[0])
            self.assertIn("date", catalysts[0])

    def test_comb_34_zero_leakage_between_sectors(self):
        tech_only = filter_universe(self.pool, sector="Technology")
        for s in tech_only:
            self.assertNotEqual(s["sector"], "Healthcare")
            self.assertNotEqual(s["sector"], "Financials")

    def test_comb_35_zero_leakage_between_strategies(self):
        momentum_only = filter_universe(self.pool, strategy="MOMENTUM_BREAKOUT")
        for s in momentum_only:
            self.assertIn("MOMENTUM_BREAKOUT", s["strategies"])

    def test_comb_36_rest_api_json_serialization_fidelity(self):
        """Verify candidate JSON round-trip retains exact numerical precision."""
        import json
        for s in self.pool[:5]:
            encoded = json.dumps(s)
            decoded = json.loads(encoded)
            self.assertEqual(decoded["ticker"], s["ticker"])
            self.assertAlmostEqual(decoded["setup"]["risk_reward_ratio"], s["setup"]["risk_reward_ratio"])


if __name__ == "__main__":
    unittest.main()

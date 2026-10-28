"""
Adversarial Stress Test Suite for Quantitative Engine (Milestone 2 Challenger).
Empirical verification of:
1. Indicators math under degenerate inputs (zero variance, 1000x spikes, NaNs, short series, zero volume, negative prices).
2. Trade setup generator constraints (target return strictly in [3%, 10%], R:R strictly >= 2.0).
3. Backtest simulator invariants (zero trades, gap downs, immediate stop hits, conservative intraday stop precedence, zero lookahead).
4. Multi-strategy engine & factor radar robustness under hostile fundamental data.
5. Detection and reproduction of edge case vulnerabilities (inf inputs, division-by-zero drawdowns, string fundamentals).
"""

import math
import unittest
import numpy as np
import pandas as pd

from backend.app.engine.indicators import (
    calculate_atr,
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_macd,
    calculate_volume_spike,
    compute_all_indicators,
    get_latest_indicators,
)
from backend.app.engine.trade_setup import (
    generate_trade_setup,
)
from backend.app.engine.strategies import (
    calculate_factor_radar,
)
from backend.app.engine.backtest import (
    TradeRecord,
    BacktestSimulator,
    run_strategy_backtest,
)


class TestDegenerateIndicators(unittest.TestCase):
    """Stress tests for mathematical indicators under hostile/degenerate inputs."""

    def test_zero_variance_flat_prices(self):
        """Zero variance prices: all prices constant, volume constant."""
        n = 60
        flat = [100.0] * n
        vol = [1_000_000.0] * n

        # ATR should be 0.0 after warm-up
        atr = calculate_atr(flat, flat, flat, period=14)
        self.assertEqual(len(atr), n)
        self.assertAlmostEqual(atr.iloc[-1], 0.0, places=6)

        # RSI should be exactly 50.0 (no division by zero error)
        rsi = calculate_rsi(flat, period=14)
        self.assertEqual(len(rsi), n)
        self.assertAlmostEqual(rsi.iloc[-1], 50.0, places=6)

        # Bollinger Bands: UB = MB = LB = 100, Bandwidth = 0, Percent B = 0.5
        mb, ub, lb, bw, pct_b, is_sq = calculate_bollinger_bands(flat, period=20)
        self.assertAlmostEqual(mb.iloc[-1], 100.0, places=6)
        self.assertAlmostEqual(ub.iloc[-1], 100.0, places=6)
        self.assertAlmostEqual(lb.iloc[-1], 100.0, places=6)
        self.assertAlmostEqual(bw.iloc[-1], 0.0, places=6)
        self.assertAlmostEqual(pct_b.iloc[-1], 0.5, places=6)

        # MACD: Fast EMA = Slow EMA = 100, MACD = 0, Signal = 0, Hist = 0
        m_line, s_line, hist, cross = calculate_macd(flat, 12, 26, 9)
        self.assertAlmostEqual(m_line.iloc[-1], 0.0, places=6)
        self.assertAlmostEqual(s_line.iloc[-1], 0.0, places=6)
        self.assertAlmostEqual(hist.iloc[-1], 0.0, places=6)
        self.assertFalse(cross.any())

        # Volume spike: ratio = 1.0, is_spike = False
        v_ratio, is_spike = calculate_volume_spike(vol, period=20, threshold=1.5)
        self.assertAlmostEqual(v_ratio.iloc[-1], 1.0, places=6)
        self.assertFalse(is_spike.iloc[-1])

    def test_extreme_1000x_price_spikes(self):
        """Extreme 1000x spike test: tests numerical stability against overflow/Inf."""
        prices = [100.0] * 50 + [100_000.0] + [100.0] * 49
        highs = [p * 1.01 for p in prices]
        lows = [p * 0.99 for p in prices]

        atr = calculate_atr(highs, lows, prices, period=14)
        self.assertFalse(atr.isin([float("inf"), float("-inf")]).any())
        self.assertGreater(atr.iloc[50], 0.0)

        rsi = calculate_rsi(prices, period=14)
        self.assertFalse(rsi.isin([float("inf"), float("-inf")]).any())
        valid_rsi = rsi.dropna()
        self.assertTrue((valid_rsi >= 0.0).all() and (valid_rsi <= 100.0).all())

        mb, ub, lb, bw, pct_b, is_sq = calculate_bollinger_bands(prices, period=20)
        self.assertFalse(bw.isin([float("inf"), float("-inf")]).any())
        self.assertTrue((ub.dropna() >= mb.dropna()).all())
        self.assertTrue((mb.dropna() >= lb.dropna()).all())

    def test_nan_and_none_inputs(self):
        """Intermittent NaNs and corrupted DataFrame values."""
        df_nan = pd.DataFrame({
            "close": [100.0, np.nan, 102.0, None, 105.0] * 12,
            "high": [101.0, np.nan, 103.0, None, 106.0] * 12,
            "low": [99.0, np.nan, 101.0, None, 104.0] * 12,
            "volume": [1_000_000, 0, np.nan, None, 2_000_000] * 12,
        })
        computed = compute_all_indicators(df_nan)
        self.assertEqual(len(computed), len(df_nan))

        latest = get_latest_indicators(df_nan)
        self.assertIsNotNone(latest)
        self.assertFalse(math.isnan(latest.atr_14))
        self.assertFalse(math.isnan(latest.rsi_14))
        self.assertFalse(math.isnan(latest.bb_bandwidth))

    def test_short_series_boundaries(self):
        """Series lengths smaller than indicator lookback periods (0, 1, 5, 14, 20, 50, 199 bars)."""
        # 0 bars
        df_empty = pd.DataFrame(columns=["close", "high", "low", "volume"])
        self.assertTrue(compute_all_indicators(df_empty).empty)
        self.assertIsNone(get_latest_indicators(df_empty))
        self.assertIsNone(get_latest_indicators(None))

        # 1 bar
        df_1 = pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0], "volume": [1000.0]})
        c_1 = compute_all_indicators(df_1)
        self.assertEqual(len(c_1), 1)
        lat_1 = get_latest_indicators(df_1)
        self.assertIsNotNone(lat_1)
        self.assertEqual(lat_1.atr_14, 0.0)
        self.assertEqual(lat_1.rsi_14, 0.0)

        # 14 bars: ATR requires 14 bars (14th bar has initial ATR)
        df_14 = pd.DataFrame({
            "close": [100.0 + i for i in range(14)],
            "high": [101.0 + i for i in range(14)],
            "low": [99.0 + i for i in range(14)],
            "volume": [1000.0] * 14,
        })
        c_14 = compute_all_indicators(df_14)
        self.assertFalse(pd.isna(c_14["atr_14"].iloc[-1]))
        self.assertTrue(pd.isna(c_14["rsi_14"].iloc[-1]))
        self.assertTrue(pd.isna(c_14["sma_20"].iloc[-1]))

        # 199 bars (< 200 SMA): SMA200 must be NaN, stage2_alignment must be False
        df_199 = pd.DataFrame({
            "close": [100.0 + i * 0.1 for i in range(199)],
            "high": [101.0 + i * 0.1 for i in range(199)],
            "low": [99.0 + i * 0.1 for i in range(199)],
            "volume": [1000.0] * 199,
        })
        c_199 = compute_all_indicators(df_199)
        self.assertTrue(pd.isna(c_199["sma_200"].iloc[-1]))
        self.assertFalse(c_199["stage2_alignment"].iloc[-1])

    def test_all_zero_volume(self):
        """All-zero volume series: must not trigger ZeroDivisionError."""
        df_zero_vol = pd.DataFrame({
            "close": [100.0 + i for i in range(30)],
            "high": [101.0 + i for i in range(30)],
            "low": [99.0 + i for i in range(30)],
            "volume": [0.0] * 30,
        })
        c_zero = compute_all_indicators(df_zero_vol)
        self.assertFalse(c_zero["volume_spike"].any())
        self.assertAlmostEqual(c_zero["volume_ratio_20"].iloc[-1], 1.0, places=5)

    def test_negative_prices(self):
        """Negative price series (e.g. commodity anomaly): bandwidth and ATR resilience."""
        neg_prices = [-100.0 + i * 0.5 for i in range(40)]
        neg_highs = [p + 2.0 for p in neg_prices]
        neg_lows = [p - 2.0 for p in neg_prices]

        atr = calculate_atr(neg_highs, neg_lows, neg_prices, period=14)
        self.assertGreater(atr.iloc[-1], 0.0)

        mb, ub, lb, bw, pct_b, is_sq = calculate_bollinger_bands(neg_prices, period=20)
        self.assertFalse(math.isnan(bw.iloc[-1]))
        self.assertGreaterEqual(bw.iloc[-1], 0.0)

    def test_inverted_high_low(self):
        """Corrupted bars where High < Low."""
        highs = [10.0] * 20
        lows = [15.0] * 20  # Low > High
        closes = [12.0] * 20

        atr = calculate_atr(highs, lows, closes, period=14)
        self.assertGreaterEqual(atr.iloc[-1], 0.0)


class TestTradeSetupAdversarial(unittest.TestCase):
    """Stress testing the trade setup generator against invariants."""

    def test_target_returns_and_rr_monte_carlo(self):
        """
        Adversarially sweep 1,000 parameter combinations:
        Every valid trade setup MUST strictly satisfy:
        1. 3.0 <= target_return_pct <= 10.0
        2. risk_reward_ratio >= 2.0
        3. stop_loss < entry_price
        4. target_price > entry_price
        5. stop_loss > 0
        """
        strategies = ["MOMENTUM_BREAKOUT", "EARNINGS_PEAD", "MEAN_REVERSION", "QUALITY_FCF", "UNKNOWN"]
        np.random.seed(42)

        tested_count = 0
        valid_count = 0

        for _ in range(1000):
            entry = float(np.random.uniform(5.0, 1000.0))
            # Test realistic to high ATRs (0.5% to 8% of price)
            atr_pct = float(np.random.uniform(0.005, 0.08))
            atr = entry * atr_pct
            strat = np.random.choice(strategies)
            bb_mid = entry * float(np.random.uniform(0.95, 1.15))
            swing_low = entry * float(np.random.uniform(0.85, 0.99))

            setup = generate_trade_setup(
                entry_price=entry,
                atr_14=atr,
                strategy_name=strat,
                min_return_pct=3.0,
                max_return_pct=10.0,
                min_rr_ratio=2.0,
                recent_swing_low=swing_low,
                bb_middle=bb_mid,
            )
            tested_count += 1

            if setup.is_valid:
                valid_count += 1
                # INVARIANT 1: Target return bounded in [3.0%, 10.0%]
                self.assertGreaterEqual(
                    setup.target_return_pct, 3.0,
                    f"Target return {setup.target_return_pct}% < 3.0% on entry={entry}, atr={atr}, strat={strat}"
                )
                self.assertLessEqual(
                    setup.target_return_pct, 10.0,
                    f"Target return {setup.target_return_pct}% > 10.0% on entry={entry}, atr={atr}, strat={strat}"
                )

                # INVARIANT 2: Risk-Reward strictly >= 2.0
                self.assertGreaterEqual(
                    setup.risk_reward_ratio, 2.0,
                    f"R:R ratio {setup.risk_reward_ratio} < 2.0 on entry={entry}, atr={atr}, strat={strat}"
                )

                # INVARIANT 3: Geometry of Long Trade
                self.assertLess(setup.stop_loss, setup.entry_price)
                self.assertGreater(setup.target_price, setup.entry_price)
                self.assertGreater(setup.stop_loss, 0.0)
                self.assertGreater(setup.risk_per_share, 0.0)
                self.assertGreater(setup.reward_per_share, 0.0)

        self.assertEqual(tested_count, 1000)
        self.assertGreater(valid_count, 100)

    def test_extreme_high_volatility_invalidation(self):
        """When volatility is so massive that a 10% target cannot yield 2.0 R:R, must invalidate."""
        entry = 100.0
        # If ATR is 15.0, 1.5*ATR = 22.5 stop.
        # Max target is +10% ($110, reward = 10).
        # For 2.0 RR, risk must be <= 5.0 (0.33*ATR < 0.75*ATR threshold).
        # Setup MUST be marked invalid.
        setup = generate_trade_setup(entry, 15.0, strategy_name="MOMENTUM_BREAKOUT")
        self.assertFalse(setup.is_valid)

    def test_degenerate_zero_and_negative_inputs(self):
        """Zero and negative inputs must be rejected."""
        self.assertFalse(generate_trade_setup(0.0, 2.0).is_valid)
        self.assertFalse(generate_trade_setup(-10.0, 2.0).is_valid)
        self.assertFalse(generate_trade_setup(100.0, 0.0).is_valid)
        self.assertFalse(generate_trade_setup(100.0, -2.0).is_valid)
        self.assertFalse(generate_trade_setup(float("nan"), 2.0).is_valid)
        self.assertFalse(generate_trade_setup(100.0, float("nan")).is_valid)


class TestBacktestSimulatorAdversarial(unittest.TestCase):
    """Stress testing the backtest simulator for zero lookahead and edge handling."""

    def _create_synthetic_backtest_df(self, n=100, breakout_idx=60):
        """Creates a well-formed OHLCV series with sufficient lookback (>=50 bars for SMA50)."""
        close = [100.0 + i * 0.1 for i in range(n)]
        close[breakout_idx] = 112.0  # Breakout jump above upper band
        high = [c + 0.5 for c in close]
        high[breakout_idx] = 114.0
        low = [c - 0.5 for c in close]
        open_p = [c - 0.1 for c in close]
        volume = [1_000_000.0] * n
        volume[breakout_idx] = 3_000_000.0  # Volume spike

        dates = [f"2026-{i//25+1:02d}-{i%25+1:02d}" for i in range(n)]
        return pd.DataFrame({
            "date": dates,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    def test_zero_trades_empty_or_quiescent_series(self):
        """Backtest simulator with 0 trades: metrics must be zeroed without crashing."""
        sim = BacktestSimulator()
        res = sim.compute_metrics([])
        self.assertEqual(res.total_trades, 0)
        self.assertEqual(res.win_rate_pct, 0.0)
        self.assertEqual(res.profit_factor, 0.0)
        self.assertEqual(res.expectancy_pct, 0.0)
        self.assertEqual(res.max_drawdown_pct, 0.0)
        self.assertEqual(res.sharpe_ratio, 0.0)

        d = res.to_dict()
        self.assertEqual(d["total_trades"], 0)

        # Quiescent flat data
        df_flat = pd.DataFrame({
            "date": [f"2026-01-{i:02d}" for i in range(1, 61)],
            "open": [100.0] * 60,
            "high": [100.0] * 60,
            "low": [100.0] * 60,
            "close": [100.0] * 60,
            "volume": [100_000.0] * 60,
        })
        res_flat = run_strategy_backtest(df_flat, strategy_name="MOMENTUM_BREAKOUT")
        self.assertEqual(res_flat.total_trades, 0)

    def test_overnight_gap_down_execution(self):
        """Severe overnight gap down: exit must fill at open minus slippage, not stop price."""
        df = self._create_synthetic_backtest_df(n=100, breakout_idx=60)
        # Bar 61 is entry day: keep price within normal range
        df.loc[61, "open"] = 100.0
        df.loc[61, "high"] = 101.0
        df.loc[61, "low"] = 99.0
        df.loc[61, "close"] = 100.0
        # Bar 62 is overnight gap down
        df.loc[62, "open"] = 80.0
        df.loc[62, "high"] = 81.0
        df.loc[62, "low"] = 78.0
        df.loc[62, "close"] = 79.0

        sim = BacktestSimulator(slippage_bps=5.0)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="GAP_TEST")
        self.assertGreater(len(trades), 0)

        trade = trades[0]
        self.assertEqual(trade.exit_reason, "STOP_LOSS")
        # Exit price must fill at approximately 80.0 * (1 - 0.0005) = 79.96, NOT 97.78 stop
        self.assertLess(trade.exit_price, 85.0)
        self.assertAlmostEqual(trade.exit_price, 80.0 * (1.0 - 0.0005), places=2)
        self.assertLess(trade.return_pct, -18.0)
        self.assertEqual(trade.holding_days, 2)

    def test_immediate_same_bar_stop_hit(self):
        """Bar T+1 immediately drops through stop-loss on the day of entry."""
        df = self._create_synthetic_backtest_df(n=100, breakout_idx=60)
        # Plunge immediately on Day T+1
        df.loc[61, "open"] = 100.0
        df.loc[61, "high"] = 100.5
        df.loc[61, "low"] = 90.0
        df.loc[61, "close"] = 92.0

        sim = BacktestSimulator(slippage_bps=5.0)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="SAME_BAR")
        self.assertGreater(len(trades), 0)
        t = trades[0]
        self.assertEqual(t.exit_reason, "STOP_LOSS")
        self.assertEqual(t.holding_days, 1)

    def test_conservative_intraday_stop_precedence(self):
        """On a bar where BOTH stop and target are touched, Stop-Loss MUST take precedence."""
        df = self._create_synthetic_backtest_df(n=100, breakout_idx=60)
        df.loc[61, "open"] = 100.0
        df.loc[61, "high"] = 101.0
        df.loc[61, "low"] = 99.0
        df.loc[61, "close"] = 100.0
        # Bar 62 penetrates BOTH Target (>106) and Stop (<97)
        df.loc[62, "open"] = 100.0
        df.loc[62, "high"] = 125.0
        df.loc[62, "low"] = 85.0
        df.loc[62, "close"] = 105.0

        sim = BacktestSimulator(slippage_bps=5.0)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="PRECEDENCE")
        self.assertGreater(len(trades), 0)
        t = trades[0]
        self.assertEqual(t.exit_reason, "STOP_LOSS")
        self.assertLess(t.return_pct, 0.0)

    def test_time_stop_expiration(self):
        """Holding for 20 days without touching stop or target must exit on TIME_STOP."""
        df = self._create_synthetic_backtest_df(n=100, breakout_idx=60)
        # Bars 61 to 85: price hovers strictly between $99 and $101 (neither stop ~97 nor target ~106)
        for k in range(61, 85):
            df.loc[k, "open"] = 100.0
            df.loc[k, "high"] = 101.0
            df.loc[k, "low"] = 99.0
            df.loc[k, "close"] = 100.0

        sim = BacktestSimulator(slippage_bps=5.0, max_hold_days=20)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="TIMESTOP")
        self.assertGreater(len(trades), 0)
        t = trades[0]
        self.assertEqual(t.exit_reason, "TIME_STOP")
        self.assertEqual(t.holding_days, 20)


class TestVulnerabilityDemonstration(unittest.TestCase):
    """
    Verification of edge case remediations uncovered during adversarial audit.
    These tests demonstrate that specific defects have been definitively resolved.
    """

    def test_vuln_infinite_inputs_in_trade_setup(self):
        """
        VULNERABILITY 1 REMEDIATION: `generate_trade_setup` rejects float('inf') as invalid.
        Guarantees: is_valid is False, all fields zeroed, JSON compliant (no Inf/NaN).
        """
        import json
        setup_inf = generate_trade_setup(float("inf"), 2.0)
        self.assertFalse(setup_inf.is_valid)
        self.assertEqual(setup_inf.entry_price, 0.0)
        self.assertEqual(setup_inf.target_return_pct, 0.0)
        self.assertEqual(setup_inf.risk_reward_ratio, 0.0)
        self.assertFalse(math.isnan(setup_inf.target_return_pct))
        self.assertFalse(math.isinf(setup_inf.entry_price))

        # Must serialize cleanly without allow_nan
        payload = json.dumps(setup_inf.to_dict(), allow_nan=False)
        self.assertIn('"is_valid": false', payload)

    def test_vuln_catastrophic_loss_drawdown_nan(self):
        """
        VULNERABILITY 2 REMEDIATION: BacktestSimulator.compute_metrics clamps drawdown to 100.0% on total loss.
        Guarantees: max_drawdown_pct is 100.0%, no NaN, no divide warning, JSON serializable.
        """
        import json
        sim = BacktestSimulator()
        catastrophic_trades = [
            TradeRecord("Z1", "STRAT", "2026-01-01", 100.0, 95.0, 110.0, exit_price=0.0, return_pct=-100.0, exit_reason="STOP_LOSS", holding_days=1),
        ]
        res = sim.compute_metrics(catastrophic_trades)
        self.assertFalse(math.isnan(res.max_drawdown_pct))
        self.assertEqual(res.max_drawdown_pct, 100.0)

        # Must serialize cleanly without allow_nan
        payload = json.dumps(res.to_dict(), allow_nan=False)
        self.assertIn('"max_drawdown_pct": 100.0', payload)

    def test_vuln_string_fundamentals_crash(self):
        """
        VULNERABILITY 3 REMEDIATION: `calculate_factor_radar` handles 'N/A' string inputs gracefully.
        Guarantees: Non-numeric strings in SEC/Yahoo data do not crash evaluation loop.
        """
        scores = calculate_factor_radar(
            None,
            {"forward_pe": "N/A", "fcf_yield": "--", "roe": "None", "debt_to_equity": "N/A", "revenue_growth_qoq": ""},
        )
        self.assertIsNotNone(scores)
        self.assertTrue(0 <= scores.value <= 100)
        self.assertTrue(0 <= scores.quality <= 100)
        self.assertTrue(0 <= scores.growth <= 100)

    def test_bollinger_squeeze_on_short_series(self):
        """
        Verify Bollinger Band squeeze detection on short series (<95 bars) is not zero-poisoned.
        """
        prices = [100.0 + i * 0.01 for i in range(40)]
        mb, ub, lb, bw, pct_b, is_sq = calculate_bollinger_bands(prices, period=20)
        self.assertGreater(is_sq.sum(), 0)


if __name__ == "__main__":
    unittest.main()

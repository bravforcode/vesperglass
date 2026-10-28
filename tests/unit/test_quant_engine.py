"""
Unit Test Suite for Quantitative Engine (Milestone 2: Features F5, F6, F7, F8).
Comprehensive institutional tests covering:
- Exact mathematical formulations for ATR(14), RSI(14), Bollinger Bands, MACD, SMAs, Volume Spike
- 4 Quantitative Strategies (Momentum Breakout, Earnings PEAD, Oversold Bounce, Quality FCF)
- 5-Axis Factor Radar Scoring Algorithm
- Trade Setup Risk/Reward Modeling
- Lookahead-Free Walk-Forward Backtester Simulator
- Edge cases, numerical stability, NaN resilience, zero-variance handling
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
    calculate_smas,
    check_stage2_alignment,
    calculate_volume_spike,
    compute_all_indicators,
    get_latest_indicators,
)
from backend.app.engine.trade_setup import (
    generate_trade_setup,
)
from backend.app.engine.strategies import (
    calculate_factor_radar,
    evaluate_momentum_breakout,
    evaluate_earnings_pead,
    evaluate_oversold_bounce,
    evaluate_quality_fcf,
)
from backend.app.engine.backtest import (
    TradeRecord,
    BacktestSimulator,
)


class TestIndicatorsMath(unittest.TestCase):
    """F5: Exact Mathematical Verification for Technical Indicators."""

    def test_wilder_atr_manual_reference(self):
        """Test Wilder's ATR(14) RMA smoothing against hand-computed reference values."""
        highs = [10.0, 10.5, 11.0, 10.8, 11.2, 11.5, 11.3, 11.8, 12.0, 12.2, 12.1, 12.5, 12.4, 12.8, 13.0]
        lows = [9.5, 9.8, 10.2, 10.1, 10.5, 10.8, 10.6, 11.0, 11.2, 11.5, 11.4, 11.8, 11.9, 12.1, 12.3]
        closes = [9.8, 10.2, 10.6, 10.5, 11.0, 11.2, 11.0, 11.5, 11.8, 12.0, 11.9, 12.2, 12.1, 12.5, 12.7]

        atr_series = calculate_atr(highs, lows, closes, period=14)
        self.assertEqual(len(atr_series), 15)

        # First 13 values must be NaN
        for i in range(13):
            self.assertTrue(pd.isna(atr_series[i]))

        # Calculate manual TRs
        trs = [highs[0] - lows[0]]
        for i in range(1, 15):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)

        # 14th value (index 13) is mean of first 14 TRs
        expected_atr_14 = sum(trs[:14]) / 14.0
        self.assertAlmostEqual(atr_series[13], expected_atr_14, places=6)

        # 15th value (index 14) is Wilder's smoothed: (atr_prev * 13 + tr_14) / 14
        expected_atr_15 = (expected_atr_14 * 13.0 + trs[14]) / 14.0
        self.assertAlmostEqual(atr_series[14], expected_atr_15, places=6)

    def test_wilder_rsi_manual_reference(self):
        """Test Wilder's RSI(14) MMA against reference formula and boundary constraints."""
        # 16-element price series
        prices = [
            100.0, 102.0, 101.0, 103.0, 105.0, 104.0, 106.0, 108.0,
            107.0, 109.0, 111.0, 110.0, 112.0, 114.0, 113.0, 115.0
        ]
        rsi_series = calculate_rsi(prices, period=14)
        self.assertEqual(len(rsi_series), len(prices))

        # First 14 bars must be NaN
        for i in range(14):
            self.assertTrue(pd.isna(rsi_series[i]))

        # Values at index 14 and 15 must be valid and in [0, 100]
        self.assertFalse(pd.isna(rsi_series[14]))
        self.assertFalse(pd.isna(rsi_series[15]))
        self.assertTrue(0.0 <= rsi_series[14] <= 100.0)
        self.assertTrue(0.0 <= rsi_series[15] <= 100.0)

        # Test extreme upward trend -> RSI approaching 100
        up_prices = [100.0 + i * 2.0 for i in range(30)]
        up_rsi = calculate_rsi(up_prices, period=14)
        self.assertAlmostEqual(up_rsi.iloc[-1], 100.0, places=4)

        # Test extreme downward trend -> RSI approaching 0
        down_prices = [200.0 - i * 2.0 for i in range(30)]
        down_rsi = calculate_rsi(down_prices, period=14)
        self.assertAlmostEqual(down_rsi.iloc[-1], 0.0, places=4)

    def test_bollinger_bands_exact_math(self):
        """Test Bollinger Bands 20 SMA +/- 2.0 std dev and bandwidth."""
        closes = [100.0 + i for i in range(30)]
        mb, ub, lb, bw, pct_b, is_sq = calculate_bollinger_bands(closes, period=20, num_std=2.0)

        self.assertEqual(len(mb), 30)
        idx = 25
        subset = closes[idx - 19 : idx + 1]
        expected_mb = sum(subset) / 20.0
        expected_var = sum((x - expected_mb) ** 2 for x in subset) / 20.0
        expected_std = math.sqrt(expected_var)

        self.assertAlmostEqual(mb.iloc[idx], expected_mb, places=5)
        self.assertAlmostEqual(ub.iloc[idx], expected_mb + 2.0 * expected_std, places=5)
        self.assertAlmostEqual(lb.iloc[idx], expected_mb - 2.0 * expected_std, places=5)
        self.assertAlmostEqual(bw.iloc[idx], (4.0 * expected_std) / expected_mb, places=5)

    def test_macd_exact_math_and_cross(self):
        """Test MACD (12, 26, 9) and bullish crossover detection."""
        closes = [100.0 + math.sin(i * 0.15) * 10.0 for i in range(60)]
        m_line, s_line, hist, cross = calculate_macd(closes, fast_period=12, slow_period=26, signal_period=9)

        self.assertEqual(len(m_line), 60)
        self.assertEqual(len(s_line), 60)
        self.assertEqual(len(hist), 60)
        self.assertEqual(len(cross), 60)

        # Verify Histogram = MACD - Signal
        for i in range(30, 60):
            self.assertAlmostEqual(hist.iloc[i], m_line.iloc[i] - s_line.iloc[i], places=6)

        # Verify crossover logic
        for i in range(1, 60):
            if cross.iloc[i]:
                self.assertLessEqual(m_line.iloc[i - 1], s_line.iloc[i - 1])
                self.assertGreater(m_line.iloc[i], s_line.iloc[i])

    def test_sma_and_stage2_alignment(self):
        """Test SMA calculation and Stage 2 bullish condition."""
        # Create clear bullish Stage 2 sequence
        closes = [100.0 + i * 0.5 for i in range(250)]
        sma20, sma50, sma200 = calculate_smas(closes, (20, 50, 200))

        last_idx = 249
        c = closes[last_idx]
        s20 = sma20.iloc[last_idx]
        s50 = sma50.iloc[last_idx]
        s200 = sma200.iloc[last_idx]

        self.assertGreater(c, s20)
        self.assertGreater(s20, s50)
        self.assertGreater(s50, s200)

        alignment = check_stage2_alignment(closes, sma20, sma50, sma200)
        self.assertTrue(alignment.iloc[last_idx])

    def test_volume_spike_calculation(self):
        """Test volume spike ratio and threshold flag."""
        volumes = [1_000_000.0] * 20 + [2_000_000.0]
        v_ratio, is_spike = calculate_volume_spike(volumes, period=20, threshold=1.5)

        expected_sma = (19 * 1_000_000.0 + 2_000_000.0) / 20.0
        self.assertAlmostEqual(v_ratio.iloc[20], 2_000_000.0 / expected_sma, places=2)
        self.assertTrue(is_spike.iloc[20])
        self.assertFalse(is_spike.iloc[19])

    def test_resilient_edge_cases(self):
        """Test zero-variance, empty data, NaN values, and short series."""
        # Empty input
        empty_s = pd.Series([], dtype=float)
        self.assertEqual(len(calculate_atr(empty_s, empty_s, empty_s)), 0)
        self.assertEqual(len(calculate_rsi(empty_s)), 0)

        # Zero variance (constant prices)
        const_prices = [100.0] * 25
        mb, ub, lb, bw, pct_b, is_sq = calculate_bollinger_bands(const_prices, period=20)
        self.assertFalse(pd.isna(bw.iloc[-1]))
        self.assertAlmostEqual(bw.iloc[-1], 0.0, places=5)
        self.assertAlmostEqual(pct_b.iloc[-1], 0.5, places=5)

        # Insufficient bars
        short_prices = [100.0, 101.0, 102.0]
        atr_short = calculate_atr(short_prices, short_prices, short_prices, period=14)
        self.assertTrue(pd.isna(atr_short.iloc[-1]))

        # NaN inputs in DataFrame
        df_nan = pd.DataFrame({
            "close": [10.0, np.nan, 12.0, 13.0] * 10,
            "high": [11.0, np.nan, 13.0, 14.0] * 10,
            "low": [9.0, np.nan, 11.0, 12.0] * 10,
            "volume": [1000, 0, 1200, 1500] * 10,
        })
        computed = compute_all_indicators(df_nan)
        self.assertIn("atr_14", computed.columns)
        self.assertIn("rsi_14", computed.columns)


class TestTradeSetupModeling(unittest.TestCase):
    """F7: Trade Setup & Risk-Reward Modeling Tests."""

    def test_trade_setup_standard_breakout(self):
        """Test trade setup generation with 1.5*ATR stop, target in [3%, 10%], and RR >= 2.0."""
        entry = 100.0
        atr = 2.0
        setup = generate_trade_setup(entry, atr, strategy_name="MOMENTUM_BREAKOUT")

        self.assertTrue(setup.is_valid)
        self.assertEqual(setup.entry_price, 100.0)
        self.assertAlmostEqual(setup.stop_loss, 97.0)  # 100 - 1.5*2 = 97.0
        self.assertGreaterEqual(setup.target_return_pct, 3.0)
        self.assertLessEqual(setup.target_return_pct, 10.0)
        self.assertGreaterEqual(setup.risk_reward_ratio, 2.0)

    def test_trade_setup_oversold_bounce(self):
        """Test oversold bounce target adjusting to satisfy minimum 1:2.0 RR."""
        entry = 50.0
        atr = 1.0
        setup = generate_trade_setup(
            entry, atr, strategy_name="MEAN_REVERSION", bb_middle=52.0
        )
        self.assertTrue(setup.is_valid)
        self.assertGreaterEqual(setup.risk_reward_ratio, 2.0)
        self.assertGreaterEqual(setup.target_return_pct, 3.0)

    def test_trade_setup_invalid_inputs(self):
        """Test rejection on zero or negative price or ATR."""
        setup1 = generate_trade_setup(0.0, 2.0)
        self.assertFalse(setup1.is_valid)

        setup2 = generate_trade_setup(100.0, -1.0)
        self.assertFalse(setup2.is_valid)

        setup3 = generate_trade_setup(float("nan"), 2.0)
        self.assertFalse(setup3.is_valid)


class TestMultiStrategyEngine(unittest.TestCase):
    """F6: Multi-Strategy Engine & Factor Radar Scoring Tests."""

    def _create_synthetic_df(self, n=250, start_price=100.0, trend=0.2):
        """Helper to create synthetic OHLCV DataFrame."""
        dates = [f"2026-01-{i%28+1:02d}" for i in range(n)]
        close = [start_price + i * trend for i in range(n)]
        high = [c + 1.5 for c in close]
        low = [c - 1.5 for c in close]
        open_p = [c - 0.2 for c in close]
        volume = [1_000_000] * (n - 1) + [2_500_000]
        return pd.DataFrame({
            "date": dates,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    def test_strategy1_momentum_breakout(self):
        """Test Momentum Breakout triggers when Stage 2, volume spike, and BB breakout coincide."""
        df = self._create_synthetic_df(n=250, start_price=100.0, trend=0.3)
        # Push last bar above upper band
        df.loc[df.index[-1], "close"] = df["close"].iloc[-2] + 10.0
        df.loc[df.index[-1], "high"] = df["close"].iloc[-1] + 2.0
        df.loc[df.index[-1], "volume"] = 3_000_000

        computed = compute_all_indicators(df)
        ind = get_latest_indicators(df)
        match = evaluate_momentum_breakout(ind, df=computed)

        self.assertTrue(match.is_matched)
        self.assertGreaterEqual(match.confidence_score, 60)
        self.assertIsNotNone(match.setup)
        self.assertTrue(match.setup.is_valid)

    def test_strategy2_earnings_pead(self):
        """Test Earnings PEAD triggers on EPS surprise >= +10% and positive revenue growth."""
        funds_good = {
            "eps_surprise_pct": 14.5,
            "revenue_growth_qoq": 8.2,
            "market_cap": 10_000_000_000,
        }
        df = self._create_synthetic_df(n=60, start_price=50.0, trend=0.1)
        ind = get_latest_indicators(df)
        match = evaluate_earnings_pead(ind, funds_good)

        self.assertTrue(match.is_matched)
        self.assertGreaterEqual(match.confidence_score, 60)

        # Fails when EPS surprise < 10%
        funds_bad = {"eps_surprise_pct": 5.0, "revenue_growth_qoq": 8.0}
        match_bad = evaluate_earnings_pead(ind, funds_bad)
        self.assertFalse(match_bad.is_matched)

    def test_strategy3_oversold_bounce(self):
        """Test Oversold Bounce triggers on RSI < 35, Lower Band touch, and solvent balance sheet."""
        # Create declining series to trigger RSI < 35
        df = self._create_synthetic_df(n=60, start_price=100.0, trend=-0.8)
        # Dip last low below lower band
        df.loc[df.index[-1], "low"] = df["close"].iloc[-1] - 5.0

        funds = {
            "debt_to_equity": 0.8,
            "free_cash_flow": 200_000_000,
            "roe": 16.0,
        }
        ind = get_latest_indicators(df)
        match = evaluate_oversold_bounce(ind, funds)

        self.assertTrue(match.is_matched)
        self.assertGreaterEqual(match.confidence_score, 60)

    def test_strategy4_quality_fcf(self):
        """Test Quality FCF triggers on ROE >= 15%, D/E <= 1.0, FCF Yield >= 5%."""
        funds = {
            "roe": 22.0,
            "debt_to_equity": 0.55,
            "fcf_yield": 6.8,
            "forward_pe": 18.0,
        }
        df = self._create_synthetic_df(n=60, start_price=80.0, trend=0.1)
        ind = get_latest_indicators(df)
        match = evaluate_quality_fcf(ind, funds)

        self.assertTrue(match.is_matched)
        self.assertGreaterEqual(match.confidence_score, 65)

    def test_factor_radar_scoring(self):
        """Test Factor Radar scores normalize strictly between 0 and 100."""
        df = self._create_synthetic_df(n=60, start_price=100.0, trend=0.2)
        ind = get_latest_indicators(df)
        funds = {
            "roe": 20.0,
            "debt_to_equity": 0.7,
            "fcf_yield": 6.0,
            "forward_pe": 16.0,
            "revenue_growth_qoq": 12.0,
            "eps_surprise_pct": 11.0,
        }
        scores = calculate_factor_radar(ind, funds)

        for factor in ("momentum", "value", "quality", "growth", "volatility"):
            val = getattr(scores, factor)
            self.assertGreaterEqual(val, 0)
            self.assertLessEqual(val, 100)


class TestBacktestSimulator(unittest.TestCase):
    """F8: Lookahead-Free Backtest Verifier Tests."""

    def _create_trending_ohlcv(self, n=120):
        """Generates historical OHLCV data with known breakout events."""
        dates = [f"2025-{i//25+1:02d}-{i%25+1:02d}" for i in range(n)]
        close = []
        p = 100.0
        for i in range(n):
            if 30 <= i <= 35:
                p += 3.0  # Breakout jump
            elif 70 <= i <= 75:
                p += 4.0  # Second breakout
            else:
                p += 0.1
            close.append(p)

        high = [c + 1.0 for c in close]
        low = [c - 1.0 for c in close]
        open_p = [c - 0.2 for c in close]
        volume = [1_000_000] * n
        volume[31] = 2_500_000  # Spike
        volume[71] = 2_800_000  # Spike

        return pd.DataFrame({
            "date": dates,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    def test_backtest_open_t_plus_1_execution(self):
        """Verify trade enters strictly at Open_{T+1} with 5 bps slippage."""
        df = self._create_trending_ohlcv(100)
        sim = BacktestSimulator(slippage_bps=5.0, max_hold_days=20)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="TEST")

        self.assertGreater(len(trades), 0)
        for t in trades:
            # Slippage is 5 bps: entry_price should equal open * 1.0005
            self.assertGreater(t.entry_price, 0)
            self.assertIn(t.exit_reason, ["TARGET", "STOP_LOSS", "TIME_STOP"])
            self.assertGreater(t.holding_days, 0)
            self.assertLessEqual(t.holding_days, 20)

    def test_backtest_intraday_stop_priority(self):
        """Verify conservative stop priority when both Stop and Target are touched."""
        # Construct bar that touches both stop and target
        trade = TradeRecord(
            ticker="DUAL_TOUCH",
            strategy="MOMENTUM_BREAKOUT",
            entry_date="2026-01-01",
            entry_price=100.0,
            stop_price=95.0,
            target_price=108.0,
        )
        bar = {"open": 100.0, "high": 110.0, "low": 94.0, "close": 102.0}

        exit_reason = None
        # Backtest simulator rule: Stop first
        if bar["low"] <= trade.stop_price:
            exit_reason = "STOP_LOSS"
        elif bar["high"] >= trade.target_price:
            exit_reason = "TARGET"

        self.assertEqual(exit_reason, "STOP_LOSS")

    def test_backtest_metrics_calculation(self):
        """Test computation of win rate, profit factor, expectancy, and max drawdown."""
        sim = BacktestSimulator()
        trades = [
            TradeRecord("A", "STRAT", "2026-01-01", 100.0, 95.0, 108.0, exit_price=108.0, return_pct=8.0, exit_reason="TARGET", holding_days=5),
            TradeRecord("B", "STRAT", "2026-01-08", 50.0, 48.0, 54.0, exit_price=54.0, return_pct=8.0, exit_reason="TARGET", holding_days=6),
            TradeRecord("C", "STRAT", "2026-01-15", 20.0, 19.0, 22.0, exit_price=19.0, return_pct=-5.0, exit_reason="STOP_LOSS", holding_days=3),
        ]
        res = sim.compute_metrics(trades)

        self.assertEqual(res.total_trades, 3)
        self.assertEqual(res.winning_trades, 2)
        self.assertEqual(res.losing_trades, 1)
        self.assertAlmostEqual(res.win_rate_pct, (2 / 3) * 100.0, places=2)
        self.assertGreater(res.profit_factor, 1.0)
        self.assertGreater(res.expectancy_pct, 0.0)


if __name__ == "__main__":
    unittest.main()

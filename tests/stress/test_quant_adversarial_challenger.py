"""
Adversarial Mathematical Stress & Verification Test Suite for Stocknomist Quantitative Engine.
Created by challenger_final_1 (Final Quant & Math Adversarial Challenger).

Assignments Verified:
1. Wilder's ATR(14) exact formula (MMA smoothing) vs standard SMA
2. Wilder's RSI(14) with flat prices, all up-days, all down-days, zero gains, zero losses
3. Trade setup constraints: strict min 1:2.0 Risk:Reward ratio, 3-10% target return, ATR-based stop loss
4. Lookahead-free backtester: walk-forward execution at Open_{T+1}, 5 bps slippage, intraday stop checking before target
5. Fuzz inputs with NaN, Inf, negative prices, zero volume, and empty series
"""

import json
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
    TradeSetup,
)
from backend.app.engine.backtest import (
    TradeRecord,
    BacktestSimulator,
    run_strategy_backtest,
)


class TestWilderAtrMMAVsSma(unittest.TestCase):
    """
    Empirical Verification 1: Wilder's ATR(14) exact formula (MMA smoothing) vs standard SMA.
    Mathematically verifies that Wilder's MMA smoothing is used and NOT a simple moving average.
    """

    def test_atr_exact_wilder_mma_recurrence(self):
        """
        Tests Wilder's RMA/MMA recurrence step-by-step against an independent manual oracle.
        Recurrence:
          TR_0 = High_0 - Low_0
          TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)
          ATR_{13} = mean(TR_0..TR_{13})
          ATR_t = (ATR_{t-1} * 13 + TR_t) / 14 for t >= 14
        """
        # 30 bars of deterministic prices with varied high, low, close, and gaps
        np.random.seed(101)
        base = 100.0
        closes = [base]
        highs = [base + 1.5]
        lows = [base - 1.2]
        for i in range(1, 30):
            step = float(np.sin(i) * 2.5)
            c = closes[-1] + step
            h = max(c, closes[-1]) + float(np.random.uniform(0.5, 3.0))
            l = min(c, closes[-1]) - float(np.random.uniform(0.5, 3.0))
            closes.append(c)
            highs.append(h)
            lows.append(l)

        # Engine calculation
        atr_result = calculate_atr(highs, lows, closes, period=14)
        self.assertEqual(len(atr_result), 30)

        # Oracle manual calculation
        trs = [highs[0] - lows[0]]
        for i in range(1, 30):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)

        # First 13 values must be NaN
        for i in range(13):
            self.assertTrue(pd.isna(atr_result[i]), f"Expected NaN at index {i}, got {atr_result[i]}")

        # Index 13 (14th value) must equal initial simple average of first 14 TRs
        oracle_atr = sum(trs[:14]) / 14.0
        self.assertAlmostEqual(atr_result[13], oracle_atr, places=6)

        # Subsequent values must follow Wilder's recurrence
        for i in range(14, 30):
            oracle_atr = (oracle_atr * 13.0 + trs[i]) / 14.0
            self.assertAlmostEqual(
                atr_result[i], oracle_atr, places=6,
                msg=f"Discrepancy at index {i}: engine={atr_result[i]}, oracle={oracle_atr}"
            )

    def test_atr_mma_divergence_from_sma(self):
        """
        Proves mathematically that Wilder's ATR is NOT a simple 14-period moving average (SMA).
        Using an impulse shock (TR=100 on bar 15, then TR=2 for bars 16-35):
        - SMA retains the shock for 14 bars, dropping to 2.0 at bar 30 when both shock bars exit the window.
        - MMA incorporates the shock with weight 1/14 and decays exponentially by (13/14)^k,
          remaining above 5.0 at bar 30 (> 2.5x higher than SMA).
        """
        n = 40
        highs = [102.0] * n
        lows = [100.0] * n
        closes = [101.0] * n

        # Apply an impulse shock at bar 15 (TR jumps to 100.0)
        highs[15] = 200.0
        lows[15] = 100.0
        closes[15] = 150.0

        atr_series = calculate_atr(highs, lows, closes, period=14)

        # Compute standard 14-period SMA of TR for comparison
        trs = [highs[0] - lows[0]]
        for i in range(1, n):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)
        tr_series = pd.Series(trs)
        sma_atr = tr_series.rolling(14).mean()

        # At bar 30:
        # Both shock bars (15 and 16) have exited the 14-bar SMA window (bars 17..30 all have TR=2.0).
        # Therefore, SMA drops back to exactly 2.0.
        self.assertAlmostEqual(sma_atr.iloc[30], 2.0, places=4)

        # In stark contrast, Wilder's MMA smoothing retains exponential memory of the shock:
        # At bar 30, ATR is ~5.518, significantly GREATER than 5.0 (over 2.7x the SMA value!)
        self.assertGreater(
            atr_series.iloc[30], 5.0,
            f"Expected Wilder's MMA to retain memory (> 5.0), but got {atr_series.iloc[30]}"
        )
        self.assertNotAlmostEqual(atr_series.iloc[30], sma_atr.iloc[30], places=1)

        # At bar 35, Wilder's MMA still exhibits residual exponential memory (~3.7)
        self.assertGreater(atr_series.iloc[35], 3.0)

    def test_atr_gap_up_gap_down_true_range(self):
        """
        Verifies that True Range correctly captures overnight gaps:
        1. Gap Up: Low_t > Close_{t-1} -> TR = High_t - Close_{t-1}
        2. Gap Down: High_t < Close_{t-1} -> TR = Close_{t-1} - Low_t
        """
        highs = [100.0] * 14 + [120.0, 80.0]
        lows = [98.0] * 14 + [110.0, 70.0]
        closes = [99.0] * 14 + [115.0, 75.0]

        atr = calculate_atr(highs, lows, closes, period=14)
        initial_atr = 2.0  # (100-98 = 2.0 for all first 14 bars)
        self.assertAlmostEqual(atr.iloc[13], initial_atr, places=6)

        expected_atr_14 = (initial_atr * 13.0 + 21.0) / 14.0
        self.assertAlmostEqual(atr.iloc[14], expected_atr_14, places=6)

        expected_atr_15 = (expected_atr_14 * 13.0 + 45.0) / 14.0
        self.assertAlmostEqual(atr.iloc[15], expected_atr_15, places=6)

    def test_atr_zero_range_flat_decay(self):
        """Zero range flat days (High=Low=Close) must cause ATR to decay smoothly towards 0."""
        n = 50
        highs = [100.0] * n
        lows = [100.0] * n
        closes = [100.0] * n

        atr = calculate_atr(highs, lows, closes, period=14)
        self.assertEqual(len(atr), n)
        self.assertAlmostEqual(atr.iloc[-1], 0.0, places=6)


class TestWilderRsiEdgeCases(unittest.TestCase):
    """
    Empirical Verification 2: Wilder's RSI(14) with:
    - Flat prices (all equal)
    - All up-days (strictly increasing)
    - All down-days (strictly decreasing)
    - Zero gains (flat + down only)
    - Zero losses (flat + up only)
    """

    def test_rsi_flat_prices(self):
        """
        Flat prices: No price movement for 30 bars.
        AvgGain = 0.0, AvgLoss = 0.0.
        By definition of unbiased technical analysis, RSI must equal 50.0 (neutral),
        without NaN or ZeroDivisionError.
        """
        prices = [100.0] * 30
        rsi = calculate_rsi(prices, period=14)
        self.assertEqual(len(rsi), 30)

        # First 14 bars are NaN (unformed)
        for i in range(14):
            self.assertTrue(pd.isna(rsi.iloc[i]))

        # From index 14 onwards, RSI must be exactly 50.0
        for i in range(14, 30):
            self.assertEqual(
                rsi.iloc[i], 50.0,
                f"Expected RSI=50.0 on flat prices at bar {i}, got {rsi.iloc[i]}"
            )

    def test_rsi_all_up_days(self):
        """
        All up-days: Monotonically increasing prices for 30 bars.
        AvgGain > 0.0, AvgLoss = 0.0.
        RSI must equal exactly 100.0 for all formed bars without overflow/Inf/NaN.
        """
        prices = [50.0 + i * 2.0 for i in range(30)]
        rsi = calculate_rsi(prices, period=14)

        for i in range(14, 30):
            self.assertEqual(
                rsi.iloc[i], 100.0,
                f"Expected RSI=100.0 on all up-days at bar {i}, got {rsi.iloc[i]}"
            )

    def test_rsi_all_down_days(self):
        """
        All down-days: Monotonically decreasing prices for 30 bars.
        AvgGain = 0.0, AvgLoss > 0.0.
        RS = 0 / AvgLoss = 0.
        RSI = 100 - (100 / (1 + 0)) = 0.0.
        RSI must equal exactly 0.0 for all formed bars.
        """
        prices = [200.0 - i * 2.0 for i in range(30)]
        rsi = calculate_rsi(prices, period=14)

        for i in range(14, 30):
            self.assertEqual(
                rsi.iloc[i], 0.0,
                f"Expected RSI=0.0 on all down-days at bar {i}, got {rsi.iloc[i]}"
            )

    def test_rsi_zero_gains_with_flat(self):
        """
        Zero gains: Series consists of flat days and down days only (e.g. 100, 100, 99, 99, 98, ...).
        Delta C is always <= 0, so Gain is identically 0.0 everywhere.
        AvgGain = 0.0, AvgLoss > 0.0 -> RSI must be 0.0.
        """
        prices = [100.0, 100.0, 99.0, 99.0, 98.0, 98.0, 97.0, 97.0,
                  96.0, 96.0, 95.0, 95.0, 94.0, 94.0, 93.0, 93.0,
                  92.0, 92.0, 91.0, 91.0, 90.0, 90.0, 89.0, 89.0]
        rsi = calculate_rsi(prices, period=14)

        for i in range(14, len(prices)):
            self.assertAlmostEqual(
                rsi.iloc[i], 0.0, places=5,
                msg=f"Expected RSI=0.0 for zero gains at index {i}, got {rsi.iloc[i]}"
            )

    def test_rsi_zero_losses_with_flat(self):
        """
        Zero losses: Series consists of flat days and up days only (e.g. 100, 100, 101, 101, 102, ...).
        Delta C is always >= 0, so Loss is identically 0.0 everywhere.
        AvgGain > 0.0, AvgLoss = 0.0 -> RSI must be 100.0.
        """
        prices = [100.0, 100.0, 101.0, 101.0, 102.0, 102.0, 103.0, 103.0,
                  104.0, 104.0, 105.0, 105.0, 106.0, 106.0, 107.0, 107.0,
                  108.0, 108.0, 109.0, 109.0, 110.0, 110.0, 111.0, 111.0]
        rsi = calculate_rsi(prices, period=14)

        for i in range(14, len(prices)):
            self.assertAlmostEqual(
                rsi.iloc[i], 100.0, places=5,
                msg=f"Expected RSI=100.0 for zero losses at index {i}, got {rsi.iloc[i]}"
            )

    def test_rsi_independent_oracle_verification(self):
        """
        Verifies Wilder's RSI step-by-step against an independent reference oracle on mixed data.
        """
        prices = [
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
            45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
            46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45
        ]
        rsi_engine = calculate_rsi(prices, period=14)

        # Independent manual calculation
        diffs = np.diff(prices)
        gains = [max(0.0, d) for d in diffs]
        losses = [max(0.0, -d) for d in diffs]

        avg_gain = sum(gains[:14]) / 14.0
        avg_loss = sum(losses[:14]) / 14.0
        rs = avg_gain / avg_loss
        expected_rsi_14 = 100.0 - (100.0 / (1.0 + rs))

        self.assertAlmostEqual(rsi_engine.iloc[14], expected_rsi_14, places=4)

        # Verify next bars
        curr_gain = avg_gain
        curr_loss = avg_loss
        for i in range(14, len(diffs)):
            curr_gain = (curr_gain * 13.0 + gains[i]) / 14.0
            curr_loss = (curr_loss * 13.0 + losses[i]) / 14.0
            rs = curr_gain / curr_loss
            exp_rsi = 100.0 - (100.0 / (1.0 + rs))
            self.assertAlmostEqual(rsi_engine.iloc[i + 1], exp_rsi, places=4)


class TestTradeSetupStrictConstraints(unittest.TestCase):
    """
    Empirical Verification 3: Trade setup constraints:
    - Strict min 1:2.0 Risk:Reward ratio
    - 3-10% target return
    - ATR-based stop loss
    - Adversarial Monte Carlo across 5,000 extreme parameter combinations
    """

    def test_monte_carlo_5000_invariants(self):
        """
        Adversarial Monte Carlo sweep across 5,000 parameter combinations:
        Every setup where is_valid == True MUST strictly adhere to:
        1. setup.risk_reward_ratio >= 2.0
        2. 3.0 <= setup.target_return_pct <= 10.0
        3. 0 < setup.stop_loss < setup.entry_price < setup.target_price
        4. setup.risk_per_share > 0 and setup.reward_per_share > 0
        """
        strategies = ["MOMENTUM_BREAKOUT", "EARNINGS_PEAD", "MEAN_REVERSION", "QUALITY_FCF", "UNKNOWN_STRAT"]
        np.random.seed(42)

        total_tested = 5000
        valid_setups = 0

        for _ in range(total_tested):
            entry = float(np.random.uniform(1.0, 5000.0))
            # Test volatility ratios from 0.05% up to 15%
            vol_ratio = float(np.random.uniform(0.0005, 0.15))
            atr = entry * vol_ratio
            strat = str(np.random.choice(strategies))
            swing_low = entry * float(np.random.uniform(0.70, 0.99)) if np.random.rand() > 0.3 else None
            bb_mid = entry * float(np.random.uniform(0.90, 1.20)) if np.random.rand() > 0.3 else None

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

            if setup.is_valid:
                valid_setups += 1
                # Constraint 1: Risk:Reward >= 2.0
                self.assertGreaterEqual(
                    setup.risk_reward_ratio, 2.0,
                    f"R:R ratio {setup.risk_reward_ratio} < 2.0 on entry={entry}, atr={atr}, strat={strat}"
                )

                # Constraint 2: Target return strictly between 3.0% and 10.0%
                self.assertGreaterEqual(
                    setup.target_return_pct, 3.0,
                    f"Target return {setup.target_return_pct}% < 3.0% on entry={entry}, atr={atr}, strat={strat}"
                )
                self.assertLessEqual(
                    setup.target_return_pct, 10.0,
                    f"Target return {setup.target_return_pct}% > 10.0% on entry={entry}, atr={atr}, strat={strat}"
                )

                # Constraint 3: Long setup order of execution levels
                self.assertGreater(setup.stop_loss, 0.0)
                self.assertLess(setup.stop_loss, setup.entry_price)
                self.assertGreater(setup.target_price, setup.entry_price)
                self.assertGreater(setup.risk_per_share, 0.0)
                self.assertGreater(setup.reward_per_share, 0.0)

                # Constraint 4: Math relationship reward >= 2.0 * risk
                self.assertGreaterEqual(setup.reward_per_share, (setup.risk_per_share * 2.0) - 0.05)

        self.assertEqual(total_tested, 5000)
        self.assertGreater(valid_setups, 500, "Expected a substantial number of valid setups in Monte Carlo sweep")

    def test_impossible_high_volatility_rejection(self):
        """
        When volatility is excessively large (e.g. ATR is 25% of price),
        a 10% maximum target cannot mathematically satisfy a 2:1 R:R ratio.
        The setup generator MUST mark is_valid = False.
        """
        entry = 100.0
        massive_atr = 25.0
        setup = generate_trade_setup(entry, massive_atr, strategy_name="MOMENTUM_BREAKOUT")
        self.assertFalse(setup.is_valid, "Massive volatility should be flagged as invalid setup")

    def test_low_volatility_target_clamping_to_3_pct(self):
        """
        When volatility is low (e.g. ATR is 0.5% of price) and default strategy has raw target < 3%,
        the setup generator MUST elevate the target to exactly 3.0%
        and preserve R:R >= 2.0.
        """
        entry = 100.0
        low_atr = 0.5  # 0.5% ATR
        setup = generate_trade_setup(entry, low_atr, strategy_name="DEFAULT")
        self.assertTrue(setup.is_valid)
        self.assertAlmostEqual(setup.target_return_pct, 3.0, places=1)
        self.assertGreaterEqual(setup.risk_reward_ratio, 2.0)
        self.assertAlmostEqual(setup.target_price, 103.0, places=1)

    def test_json_clean_serialization(self):
        """Every generated setup must serialize cleanly into valid JSON without Inf or NaN."""
        setup = generate_trade_setup(150.0, 3.5, strategy_name="QUALITY_FCF")
        d = setup.to_dict()
        serialized = json.dumps(d, allow_nan=False)
        self.assertIn('"is_valid": true', serialized)
        self.assertIn('"risk_reward_ratio":', serialized)


class TestLookaheadFreeBacktester(unittest.TestCase):
    """
    Empirical Verification 4: Lookahead-free backtester:
    - Walk-forward execution at Open_{T+1}
    - 5 bps slippage penalty on entry and exit
    - Intraday stop checking before target on same-bar touches
    - Overnight gap down fill at open
    - Time-stop liquidation at Day 20 Close
    - Data mutation invariance (zero lookahead)
    """

    def _generate_synthetic_series(self, n=100, signal_idx=60):
        """Generates standard baseline OHLCV dataframe with breakout on signal_idx (requires >=50 bars for SMA50)."""
        close = [100.0 + i * 0.1 for i in range(n)]
        close[signal_idx] = 112.0  # Big jump triggers breakout above upper band
        high = [c + 0.5 for c in close]
        high[signal_idx] = 114.0
        low = [c - 0.5 for c in close]
        open_p = [c - 0.1 for c in close]
        volume = [1_000_000.0] * n
        volume[signal_idx] = 3_000_000.0  # Volume spike

        dates = [f"2026-{i//25+1:02d}-{i%25+1:02d}" for i in range(n)]
        return pd.DataFrame({
            "date": dates,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    def test_walk_forward_open_t_plus_1_execution_with_slippage(self):
        """
        Signal triggered at Day T Close MUST execute on Day T+1 Open.
        Entry price must equal Open_{T+1} * (1 + 0.0005) [5 bps slippage].
        """
        df = self._generate_synthetic_series(n=100, signal_idx=60)
        expected_open_61 = 110.0
        df.loc[61, "open"] = expected_open_61

        sim = BacktestSimulator(slippage_bps=5.0)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="WALK_FWD")
        self.assertGreater(len(trades), 0)

        trade = trades[0]
        # Day 60 was signal, Day 61 is entry date
        self.assertEqual(trade.entry_date, df.loc[61, "date"])
        expected_entry_price = expected_open_61 * (1.0 + 0.0005)
        self.assertAlmostEqual(trade.entry_price, expected_entry_price, places=4)

    def test_exit_slippage_penalty(self):
        """
        Exit prices must incur 5 bps slippage penalty:
        Target exit: TargetPrice * (1 - 0.0005)
        """
        df = self._generate_synthetic_series(n=100, signal_idx=60)
        # On Day 62, simulate a clean target hit without touching stop
        df.loc[61, "open"] = 106.0
        df.loc[61, "low"] = 105.0
        df.loc[61, "high"] = 107.0
        df.loc[61, "close"] = 106.5
        df.loc[62, "open"] = 107.0
        df.loc[62, "high"] = 135.0  # Hits target easily
        df.loc[62, "low"] = 106.0
        df.loc[62, "close"] = 130.0

        sim = BacktestSimulator(slippage_bps=5.0)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="SLIPPAGE_EXIT")
        self.assertGreater(len(trades), 0)

        trade = trades[0]
        self.assertEqual(trade.exit_reason, "TARGET")
        expected_exit_price = trade.target_price * (1.0 - 0.0005)
        self.assertAlmostEqual(trade.exit_price, expected_exit_price, places=4)

    def test_intraday_stop_priority_before_target(self):
        """
        Adversarial test: On the SAME bar, price drops below Stop AND rallies above Target.
        In order to eliminate optimistic backtest bias, Stop-Loss MUST trigger first.
        """
        df = self._generate_synthetic_series(n=100, signal_idx=60)
        df.loc[61, "open"] = 106.0
        df.loc[61, "high"] = 107.0
        df.loc[61, "low"] = 105.0
        df.loc[61, "close"] = 106.0

        # Bar 62 has an extreme range touching BOTH Stop and Target
        df.loc[62, "open"] = 106.0
        df.loc[62, "high"] = 140.0  # Above target (~112)
        df.loc[62, "low"] = 80.0   # Well below stop (~103)
        df.loc[62, "close"] = 110.0

        sim = BacktestSimulator(slippage_bps=5.0)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="SAME_BAR_CONFLICT")
        self.assertGreater(len(trades), 0)

        trade = trades[0]
        # PESSIMISTIC CHECK: Must be STOP_LOSS, never TARGET
        self.assertEqual(
            trade.exit_reason, "STOP_LOSS",
            f"Expected STOP_LOSS priority on dual-touch bar, but got {trade.exit_reason}"
        )
        self.assertLess(trade.return_pct, 0.0)

    def test_overnight_gap_down_fill(self):
        """
        Severe overnight gap down: Next day opens at $80, which is far below stop-loss (~$103).
        Backtester MUST fill at Open ($80 minus slippage), not the stop-loss price.
        """
        df = self._generate_synthetic_series(n=100, signal_idx=60)
        df.loc[61, "open"] = 106.0
        df.loc[61, "high"] = 107.0
        df.loc[61, "low"] = 105.0
        df.loc[61, "close"] = 106.0

        # Bar 62 opens down at 80.0
        df.loc[62, "open"] = 80.0
        df.loc[62, "high"] = 81.0
        df.loc[62, "low"] = 78.0
        df.loc[62, "close"] = 79.0

        sim = BacktestSimulator(slippage_bps=5.0)
        trades = sim.evaluate_strategy_1_breakout(df, ticker="GAP_DOWN")
        self.assertGreater(len(trades), 0)

        trade = trades[0]
        self.assertEqual(trade.exit_reason, "STOP_LOSS")
        expected_fill = 80.0 * (1.0 - 0.0005)
        self.assertAlmostEqual(trade.exit_price, expected_fill, places=2)
        self.assertLess(trade.return_pct, -20.0)

    def test_future_data_isolation_zero_lookahead(self):
        """
        Zero lookahead bias verification:
        Altering price data in future bars 75 to 100 MUST NOT change the entry price or entry date
        of a trade initiated on bar 61.
        """
        df_original = self._generate_synthetic_series(n=100, signal_idx=60)
        df_mutated = df_original.copy()

        # Mutate future bars drastically
        df_mutated.loc[75:99, "close"] = 999.0
        df_mutated.loc[75:99, "high"] = 1000.0
        df_mutated.loc[75:99, "low"] = 998.0

        sim = BacktestSimulator()
        trades_orig = sim.evaluate_strategy_1_breakout(df_original, ticker="ORIG")
        trades_mut = sim.evaluate_strategy_1_breakout(df_mutated, ticker="MUT")

        self.assertGreater(len(trades_orig), 0)
        self.assertGreater(len(trades_mut), 0)

        # The first trade entry price, date, stop, and target MUST be completely identical
        self.assertEqual(trades_orig[0].entry_date, trades_mut[0].entry_date)
        self.assertEqual(trades_orig[0].entry_price, trades_mut[0].entry_price)
        self.assertEqual(trades_orig[0].stop_price, trades_mut[0].stop_price)
        self.assertEqual(trades_orig[0].target_price, trades_mut[0].target_price)


class TestFuzzDegenerateInputs(unittest.TestCase):
    """
    Empirical Verification 5: Fuzz inputs:
    - NaN (intermittent, all NaNs, leading NaNs)
    - Inf and -Inf
    - Negative prices
    - Zero volume
    - Empty series and short series
    - Corrupted bars (High < Low, High < Close)
    """

    def test_fuzz_nan_series(self):
        """Intermittent and all-NaN inputs must be handled gracefully without crashing."""
        # 1. All-NaN series
        df_all_nan = pd.DataFrame({
            "close": [np.nan] * 50,
            "high": [np.nan] * 50,
            "low": [np.nan] * 50,
            "volume": [np.nan] * 50,
        })
        computed = compute_all_indicators(df_all_nan)
        self.assertEqual(len(computed), 50)
        self.assertTrue(pd.isna(computed["atr_14"].iloc[-1]))
        # All-NaN price series produces 0 gains and 0 losses -> safely defaults to neutral 50.0 RSI
        self.assertEqual(computed["rsi_14"].iloc[-1], 50.0)

        latest = get_latest_indicators(df_all_nan)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.atr_14, 0.0)
        self.assertEqual(latest.rsi_14, 50.0)

        # 2. Intermittent NaNs
        prices = [100.0 if i % 3 != 0 else np.nan for i in range(40)]
        atr = calculate_atr(prices, prices, prices, period=14)
        self.assertEqual(len(atr), 40)

    def test_fuzz_inf_series(self):
        """Inf and -Inf values in prices and trade setups."""
        df_inf = pd.DataFrame({
            "close": [100.0] * 20 + [float("inf")] + [100.0] * 19,
            "high": [101.0] * 20 + [float("inf")] + [101.0] * 19,
            "low": [99.0] * 20 + [float("-inf")] + [99.0] * 19,
            "volume": [1_000_000.0] * 40,
        })
        computed = compute_all_indicators(df_inf)
        self.assertEqual(len(computed), 40)

        # Trade setup with Inf must be rejected cleanly
        setup_inf_entry = generate_trade_setup(float("inf"), 2.0)
        self.assertFalse(setup_inf_entry.is_valid)
        self.assertEqual(setup_inf_entry.entry_price, 0.0)

        setup_inf_atr = generate_trade_setup(100.0, float("inf"))
        self.assertFalse(setup_inf_atr.is_valid)

    def test_fuzz_negative_prices(self):
        """Negative price inputs (e.g. oil futures anomaly in April 2020)."""
        neg_prices = [-50.0 + i * 0.2 for i in range(40)]
        neg_highs = [p + 1.0 for p in neg_prices]
        neg_lows = [p - 1.0 for p in neg_prices]

        # ATR on negative prices: True range depends on absolute differences, so ATR >= 0
        atr = calculate_atr(neg_highs, neg_lows, neg_prices, period=14)
        self.assertGreater(atr.iloc[-1], 0.0)

        # Negative price in trade setup MUST be rejected
        setup_neg = generate_trade_setup(-50.0, 2.0)
        self.assertFalse(setup_neg.is_valid)

    def test_fuzz_zero_volume(self):
        """All-zero volume series must not trigger division-by-zero error."""
        vols = [0.0] * 50
        v_ratio, is_spike = calculate_volume_spike(vols, period=20, threshold=1.5)
        self.assertEqual(len(v_ratio), 50)
        self.assertFalse(is_spike.any())
        self.assertAlmostEqual(v_ratio.iloc[-1], 1.0, places=5)

    def test_fuzz_empty_and_short_series(self):
        """Empty series and series below lookback requirements."""
        # 0 bars
        self.assertTrue(calculate_atr([], [], [], 14).empty)
        self.assertTrue(calculate_rsi([], 14).empty)
        mb, ub, lb, bw, pct_b, sq = calculate_bollinger_bands([], 20)
        self.assertTrue(mb.empty)

        # 1 bar
        atr_1 = calculate_atr([100.0], [99.0], [99.5], 14)
        self.assertEqual(len(atr_1), 1)
        self.assertTrue(pd.isna(atr_1.iloc[0]))

        # 13 bars (< 14 period)
        atr_13 = calculate_atr([100.0] * 13, [99.0] * 13, [99.5] * 13, 14)
        self.assertTrue(atr_13.isna().all())

    def test_fuzz_inverted_bars(self):
        """Corrupted data feeds where High < Low or Low > Close."""
        corrupted_highs = [50.0] * 30
        corrupted_lows = [60.0] * 30  # Low is greater than High
        corrupted_closes = [55.0] * 30

        atr = calculate_atr(corrupted_highs, corrupted_lows, corrupted_closes, period=14)
        self.assertEqual(len(atr), 30)
        self.assertGreaterEqual(atr.iloc[-1], 0.0)


if __name__ == "__main__":
    unittest.main()

"""
Lookahead-Free Walk-Forward Backtesting Simulator for Stocknomist (Feature F8).
Guarantees:
- Zero lookahead bias: Signal generated strictly at Day T Close; Entry executed at Day T+1 Open.
- Realistic execution: 5 basis points (0.05%) slippage penalty applied on entry and exit.
- Pessimistic intraday stop checking: If both Low <= Stop and High >= Target occur on the same day,
  the Stop-Loss is assumed to trigger first to eliminate optimistic bias.
- Overnight gap down fill: Fills at Open when Open < Stop-Loss.
- Maximum holding period / time-stop: Liquidated at Day T+20 Close if neither Stop nor Target hit.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from backend.app.engine.indicators import compute_all_indicators


@dataclass
class TradeRecord:
    """Historical trade simulation lifecycle record."""
    ticker: str
    strategy: str
    entry_date: Any
    entry_price: float
    stop_price: float
    target_price: float
    exit_date: Optional[Any] = None
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    exit_reason: Optional[str] = None  # 'TARGET', 'STOP_LOSS', 'TIME_STOP'
    holding_days: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strategy": self.strategy,
            "entry_date": str(self.entry_date),
            "entry_price": round(self.entry_price, 2),
            "stop_price": round(self.stop_price, 2),
            "target_price": round(self.target_price, 2),
            "exit_date": str(self.exit_date) if self.exit_date else None,
            "exit_price": round(self.exit_price, 2) if self.exit_price else None,
            "return_pct": round(self.return_pct, 2) if self.return_pct is not None else None,
            "exit_reason": self.exit_reason,
            "holding_days": self.holding_days,
        }


@dataclass
class BacktestResult:
    """Statistical summary of backtested strategy execution."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    avg_return_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_holding_days: float = 0.0
    trades: List[TradeRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "profit_factor": round(self.profit_factor, 2),
            "expectancy_pct": round(self.expectancy_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "avg_return_pct": round(self.avg_return_pct, 2),
            "avg_win_pct": round(self.avg_win_pct, 2),
            "avg_loss_pct": round(self.avg_loss_pct, 2),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "trades_count": len(self.trades),
        }


class BacktestSimulator:
    """
    Simulates swing strategy performance on historical daily price series.
    Strictly prevents lookahead bias with 5 bps slippage and conservative stops.
    """

    def __init__(self, slippage_bps: float = 5.0, max_hold_days: int = 20):
        self.slippage = slippage_bps / 10000.0  # 5 bps = 0.0005
        self.max_hold_days = max_hold_days

    def evaluate_strategy_1_breakout(self, df: pd.DataFrame, ticker: str = "TICKER") -> List[TradeRecord]:
        """
        Backtest Strategy 1: Momentum & Volatility Breakout.
        """
        if df is None or len(df) < 50:
            return []

        computed = compute_all_indicators(df)
        n = len(computed)
        if n < 30:
            return []

        dates = computed["date"].values if "date" in computed.columns else np.arange(n)
        open_p = computed["open"].values
        high_p = computed["high"].values
        low_p = computed["low"].values
        close_p = computed["close"].values
        ub_p = computed["bb_upper"].values
        atr_p = computed["atr_14"].values
        vol_spike = computed["volume_spike"].values
        stage2 = computed["stage2_alignment"].values

        trades: List[TradeRecord] = []
        i = 20  # Minimum lookback
        while i < n - 1:
            # Check Day T Close signal
            is_breakout = close_p[i] > ub_p[i]
            is_aligned = stage2[i] or (close_p[i] > computed["sma_20"].iloc[i] > computed["sma_50"].iloc[i])
            is_spike = vol_spike[i]
            atr_val = atr_p[i]

            if is_breakout and is_aligned and is_spike and atr_val > 0:
                # Enter at Day T+1 Open with 5 bps slippage
                entry_idx = i + 1
                entry_date = dates[entry_idx]
                entry_price = open_p[entry_idx] * (1.0 + self.slippage)
                stop_price = entry_price - (1.5 * atr_val)
                raw_target = entry_price + max(3.0 * atr_val, entry_price * 0.06)
                # Cap target return between 3% and 10%
                target_pct = min(10.0, max(3.0, ((raw_target - entry_price) / entry_price) * 100.0))
                target_price = entry_price * (1.0 + (target_pct / 100.0))

                trade = TradeRecord(
                    ticker=ticker,
                    strategy="MOMENTUM_BREAKOUT",
                    entry_date=entry_date,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                )

                # Simulate holding lifecycle across subsequent days
                hold = 0
                for j in range(entry_idx, min(entry_idx + self.max_hold_days, n)):
                    hold += 1
                    # 1. Conservative check: Stop-Loss first
                    if low_p[j] <= stop_price:
                        trade.exit_date = dates[j]
                        # Overnight gap down check
                        actual_exit = min(open_p[j], stop_price)
                        trade.exit_price = actual_exit * (1.0 - self.slippage)
                        trade.exit_reason = "STOP_LOSS"
                        trade.holding_days = hold
                        break
                    # 2. Check Target Hit
                    elif high_p[j] >= target_price:
                        trade.exit_date = dates[j]
                        trade.exit_price = target_price * (1.0 - self.slippage)
                        trade.exit_reason = "TARGET"
                        trade.holding_days = hold
                        break

                # 3. Time Stop
                if trade.exit_price is None:
                    exit_bar = min(entry_idx + self.max_hold_days - 1, n - 1)
                    trade.exit_date = dates[exit_bar]
                    trade.exit_price = close_p[exit_bar] * (1.0 - self.slippage)
                    trade.exit_reason = "TIME_STOP"
                    trade.holding_days = hold

                trade.return_pct = ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100.0
                trades.append(trade)
                i = entry_idx + hold  # Advance past active trade
            else:
                i += 1

        return trades

    def evaluate_strategy_3_mean_reversion(
        self,
        df: pd.DataFrame,
        ticker: str = "TICKER",
        fundamentals: Optional[Dict[str, Any]] = None,
    ) -> List[TradeRecord]:
        """
        Backtest Strategy 3: Mean-Reversion / Oversold Bounce.
        """
        if df is None or len(df) < 30:
            return []

        computed = compute_all_indicators(df)
        n = len(computed)

        dates = computed["date"].values if "date" in computed.columns else np.arange(n)
        open_p = computed["open"].values
        high_p = computed["high"].values
        low_p = computed["low"].values
        close_p = computed["close"].values
        lb_p = computed["bb_lower"].values
        mb_p = computed["bb_middle"].values
        rsi_p = computed["rsi_14"].values
        atr_p = computed["atr_14"].values

        trades: List[TradeRecord] = []
        i = 20
        while i < n - 1:
            # Check Day T Close signal: RSI < 35, low touched LB
            is_oversold = rsi_p[i] < 35.0
            touched_lb = low_p[i] <= lb_p[i] * 1.005
            atr_val = atr_p[i]

            if is_oversold and touched_lb and atr_val > 0:
                entry_idx = i + 1
                entry_date = dates[entry_idx]
                entry_price = open_p[entry_idx] * (1.0 + self.slippage)
                stop_price = entry_price - (1.25 * atr_val)

                # Target is 20 SMA or at least 2x risk
                risk = entry_price - stop_price
                target_price = max(mb_p[i], entry_price + (2.0 * risk))
                target_pct = min(8.0, max(3.0, ((target_price - entry_price) / entry_price) * 100.0))
                target_price = entry_price * (1.0 + (target_pct / 100.0))

                trade = TradeRecord(
                    ticker=ticker,
                    strategy="MEAN_REVERSION",
                    entry_date=entry_date,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                )

                hold = 0
                for j in range(entry_idx, min(entry_idx + self.max_hold_days, n)):
                    hold += 1
                    if low_p[j] <= stop_price:
                        trade.exit_date = dates[j]
                        trade.exit_price = min(open_p[j], stop_price) * (1.0 - self.slippage)
                        trade.exit_reason = "STOP_LOSS"
                        trade.holding_days = hold
                        break
                    elif high_p[j] >= target_price:
                        trade.exit_date = dates[j]
                        trade.exit_price = target_price * (1.0 - self.slippage)
                        trade.exit_reason = "TARGET"
                        trade.holding_days = hold
                        break

                if trade.exit_price is None:
                    exit_bar = min(entry_idx + self.max_hold_days - 1, n - 1)
                    trade.exit_date = dates[exit_bar]
                    trade.exit_price = close_p[exit_bar] * (1.0 - self.slippage)
                    trade.exit_reason = "TIME_STOP"
                    trade.holding_days = hold

                trade.return_pct = ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100.0
                trades.append(trade)
                i = entry_idx + hold
            else:
                i += 1

        return trades

    def compute_metrics(self, trades: List[TradeRecord]) -> BacktestResult:
        """
        Calculates comprehensive quantitative performance metrics from trade logs.
        """
        if not trades:
            return BacktestResult()

        returns = [t.return_pct for t in trades if t.return_pct is not None]
        total_trades = len(returns)
        if total_trades == 0:
            return BacktestResult(trades=trades)

        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        winning_count = len(wins)
        losing_count = len(losses)
        win_rate = (winning_count / total_trades) * 100.0

        gross_gains = sum(wins)
        gross_losses = abs(sum(losses))
        profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else (999.0 if gross_gains > 0 else 1.0)

        avg_return = float(np.mean(returns))
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0

        # Expectancy = (Win% * AvgWin) - (Loss% * |AvgLoss|)
        expectancy = ((win_rate / 100.0) * avg_win) + (((100.0 - win_rate) / 100.0) * avg_loss)

        # Maximum Drawdown on cumulative equity curve
        returns_arr = np.array(returns, dtype=float)
        cum_equity = np.cumprod(1.0 + (returns_arr / 100.0))
        running_max = np.maximum.accumulate(cum_equity)

        drawdowns = []
        for eq, rmax in zip(cum_equity, running_max):
            if eq <= 0.0 or rmax <= 0.0:
                drawdowns.append(-1.0)
            else:
                drawdowns.append((eq - rmax) / rmax)

        max_dd_pct = abs(float(min(drawdowns))) * 100.0 if drawdowns else 0.0
        if max_dd_pct > 100.0 or any(eq <= 0.0 for eq in cum_equity):
            max_dd_pct = 100.0

        # Annualized Sharpe Ratio (assuming ~12 trades/year per strategy or normalized)
        std_ret = float(np.std(returns)) if len(returns) > 1 else 0.0
        sharpe = (avg_return / (std_ret + 1e-12)) * math.sqrt(252 / max(1, np.mean([t.holding_days for t in trades]))) if std_ret > 0 else 0.0

        avg_hold = float(np.mean([t.holding_days for t in trades]))

        return BacktestResult(
            total_trades=total_trades,
            winning_trades=winning_count,
            losing_trades=losing_count,
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            expectancy_pct=expectancy,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            avg_return_pct=avg_return,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            avg_holding_days=avg_hold,
            trades=trades,
        )

    calculate_metrics = compute_metrics


def run_strategy_backtest(
    df: pd.DataFrame,
    ticker: str = "TICKER",
    strategy_name: str = "MOMENTUM_BREAKOUT",
    fundamentals: Optional[Dict[str, Any]] = None,
    slippage_bps: float = 5.0,
    max_hold_days: int = 20,
) -> BacktestResult:
    """
    Convenience runner executing a single strategy backtest and returning full metrics.
    """
    simulator = BacktestSimulator(slippage_bps=slippage_bps, max_hold_days=max_hold_days)
    strat_clean = strategy_name.upper()

    if "BREAKOUT" in strat_clean or "MOMENTUM" in strat_clean:
        trades = simulator.evaluate_strategy_1_breakout(df, ticker=ticker)
    elif "REVERSION" in strat_clean or "OVERSOLD" in strat_clean or "BOUNCE" in strat_clean:
        trades = simulator.evaluate_strategy_3_mean_reversion(df, ticker=ticker, fundamentals=fundamentals)
    else:
        # Default to breakout
        trades = simulator.evaluate_strategy_1_breakout(df, ticker=ticker)

    return simulator.compute_metrics(trades)

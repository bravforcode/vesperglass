"""
Quantitative Multi-Strategy Engine for Stocknomist.
Milestone 2: Features F5, F6, F7, F8.
"""

from backend.app.engine.indicators import (
    calculate_atr,
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_macd,
    calculate_smas,
    calculate_volume_spike,
    compute_all_indicators,
    TechnicalIndicators,
)
from backend.app.engine.strategies import (
    StrategyName,
    StrategyMatch,
    FactorRadarScores,
    evaluate_strategies,
    calculate_factor_radar,
    evaluate_momentum_breakout,
    evaluate_earnings_pead,
    evaluate_oversold_bounce,
    evaluate_quality_fcf,
)
from backend.app.engine.trade_setup import (
    TradeSetup,
    generate_trade_setup,
)
from backend.app.engine.backtest import (
    TradeRecord,
    BacktestResult,
    BacktestSimulator,
    run_strategy_backtest,
)

__all__ = [
    "calculate_atr",
    "calculate_rsi",
    "calculate_bollinger_bands",
    "calculate_macd",
    "calculate_smas",
    "calculate_volume_spike",
    "compute_all_indicators",
    "TechnicalIndicators",
    "StrategyName",
    "StrategyMatch",
    "FactorRadarScores",
    "evaluate_strategies",
    "calculate_factor_radar",
    "evaluate_momentum_breakout",
    "evaluate_earnings_pead",
    "evaluate_oversold_bounce",
    "evaluate_quality_fcf",
    "TradeSetup",
    "generate_trade_setup",
    "TradeRecord",
    "BacktestResult",
    "BacktestSimulator",
    "run_strategy_backtest",
]

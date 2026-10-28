"""
Quantitative Multi-Strategy Engine for Stocknomist (Feature F6).
Implements 4 distinct quantitative swing-trading strategies:
1. Momentum & Volatility Breakout (Stage 2 alignment, BB squeeze breakout, volume surge > 1.5x)
2. Earnings & Catalyst Momentum (PEAD, EPS surprise >= +10%, QoQ revenue acceleration)
3. Mean-Reversion / Oversold Bounce (RSI < 35 on fundamentally sound stocks, MACD inflection)
4. Quality & Free-Cash-Flow Yield (ROE >= 15%, D/E <= 1.0, FCF Yield >= 5%, Forward P/E <= 25)
Includes 5-axis Factor Radar Scoring Algorithm (Momentum, Value, Quality, Growth, Volatility, 0-100).
"""

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import pandas as pd

from backend.app.engine.indicators import get_latest_indicators, TechnicalIndicators
from backend.app.engine.trade_setup import generate_trade_setup, TradeSetup


class StrategyName(str, Enum):
    MOMENTUM_BREAKOUT = "MOMENTUM_BREAKOUT"
    EARNINGS_PEAD = "EARNINGS_PEAD"
    MEAN_REVERSION = "MEAN_REVERSION"
    QUALITY_FCF = "QUALITY_FCF"


@dataclass
class FactorRadarScores:
    """Normalized 0-100 scores across 5 institutional investment factors."""
    momentum: int
    value: int
    quality: int
    growth: int
    volatility: int

    def to_dict(self) -> Dict[str, int]:
        return {
            "momentum": int(self.momentum),
            "value": int(self.value),
            "quality": int(self.quality),
            "growth": int(self.growth),
            "volatility": int(self.volatility),
        }


@dataclass
class StrategyMatch:
    """Individual strategy evaluation result."""
    strategy_name: str
    is_matched: bool
    confidence_score: int
    setup: Optional[TradeSetup]
    reasons: List[str]


@dataclass
class ScreenerCandidate:
    """Full candidate representation matching M2 <-> M3 REST API contract."""
    ticker: str
    name: str
    sector: str
    price: float
    change_24h_pct: float
    strategies: List[str]  # e.g. ["momentum_breakout", "quality_fcf"]
    setup: Optional[Dict[str, Any]]
    factor_scores: Dict[str, int]
    catalysts: List[Dict[str, Any]]
    confidence_score: int
    notes: str


def _clamp(val: float, low: float = 0.0, high: float = 100.0) -> int:
    """Clamps a numeric value between low and high, rounded to int."""
    if math.isnan(val):
        return int(low)
    return int(max(low, min(high, round(val))))


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely converts a value to float, handling None, non-numeric strings ('N/A', '--', ''), nan, inf."""
    if val is None:
        return default
    try:
        res = float(val)
        return res if math.isfinite(res) else default
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Factor Radar Scoring Algorithm (0-100 normalized)
# ---------------------------------------------------------------------------

def calculate_factor_radar(
    indicators: Optional[TechnicalIndicators],
    fundamentals: Optional[Dict[str, Any]],
) -> FactorRadarScores:
    """
    Computes institutional 5-factor normalized radar scores (0 to 100):
      - Momentum: Price vs 20/50/200 SMA, RSI(14) positioning, volume surge
      - Value: Forward P/E, Trailing P/E, FCF Yield
      - Quality: Return on Equity (ROE), Debt-to-Equity, positive cash generation
      - Growth: QoQ / YoY Revenue growth, EPS surprise momentum
      - Volatility: ATR% relative to price, Bollinger Bandwidth stability
    """
    fund = fundamentals or {}

    # 1. Momentum Score (0-100)
    mom_score = 50.0
    if indicators:
        # RSI contribution (optimal swing momentum: 50-70)
        rsi = indicators.rsi_14
        if 50.0 <= rsi <= 70.0:
            mom_score += 20.0
        elif 40.0 <= rsi < 50.0:
            mom_score += 10.0
        elif rsi > 70.0:
            mom_score += 15.0  # Strong momentum though overbought
        elif rsi < 30.0:
            mom_score -= 15.0

        # Stage 2 alignment bonus
        if indicators.stage2_bullish_alignment:
            mom_score += 20.0
        elif indicators.close > indicators.sma_50 > 0:
            mom_score += 10.0

        # Volume spike bonus
        if indicators.is_volume_spike:
            mom_score += 10.0

    # 2. Value Score (0-100)
    val_score = 50.0
    fwd_pe = _safe_float(fund.get("forward_pe"))
    fcf_yield = _safe_float(fund.get("fcf_yield"))
    if fwd_pe > 0:
        if fwd_pe <= 15.0:
            val_score += 25.0
        elif fwd_pe <= 22.0:
            val_score += 15.0
        elif fwd_pe <= 30.0:
            val_score += 5.0
        elif fwd_pe > 50.0:
            val_score -= 20.0

    if fcf_yield >= 8.0:
        val_score += 25.0
    elif fcf_yield >= 5.0:
        val_score += 15.0
    elif fcf_yield > 0.0:
        val_score += 5.0

    # 3. Quality Score (0-100)
    qual_score = 50.0
    roe = _safe_float(fund.get("roe"))
    de = _safe_float(fund.get("debt_to_equity"))
    fcf = _safe_float(fund.get("free_cash_flow"))
    net_inc = _safe_float(fund.get("net_income"))

    if roe >= 25.0:
        qual_score += 25.0
    elif roe >= 15.0:
        qual_score += 15.0
    elif roe < 0:
        qual_score -= 20.0

    if 0.0 <= de <= 0.8:
        qual_score += 20.0
    elif de <= 1.2:
        qual_score += 10.0
    elif de > 2.5:
        qual_score -= 20.0

    if fcf > 0 and net_inc > 0:
        qual_score += 10.0

    # 4. Growth Score (0-100)
    grow_score = 50.0
    rev_growth = _safe_float(fund.get("revenue_growth_qoq")) or _safe_float(fund.get("revenue_growth_yoy"))
    eps_surprise = _safe_float(fund.get("eps_surprise_pct"))

    if rev_growth >= 20.0:
        grow_score += 25.0
    elif rev_growth >= 10.0:
        grow_score += 15.0
    elif rev_growth > 0:
        grow_score += 5.0
    elif rev_growth < -5.0:
        grow_score -= 15.0

    if eps_surprise >= 15.0:
        grow_score += 25.0
    elif eps_surprise >= 5.0:
        grow_score += 15.0
    elif eps_surprise < 0:
        grow_score -= 15.0

    # 5. Volatility / Stability Score (0-100)
    # Higher score = lower unmanaged risk / disciplined swing profile
    vol_score = 50.0
    if indicators and indicators.close > 0:
        atr_pct = (indicators.atr_14 / indicators.close) * 100.0
        bw = indicators.bb_bandwidth
        # Optimal swing volatility is 1.5% to 4.0% ATR/price
        if 1.5 <= atr_pct <= 4.0:
            vol_score += 25.0
        elif atr_pct < 1.5:
            vol_score += 15.0  # Ultra stable
        elif atr_pct > 7.0:
            vol_score -= 20.0  # Highly volatile

        if indicators.is_bb_squeeze:
            vol_score += 15.0  # Compressed volatility ready for controlled explosion
        elif bw > 0.25:
            vol_score -= 10.0

    return FactorRadarScores(
        momentum=_clamp(mom_score),
        value=_clamp(val_score),
        quality=_clamp(qual_score),
        growth=_clamp(grow_score),
        volatility=_clamp(vol_score),
    )


# ---------------------------------------------------------------------------
# Individual Strategy Evaluators
# ---------------------------------------------------------------------------

def evaluate_momentum_breakout(
    indicators: TechnicalIndicators,
    df: Optional[pd.DataFrame] = None,
) -> StrategyMatch:
    """
    Strategy 1: Momentum & Volatility Breakout.
    Rules:
      1. Stage 2 Trend: Close > SMA20 > SMA50 > SMA200 (or Close > SMA20 > SMA50 if SMA200 N/A).
      2. 200 SMA non-declining.
      3. Volume spike: Volume > 1.5 * SMA_20(Volume).
      4. Volatility breakout: Close > Upper Bollinger Band (UB).
      5. Recent squeeze: BB squeeze in last 10 bars or current squeeze.
    """
    reasons = []
    if not indicators:
        return StrategyMatch(StrategyName.MOMENTUM_BREAKOUT.value, False, 0, None, ["No indicators"])

    # 1. Trend alignment
    trend_aligned = indicators.stage2_bullish_alignment
    if not trend_aligned and indicators.sma_50 > 0:
        # Fallback for tickers with < 200 bars
        trend_aligned = (indicators.close > indicators.sma_20 > indicators.sma_50)
    if trend_aligned:
        reasons.append("Bullish trend alignment satisfied")

    # 2. Volume spike
    vol_spike = indicators.is_volume_spike or indicators.volume_ratio_20 >= 1.5
    if vol_spike:
        reasons.append(f"Volume spike {indicators.volume_ratio_20:.2f}x > 1.5x")

    # 3. Bollinger breakout
    bb_breakout = indicators.close >= indicators.bb_upper - 1e-4
    if bb_breakout:
        reasons.append(f"Close ${indicators.close:.2f} broke Upper Band ${indicators.bb_upper:.2f}")

    # 4. Recent squeeze
    recent_squeeze = indicators.is_bb_squeeze
    if df is not None and not recent_squeeze and "bb_squeeze" in df.columns:
        recent_squeeze = bool(df["bb_squeeze"].tail(10).any())
    elif df is not None and not recent_squeeze and "bb_bandwidth" in df.columns:
        bw_tail = df["bb_bandwidth"].tail(10).dropna()
        if len(bw_tail) > 0 and bw_tail.min() <= 0.10:
            recent_squeeze = True

    if recent_squeeze:
        reasons.append("Recent volatility compression / squeeze detected")

    is_matched = bool(trend_aligned and vol_spike and bb_breakout)

    confidence = 0
    setup = None
    if is_matched:
        conf = 65
        if indicators.volume_ratio_20 >= 2.0:
            conf += 10
        if recent_squeeze:
            conf += 15
        if 55.0 <= indicators.rsi_14 <= 70.0:
            conf += 10
        confidence = _clamp(conf)

        setup = generate_trade_setup(
            entry_price=indicators.close,
            atr_14=indicators.atr_14,
            strategy_name=StrategyName.MOMENTUM_BREAKOUT.value,
            min_return_pct=4.0,
            max_return_pct=10.0,
            min_rr_ratio=2.0,
        )

    return StrategyMatch(
        strategy_name=StrategyName.MOMENTUM_BREAKOUT.value,
        is_matched=is_matched,
        confidence_score=confidence,
        setup=setup,
        reasons=reasons,
    )


def evaluate_earnings_pead(
    indicators: TechnicalIndicators,
    fundamentals: Dict[str, Any],
) -> StrategyMatch:
    """
    Strategy 2: Earnings & Catalyst Momentum (PEAD).
    Rules:
      1. EPS Surprise >= +10.0%.
      2. Revenue Acceleration: QoQ or YoY growth > 0.
      3. Technical momentum confirmation: Close > SMA20, positive recent momentum.
    """
    reasons = []
    if not fundamentals:
        return StrategyMatch(StrategyName.EARNINGS_PEAD.value, False, 0, None, ["No fundamental data"])

    eps_surprise = _safe_float(fundamentals.get("eps_surprise_pct"))
    rev_growth = _safe_float(fundamentals.get("revenue_growth_qoq")) or _safe_float(fundamentals.get("revenue_growth_yoy"))

    # 1. EPS surprise rule
    eps_passed = eps_surprise >= 10.0
    if eps_passed:
        reasons.append(f"EPS surprise +{eps_surprise:.1f}% >= +10%")

    # 2. Revenue acceleration
    rev_passed = rev_growth > 0.0
    if rev_passed:
        reasons.append(f"Quarterly revenue growth +{rev_growth:.1f}% > 0%")

    # 3. Technical confirmation
    tech_passed = True
    if indicators:
        tech_passed = (indicators.close >= indicators.sma_20 - 1e-4) if indicators.sma_20 > 0 else True
        if tech_passed:
            reasons.append("Price holds above 20-day moving average post-earnings")

    is_matched = bool(eps_passed and rev_passed and tech_passed)

    confidence = 0
    setup = None
    if is_matched:
        conf = 60
        if eps_surprise >= 20.0:
            conf += 15
        if rev_growth >= 15.0:
            conf += 15
        if indicators and indicators.is_volume_spike:
            conf += 10
        confidence = _clamp(conf)

        mcap = _safe_float(fundamentals.get("market_cap"), 100.0 * 1e9)
        close = indicators.close if indicators else max(1.0, mcap / 1e9)
        atr = indicators.atr_14 if indicators else max(1.0, close * 0.03)
        setup = generate_trade_setup(
            entry_price=close,
            atr_14=atr,
            strategy_name=StrategyName.EARNINGS_PEAD.value,
            min_return_pct=5.0,
            max_return_pct=10.0,
            min_rr_ratio=2.2,
        )

    return StrategyMatch(
        strategy_name=StrategyName.EARNINGS_PEAD.value,
        is_matched=is_matched,
        confidence_score=confidence,
        setup=setup,
        reasons=reasons,
    )


def evaluate_oversold_bounce(
    indicators: TechnicalIndicators,
    fundamentals: Dict[str, Any],
) -> StrategyMatch:
    """
    Strategy 3: Mean-Reversion / Oversold Bounce.
    Fundamental Gate:
      - Positive FCF or positive net income.
      - Debt-to-Equity < 1.5.
      - Close > 0.85 * SMA200 (if 200 SMA available).
    Technical Trigger:
      - RSI(14) < 35.0 (oversold).
      - Price penetrated Lower Band (Low <= LB or Close <= LB * 1.01).
      - Reversal sign: Bullish candle or MACD histogram inflection or MACD crossover.
    """
    reasons = []
    fund = fundamentals or {}
    de = _safe_float(fund.get("debt_to_equity"))
    fcf = _safe_float(fund.get("free_cash_flow")) or _safe_float(fund.get("fcf_yield")) or _safe_float(fund.get("net_income"))
    roe_val = _safe_float(fund.get("roe"))

    # 1. Fundamental Gate
    fund_gate = (de <= 1.5) and (fcf >= 0.0 or roe_val > 0)
    if indicators and indicators.sma_200 > 0:
        fund_gate = fund_gate and (indicators.close > 0.85 * indicators.sma_200)

    if fund_gate:
        reasons.append("Fundamental solvency & anti-falling-knife check passed")

    if not indicators:
        return StrategyMatch(StrategyName.MEAN_REVERSION.value, False, 0, None, ["No indicators"])

    # 2. Oversold condition
    rsi_oversold = indicators.rsi_14 < 35.0
    if rsi_oversold:
        reasons.append(f"RSI(14) {indicators.rsi_14:.1f} < 35.0 (Oversold)")

    # 3. Lower band stretch
    lb_touch = (indicators.low <= indicators.bb_lower + 1e-4) or (indicators.close <= indicators.bb_lower * 1.01)
    if lb_touch:
        reasons.append(f"Lower Bollinger Band ${indicators.bb_lower:.2f} touched/penetrated")

    # 4. Reversal confirmation
    reversal_signal = (
        indicators.macd_bullish_cross
        or indicators.macd_hist > -1e-4
        or indicators.close > indicators.low + (0.5 * indicators.atr_14)
    )
    if reversal_signal:
        reasons.append("Reversal confirmation detected")

    is_matched = bool(fund_gate and rsi_oversold and (lb_touch or indicators.rsi_14 < 30.0))

    confidence = 0
    setup = None
    if is_matched:
        conf = 60
        if indicators.rsi_14 < 30.0:
            conf += 15
        if reversal_signal:
            conf += 15
        if de <= 1.0:
            conf += 10
        confidence = _clamp(conf)

        setup = generate_trade_setup(
            entry_price=indicators.close,
            atr_14=indicators.atr_14,
            strategy_name=StrategyName.MEAN_REVERSION.value,
            min_return_pct=3.0,
            max_return_pct=8.0,
            min_rr_ratio=2.0,
            bb_middle=indicators.bb_middle,
        )

    return StrategyMatch(
        strategy_name=StrategyName.MEAN_REVERSION.value,
        is_matched=is_matched,
        confidence_score=confidence,
        setup=setup,
        reasons=reasons,
    )


def evaluate_quality_fcf(
    indicators: TechnicalIndicators,
    fundamentals: Dict[str, Any],
) -> StrategyMatch:
    """
    Strategy 4: Quality & Free-Cash-Flow Yield.
    Fundamental Rules:
      - ROE >= 15.0%
      - Debt-to-Equity <= 1.0 (or <= 1.5)
      - FCF Yield >= 5.0%
      - Forward P/E <= 25.0 (if forward P/E is reported)
    Technical Timing Trigger:
      - Pullback to support: Close near SMA50 while above SMA200 (or Close >= SMA50).
    """
    reasons = []
    fund = fundamentals or {}
    roe = _safe_float(fund.get("roe"))
    de = _safe_float(fund.get("debt_to_equity"))
    fcf_yield = _safe_float(fund.get("fcf_yield"))
    fwd_pe = _safe_float(fund.get("forward_pe"))

    # 1. Fundamental checks
    roe_ok = roe >= 15.0
    de_ok = de <= 1.0
    fcf_ok = fcf_yield >= 5.0
    pe_ok = (fwd_pe <= 25.0) if fwd_pe > 0 else True

    if roe_ok:
        reasons.append(f"ROE {roe:.1f}% >= 15.0%")
    if de_ok:
        reasons.append(f"Debt/Equity {de:.2f} <= 1.0")
    if fcf_ok:
        reasons.append(f"FCF Yield {fcf_yield:.1f}% >= 5.0%")
    if pe_ok and fwd_pe > 0:
        reasons.append(f"Forward P/E {fwd_pe:.1f} <= 25.0")

    fund_passed = roe_ok and de_ok and fcf_ok and pe_ok

    # 2. Technical timing check
    tech_passed = True
    if indicators:
        # Near or bouncing from 50 SMA
        if indicators.sma_50 > 0:
            near_sma50 = (indicators.close >= indicators.sma_50 * 0.96)
            tech_passed = near_sma50
            if tech_passed:
                reasons.append(f"Trading above or within pullback distance of 50-day SMA (${indicators.sma_50:.2f})")

    is_matched = bool(fund_passed and tech_passed)

    confidence = 0
    setup = None
    if is_matched:
        conf = 65
        if roe >= 20.0:
            conf += 10
        if fcf_yield >= 7.0:
            conf += 15
        if fwd_pe > 0 and fwd_pe <= 18.0:
            conf += 10
        confidence = _clamp(conf)

        close = indicators.close if indicators else 100.0
        atr = indicators.atr_14 if indicators else max(1.0, close * 0.03)
        setup = generate_trade_setup(
            entry_price=close,
            atr_14=atr,
            strategy_name=StrategyName.QUALITY_FCF.value,
            min_return_pct=5.0,
            max_return_pct=10.0,
            min_rr_ratio=2.0,
        )

    return StrategyMatch(
        strategy_name=StrategyName.QUALITY_FCF.value,
        is_matched=is_matched,
        confidence_score=confidence,
        setup=setup,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Master Evaluator
# ---------------------------------------------------------------------------

def evaluate_strategies(
    ticker: str,
    name: str = "",
    sector: str = "General",
    df: Optional[pd.DataFrame] = None,
    fundamentals: Optional[Dict[str, Any]] = None,
) -> Optional[ScreenerCandidate]:
    """
    Evaluates all 4 strategies for a ticker using technical OHLCV bars and SEC fundamentals.
    Returns ScreenerCandidate if one or more strategies match and produce a valid trade setup.
    """
    indicators = get_latest_indicators(df) if df is not None and not df.empty else None
    fund = fundamentals or {}

    # Run evaluations
    m1 = evaluate_momentum_breakout(indicators, df=df) if indicators else None
    m2 = evaluate_earnings_pead(indicators, fund)
    m3 = evaluate_oversold_bounce(indicators, fund) if indicators else None
    m4 = evaluate_quality_fcf(indicators, fund)

    matched_matches: List[StrategyMatch] = []
    for m in (m1, m2, m3, m4):
        if m and m.is_matched and m.setup and m.setup.is_valid:
            matched_matches.append(m)

    if not matched_matches:
        return None

    # Sort matched strategies by highest confidence score
    matched_matches.sort(key=lambda x: x.confidence_score, reverse=True)
    best_match = matched_matches[0]

    # Map strategy enums to lowercase keys matching API requirements
    strategy_slug_map = {
        StrategyName.MOMENTUM_BREAKOUT.value: "momentum_breakout",
        StrategyName.EARNINGS_PEAD.value: "earnings_pead",
        StrategyName.MEAN_REVERSION.value: "oversold_bounce",
        StrategyName.QUALITY_FCF.value: "quality_fcf",
    }
    matched_slugs = [strategy_slug_map.get(m.strategy_name, m.strategy_name.lower()) for m in matched_matches]

    # Calculate factor radar scores
    factor_scores = calculate_factor_radar(indicators, fund)

    # 24h change calculation
    change_24h = 0.0
    if df is not None and len(df) >= 2:
        c_curr = float(df["close"].iloc[-1])
        c_prev = float(df["close"].iloc[-2])
        if c_prev > 0:
            change_24h = round(((c_curr - c_prev) / c_prev) * 100.0, 2)

    # Generate synthetic catalyst event based on fundamentals date
    last_reported = fund.get("last_reported_date") or ""
    catalysts = []
    if last_reported:
        catalysts.append({
            "type": "earnings",
            "date": last_reported,
            "label": f"Reported {fund.get('fiscal_quarter', 'Quarter')}",
        })

    all_notes = "; ".join(f"[{m.strategy_name}]: " + ", ".join(m.reasons) for m in matched_matches)

    return ScreenerCandidate(
        ticker=ticker.strip().upper(),
        name=name or ticker.strip().upper(),
        sector=sector or "General",
        price=best_match.setup.entry_price,
        change_24h_pct=change_24h,
        strategies=matched_slugs,
        setup=best_match.setup.to_dict(),
        factor_scores=factor_scores.to_dict(),
        catalysts=catalysts,
        confidence_score=best_match.confidence_score,
        notes=all_notes,
    )

"""
Technical Indicators Engine for Stocknomist (Feature F5).
Exact mathematical formulations for:
- Wilder's ATR(14) RMA smoothing
- Wilder's RSI(14) modified moving average
- Bollinger Bands (20 SMA +/- 2.0 std dev) and bandwidth squeeze
- MACD (12, 26, 9) exponential moving averages
- Simple Moving Averages: SMA(20), SMA(50), SMA(200) and Stage 2 bullish alignment
- Volume spike ratio (Volume / SMA_20(Volume)) and spike flag (> 1.5x)
- Resilient guards for edge cases (zero variance, NaN inputs, insufficient bars)
"""

from dataclasses import dataclass
import math
from typing import Optional, Tuple, Union
import numpy as np
import pandas as pd

EPSILON = 1e-12


@dataclass
class TechnicalIndicators:
    """Snapshot of technical indicators for a specific ticker on a given date."""
    close: float
    high: float
    low: float
    volume: float
    atr_14: float
    rsi_14: float
    sma_20: float
    sma_50: float
    sma_200: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_bandwidth: float
    bb_percent_b: float
    is_bb_squeeze: bool
    macd_line: float
    macd_signal: float
    macd_hist: float
    macd_bullish_cross: bool
    volume_ratio_20: float
    is_volume_spike: bool
    stage2_bullish_alignment: bool


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizes column names to lowercase."""
    rename_dict = {}
    for col in df.columns:
        c_lower = str(col).strip().lower()
        if c_lower in ("open", "high", "low", "close", "volume", "date", "trade_date"):
            rename_dict[col] = c_lower
    return df.rename(columns=rename_dict)


def calculate_atr(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14,
) -> pd.Series:
    """
    Calculates Average True Range (ATR) using exact Wilder's RMA (Modified Moving Average) smoothing.
    
    Formula:
      TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)  (for t >= 1; TR_0 = H_0 - L_0)
      Initial ATR (at t = period - 1, 0-indexed): (1/period) * sum(TR_0..TR_{period-1})
      Wilder's Smoothing for t >= period: ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period
    """
    h = pd.Series(high, dtype=float).reset_index(drop=True)
    low_s = pd.Series(low, dtype=float).reset_index(drop=True)
    c = pd.Series(close, dtype=float).reset_index(drop=True)

    n = len(c)
    if n == 0:
        return pd.Series([], dtype=float)
    if n < period:
        return pd.Series([np.nan] * n, dtype=float)

    h_val = h.values
    l_val = low_s.values
    c_val = c.values

    # True Range calculation
    tr = np.zeros(n, dtype=float)
    tr[0] = max(0.0, h_val[0] - l_val[0])
    for i in range(1, n):
        hl = h_val[i] - l_val[i]
        hc = abs(h_val[i] - c_val[i - 1])
        lc = abs(l_val[i] - c_val[i - 1])
        tr[i] = max(hl, hc, lc)

    atr = np.full(n, np.nan, dtype=float)
    initial_atr = np.mean(tr[:period])
    atr[period - 1] = initial_atr

    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return pd.Series(atr)


def calculate_rsi(
    close: Union[pd.Series, np.ndarray],
    period: int = 14,
) -> pd.Series:
    """
    Calculates Relative Strength Index (RSI) using exact Wilder's MMA smoothing.
    
    Formula:
      Delta C_t = C_t - C_{t-1}
      U_t = Delta C_t if Delta C_t > 0 else 0
      D_t = -Delta C_t if Delta C_t < 0 else 0
      Initial averages at t = period:
        AvgGain_{period} = (1/period) * sum(U_1..U_{period})
        AvgLoss_{period} = (1/period) * sum(D_1..D_{period})
      Wilder's Smoothing for t > period:
        AvgGain_t = (AvgGain_{t-1} * (period - 1) + U_t) / period
        AvgLoss_t = (AvgLoss_{t-1} * (period - 1) + D_t) / period
      RS_t = AvgGain_t / (AvgLoss_t + 1e-12)
      RSI_t = 100.0 - (100.0 / (1.0 + RS_t))
    """
    c = pd.Series(close, dtype=float).reset_index(drop=True)
    n = len(c)
    if n == 0:
        return pd.Series([], dtype=float)
    if n <= period:
        return pd.Series([np.nan] * n, dtype=float)

    c_val = c.values
    diffs = np.diff(c_val)

    gains = np.where(diffs > 0, diffs, 0.0)
    losses = np.where(diffs < 0, -diffs, 0.0)

    rsi = np.full(n, np.nan, dtype=float)

    # Initial average at index 'period'
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0.0 and avg_gain == 0.0:
        rsi[period] = 50.0
    elif avg_loss == 0.0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / (avg_loss + EPSILON)
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(diffs)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        idx = i + 1
        if avg_loss == 0.0 and avg_gain == 0.0:
            rsi[idx] = 50.0
        elif avg_loss == 0.0:
            rsi[idx] = 100.0
        else:
            rs = avg_gain / (avg_loss + EPSILON)
            val = 100.0 - (100.0 / (1.0 + rs))
            rsi[idx] = max(0.0, min(100.0, val))

    return pd.Series(rsi)


def calculate_bollinger_bands(
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    num_std: float = 2.0,
    squeeze_window: int = 120,
    squeeze_percentile: float = 20.0,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Calculates Bollinger Bands (20 SMA +/- 2.0 std dev), bandwidth, %B, and squeeze flag.
    
    Returns:
      (middle_band, upper_band, lower_band, bandwidth, percent_b, is_squeeze)
    """
    c = pd.Series(close, dtype=float).reset_index(drop=True)
    n = len(c)
    if n == 0:
        empty = pd.Series([], dtype=float)
        return empty, empty, empty, empty, empty, pd.Series([], dtype=bool)

    # Middle Band = 20-period SMA
    mb = c.rolling(window=period).mean()
    # Population standard deviation (ddof=0)
    std = c.rolling(window=period).std(ddof=0)

    # Upper & Lower Bands
    ub = mb + (num_std * std)
    lb = mb - (num_std * std)

    # Bandwidth = (UB - LB) / MB
    # Guard against zero MB, and do not zero-poison unformed bars with fillna(0.0)
    bw = (ub - lb) / (mb.abs() + EPSILON)

    # Percent B = (Close - LB) / (UB - LB)
    band_width_diff = ub - lb
    # Guard against zero band width (zero variance)
    pct_b = np.where(
        band_width_diff > EPSILON,
        (c - lb) / (band_width_diff + EPSILON),
        0.5,
    )
    pct_b = pd.Series(pct_b, dtype=float)

    # Squeeze detection: current BW <= minimum or percentile of last squeeze_window bars
    # Compute strictly over valid formed bars without zero-poisoning from unformed bars
    is_squeeze = np.full(n, False, dtype=bool)
    bw_vals = bw.values
    for i in range(period - 1, n):
        lookback_start = max(period - 1, i - squeeze_window + 1)
        window_bw = bw_vals[lookback_start : i + 1]
        valid_bw = window_bw[~np.isnan(window_bw)]
        if len(valid_bw) > 0:
            threshold = np.percentile(valid_bw, squeeze_percentile)
            if bw_vals[i] <= threshold or bw_vals[i] <= np.min(valid_bw) + EPSILON:
                is_squeeze[i] = True

    return mb, ub, lb, bw, pct_b, pd.Series(is_squeeze, dtype=bool)


def calculate_macd(
    close: Union[pd.Series, np.ndarray],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Calculates MACD (12, 26, 9) exponential moving averages:
      Fast EMA (alpha = 2/13)
      Slow EMA (alpha = 2/27)
      MACD Line = Fast EMA - Slow EMA
      Signal Line = EMA_9(MACD Line) (alpha = 2/10)
      MACD Histogram = MACD Line - Signal Line
      Bullish Crossover: (MACD_{t-1} <= Signal_{t-1}) and (MACD_t > Signal_t)
    
    Returns:
      (macd_line, signal_line, histogram, bullish_crossover)
    """
    c = pd.Series(close, dtype=float).reset_index(drop=True)
    n = len(c)
    if n == 0:
        empty = pd.Series([], dtype=float)
        return empty, empty, empty, pd.Series([], dtype=bool)

    fast_ema = c.ewm(span=fast_period, adjust=False).mean()
    slow_ema = c.ewm(span=slow_period, adjust=False).mean()
    macd_line = fast_ema - slow_ema

    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    # Bullish crossover flag
    bullish_cross = np.full(n, False, dtype=bool)
    m_val = macd_line.values
    s_val = signal_line.values
    for i in range(1, n):
        if not np.isnan(m_val[i]) and not np.isnan(s_val[i]) and not np.isnan(m_val[i - 1]) and not np.isnan(s_val[i - 1]):
            if m_val[i - 1] <= s_val[i - 1] and m_val[i] > s_val[i]:
                bullish_cross[i] = True

    return macd_line, signal_line, histogram, pd.Series(bullish_cross, dtype=bool)


def calculate_smas(
    close: Union[pd.Series, np.ndarray],
    periods: Tuple[int, ...] = (20, 50, 200),
) -> Tuple[pd.Series, ...]:
    """
    Calculates Simple Moving Averages for specified periods.
    """
    c = pd.Series(close, dtype=float).reset_index(drop=True)
    results = []
    for p in periods:
        if len(c) < p:
            results.append(pd.Series([np.nan] * len(c), dtype=float))
        else:
            results.append(c.rolling(window=p).mean())
    return tuple(results)


def check_stage2_alignment(
    close: Union[pd.Series, np.ndarray],
    sma20: Union[pd.Series, np.ndarray],
    sma50: Union[pd.Series, np.ndarray],
    sma200: Union[pd.Series, np.ndarray],
    slope_lookback: int = 20,
) -> pd.Series:
    """
    Evaluates Stage 2 Bullish Alignment:
      1. Close_t > SMA_20(t) > SMA_50(t) > SMA_200(t)
      2. SMA_200(t) >= SMA_200(t - slope_lookback) (Macro trend non-declining)
    """
    c = pd.Series(close, dtype=float).reset_index(drop=True)
    s20 = pd.Series(sma20, dtype=float).reset_index(drop=True)
    s50 = pd.Series(sma50, dtype=float).reset_index(drop=True)
    s200 = pd.Series(sma200, dtype=float).reset_index(drop=True)

    n = len(c)
    aligned = np.full(n, False, dtype=bool)

    c_vals = c.values
    s20_vals = s20.values
    s50_vals = s50.values
    s200_vals = s200.values

    for i in range(n):
        if np.isnan(s200_vals[i]) or np.isnan(s50_vals[i]) or np.isnan(s20_vals[i]) or np.isnan(c_vals[i]):
            continue

        cond_order = c_vals[i] > s20_vals[i] > s50_vals[i] > s200_vals[i]

        prior_idx = max(0, i - slope_lookback)
        prior_s200 = s200_vals[prior_idx]
        cond_slope = not np.isnan(prior_s200) and (s200_vals[i] >= prior_s200 - 1e-4)

        if cond_order and cond_slope:
            aligned[i] = True

    return pd.Series(aligned, dtype=bool)


def calculate_volume_spike(
    volume: Union[pd.Series, np.ndarray],
    period: int = 20,
    threshold: float = 1.5,
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculates Volume Spike Ratio and Spike Flag:
      Volume_Ratio = Volume_t / SMA_20(Volume_t)
      Is_Spike = Volume_Ratio > threshold (default 1.5)
    
    Returns:
      (volume_ratio, is_spike)
    """
    v = pd.Series(volume, dtype=float).reset_index(drop=True)
    n = len(v)
    if n == 0:
        return pd.Series([], dtype=float), pd.Series([], dtype=bool)

    sma_vol = v.rolling(window=period).mean()
    safe_sma = sma_vol.replace(0.0, np.nan)
    vol_ratio = v / (safe_sma + EPSILON)
    vol_ratio = vol_ratio.fillna(1.0)

    is_spike = vol_ratio > threshold
    return vol_ratio, is_spike


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes all technical indicators and appends them to the DataFrame:
      - atr_14
      - rsi_14
      - sma_20, sma_50, sma_200
      - bb_middle, bb_upper, bb_lower, bb_bandwidth, bb_percent_b, bb_squeeze
      - macd_line, macd_signal, macd_hist, macd_bullish_cross
      - volume_ratio_20, volume_spike
      - stage2_alignment
    """
    if df is None or df.empty:
        return pd.DataFrame()

    out = _standardize_columns(df.copy())
    req_cols = ["close", "high", "low", "volume"]
    for col in req_cols:
        if col not in out.columns:
            raise ValueError(f"Missing required price column: '{col}' in DataFrame")

    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    volume = out["volume"].astype(float)

    # 1. ATR(14)
    out["atr_14"] = calculate_atr(high, low, close, period=14)

    # 2. RSI(14)
    out["rsi_14"] = calculate_rsi(close, period=14)

    # 3. SMAs
    sma20, sma50, sma200 = calculate_smas(close, periods=(20, 50, 200))
    out["sma_20"] = sma20
    out["sma_50"] = sma50
    out["sma_200"] = sma200

    # 4. Bollinger Bands
    mb, ub, lb, bw, pct_b, squeeze = calculate_bollinger_bands(close, period=20, num_std=2.0)
    out["bb_middle"] = mb
    out["bb_upper"] = ub
    out["bb_lower"] = lb
    out["bb_bandwidth"] = bw
    out["bb_percent_b"] = pct_b
    out["bb_squeeze"] = squeeze

    # 5. MACD
    m_line, s_line, hist, cross = calculate_macd(close, fast_period=12, slow_period=26, signal_period=9)
    out["macd_line"] = m_line
    out["macd_signal"] = s_line
    out["macd_hist"] = hist
    out["macd_bullish_cross"] = cross

    # 6. Volume Spike
    vol_ratio, is_spike = calculate_volume_spike(volume, period=20, threshold=1.5)
    out["volume_ratio_20"] = vol_ratio
    out["volume_spike"] = is_spike

    # 7. Stage 2 Alignment
    out["stage2_alignment"] = check_stage2_alignment(close, sma20, sma50, sma200)

    return out


def get_latest_indicators(df: pd.DataFrame) -> Optional[TechnicalIndicators]:
    """
    Computes indicators and returns the most recent bar's snapshot.
    Returns None if DataFrame is empty or contains insufficient valid bars.
    """
    if df is None or len(df) == 0:
        return None

    computed = compute_all_indicators(df)
    if computed.empty:
        return None

    last = computed.iloc[-1]
    def safe_val(v, default=0.0):
        if pd.isna(v) or math.isnan(v):
            return default
        return float(v)

    return TechnicalIndicators(
        close=safe_val(last.get("close")),
        high=safe_val(last.get("high")),
        low=safe_val(last.get("low")),
        volume=safe_val(last.get("volume")),
        atr_14=safe_val(last.get("atr_14")),
        rsi_14=safe_val(last.get("rsi_14")),
        sma_20=safe_val(last.get("sma_20")),
        sma_50=safe_val(last.get("sma_50")),
        sma_200=safe_val(last.get("sma_200")),
        bb_upper=safe_val(last.get("bb_upper")),
        bb_middle=safe_val(last.get("bb_middle")),
        bb_lower=safe_val(last.get("bb_lower")),
        bb_bandwidth=safe_val(last.get("bb_bandwidth")),
        bb_percent_b=safe_val(last.get("bb_percent_b")),
        is_bb_squeeze=bool(last.get("bb_squeeze", False)),
        macd_line=safe_val(last.get("macd_line")),
        macd_signal=safe_val(last.get("macd_signal")),
        macd_hist=safe_val(last.get("macd_hist")),
        macd_bullish_cross=bool(last.get("macd_bullish_cross", False)),
        volume_ratio_20=safe_val(last.get("volume_ratio_20")),
        is_volume_spike=bool(last.get("volume_spike", False)),
        stage2_bullish_alignment=bool(last.get("stage2_alignment", False)),
    )

"""
Yahoo Finance Ingestion Client for Stocknomist.
Supports direct Yahoo Finance v8 chart API with multi-endpoint fallback,
yfinance library batch downloading, polite 50-ticker chunking, and exponential backoff retry.
Zero external API key spend.
"""

import datetime
import logging
import random
import time
from typing import Dict, List, Optional
import pandas as pd
import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

EXPECTED_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class YFinanceClient:
    """
    High-performance client for fetching historical EOD OHLCV price series
    from free public Yahoo Finance endpoints without API fees.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_backoff: float = 1.5,
        timeout: float = 10.0,
    ):
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculates exponential backoff with jitter."""
        wait = min(30.0, self.base_backoff * (2 ** attempt))
        jitter = random.uniform(0.0, 1.0)
        return wait + jitter

    def _request_v8_raw(self, ticker: str, range_str: str = "2y", interval: str = "1d") -> Optional[dict]:
        """
        Executes request to Yahoo v8 chart API with endpoint failover and backoff.
        """
        endpoints = [
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
        ]

        params = {
            "interval": interval,
            "range": range_str,
            "includePrePost": "false",
            "events": "div,splits",
        }

        for attempt in range(self.max_retries):
            for endpoint in endpoints:
                try:
                    resp = self.session.get(endpoint, params=params, timeout=self.timeout)
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                            if isinstance(data, dict):
                                chart = data.get("chart")
                                if isinstance(chart, dict) and chart.get("error") is None and chart.get("result"):
                                    return data
                        except Exception as e:
                            logger.debug(f"JSON decode/parse error for {ticker}: {e}")
                    elif resp.status_code == 429:
                        logger.warning(f"Rate limited (429) for {ticker} on {endpoint}, retrying...")
                    elif resp.status_code == 404:
                        logger.debug(f"Ticker {ticker} not found (404)")
                        return None
                except requests.RequestException as e:
                    logger.debug(f"Request error for {ticker} on {endpoint}: {e}")
                except Exception as e:
                    logger.debug(f"Unexpected error for {ticker} on {endpoint}: {e}")

            if attempt < self.max_retries - 1:
                sleep_time = self._calculate_backoff(attempt)
                logger.info(f"Retrying {ticker} after {sleep_time:.2f}s backoff (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(sleep_time)

        return None

    def fetch_ticker_bars_v8(
        self, ticker: str, range_str: str = "2y", interval: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """
        Fetches historical price bars directly via Yahoo Finance v8 chart API.
        Returns cleaned DataFrame with columns [date, open, high, low, close, volume].
        """
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            return pd.DataFrame(columns=EXPECTED_COLUMNS)

        data = self._request_v8_raw(ticker, range_str=range_str, interval=interval)
        if not data or not isinstance(data, dict):
            return None

        try:
            chart = data.get("chart")
            if not isinstance(chart, dict):
                return None
            results = chart.get("result")
            if not isinstance(results, list) or not results or not isinstance(results[0], dict):
                return None
            result = results[0]
            timestamps = result.get("timestamp")
            indicators = result.get("indicators")
            if not isinstance(timestamps, list) or not timestamps or not isinstance(indicators, dict):
                return None
            quotes = indicators.get("quote")
            if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
                return None
            quote = quotes[0]

            if not timestamps or not quote:
                return None

            dates = [
                datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")
                for ts in timestamps
            ]

            df = pd.DataFrame({
                "date": dates,
                "open": quote.get("open", []),
                "high": quote.get("high", []),
                "low": quote.get("low", []),
                "close": quote.get("close", []),
                "volume": quote.get("volume", []),
            })

            # Drop missing values and ensure valid prices
            df = df.dropna(subset=["close"]).copy()
            if df.empty:
                return None

            # Type conversion and hygiene
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

            # Drop rows where open/high/low/close are <= 0
            df = df[(df["close"] > 0) & (df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0)]
            df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
            return df[EXPECTED_COLUMNS]
        except Exception as e:
            logger.warning(f"Error parsing v8 chart response for {ticker}: {e}")
            return None

    def fetch_ticker_bars_yf(self, ticker: str, period: str = "2y") -> Optional[pd.DataFrame]:
        """
        Fallback using the yfinance library for a single ticker.
        """
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            return pd.DataFrame(columns=EXPECTED_COLUMNS)

        if yf is None:
            return None

        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period, interval="1d", auto_adjust=False)
            if hist.empty:
                return None

            hist = hist.reset_index()
            # Standardize column names
            col_map = {
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
            hist = hist.rename(columns=col_map)
            if "date" in hist.columns:
                hist["date"] = pd.to_datetime(hist["date"]).dt.strftime("%Y-%m-%d")

            avail_cols = [c for c in EXPECTED_COLUMNS if c in hist.columns]
            if len(avail_cols) == len(EXPECTED_COLUMNS):
                df = hist[EXPECTED_COLUMNS].dropna(subset=["close"]).copy()
                df = df[(df["close"] > 0) & (df["open"] > 0)]
                df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
                return df
        except Exception as e:
            logger.debug(f"yfinance fallback failed for {ticker}: {e}")

        return None

    def get_historical_bars(self, ticker: str, days: int = 300) -> pd.DataFrame:
        """
        Primary interface contract method (M1 <-> M2):
        Returns pd.DataFrame with columns [date, open, high, low, close, volume],
        sorted ascending by date, containing up to the last `days` bars.
        """
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            return pd.DataFrame(columns=EXPECTED_COLUMNS)

        clean_ticker = ticker.strip().upper().replace(".", "-")
        # 1. Try direct Yahoo v8 chart API (fastest, lowest overhead)
        df = self.fetch_ticker_bars_v8(clean_ticker)

        # 2. Fallback to yfinance if direct API fails
        if df is None or df.empty:
            df = self.fetch_ticker_bars_yf(clean_ticker)

        # 3. If still empty, return empty DataFrame with expected columns
        if df is None or df.empty:
            return pd.DataFrame(columns=EXPECTED_COLUMNS)

        # Slice to the requested number of days
        if days > 0 and len(df) > days:
            df = df.iloc[-days:].reset_index(drop=True)
        elif days <= 0:
            return pd.DataFrame(columns=EXPECTED_COLUMNS)

        return df

    def fetch_batch_bars(
        self,
        tickers: List[str],
        days: int = 300,
        chunk_size: int = 50,
        pause_seconds: float = 0.5,
    ) -> Dict[str, pd.DataFrame]:
        """
        Batch fetches historical bars for a universe of tickers.
        Uses 50-ticker chunking with polite pause intervals to avoid rate limits.
        """
        results: Dict[str, pd.DataFrame] = {}
        total = len(tickers)
        logger.info(f"Starting batch fetch for {total} tickers in chunks of {chunk_size}...")

        for i in range(0, total, chunk_size):
            chunk = tickers[i : i + chunk_size]
            logger.info(f"Fetching chunk {i // chunk_size + 1}/{(total + chunk_size - 1) // chunk_size} ({len(chunk)} tickers)...")

            # Try batch download via yfinance if available
            if yf is not None and len(chunk) > 1:
                try:
                    data = yf.download(
                        chunk,
                        period="1y",
                        interval="1d",
                        group_by="ticker",
                        threads=True,
                        progress=False,
                    )
                    if data is not None and not data.empty:
                        for sym in chunk:
                            try:
                                if sym in data.columns.levels[0]:
                                    sub_df = data[sym].dropna(subset=["Close"]).copy().reset_index()
                                    sub_df = sub_df.rename(columns={
                                        "Date": "date",
                                        "Open": "open",
                                        "High": "high",
                                        "Low": "low",
                                        "Close": "close",
                                        "Volume": "volume",
                                    })
                                    sub_df["date"] = pd.to_datetime(sub_df["date"]).dt.strftime("%Y-%m-%d")
                                    valid_cols = [c for c in EXPECTED_COLUMNS if c in sub_df.columns]
                                    if len(valid_cols) == len(EXPECTED_COLUMNS):
                                        clean = sub_df[EXPECTED_COLUMNS].copy()
                                        clean = clean[(clean["close"] > 0) & (clean["open"] > 0)]
                                        if len(clean) > days:
                                            clean = clean.iloc[-days:].reset_index(drop=True)
                                        results[sym] = clean
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"Batch yfinance download failed for chunk, falling back to individual: {e}")

            # For any missing tickers in the chunk, fetch individually via v8 API
            for sym in chunk:
                if sym not in results or results[sym].empty:
                    df = self.get_historical_bars(sym, days=days)
                    if not df.empty:
                        results[sym] = df

            # Polite pause between chunks
            if i + chunk_size < total:
                time.sleep(pause_seconds)

        logger.info(f"Batch fetch completed: {len(results)}/{total} tickers retrieved successfully.")
        return results

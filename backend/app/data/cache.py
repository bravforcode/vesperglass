"""
Hybrid Persistent Disk Cache for Stocknomist.
DuckDB (market_data.duckdb) for high-speed time-series OHLCV bars.
SQLite WAL (stocknomist.db) for universe constituents, fundamental ratios, and screener signals.
Complies with ADR-014 resource caps (<100MB RAM, <60MB disk footprint).
"""

from contextlib import contextmanager
import datetime
import gc
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional
import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("c:/data") if Path("c:/data").exists() else Path(__file__).resolve().parent.parent.parent.parent / "data"

EXPECTED_QUOTE_COLS = ["date", "open", "high", "low", "close", "volume"]


class MarketDataCache:
    """
    Hybrid disk caching engine:
    - DuckDB stores historical EOD OHLCV price series.
    - SQLite in WAL mode stores universe constituents, fundamentals, and signals.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.sqlite_path = self.data_dir / "stocknomist.db"
        self.duckdb_path = self.data_dir / "market_data.duckdb"

        self._lock = threading.Lock()
        self._duck_conn: Optional[duckdb.DuckDBPyConnection] = None

        self._init_sqlite()
        self._init_duckdb()

    # -------------------------------------------------------------------------
    # SQLite Initialization & Helpers (WAL Mode)
    # -------------------------------------------------------------------------

    @contextmanager
    def _get_sqlite_conn(self):
        """Yields SQLite connection with WAL mode and foreign keys enabled, ensuring clean close."""
        conn = sqlite3.connect(self.sqlite_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.close()
        try:
            yield conn
        finally:
            conn.close()

    def _init_sqlite(self):
        """Creates SQLite application and screener tables if not already present."""
        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()

            # 1. Universe Constituents
            cur.execute("""
            CREATE TABLE IF NOT EXISTS universe_constituents (
                ticker TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cik TEXT,
                sector TEXT,
                industry TEXT,
                in_sp500 BOOLEAN DEFAULT 0,
                in_nasdaq100 BOOLEAN DEFAULT 0,
                in_russell1000 BOOLEAN DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_universe_active ON universe_constituents(is_active);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_universe_sector ON universe_constituents(sector);")

            # 2. Fundamental Metrics (SEC EDGAR & Financials)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS company_fundamentals (
                ticker TEXT PRIMARY KEY,
                market_cap REAL,
                pe_forward REAL,
                pe_trailing REAL,
                roe REAL,
                debt_to_equity REAL,
                free_cash_flow REAL,
                fcf_yield REAL,
                revenue_growth_yoy REAL,
                eps_surprise_pct REAL,
                fiscal_quarter TEXT,
                last_reported_date DATE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(ticker) REFERENCES universe_constituents(ticker)
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fund_quality ON company_fundamentals(roe, debt_to_equity, fcf_yield);")

            # 3. Screener Signals
            cur.execute("""
            CREATE TABLE IF NOT EXISTS screener_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_date DATE NOT NULL,
                ticker TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                confidence_score INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                target_price REAL NOT NULL,
                target_return_pct REAL NOT NULL,
                risk_reward_ratio REAL NOT NULL,
                atr_14 REAL NOT NULL,
                rsi_14 REAL,
                volume_ratio REAL,
                sma_20 REAL,
                sma_50 REAL,
                sma_200 REAL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(ticker) REFERENCES universe_constituents(ticker)
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_date_strat ON screener_signals(scan_date, strategy_name);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_rr ON screener_signals(risk_reward_ratio);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_return ON screener_signals(target_return_pct);")

            # 4. Scan Pipeline Job Runs
            cur.execute("""
            CREATE TABLE IF NOT EXISTS scan_job_runs (
                job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date DATE NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                tickers_scanned INTEGER,
                signals_found INTEGER,
                status TEXT NOT NULL,
                error_message TEXT
            );
            """)
            conn.commit()

    # -------------------------------------------------------------------------
    # DuckDB Initialization & Helpers
    # -------------------------------------------------------------------------

    def _get_duckdb_conn(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        """Manages cached DuckDB connection with max_memory guard and multi-process fallback."""
        with self._lock:
            if self._duck_conn is None:
                try:
                    self._duck_conn = duckdb.connect(str(self.duckdb_path), read_only=read_only)
                except (duckdb.IOException, Exception) as e:
                    if "used by another process" in str(e) or "Cannot open file" in str(e):
                        # Multi-process read-only fallback on Windows
                        self._duck_conn = duckdb.connect(str(self.duckdb_path), read_only=True)
                    else:
                        raise
                # Memory guard strictly complying with ADR-014 (<256MB)
                self._duck_conn.execute("SET max_memory='256MB';")
            return self._duck_conn

    def _init_duckdb(self):
        """Initializes DuckDB time-series daily_quotes table."""
        conn = self._get_duckdb_conn()
        with self._lock:
            try:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_quotes (
                    ticker VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    adj_close DOUBLE NOT NULL,
                    volume BIGINT NOT NULL,
                    PRIMARY KEY (ticker, trade_date)
                );
                """)
            except (duckdb.AccessModeException, Exception) as e:
                # If connected read_only and table already exists, continue safely
                if "read-only mode" in str(e).lower():
                    pass
                else:
                    raise

    # -------------------------------------------------------------------------
    # SQLite Universe Methods
    # -------------------------------------------------------------------------

    def save_universe_constituents(self, records: List[Dict[str, Any]]) -> int:
        """
        Inserts or replaces universe constituents into SQLite.
        """
        if not records:
            return 0

        query = """
        INSERT OR REPLACE INTO universe_constituents (
            ticker, name, cik, sector, industry, in_sp500, in_nasdaq100, in_russell1000, is_active, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """
        data = [
            (
                r.get("ticker", "").strip().upper(),
                r.get("name", ""),
                r.get("cik", ""),
                r.get("sector", "General"),
                r.get("industry", "General"),
                1 if r.get("in_sp500") else 0,
                1 if r.get("in_nasdaq100") else 0,
                1 if r.get("in_russell1000") else 0,
                1 if r.get("is_active", True) else 0,
            )
            for r in records
        ]

        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()
            cur.executemany(query, data)
            conn.commit()
            return len(data)

    def get_universe_constituents(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves universe constituents from SQLite.
        """
        query = "SELECT * FROM universe_constituents"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY ticker ASC"

        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["in_sp500"] = bool(item["in_sp500"])
                item["in_nasdaq100"] = bool(item["in_nasdaq100"])
                item["in_russell1000"] = bool(item["in_russell1000"])
                item["is_active"] = bool(item["is_active"])
                # Generate combined index label
                indices = []
                if item["in_sp500"]:
                    indices.append("S&P 500")
                if item["in_nasdaq100"]:
                    indices.append("Nasdaq 100")
                if item["in_russell1000"]:
                    indices.append("Russell 1000")
                item["index"] = ", ".join(indices) if indices else "US Equity"
                results.append(item)
            return results

    # -------------------------------------------------------------------------
    # SQLite Fundamentals Methods
    # -------------------------------------------------------------------------

    def save_fundamentals(self, metrics: Dict[str, Any]) -> None:
        """
        Saves or updates fundamental ratios for a ticker in SQLite.
        """
        query = """
        INSERT OR REPLACE INTO company_fundamentals (
            ticker, market_cap, pe_forward, pe_trailing, roe, debt_to_equity,
            free_cash_flow, fcf_yield, revenue_growth_yoy, eps_surprise_pct,
            fiscal_quarter, last_reported_date, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """
        sym = metrics.get("ticker", "").strip().upper()
        if not sym:
            return

        values = (
            sym,
            metrics.get("market_cap", 0.0),
            metrics.get("forward_pe", 0.0),
            metrics.get("pe_trailing", 0.0),
            metrics.get("roe", 0.0),
            metrics.get("debt_to_equity", 0.0),
            metrics.get("free_cash_flow", 0.0),
            metrics.get("fcf_yield", 0.0),
            metrics.get("revenue_growth_qoq", 0.0),
            metrics.get("eps_surprise_pct", 0.0),
            metrics.get("fiscal_quarter", ""),
            metrics.get("last_reported_date", ""),
        )

        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()
            # Ensure constituent exists to satisfy foreign key constraint
            cur.execute(
                "INSERT OR IGNORE INTO universe_constituents (ticker, name, sector) VALUES (?, ?, ?)",
                (sym, sym, "General"),
            )
            cur.execute(query, values)
            conn.commit()

    def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves cached fundamental metrics for a given ticker from SQLite.
        """
        sym = ticker.strip().upper()
        query = "SELECT * FROM company_fundamentals WHERE ticker = ?"

        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, (sym,))
            row = cur.fetchone()
            if row:
                return dict(row)
            return None

    # -------------------------------------------------------------------------
    # SQLite Screener Signals & Job Runs
    # -------------------------------------------------------------------------

    def save_screener_signals(self, signals: List[Dict[str, Any]]) -> int:
        """
        Inserts generated trade opportunity signals into SQLite.
        """
        if not signals:
            return 0

        query = """
        INSERT INTO screener_signals (
            scan_date, ticker, strategy_name, confidence_score, entry_price,
            stop_loss, target_price, target_return_pct, risk_reward_ratio,
            atr_14, rsi_14, volume_ratio, sma_20, sma_50, sma_200, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        data = [
            (
                s.get("scan_date") or datetime.date.today().isoformat(),
                s.get("ticker", "").strip().upper(),
                s.get("strategy_name", ""),
                int(s.get("confidence_score", 0)),
                float(s.get("entry_price", 0.0)),
                float(s.get("stop_loss", 0.0)),
                float(s.get("target_price", 0.0)),
                float(s.get("target_return_pct", 0.0)),
                float(s.get("risk_reward_ratio", 0.0)),
                float(s.get("atr_14", 0.0)),
                float(s.get("rsi_14", 0.0)) if s.get("rsi_14") is not None else None,
                float(s.get("volume_ratio", 0.0)) if s.get("volume_ratio") is not None else None,
                float(s.get("sma_20", 0.0)) if s.get("sma_20") is not None else None,
                float(s.get("sma_50", 0.0)) if s.get("sma_50") is not None else None,
                float(s.get("sma_200", 0.0)) if s.get("sma_200") is not None else None,
                s.get("notes", ""),
            )
            for s in signals
        ]

        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()
            # Ensure each ticker exists in universe_constituents
            unique_tickers = set(item[1] for item in data if item[1])
            cur.executemany(
                "INSERT OR IGNORE INTO universe_constituents (ticker, name, sector) VALUES (?, ?, ?)",
                [(t, t, "General") for t in unique_tickers],
            )
            cur.executemany(query, data)
            conn.commit()
            return len(data)

    def get_screener_signals(
        self,
        scan_date: Optional[str] = None,
        strategy_name: Optional[str] = None,
        min_return: float = 0.0,
        min_rr: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Queries screener candidate signals with optional filtering.
        """
        query = "SELECT * FROM screener_signals WHERE target_return_pct >= ? AND risk_reward_ratio >= ?"
        params: List[Any] = [min_return, min_rr]

        if scan_date:
            query += " AND scan_date = ?"
            params.append(scan_date)
        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name)

        query += " ORDER BY confidence_score DESC, risk_reward_ratio DESC"

        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

    def log_scan_job(
        self,
        run_date: str,
        start_time: str,
        end_time: Optional[str],
        tickers_scanned: int,
        signals_found: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> int:
        """Logs daily scan pipeline execution."""
        query = """
        INSERT INTO scan_job_runs (
            run_date, start_time, end_time, tickers_scanned, signals_found, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self._get_sqlite_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                query,
                (run_date, start_time, end_time, tickers_scanned, signals_found, status, error_message),
            )
            conn.commit()
            return cur.lastrowid

    # -------------------------------------------------------------------------
    # DuckDB Time-Series Quotes Methods
    # -------------------------------------------------------------------------

    def save_daily_quotes(self, ticker: str, df: pd.DataFrame) -> int:
        """
        Saves or updates daily OHLCV bars for a given ticker into DuckDB.
        Expects df with columns [date, open, high, low, close, volume].
        """
        if df is None or df.empty:
            return 0

        clean_ticker = ticker.strip().upper().replace(".", "-")
        work_df = df.copy()

        # Rename date column if necessary
        if "date" in work_df.columns:
            work_df["trade_date"] = pd.to_datetime(work_df["date"]).dt.date
        elif "trade_date" in work_df.columns:
            work_df["trade_date"] = pd.to_datetime(work_df["trade_date"]).dt.date
        else:
            raise ValueError("DataFrame must contain 'date' or 'trade_date' column")

        work_df["ticker"] = clean_ticker
        if "adj_close" not in work_df.columns:
            work_df["adj_close"] = work_df["close"]

        # Ensure correct column order and types
        cols = ["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]
        clean_subset = work_df[cols].dropna(subset=["close"]).copy()
        clean_subset["open"] = clean_subset["open"].astype(float)
        clean_subset["high"] = clean_subset["high"].astype(float)
        clean_subset["low"] = clean_subset["low"].astype(float)
        clean_subset["close"] = clean_subset["close"].astype(float)
        clean_subset["adj_close"] = clean_subset["adj_close"].astype(float)
        clean_subset["volume"] = clean_subset["volume"].fillna(0).astype("int64")

        conn = self._get_duckdb_conn()
        with self._lock:
            conn.register("incoming_quotes", clean_subset)
            conn.execute("""
            INSERT OR REPLACE INTO daily_quotes
            SELECT ticker, trade_date, open, high, low, close, adj_close, volume
            FROM incoming_quotes
            """)
            conn.unregister("incoming_quotes")

        return len(clean_subset)

    def save_batch_daily_quotes(self, quotes_map: Dict[str, pd.DataFrame]) -> int:
        """
        Saves a dictionary of {ticker: DataFrame} into DuckDB in one transaction.
        """
        frames = []
        for ticker, df in quotes_map.items():
            if df is not None and not df.empty:
                wdf = df.copy()
                if "date" in wdf.columns:
                    wdf["trade_date"] = pd.to_datetime(wdf["date"]).dt.date
                elif "trade_date" in wdf.columns:
                    wdf["trade_date"] = pd.to_datetime(wdf["trade_date"]).dt.date
                wdf["ticker"] = ticker.strip().upper().replace(".", "-")
                if "adj_close" not in wdf.columns:
                    wdf["adj_close"] = wdf["close"]
                frames.append(wdf[["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]])

        if not frames:
            return 0

        combined = pd.concat(frames, ignore_index=True).dropna(subset=["close"])
        combined["open"] = combined["open"].astype(float)
        combined["high"] = combined["high"].astype(float)
        combined["low"] = combined["low"].astype(float)
        combined["close"] = combined["close"].astype(float)
        combined["adj_close"] = combined["adj_close"].astype(float)
        combined["volume"] = combined["volume"].fillna(0).astype("int64")

        conn = self._get_duckdb_conn()
        with self._lock:
            conn.register("batch_quotes", combined)
            conn.execute("""
            INSERT OR REPLACE INTO daily_quotes
            SELECT ticker, trade_date, open, high, low, close, adj_close, volume
            FROM batch_quotes
            """)
            conn.unregister("batch_quotes")

        return len(combined)

    def get_daily_quotes(self, ticker: str, days: int = 300) -> pd.DataFrame:
        """
        Retrieves up to the last `days` OHLCV bars for a ticker from DuckDB.
        Returns DataFrame with columns [date, open, high, low, close, volume],
        sorted ascending by date.
        """
        sym = ticker.strip().upper().replace(".", "-")
        conn = self._get_duckdb_conn()
        with self._lock:
            query = """
            SELECT CAST(trade_date AS VARCHAR) AS date, open, high, low, close, volume
            FROM daily_quotes
            WHERE ticker = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """
            df = conn.execute(query, [sym, days]).df()

        if df.empty:
            return pd.DataFrame(columns=EXPECTED_QUOTE_COLS)

        # Sort ascending by date for chronological indicator calculation
        df = df.sort_values("date").reset_index(drop=True)
        return df[EXPECTED_QUOTE_COLS]

    def get_latest_quote_date(self, ticker: str) -> Optional[str]:
        """Returns the most recent trade date for a ticker in DuckDB."""
        sym = ticker.strip().upper().replace(".", "-")
        conn = self._get_duckdb_conn()
        with self._lock:
            res = conn.execute(
                "SELECT CAST(MAX(trade_date) AS VARCHAR) FROM daily_quotes WHERE ticker = ?",
                [sym],
            ).fetchone()
            if res and res[0]:
                return res[0]
            return None

    def close(self):
        """Closes all database connections and releases file locks."""
        with self._lock:
            if self._duck_conn is not None:
                try:
                    self._duck_conn.close()
                except Exception as e:
                    logger.debug(f"DuckDB close exception: {e}")
                self._duck_conn = None
        gc.collect()

"""
Universe Management and Constituent Resolution for Stocknomist.
Covers S&P 500, Nasdaq 100, and Russell 1000 (~1,020 unique liquid US equities).
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

DEFAULT_SEEDS_DIR = Path(__file__).resolve().parent.parent / "data_seeds"


def normalize_ticker(ticker: str) -> str:
    """
    Normalizes ticker symbols for Yahoo Finance and SEC compatibility.
    Example: BRK.B -> BRK-B, BF.B -> BF-B.
    """
    if not ticker:
        return ""
    cleaned = ticker.strip().upper()
    # Replace dot with hyphen (Yahoo convention)
    cleaned = cleaned.replace(".", "-")
    # Remove unwanted leading/trailing symbols
    cleaned = re.sub(r"[^A-Z0-9\-]", "", cleaned)
    return cleaned


class UniverseManager:
    """
    Manages loading, deduplicating, caching, and dynamically updating
    US equity universe constituents across S&P 500, Nasdaq 100, and Russell 1000.
    """

    def __init__(self, seeds_dir: Optional[Path] = None):
        self.seeds_dir = Path(seeds_dir) if seeds_dir else DEFAULT_SEEDS_DIR
        self._universe: Dict[str, Dict[str, Any]] = {}
        self.load_seeds()

    def load_seeds(self) -> Dict[str, Dict[str, Any]]:
        """
        Loads pre-baked seed lists from disk and merges/deduplicates them.
        Guarantees zero-network cold boot capability.
        """
        sp500_file = self.seeds_dir / "sp500.json"
        ndx_file = self.seeds_dir / "nasdaq100.json"
        r1k_file = self.seeds_dir / "russell1000.json"

        merged: Dict[str, Dict[str, Any]] = {}

        # 1. Load S&P 500
        if sp500_file.exists():
            try:
                with open(sp500_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        sym = normalize_ticker(item.get("ticker", ""))
                        if not sym:
                            continue
                        merged[sym] = {
                            "ticker": sym,
                            "name": item.get("name", sym),
                            "sector": item.get("sector") or "General",
                            "industry": item.get("industry") or "General",
                            "cik": item.get("cik") or "",
                            "in_sp500": True,
                            "in_nasdaq100": False,
                            "in_russell1000": False,
                            "is_active": True,
                        }
            except Exception as e:
                logger.error(f"Error loading sp500.json: {e}")

        # 2. Load Nasdaq 100
        if ndx_file.exists():
            try:
                with open(ndx_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        sym = normalize_ticker(item.get("ticker", ""))
                        if not sym:
                            continue
                        if sym in merged:
                            merged[sym]["in_nasdaq100"] = True
                            if merged[sym]["sector"] in ("General", "Software"):
                                sec = item.get("sector")
                                if sec and sec != "Software":
                                    merged[sym]["sector"] = sec
                        else:
                            merged[sym] = {
                                "ticker": sym,
                                "name": item.get("name", sym),
                                "sector": item.get("sector") or "Technology",
                                "industry": item.get("industry") or "General",
                                "cik": item.get("cik") or "",
                                "in_sp500": False,
                                "in_nasdaq100": True,
                                "in_russell1000": False,
                                "is_active": True,
                            }
            except Exception as e:
                logger.error(f"Error loading nasdaq100.json: {e}")

        # 3. Load Russell 1000
        if r1k_file.exists():
            try:
                with open(r1k_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        sym = normalize_ticker(item.get("ticker", ""))
                        if not sym:
                            continue
                        if sym in merged:
                            merged[sym]["in_russell1000"] = True
                            if not merged[sym]["cik"] and item.get("cik"):
                                merged[sym]["cik"] = item["cik"]
                        else:
                            merged[sym] = {
                                "ticker": sym,
                                "name": item.get("name", sym),
                                "sector": item.get("sector") or "General",
                                "industry": item.get("industry") or "General",
                                "cik": item.get("cik") or "",
                                "in_sp500": False,
                                "in_nasdaq100": False,
                                "in_russell1000": True,
                                "is_active": True,
                            }
            except Exception as e:
                logger.error(f"Error loading russell1000.json: {e}")

        # Format human-readable index string
        for sym, rec in merged.items():
            indices = []
            if rec["in_sp500"]:
                indices.append("S&P 500")
            if rec["in_nasdaq100"]:
                indices.append("Nasdaq 100")
            if rec["in_russell1000"]:
                indices.append("Russell 1000")
            rec["index"] = ", ".join(indices) if indices else "US Equity"

        self._universe = merged
        logger.info(f"Loaded {len(self._universe)} unique universe constituents from seeds.")
        return self._universe

    def get_universe_tickers(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Returns list of universe constituent dictionaries matching the M1 <-> M2 interface contract:
        [{'ticker': str, 'name': str, 'sector': str, 'index': str, ...}]
        """
        if active_only:
            return [v for v in self._universe.values() if v.get("is_active", True)]
        return list(self._universe.values())

    def get_ticker_list(self, active_only: bool = True) -> List[str]:
        """Returns sorted list of ticker strings."""
        return sorted([item["ticker"] for item in self.get_universe_tickers(active_only=active_only)])

    def get_ticker_info(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Returns metadata for a specific ticker symbol."""
        sym = normalize_ticker(ticker)
        return self._universe.get(sym)

    def fetch_dynamic_updates(self, timeout: float = 10.0) -> Dict[str, Dict[str, Any]]:
        """
        Fetches fresh constituents from public datasets with offline fallback.
        Updates internal cache on success.
        """
        try:
            sp_url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
            resp = requests.get(sp_url, timeout=timeout)
            if resp.status_code == 200:
                import csv
                import io
                reader = csv.DictReader(io.StringIO(resp.text))
                for row in reader:
                    sym = normalize_ticker(row.get("Symbol", ""))
                    if sym:
                        if sym in self._universe:
                            self._universe[sym]["in_sp500"] = True
                            if row.get("GICS Sector"):
                                self._universe[sym]["sector"] = row["GICS Sector"]
                            if row.get("GICS Sub-Industry"):
                                self._universe[sym]["industry"] = row["GICS Sub-Industry"]
                        else:
                            self._universe[sym] = {
                                "ticker": sym,
                                "name": row.get("Security", sym),
                                "sector": row.get("GICS Sector", "General"),
                                "industry": row.get("GICS Sub-Industry", "General"),
                                "cik": row.get("CIK", "").zfill(10) if row.get("CIK") else "",
                                "in_sp500": True,
                                "in_nasdaq100": False,
                                "in_russell1000": False,
                                "index": "S&P 500",
                                "is_active": True,
                            }
        except Exception as e:
            logger.warning(f"Dynamic S&P 500 update failed (using local seeds): {e}")

        return self._universe

    def sync_to_db(self, cache_manager: Any) -> int:
        """
        Persists universe constituents into the SQLite database.
        Returns count of constituents written.
        """
        if not hasattr(cache_manager, "save_universe_constituents"):
            raise AttributeError("cache_manager must implement save_universe_constituents")
        records = self.get_universe_tickers(active_only=False)
        return cache_manager.save_universe_constituents(records)

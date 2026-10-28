"""
SEC EDGAR XBRL Company Facts Ingestion Client for Stocknomist.
Extracts GAAP financial facts (Net Income, Stockholders' Equity, Operating Cash Flow,
CapEx, Debt, EPS, Revenue) from free public SEC data.gov endpoints with compliance User-Agent.
Zero external API key spend.
"""

import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Dict, Optional
import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

logger = logging.getLogger(__name__)

SEC_USER_AGENT = "StockNomist/1.0 (admin@stocknomist.local)"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK"


class SecEdgarClient:
    """
    Client for querying SEC EDGAR company facts and computing
    fundamental quality and valuation ratios.
    """

    def __init__(
        self,
        user_agent: str = SEC_USER_AGENT,
        timeout: float = 10.0,
        cache_dir: Optional[Path] = None,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self._cik_map: Dict[str, str] = {}
        self._last_request_time = 0.0
        self._min_request_interval = 0.1  # SEC max 10 requests/sec fair access rule
        self.cache_dir = cache_dir

    def _rate_limit(self):
        """Enforces SEC fair access rate limit of <= 10 requests/second."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def load_cik_mapping(self, force_refresh: bool = False) -> Dict[str, str]:
        """
        Loads ticker -> CIK mapping from SEC or local cache.
        """
        if self._cik_map and not force_refresh:
            return self._cik_map

        # Check local cache if available
        if self.cache_dir:
            cache_file = Path(self.cache_dir) / "sec_cik_map.json"
            if cache_file.exists() and not force_refresh:
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        self._cik_map = json.load(f)
                        return self._cik_map
                except Exception as e:
                    logger.debug(f"Error loading cached CIK map: {e}")

        self._rate_limit()
        try:
            resp = self.session.get(SEC_TICKERS_URL, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                mapping = {}
                for item in data.values():
                    sym = item.get("ticker", "").strip().upper().replace(".", "-")
                    cik_num = str(item.get("cik_str", "")).zfill(10)
                    if sym and cik_num:
                        mapping[sym] = cik_num
                self._cik_map = mapping

                if self.cache_dir:
                    try:
                        cache_file = Path(self.cache_dir) / "sec_cik_map.json"
                        cache_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(mapping, f)
                    except Exception as e:
                        logger.debug(f"Error saving CIK map to disk: {e}")

                logger.info(f"Loaded {len(self._cik_map)} SEC CIK mappings.")
                return self._cik_map
        except Exception as e:
            logger.warning(f"Failed to fetch SEC company tickers: {e}")

        return self._cik_map

    def get_cik(self, ticker: str) -> Optional[str]:
        """Retrieves 10-digit zero-padded CIK string for a given ticker."""
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            return None
        sym = ticker.strip().upper().replace(".", "-")
        if sym in self._cik_map:
            return self._cik_map[sym]
        self.load_cik_mapping()
        return self._cik_map.get(sym)

    def _safe_float(self, val: Any, default: float = 0.0) -> float:
        """Safely parses a value to float; returns default on None, TypeError, or ValueError."""
        if val is None:
            return default
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except (ValueError, TypeError):
            return default

    def fetch_company_facts_raw(self, cik: str) -> Optional[dict]:
        """
        Queries raw XBRL facts JSON for the specified CIK from data.sec.gov.
        """
        padded_cik = str(cik).zfill(10)
        url = f"{SEC_FACTS_BASE_URL}{padded_cik}.json"
        self._rate_limit()

        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                logger.debug(f"CIK {padded_cik} facts not found on SEC (404)")
                return None
            else:
                logger.warning(f"SEC returned status {resp.status_code} for CIK {padded_cik}")
                return None
        except Exception as e:
            logger.warning(f"Network error querying SEC facts for CIK {padded_cik}: {e}")
            return None

    def _extract_latest_metric(
        self,
        gaap: dict,
        keys: list,
        unit: str = "USD",
        prefer_form: Optional[str] = None,
        annual_only: bool = False,
    ) -> Optional[dict]:
        """
        Extracts the most recent reporting entry for a list of GAAP candidate tags.
        """
        if not isinstance(gaap, dict):
            return None

        for k in keys:
            fact = gaap.get(k)
            if not isinstance(fact, dict):
                continue
            units_dict = fact.get("units")
            if not isinstance(units_dict, dict):
                continue
            units = units_dict.get(unit, [])
            if not isinstance(units, list) or not units:
                continue

            filtered = [u for u in units if isinstance(u, dict)]
            if not filtered:
                continue

            if annual_only:
                annual_filtered = [u for u in filtered if u.get("form") == "10-K"]
                if annual_filtered:
                    filtered = annual_filtered
            elif prefer_form:
                matching = [u for u in filtered if u.get("form") == prefer_form]
                if matching:
                    filtered = matching

            sorted_entries = sorted(
                filtered,
                key=lambda x: (str(x.get("end") or ""), str(x.get("filed") or "")),
            )
            if sorted_entries:
                return sorted_entries[-1]
        return None

    def _compute_ttm_net_income(self, gaap: dict) -> float:
        """
        Computes Trailing Twelve Month (TTM) Net Income:
        Sums the last 4 quarterly filings or uses the latest 10-K.
        """
        if not isinstance(gaap, dict):
            return 0.0

        net_inc_keys = [
            "NetIncomeLoss",
            "ProfitLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
        ]
        for k in net_inc_keys:
            fact = gaap.get(k)
            if not isinstance(fact, dict):
                continue
            units_dict = fact.get("units")
            if not isinstance(units_dict, dict):
                continue
            usd_entries = units_dict.get("USD", [])
            if not isinstance(usd_entries, list) or not usd_entries:
                continue

            filtered = [u for u in usd_entries if isinstance(u, dict)]
            if not filtered:
                continue

            # Check quarterly filings
            quarters = [
                u for u in filtered
                if u.get("form") == "10-Q" and u.get("fp") in ("Q1", "Q2", "Q3", "Q4") and "start" in u
            ]
            quarters_sorted = sorted(
                quarters,
                key=lambda x: (str(x.get("end") or ""), str(x.get("filed") or "")),
            )
            if len(quarters_sorted) >= 4:
                latest_4 = quarters_sorted[-4:]
                return float(sum(self._safe_float(q.get("val", 0)) for q in latest_4))

            # Fallback to latest 10-K annual
            annuals = [u for u in filtered if u.get("form") == "10-K"]
            if annuals:
                latest_10k = sorted(
                    annuals,
                    key=lambda x: (str(x.get("end") or ""), str(x.get("filed") or "")),
                )[-1]
                return self._safe_float(latest_10k.get("val", 0))

        return 0.0

    def parse_sec_fundamentals(self, ticker: str, cik: str) -> Dict[str, Any]:
        """
        Parses GAAP financial facts into structured metrics:
        ROE, Debt-to-Equity, Free Cash Flow, Revenue Growth, EPS.
        """
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            return self._empty_fundamentals(str(ticker or ""))
        clean_ticker = ticker.strip().upper().replace(".", "-")

        if not cik:
            return self._empty_fundamentals(clean_ticker)

        try:
            raw = self.fetch_company_facts_raw(cik)
            if not isinstance(raw, dict):
                return self._empty_fundamentals(clean_ticker)

            facts = raw.get("facts")
            if not isinstance(facts, dict):
                return self._empty_fundamentals(clean_ticker)

            gaap = facts.get("us-gaap")
            if not isinstance(gaap, dict) or not gaap:
                return self._empty_fundamentals(clean_ticker)

            # 1. Stockholders' Equity
            eq_entry = self._extract_latest_metric(
                gaap,
                [
                    "StockholdersEquity",
                    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                    "CommonStockholdersEquity",
                ],
            )
            equity = self._safe_float(eq_entry.get("val", 0)) if eq_entry else 0.0

            # 2. Net Income TTM
            net_income = self._compute_ttm_net_income(gaap)

            # 3. ROE
            roe = 0.0
            if equity > 0 and net_income != 0.0:
                roe = round((net_income / equity) * 100.0, 2)

            # 4. Total Debt (Long Term Debt + Current/Short-term Debt)
            lt_debt_entry = self._extract_latest_metric(
                gaap,
                ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],
            )
            st_debt_entry = self._extract_latest_metric(
                gaap,
                ["DebtCurrent", "ShortTermBorrowings", "CommercialPaper"],
            )
            lt_debt = self._safe_float(lt_debt_entry.get("val", 0)) if lt_debt_entry else 0.0
            st_debt = self._safe_float(st_debt_entry.get("val", 0)) if st_debt_entry else 0.0
            total_debt = lt_debt + st_debt

            # 5. Debt to Equity
            debt_to_equity = 0.0
            if equity > 0:
                debt_to_equity = round(total_debt / equity, 2)

            # 6. Operating Cash Flow & CapEx -> Free Cash Flow
            ocf_entry = self._extract_latest_metric(
                gaap,
                [
                    "NetCashProvidedByUsedInOperatingActivities",
                    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
                ],
            )
            capex_entry = self._extract_latest_metric(
                gaap,
                [
                    "PaymentsToAcquirePropertyPlantAndEquipment",
                    "PaymentsToAcquireProductiveAssets",
                    "PaymentsForPropertyPlantAndEquipment",
                ],
            )
            ocf = self._safe_float(ocf_entry.get("val", 0)) if ocf_entry else 0.0
            capex = self._safe_float(capex_entry.get("val", 0)) if capex_entry else 0.0
            free_cash_flow = ocf - capex

            # 7. Quarterly Revenues & Growth
            rev_entry = self._extract_latest_metric(
                gaap,
                [
                    "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "Revenues",
                    "SalesRevenueNet",
                ],
            )
            revenue_val = self._safe_float(rev_entry.get("val", 0)) if rev_entry else 0.0

            # Compute revenue growth QoQ if earlier quarter exists
            rev_growth_qoq = 0.0
            rev_fact = gaap.get("RevenueFromContractWithCustomerExcludingAssessedTax") or gaap.get("Revenues")
            if isinstance(rev_fact, dict):
                units_dict = rev_fact.get("units")
                if isinstance(units_dict, dict):
                    rev_entries = units_dict.get("USD", [])
                    if isinstance(rev_entries, list):
                        q_entries = [
                            u for u in rev_entries
                            if isinstance(u, dict) and u.get("form") == "10-Q" and "start" in u
                        ]
                        q_sorted = sorted(
                            q_entries,
                            key=lambda x: (str(x.get("end") or ""), str(x.get("filed") or "")),
                        )
                        if len(q_sorted) >= 2:
                            latest = self._safe_float(q_sorted[-1].get("val", 0))
                            prior = self._safe_float(q_sorted[-2].get("val", 0))
                            if prior > 0:
                                rev_growth_qoq = round(((latest - prior) / prior) * 100.0, 2)

            # 8. Diluted EPS
            eps_entry = self._extract_latest_metric(
                gaap,
                ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
                unit="USD/shares",
            )
            diluted_eps = self._safe_float(eps_entry.get("val", 0)) if eps_entry else 0.0

            # Metadata
            last_date = str(eq_entry.get("end") or "") if eq_entry else (str(rev_entry.get("end") or "") if rev_entry else "")
            fy = str(eq_entry.get("fy") or "") if eq_entry else ""
            fp = str(eq_entry.get("fp") or "") if eq_entry else ""
            fiscal_q = f"{fy}-{fp}" if fy and fp else ""

            return {
                "ticker": clean_ticker,
                "roe": roe,
                "debt_to_equity": debt_to_equity,
                "fcf_yield": 0.0,  # Computed when market cap is available
                "forward_pe": 0.0,
                "pe_trailing": 0.0,
                "eps_surprise_pct": 0.0,
                "revenue_growth_qoq": rev_growth_qoq,
                "diluted_eps": diluted_eps,
                "market_cap": 0.0,
                "net_income": net_income,
                "free_cash_flow": free_cash_flow,
                "total_debt": total_debt,
                "stockholders_equity": equity,
                "revenue": revenue_val,
                "fiscal_quarter": fiscal_q,
                "last_reported_date": last_date,
            }
        except Exception as e:
            logger.warning(f"Error parsing SEC fundamentals for {clean_ticker}: {e}")
            return self._empty_fundamentals(clean_ticker)

    def _empty_fundamentals(self, ticker: str) -> Dict[str, Any]:
        """Returns baseline empty metrics dictionary for a ticker."""
        return {
            "ticker": ticker,
            "roe": 0.0,
            "debt_to_equity": 0.0,
            "fcf_yield": 0.0,
            "forward_pe": 0.0,
            "pe_trailing": 0.0,
            "eps_surprise_pct": 0.0,
            "revenue_growth_qoq": 0.0,
            "diluted_eps": 0.0,
            "market_cap": 0.0,
            "net_income": 0.0,
            "free_cash_flow": 0.0,
            "total_debt": 0.0,
            "stockholders_equity": 0.0,
            "revenue": 0.0,
            "fiscal_quarter": "",
            "last_reported_date": "",
        }

    def get_fundamental_metrics(self, ticker: str, cik: Optional[str] = None) -> Dict[str, Any]:
        """
        Primary interface contract method (M1 <-> M2):
        Returns dict with keys: roe, debt_to_equity, fcf_yield, forward_pe,
        eps_surprise_pct, revenue_growth_qoq, market_cap, etc.
        Enriches SEC facts with valuation multiples from public sources.
        """
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            return self._empty_fundamentals(str(ticker or ""))

        clean_ticker = ticker.strip().upper().replace(".", "-")

        # Resolve CIK if not provided
        if not cik:
            cik = self.get_cik(clean_ticker)

        # 1. Parse SEC XBRL company facts
        metrics = self._empty_fundamentals(clean_ticker)
        if cik:
            try:
                sec_data = self.parse_sec_fundamentals(clean_ticker, cik)
                if isinstance(sec_data, dict):
                    metrics.update(sec_data)
            except Exception as e:
                logger.warning(f"Failed parsing SEC fundamentals for {clean_ticker}: {e}")

        # 2. Enrich valuation multiples via yfinance if available
        if yf is not None:
            try:
                t = yf.Ticker(clean_ticker)
                info = getattr(t, "fast_info", None) or getattr(t, "info", None)
                if info:
                    # Market Cap
                    raw_mcap = (
                        getattr(info, "market_cap", None)
                        or (info.get("marketCap") if isinstance(info, dict) else None)
                        or 0.0
                    )
                    mcap = self._safe_float(raw_mcap)
                    if mcap > 0:
                        metrics["market_cap"] = mcap
                        # Compute FCF yield if FCF is known
                        if metrics.get("free_cash_flow", 0) != 0:
                            metrics["fcf_yield"] = round(
                                (metrics["free_cash_flow"] / mcap) * 100.0, 2
                            )

                    # Valuation & Forward multiples
                    if isinstance(info, dict):
                        if info.get("forwardPE"):
                            metrics["forward_pe"] = round(self._safe_float(info["forwardPE"]), 2)
                        if info.get("trailingPE"):
                            metrics["pe_trailing"] = round(self._safe_float(info["trailingPE"]), 2)
                        if not metrics["roe"] and info.get("returnOnEquity"):
                            metrics["roe"] = round(self._safe_float(info["returnOnEquity"]) * 100.0, 2)
                        if not metrics["debt_to_equity"] and info.get("debtToEquity"):
                            metrics["debt_to_equity"] = round(self._safe_float(info["debtToEquity"]) / 100.0, 2)
            except Exception as e:
                logger.debug(f"yfinance info enrichment skipped for {clean_ticker}: {e}")

        return metrics

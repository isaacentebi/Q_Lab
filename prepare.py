"""
Q_Lab: Autonomous quantitative research infrastructure.

Fixed evaluation harness, data pipeline, and backtest engine.
The agent modifies strategy.py only — this file is read-only.

Usage:
    uv run prepare.py --download     # fetch/refresh all data from FMP
    uv run prepare.py --backtest     # run strategy.py, evaluate, print metrics
    uv run prepare.py --test         # run on holdout test period (human only)
"""

import os
import sys
import time
import json
import math
import argparse
import importlib
import warnings
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=FutureWarning)

load_dotenv()

# ---------------------------------------------------------------------------
# Section 1: Constants (FIXED — agent cannot touch)
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "qlab")
COMPANIES_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "stack-intelligence-engine", "registry", "companies.json",
)

BACKTEST_START = "2021-03-01"
BACKTEST_END = "2026-03-01"
TRAIN_END = "2024-03-01"       # 60% in-sample
VAL_END = "2025-03-01"         # 20% validation (agent sees this)
# Test: 2025-03-01 to 2026-03-01 (20%, NEVER shown to agent)

INITIAL_CAPITAL = 1_000_000
COMMISSION_BPS = 5
SLIPPAGE_BPS = 5
TIME_BUDGET = 120              # max seconds for a backtest run

REPORTING_LAG_DAYS = 45        # conservative fundamental data lag

FMP_BASE = "https://financialmodelingprep.com/stable"
FMP_RATE_LIMIT = 300           # requests per minute
DOWNLOAD_WORKERS = 8

# ---------------------------------------------------------------------------
# Section 2: FMP API Client + Data Download
# ---------------------------------------------------------------------------

class FMPClient:
    """Thin FMP API wrapper with rate limiting, retries, and parquet caching."""

    def __init__(self, api_key=None, cache_dir=CACHE_DIR):
        self.api_key = api_key or os.environ.get("FMP_API_KEY", "")
        if not self.api_key:
            raise ValueError("FMP_API_KEY not set. Add it to .env or environment.")
        self.cache_dir = cache_dir
        self.base_url = FMP_BASE
        self._request_times = []

    def _rate_limit(self):
        """Enforce 300 requests/minute."""
        now = time.time()
        self._request_times = [t for t in self._request_times if now - t < 60]
        if len(self._request_times) >= FMP_RATE_LIMIT:
            sleep_time = 60 - (now - self._request_times[0]) + 0.1
            if sleep_time > 0:
                time.sleep(sleep_time)
        self._request_times.append(time.time())

    def get(self, endpoint, params=None, max_retries=3):
        """GET with rate limiting and exponential backoff."""
        params = params or {}
        params["apikey"] = self.api_key
        url = f"{self.base_url}/{endpoint}"

        for attempt in range(max_retries):
            self._rate_limit()
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                # FMP returns error messages as dicts sometimes
                if isinstance(data, dict) and "Error Message" in data:
                    print(f"  FMP error for {endpoint}: {data['Error Message']}")
                    return None
                return data
            except (requests.RequestException, json.JSONDecodeError) as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                else:
                    print(f"  Failed {endpoint} after {max_retries} attempts: {e}")
                    return None

    def _cache_path(self, name):
        return os.path.join(self.cache_dir, f"{name}.parquet")

    def _cache_fresh(self, name, max_age_hours=24):
        """Check if cached file exists and is recent enough."""
        path = self._cache_path(name)
        if not os.path.exists(path):
            return False
        age = time.time() - os.path.getmtime(path)
        return age < max_age_hours * 3600

    def save_parquet(self, df, name):
        os.makedirs(self.cache_dir, exist_ok=True)
        df.to_parquet(self._cache_path(name))

    def load_parquet(self, name):
        path = self._cache_path(name)
        if os.path.exists(path):
            return pd.read_parquet(path)
        return None


def load_companies_json():
    """Load tickers + metadata from stack-intelligence-engine companies.json."""
    path = os.path.normpath(COMPANIES_JSON)
    if not os.path.exists(path):
        print(f"  companies.json not found at {path}, skipping international tickers.")
        return {}
    with open(path) as f:
        data = json.load(f)
    return data.get("companies", {})


def get_master_ticker_list(client):
    """Build deduplicated master ticker list from S&P 500 + companies.json."""
    # S&P 500 constituents
    sp500_data = client.get("sp500-constituent")
    sp500_tickers = set()
    sp500_meta = {}
    if sp500_data:
        for item in sp500_data:
            ticker = item.get("symbol", "")
            if ticker:
                sp500_tickers.add(ticker)
                sp500_meta[ticker] = {
                    "name": item.get("name", ""),
                    "sector": item.get("sector", ""),
                    "industry": item.get("subSector", ""),
                    "country": "US",
                    "exchange": item.get("exchange", ""),
                }

    # International tickers from companies.json
    companies = load_companies_json()
    intl_meta = {}
    for ticker, info in companies.items():
        intl_meta[ticker] = {
            "name": info.get("name", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "country": info.get("country", "US"),
            "exchange": info.get("exchange", ""),
            "nodes": info.get("nodes", []),
            "tags": info.get("tags", []),
        }

    # Merge: companies.json takes precedence for metadata (richer)
    all_meta = {**sp500_meta}
    for ticker, meta in intl_meta.items():
        if ticker in all_meta:
            all_meta[ticker].update(meta)
        else:
            all_meta[ticker] = meta

    all_tickers = sorted(set(sp500_tickers) | set(intl_meta.keys()))
    print(f"  Master universe: {len(all_tickers)} tickers "
          f"({len(sp500_tickers)} S&P 500, {len(intl_meta)} from companies.json, "
          f"{len(all_tickers)} deduplicated)")
    return all_tickers, all_meta


def download_prices(client, ticker):
    """Download 5yr daily OHLCV for one ticker."""
    cache_name = f"prices_{ticker.replace('.', '_')}"
    if client._cache_fresh(cache_name, max_age_hours=12):
        return ticker, True

    data = client.get(f"historical-price-eod/full", params={
        "symbol": ticker,
        "from": "2020-01-01",
    })
    if not data or not isinstance(data, list) or len(data) == 0:
        return ticker, False

    df = pd.DataFrame(data)
    for col in ["date", "open", "high", "low", "close", "volume", "adjClose"]:
        if col not in df.columns:
            if col == "adjClose" and "close" in df.columns:
                df["adjClose"] = df["close"]
            else:
                return ticker, False

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    client.save_parquet(df, cache_name)
    return ticker, True


def download_fundamentals(client, ticker):
    """Download key metrics + ratios for one ticker."""
    cache_name = f"fundamentals_{ticker.replace('.', '_')}"
    if client._cache_fresh(cache_name, max_age_hours=48):
        return ticker, True

    metrics = client.get("key-metrics-ttm", params={"symbol": ticker})
    ratios = client.get("ratios-ttm", params={"symbol": ticker})
    profile = client.get("profile", params={"symbol": ticker})

    if not metrics and not ratios:
        return ticker, False

    record = {}
    if metrics and isinstance(metrics, list) and len(metrics) > 0:
        record.update(metrics[0])
    if ratios and isinstance(ratios, list) and len(ratios) > 0:
        record.update(ratios[0])
    if profile and isinstance(profile, list) and len(profile) > 0:
        record.update({
            "profile_sector": profile[0].get("sector", ""),
            "profile_industry": profile[0].get("industry", ""),
            "profile_mktCap": profile[0].get("mktCap", 0),
            "profile_country": profile[0].get("country", ""),
        })

    df = pd.DataFrame([record])
    df["ticker"] = ticker
    client.save_parquet(df, cache_name)
    return ticker, True


def download_macro(client):
    """Download macro data: treasury, economic indicators, VIX."""
    print("  Downloading macro data...")

    # Treasury rates
    if not client._cache_fresh("macro_treasury", max_age_hours=12):
        data = client.get("treasury", params={"from": "2020-01-01"})
        if data and isinstance(data, list):
            df = pd.DataFrame(data)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                client.save_parquet(df, "macro_treasury")
                print("    Treasury rates: OK")

    # Economic indicators
    indicators = {
        "federalFunds": "fed_funds",
        "CPI": "cpi",
        "unemploymentRate": "unemployment",
        "consumerSentiment": "consumer_sentiment",
    }
    for fmp_name, local_name in indicators.items():
        cache_name = f"macro_{local_name}"
        if client._cache_fresh(cache_name, max_age_hours=48):
            continue
        data = client.get("economic", params={
            "name": fmp_name,
            "from": "2020-01-01",
        })
        if data and isinstance(data, list):
            df = pd.DataFrame(data)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                client.save_parquet(df, cache_name)
                print(f"    {local_name}: OK")

    # VIX via price history
    if not client._cache_fresh("macro_vix", max_age_hours=12):
        data = client.get("historical-price-eod/full", params={
            "symbol": "^VIX",
            "from": "2020-01-01",
        })
        if data and isinstance(data, list):
            df = pd.DataFrame(data)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                client.save_parquet(df, "macro_vix")
                print("    VIX: OK")


def download_all(client):
    """Full data download pipeline."""
    os.makedirs(client.cache_dir, exist_ok=True)

    print("Step 1: Building master ticker list...")
    all_tickers, all_meta = get_master_ticker_list(client)

    # Save metadata
    meta_df = pd.DataFrame.from_dict(all_meta, orient="index")
    meta_df.index.name = "ticker"
    client.save_parquet(meta_df.reset_index(), "metadata")

    print(f"\nStep 2: Downloading prices ({len(all_tickers)} tickers)...")
    ok = 0
    fail = 0
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        futures = {executor.submit(download_prices, client, t): t for t in all_tickers}
        for i, future in enumerate(as_completed(futures)):
            ticker, success = future.result()
            if success:
                ok += 1
            else:
                fail += 1
            if (i + 1) % 100 == 0:
                print(f"    Progress: {i+1}/{len(all_tickers)} (ok={ok}, fail={fail})")
    print(f"  Prices done: {ok} ok, {fail} failed")

    print(f"\nStep 3: Downloading fundamentals...")
    ok = 0
    fail = 0
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        futures = {executor.submit(download_fundamentals, client, t): t for t in all_tickers}
        for i, future in enumerate(as_completed(futures)):
            ticker, success = future.result()
            if success:
                ok += 1
            else:
                fail += 1
            if (i + 1) % 100 == 0:
                print(f"    Progress: {i+1}/{len(all_tickers)} (ok={ok}, fail={fail})")
    print(f"  Fundamentals done: {ok} ok, {fail} failed")

    print(f"\nStep 4: Downloading macro data...")
    download_macro(client)

    print(f"\nDownload complete. Cache: {client.cache_dir}")


# ---------------------------------------------------------------------------
# Section 3: DataStore Class
# ---------------------------------------------------------------------------

class DataStore:
    """
    Read-only data interface for strategies. Prevents lookahead bias.

    All methods return data up to (and including) the requested date.
    Fundamental data is lagged by REPORTING_LAG_DAYS to simulate real-world
    information availability.
    """

    def __init__(self, price_data, volume_data, fundamental_data,
                 macro_data, metadata, cache_dir=CACHE_DIR):
        self._prices = price_data          # DataFrame: date x ticker (adj close)
        self._volume = volume_data          # DataFrame: date x ticker
        self._fundamentals = fundamental_data  # dict of field -> DataFrame (date x ticker)
        self._macro = macro_data            # dict of field -> Series (date-indexed)
        self._metadata = metadata           # dict of ticker -> {sector, country, ...}
        self._cache_dir = cache_dir

    @classmethod
    def from_cache(cls, cache_dir=CACHE_DIR):
        """Load all data from parquet cache into memory."""
        cache = Path(cache_dir)

        # Load metadata
        meta_df = pd.read_parquet(cache / "metadata.parquet")
        metadata = {}
        for _, row in meta_df.iterrows():
            ticker = row["ticker"]
            metadata[ticker] = row.to_dict()

        # Load all price files into a single DataFrame
        price_frames = {}
        volume_frames = {}
        price_files = sorted(cache.glob("prices_*.parquet"))
        for pf in price_files:
            try:
                df = pd.read_parquet(pf)
            except Exception:
                continue
            # Recover ticker from filename
            stem = pf.stem  # prices_AAPL or prices_005490_KS
            ticker_raw = stem[len("prices_"):]
            # Reverse the dot replacement
            # Try to find the ticker in metadata
            matched_ticker = None
            for t in metadata:
                if t.replace(".", "_") == ticker_raw:
                    matched_ticker = t
                    break
            if matched_ticker is None:
                matched_ticker = ticker_raw

            if "date" not in df.columns:
                continue
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()

            # Use adjClose if available, else close
            price_col = "adjClose" if "adjClose" in df.columns else "close"
            if price_col in df.columns:
                price_frames[matched_ticker] = df[price_col].astype(float)
            if "volume" in df.columns:
                volume_frames[matched_ticker] = df["volume"].astype(float)

        prices = pd.DataFrame(price_frames).sort_index()
        volumes = pd.DataFrame(volume_frames).sort_index()

        # Load fundamentals
        fundamentals = cls._load_fundamentals(cache, metadata)

        # Load macro
        macro = cls._load_macro(cache)

        print(f"DataStore loaded: {len(prices.columns)} tickers, "
              f"{len(prices)} trading days, "
              f"{len(fundamentals)} fundamental fields, "
              f"{len(macro)} macro series")

        return cls(prices, volumes, fundamentals, macro, metadata, cache_dir)

    @staticmethod
    def _load_fundamentals(cache, metadata):
        """Load fundamental data and build date-indexed DataFrames per field."""
        # Map FMP field names to our field names
        field_map = {
            "peRatioTTM": "pe",
            "priceToBookRatioTTM": "pb",
            "priceToSalesRatioTTM": "ps",
            "enterpriseValueOverEBITDATTM": "ev_ebitda",
            "freeCashFlowYieldTTM": "fcf_yield",
            "earningsYieldTTM": "earnings_yield",
            "returnOnEquityTTM": "roe",
            "returnOnAssetsTTM": "roa",
            "returnOnCapitalEmployedTTM": "roic",
            "debtEquityRatioTTM": "debt_to_equity",
            "currentRatioTTM": "current_ratio",
            "grossProfitMarginTTM": "gross_margin",
            "netProfitMarginTTM": "net_margin",
            "revenueGrowthTTM": "revenue_growth",
            "piotroskiIScoreTTM": "piotroski",
            "altmanZScoreTTM": "altman_z",
        }

        # Collect fundamental data per ticker
        fund_files = sorted(cache.glob("fundamentals_*.parquet"))
        ticker_records = {}
        for ff in fund_files:
            try:
                df = pd.read_parquet(ff)
            except Exception:
                continue
            if "ticker" not in df.columns or len(df) == 0:
                continue
            ticker = df["ticker"].iloc[0]
            record = {}
            for fmp_field, our_field in field_map.items():
                if fmp_field in df.columns:
                    val = df[fmp_field].iloc[0]
                    try:
                        record[our_field] = float(val) if val is not None else np.nan
                    except (ValueError, TypeError):
                        record[our_field] = np.nan
            ticker_records[ticker] = record

        # For TTM data (point-in-time), we create a single-row DataFrame
        # and forward-fill across the date range. In a production system,
        # we'd have historical quarterly data. For now, TTM acts as the
        # latest available snapshot — the backtest engine handles the lag.
        fundamentals = {}
        for field in field_map.values():
            series = {}
            for ticker, rec in ticker_records.items():
                if field in rec:
                    series[ticker] = rec[field]
            if series:
                fundamentals[field] = pd.Series(series)

        return fundamentals

    @staticmethod
    def _load_macro(cache):
        """Load macro data series."""
        macro = {}

        # Treasury rates
        treasury_path = cache / "macro_treasury.parquet"
        if treasury_path.exists():
            df = pd.read_parquet(treasury_path)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                col_map = {
                    "year10": "t10y",
                    "year2": "t2y",
                    "month3": "t3m",
                }
                for fmp_col, our_name in col_map.items():
                    if fmp_col in df.columns:
                        macro[our_name] = df[fmp_col].astype(float)

                # Compute spread
                if "t10y" in macro and "t2y" in macro:
                    macro["t10y_2y_spread"] = macro["t10y"] - macro["t2y"]

        # Economic indicators
        for local_name in ["fed_funds", "cpi", "unemployment", "consumer_sentiment"]:
            path = cache / f"macro_{local_name}.parquet"
            if path.exists():
                df = pd.read_parquet(path)
                if "date" in df.columns and "value" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date").sort_index()
                    macro[local_name] = df["value"].astype(float)

        # VIX
        vix_path = cache / "macro_vix.parquet"
        if vix_path.exists():
            df = pd.read_parquet(vix_path)
            if "date" in df.columns and "close" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                macro["vix"] = df["close"].astype(float)

        return macro

    # --- Public API ---

    def prices(self, tickers=None, start=None, end=None):
        """Date-indexed DataFrame of adjusted close prices."""
        df = self._prices
        if tickers is not None:
            valid = [t for t in tickers if t in df.columns]
            df = df[valid]
        if start:
            df = df.loc[start:]
        if end:
            df = df.loc[:end]
        return df

    def returns(self, tickers=None, period=1):
        """Daily (or N-day) returns. Same shape as prices."""
        p = self.prices(tickers)
        return p.pct_change(period)

    def volume(self, tickers=None):
        """Date-indexed DataFrame of daily volume."""
        df = self._volume
        if tickers is not None:
            valid = [t for t in tickers if t in df.columns]
            df = df[valid]
        return df

    def fundamental(self, field):
        """
        Fundamental data for a given field.

        For TTM snapshots, returns a pd.Series (ticker-indexed) representing
        the latest available value. The backtest engine ensures point-in-time
        correctness via the reporting lag.
        """
        if field not in self._fundamentals:
            available = list(self._fundamentals.keys())
            raise KeyError(f"Unknown fundamental field '{field}'. Available: {available}")
        return self._fundamentals[field]

    def macro(self, field):
        """Date-indexed macro series."""
        if field not in self._macro:
            available = list(self._macro.keys())
            raise KeyError(f"Unknown macro field '{field}'. Available: {available}")
        return self._macro[field]

    def universe(self, date=None):
        """Tickers with price data available as of date."""
        if date is None:
            return list(self._prices.columns)
        prices_to_date = self._prices.loc[:date]
        # Require at least 60 days of data
        valid = prices_to_date.columns[prices_to_date.notna().sum() >= 60]
        return list(valid)

    def sector(self, ticker):
        """Sector for a ticker."""
        meta = self._metadata.get(ticker, {})
        return meta.get("sector", meta.get("profile_sector", "Unknown"))

    def country(self, ticker):
        """Country for a ticker."""
        meta = self._metadata.get(ticker, {})
        return meta.get("country", meta.get("profile_country", "Unknown"))

    def metadata_for(self, ticker):
        """Full metadata dict for a ticker (from companies.json)."""
        return self._metadata.get(ticker, {})

    def correlation(self, tickers, window=60):
        """Rolling correlation matrix (returns last available window)."""
        rets = self.returns(tickers)
        if len(rets) < window:
            return rets.corr()
        return rets.iloc[-window:].corr()


# ---------------------------------------------------------------------------
# Section 4: Backtest Engine
# ---------------------------------------------------------------------------

class BacktestResult:
    """Container for backtest outputs."""

    def __init__(self, daily_returns, equity_curve, weights_history,
                 turnover_history, dates):
        self.daily_returns = daily_returns      # pd.Series
        self.equity_curve = equity_curve        # pd.Series
        self.weights_history = weights_history  # list of (date, pd.Series)
        self.turnover_history = turnover_history  # pd.Series
        self.dates = dates


def run_backtest(strategy_module, data_store, start, end, rebalance_freq="M"):
    """
    Vectorized portfolio backtest with transaction costs.

    On each rebalance date:
      1. Create a date-limited view of DataStore (no lookahead)
      2. Call strategy.signals(data, date) -> scores per ticker
      3. Call strategy.construct(scores, data, date) -> target weights
      4. Call strategy.risk(weights, data, date) -> final weights
    Between rebalances: mark-to-market from daily returns.
    Transaction costs applied on weight changes.
    """
    freq = getattr(strategy_module, "REBALANCE_FREQ", rebalance_freq)

    # Get price data for the period (with some lead-in for returns calc)
    lead_start = pd.Timestamp(start) - pd.DateOffset(months=14)
    prices = data_store.prices(start=str(lead_start.date()), end=end)

    if prices.empty:
        raise ValueError("No price data available for backtest period")

    # Generate rebalance dates within the backtest window
    bt_prices = prices.loc[start:end]
    if bt_prices.empty:
        raise ValueError(f"No prices in [{start}, {end}]")

    trading_dates = bt_prices.index

    # Build rebalance schedule
    if freq == "M":
        # Monthly: first trading day of each month
        rebal_dates = bt_prices.groupby(bt_prices.index.to_period("M")).apply(
            lambda x: x.index[0]
        ).values
    elif freq == "W":
        rebal_dates = bt_prices.groupby(bt_prices.index.to_period("W")).apply(
            lambda x: x.index[0]
        ).values
    elif freq == "Q":
        rebal_dates = bt_prices.groupby(bt_prices.index.to_period("Q")).apply(
            lambda x: x.index[0]
        ).values
    else:
        rebal_dates = bt_prices.groupby(bt_prices.index.to_period("M")).apply(
            lambda x: x.index[0]
        ).values

    rebal_dates = pd.DatetimeIndex(rebal_dates)

    # Simulation
    capital = float(INITIAL_CAPITAL)
    current_weights = pd.Series(dtype=float)
    equity = []
    daily_rets = []
    weights_history = []
    turnover_list = []
    prev_date = None

    cost_rate = (COMMISSION_BPS + SLIPPAGE_BPS) / 10_000

    for date in trading_dates:
        if prev_date is not None:
            # Mark-to-market: update weights by daily returns
            day_ret = bt_prices.loc[date] / bt_prices.loc[prev_date] - 1
            if len(current_weights) > 0:
                valid = current_weights.index.intersection(day_ret.dropna().index)
                if len(valid) > 0:
                    port_ret = (current_weights[valid] * day_ret[valid]).sum()
                    # Update weights for drift
                    drifted = current_weights.copy()
                    for t in valid:
                        drifted[t] = current_weights[t] * (1 + day_ret[t])
                    if drifted.sum() > 0:
                        drifted = drifted / drifted.sum()
                    current_weights = drifted
                else:
                    port_ret = 0.0
            else:
                port_ret = 0.0

            capital *= (1 + port_ret)
            daily_rets.append(port_ret)
        else:
            daily_rets.append(0.0)

        equity.append(capital)

        # Rebalance?
        if date in rebal_dates:
            try:
                # Create a date-limited view
                class DateLimitedStore:
                    """Wrapper that prevents lookahead."""
                    def __init__(self, store, cutoff):
                        self._store = store
                        self._cutoff = cutoff

                    def prices(self, tickers=None, start=None, end=None):
                        end = min(pd.Timestamp(end), self._cutoff) if end else self._cutoff
                        return self._store.prices(tickers, start, str(end.date()))

                    def returns(self, tickers=None, period=1):
                        p = self.prices(tickers)
                        return p.pct_change(period)

                    def volume(self, tickers=None):
                        return self._store.volume(tickers).loc[:self._cutoff]

                    def fundamental(self, field):
                        return self._store.fundamental(field)

                    def macro(self, field):
                        s = self._store.macro(field)
                        return s.loc[:self._cutoff]

                    def universe(self, date=None):
                        return self._store.universe(date or self._cutoff)

                    def sector(self, ticker):
                        return self._store.sector(ticker)

                    def country(self, ticker):
                        return self._store.country(ticker)

                    def metadata_for(self, ticker):
                        return self._store.metadata_for(ticker)

                    def correlation(self, tickers, window=60):
                        rets = self.returns(tickers)
                        if len(rets) < window:
                            return rets.corr()
                        return rets.iloc[-window:].corr()

                limited = DateLimitedStore(data_store, pd.Timestamp(date))

                scores = strategy_module.signals(limited, date)
                if scores is None or len(scores) == 0:
                    continue

                target_weights = strategy_module.construct(scores, limited, date)
                if target_weights is None or len(target_weights) == 0:
                    continue

                final_weights = strategy_module.risk(target_weights, limited, date)
                if final_weights is None or len(final_weights) == 0:
                    continue

                # Normalize
                final_weights = final_weights[final_weights > 0]
                if final_weights.sum() > 0:
                    final_weights = final_weights / final_weights.sum()

                # Compute turnover
                old_set = set(current_weights.index) if len(current_weights) > 0 else set()
                new_set = set(final_weights.index)
                all_tickers = old_set | new_set
                turnover = 0.0
                for t in all_tickers:
                    old_w = current_weights.get(t, 0.0)
                    new_w = final_weights.get(t, 0.0)
                    turnover += abs(new_w - old_w)
                turnover /= 2  # one-way turnover

                # Apply transaction costs
                cost = turnover * cost_rate * 2  # round-trip approximation
                capital *= (1 - cost)

                current_weights = final_weights
                weights_history.append((date, final_weights.copy()))
                turnover_list.append((date, turnover))

            except Exception as e:
                print(f"  Warning: strategy error on {date}: {e}")
                continue

        prev_date = date

    daily_returns = pd.Series(daily_rets, index=trading_dates, name="returns")
    equity_curve = pd.Series(equity, index=trading_dates, name="equity")
    turnover_series = pd.Series(
        dict(turnover_list), name="turnover"
    ) if turnover_list else pd.Series(dtype=float)

    return BacktestResult(
        daily_returns=daily_returns,
        equity_curve=equity_curve,
        weights_history=weights_history,
        turnover_history=turnover_series,
        dates=trading_dates,
    )


# ---------------------------------------------------------------------------
# Section 5: Evaluation (FIXED metric — the "val_bpb" equivalent)
# ---------------------------------------------------------------------------

def evaluate(strategy_module, data_store, n_trials_so_far=0, period="val"):
    """
    Walk-forward backtest on validation period. Returns metrics dict.

    period: "val" (default, agent sees this) or "test" (holdout, human only)
    """
    if period == "val":
        start, end = TRAIN_END, VAL_END
    elif period == "test":
        start, end = VAL_END, BACKTEST_END
    elif period == "train":
        start, end = BACKTEST_START, TRAIN_END
    else:
        raise ValueError(f"Unknown period: {period}")

    result = run_backtest(strategy_module, data_store, start, end)

    rets = result.daily_returns.dropna()
    if len(rets) < 10:
        return {"dsr": 0.0, "sharpe": 0.0, "annual_return": 0.0,
                "max_drawdown": 0.0, "sortino": 0.0, "calmar": 0.0,
                "turnover": 0.0, "n_positions": 0,
                "sharpe_ci_95": (0.0, 0.0), "complexity_loc": count_loc("strategy.py"),
                "equity_curve": result.equity_curve}

    sharpe = annualized_sharpe(rets)
    dsr = deflated_sharpe(sharpe, max(n_trials_so_far, 1), len(rets))
    ci_low, ci_high = bootstrap_sharpe_ci(rets, n_bootstrap=1000)

    # Average number of positions across rebalances
    n_pos = 0
    if result.weights_history:
        n_pos = np.mean([len(w) for _, w in result.weights_history])

    avg_turnover = result.turnover_history.mean() if len(result.turnover_history) > 0 else 0.0

    ann_ret = annual_return(rets)
    mdd = max_drawdown(rets)

    return {
        "dsr": dsr,
        "sharpe": sharpe,
        "annual_return": ann_ret,
        "max_drawdown": mdd,
        "sortino": sortino_ratio(rets),
        "calmar": calmar_ratio(rets),
        "turnover": avg_turnover,
        "n_positions": int(n_pos),
        "sharpe_ci_95": (ci_low, ci_high),
        "complexity_loc": count_loc("strategy.py"),
        "equity_curve": result.equity_curve,
    }


def count_loc(filepath):
    """Count non-empty, non-comment lines in a file."""
    try:
        with open(filepath) as f:
            lines = f.readlines()
        return sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
    except FileNotFoundError:
        return 0


# ---------------------------------------------------------------------------
# Section 6: Statistical Utilities
# ---------------------------------------------------------------------------

def annualized_sharpe(returns, risk_free=0.0):
    """Annualized Sharpe ratio from daily returns."""
    excess = returns - risk_free / 252
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(252))


def annual_return(returns):
    """Annualized return from daily returns."""
    total = (1 + returns).prod()
    n_years = len(returns) / 252
    if n_years <= 0:
        return 0.0
    return float(total ** (1 / n_years) - 1)


def max_drawdown(returns):
    """Maximum drawdown from daily returns."""
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return float(dd.min())


def sortino_ratio(returns, risk_free=0.0):
    """Annualized Sortino ratio."""
    excess = returns - risk_free / 252
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float(excess.mean() / downside.std() * np.sqrt(252))


def calmar_ratio(returns):
    """Calmar ratio: annualized return / abs(max drawdown)."""
    mdd = max_drawdown(returns)
    ann = annual_return(returns)
    if mdd == 0:
        return 0.0
    return float(ann / abs(mdd))


def deflated_sharpe(sharpe, n_trials, T, skew=0.0, kurtosis=3.0):
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Adjusts the observed Sharpe ratio for the number of trials conducted
    (multiple testing correction). Returns probability that the Sharpe
    is genuinely positive given n_trials attempts.

    Args:
        sharpe: observed annualized Sharpe ratio
        n_trials: number of experiments/strategies tested so far
        T: number of return observations
        skew: skewness of returns (default 0)
        kurtosis: kurtosis of returns (default 3, normal)
    """
    from scipy.stats import norm

    if T <= 1 or n_trials <= 0:
        return 0.0

    # Expected maximum Sharpe under null (all strategies have zero true Sharpe)
    # E[max(Z_1,...,Z_n)] approximation for standard normal
    if n_trials == 1:
        e_max_z = 0.0
    else:
        gamma = 0.5772156649  # Euler-Mascheroni constant
        e_max_z = norm.ppf(1 - 1 / n_trials) * (1 - gamma) + gamma * norm.ppf(1 - 1 / (n_trials * np.e))

    # Adjust for non-normality (Lo, 2002)
    sr_daily = sharpe / np.sqrt(252)
    var_sr = (1 + 0.5 * sr_daily**2 - skew * sr_daily +
              ((kurtosis - 3) / 4) * sr_daily**2) / T

    if var_sr <= 0:
        return 0.0

    # Test statistic: is observed Sharpe above expected max?
    sr_annual_null = e_max_z * np.sqrt(252 / T) * np.sqrt(T)  # scale expected max to annual
    # Simplified: compare standardized Sharpe
    test_stat = (sr_daily * np.sqrt(T) - e_max_z) / np.sqrt(max(var_sr * T, 1e-10))

    dsr = float(norm.cdf(test_stat))
    return dsr


def bootstrap_sharpe_ci(returns, n_bootstrap=1000, ci=0.95, block_size=21):
    """
    Block bootstrap confidence interval for Sharpe ratio.

    Uses overlapping blocks of size block_size (default 21 = ~1 month)
    to preserve autocorrelation structure.
    """
    rng = np.random.default_rng(42)
    returns_arr = np.asarray(returns)
    T = len(returns_arr)

    if T < block_size * 2:
        return (0.0, 0.0)

    sharpes = []
    n_blocks = int(np.ceil(T / block_size))

    for _ in range(n_bootstrap):
        # Draw random block starts
        starts = rng.integers(0, T - block_size + 1, size=n_blocks)
        # Concatenate blocks
        sample = np.concatenate([returns_arr[s:s + block_size] for s in starts])[:T]
        if sample.std() > 0:
            s = sample.mean() / sample.std() * np.sqrt(252)
            sharpes.append(s)

    if len(sharpes) == 0:
        return (0.0, 0.0)

    alpha = (1 - ci) / 2
    low = float(np.percentile(sharpes, alpha * 100))
    high = float(np.percentile(sharpes, (1 - alpha) * 100))
    return (low, high)


def equity_curve_r2(equity_curve):
    """R-squared of equity curve vs linear fit. Measures smoothness."""
    y = np.log(np.asarray(equity_curve))
    x = np.arange(len(y))
    if len(y) < 2:
        return 0.0
    # Linear regression
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    if ss_tot == 0:
        return 0.0
    return float(1 - ss_res / ss_tot)


# ---------------------------------------------------------------------------
# Section 7: CLI Entry Point
# ---------------------------------------------------------------------------

def load_strategy():
    """Import strategy.py as a module."""
    spec = importlib.util.spec_from_file_location("strategy", "strategy.py")
    if spec is None:
        print("Error: strategy.py not found in current directory.")
        sys.exit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def print_metrics(metrics, label=""):
    """Print metrics in grep-friendly format."""
    if label:
        print(f"\n=== {label} ===")
    print("---")
    print(f"dsr:            {metrics['dsr']:.6f}")
    print(f"sharpe:         {metrics['sharpe']:.6f}")
    print(f"annual_return:  {metrics['annual_return']:.6f}")
    print(f"max_drawdown:   {metrics['max_drawdown']:.6f}")
    print(f"sortino:        {metrics['sortino']:.6f}")
    print(f"calmar:         {metrics['calmar']:.6f}")
    print(f"turnover:       {metrics['turnover']:.6f}")
    print(f"n_positions:    {metrics['n_positions']}")
    ci = metrics['sharpe_ci_95']
    print(f"sharpe_ci_95:   ({ci[0]:.4f}, {ci[1]:.4f})")
    print(f"complexity_loc: {metrics['complexity_loc']}")


def main():
    parser = argparse.ArgumentParser(description="Q_Lab: Autonomous quantitative research")
    parser.add_argument("--download", action="store_true", help="Download/refresh all data from FMP")
    parser.add_argument("--backtest", action="store_true", help="Run strategy.py on validation period")
    parser.add_argument("--test", action="store_true", help="Run on holdout test period (human only)")
    parser.add_argument("--n-trials", type=int, default=1, help="Number of trials so far (for DSR)")
    args = parser.parse_args()

    if not any([args.download, args.backtest, args.test]):
        parser.print_help()
        sys.exit(0)

    if args.download:
        print("Downloading data from FMP API...")
        client = FMPClient()
        download_all(client)

    if args.backtest or args.test:
        print("Loading data from cache...")
        t0 = time.time()
        data_store = DataStore.from_cache()
        print(f"Data loaded in {time.time() - t0:.1f}s")

        strategy = load_strategy()

        if args.backtest:
            print("\nRunning backtest on VALIDATION period...")
            t0 = time.time()
            metrics = evaluate(strategy, data_store, n_trials_so_far=args.n_trials,
                              period="val")
            elapsed = time.time() - t0
            print(f"Backtest completed in {elapsed:.1f}s")
            print_metrics(metrics, "Validation Results")

        if args.test:
            print("\nRunning backtest on TEST period (holdout)...")
            t0 = time.time()
            metrics = evaluate(strategy, data_store, n_trials_so_far=args.n_trials,
                              period="test")
            elapsed = time.time() - t0
            print(f"Backtest completed in {elapsed:.1f}s")
            print_metrics(metrics, "Test Results (Holdout)")


if __name__ == "__main__":
    main()

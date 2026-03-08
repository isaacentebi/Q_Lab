"""Quantitative strategy. Agent modifies this file."""

import numpy as np
import pandas as pd

# === CONFIGURATION ===
NUM_HOLDINGS = 75
REBALANCE_FREQ = "M"
LONG_ONLY = True

# === SIGNAL GENERATION ===
def signals(data, date):
    """Score each ticker. Higher = more bullish. Returns pd.Series."""
    universe = data.universe(date)
    prices = data.prices(universe)
    prices_to_date = prices.loc[:date]

    if len(prices_to_date) < 252:
        return pd.Series(dtype=float)

    # Filter: US only
    us_tickers = [t for t in universe if data.country(t) in ("US", "")]
    if len(us_tickers) < 50:
        us_tickers = universe
    cols = [t for t in us_tickers if t in prices_to_date.columns]
    if len(cols) == 0:
        return pd.Series(dtype=float)
    prices_to_date = prices_to_date[cols]

    # Momentum: blended 12-1 and 6-1 month
    ret_12m = prices_to_date.iloc[-1] / prices_to_date.iloc[-252] - 1
    ret_1m = prices_to_date.iloc[-1] / prices_to_date.iloc[-21] - 1
    mom_12_1 = ret_12m - ret_1m

    ret_6m = prices_to_date.iloc[-1] / prices_to_date.iloc[-126] - 1
    mom_6_1 = ret_6m - ret_1m

    momentum = 0.5 * mom_12_1 + 0.5 * mom_6_1

    # Value: earnings yield
    try:
        value = data.fundamental("earnings_yield")
        value = value.reindex(cols)
    except Exception:
        value = pd.Series(0.0, index=cols)

    # Quality: ROE + Piotroski
    try:
        roe = data.fundamental("roe")
        roe = roe.reindex(cols)
    except Exception:
        roe = pd.Series(0.0, index=cols)

    try:
        piotroski = data.fundamental("piotroski")
        piotroski = piotroski.reindex(cols)
    except Exception:
        piotroski = pd.Series(0.0, index=cols)

    # Low volatility signal
    rets_60d = prices_to_date.pct_change().iloc[-63:]
    vol_60d = rets_60d.std()
    low_vol = -vol_60d  # lower vol -> higher score

    # Rank everything
    mom_rank = momentum.rank(pct=True)
    val_rank = value.rank(pct=True)
    roe_rank = roe.rank(pct=True)
    pio_rank = piotroski.rank(pct=True)
    vol_rank = low_vol.rank(pct=True)

    quality_rank = 0.5 * roe_rank + 0.5 * pio_rank

    score = 0.30 * mom_rank + 0.25 * val_rank + 0.25 * quality_rank + 0.20 * vol_rank
    return score.dropna()

# === PORTFOLIO CONSTRUCTION ===
def construct(scores, data, date):
    """Convert scores to target weights. Returns pd.Series."""
    top = scores.nlargest(NUM_HOLDINGS)

    # Inverse-volatility weighting
    prices = data.prices(list(top.index))
    prices_to_date = prices.loc[:date]
    if len(prices_to_date) >= 63:
        rets = prices_to_date.pct_change().iloc[-63:]
        vol = rets.std()
        vol = vol.reindex(top.index).fillna(vol.median())
        vol = vol.clip(lower=vol.quantile(0.05))
        inv_vol = 1.0 / vol
        weights = inv_vol / inv_vol.sum()
    else:
        weights = pd.Series(1.0 / len(top), index=top.index)

    return weights

# === RISK MANAGEMENT ===
def risk(weights, data, date):
    """Apply risk constraints. Returns pd.Series."""
    # 3% max per position
    weights = weights.clip(upper=0.03)

    # 30% max per sector
    sectors = {}
    for t in weights.index:
        s = data.sector(t)
        sectors.setdefault(s, []).append(t)

    for sector, tickers in sectors.items():
        sector_weight = weights[tickers].sum()
        if sector_weight > 0.30:
            scale = 0.30 / sector_weight
            weights[tickers] *= scale

    total = weights.sum()
    if total > 0:
        weights = weights / total
    return weights

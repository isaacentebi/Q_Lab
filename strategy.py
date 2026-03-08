"""Quantitative strategy. Agent modifies this file."""

import numpy as np
import pandas as pd

# === CONFIGURATION ===
NUM_HOLDINGS = 50
REBALANCE_FREQ = "M"  # monthly
LONG_ONLY = True

# === SIGNAL GENERATION ===
def signals(data, date):
    """Score each ticker. Higher = more bullish. Returns pd.Series."""
    universe = data.universe(date)
    prices = data.prices(universe)
    prices_to_date = prices.loc[:date]

    if len(prices_to_date) < 252:
        return pd.Series(dtype=float)

    # Momentum: 12-month return minus 1-month return (skip recent month)
    if len(prices_to_date) >= 252:
        ret_12m = prices_to_date.iloc[-1] / prices_to_date.iloc[-252] - 1
    else:
        ret_12m = pd.Series(0.0, index=prices_to_date.columns)

    if len(prices_to_date) >= 21:
        ret_1m = prices_to_date.iloc[-1] / prices_to_date.iloc[-21] - 1
    else:
        ret_1m = pd.Series(0.0, index=prices_to_date.columns)

    momentum = ret_12m - ret_1m

    # Value: earnings yield
    try:
        value = data.fundamental("earnings_yield")
        value = value.reindex(universe)
    except (KeyError, Exception):
        value = pd.Series(0.0, index=universe)

    # Combine: rank-based to handle different scales
    mom_rank = momentum.rank(pct=True)
    val_rank = value.rank(pct=True)

    score = 0.5 * mom_rank + 0.5 * val_rank
    return score.dropna()

# === PORTFOLIO CONSTRUCTION ===
def construct(scores, data, date):
    """Convert scores to target weights. Returns pd.Series."""
    top = scores.nlargest(NUM_HOLDINGS)
    # Equal weight
    weights = pd.Series(1.0 / len(top), index=top.index)
    return weights

# === RISK MANAGEMENT ===
def risk(weights, data, date):
    """Apply risk constraints. Returns pd.Series."""
    # 5% max per position
    weights = weights.clip(upper=0.05)
    total = weights.sum()
    if total > 0:
        weights = weights / total
    return weights

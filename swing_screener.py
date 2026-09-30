"""
Apply filters, compute score, return picks.
Ranking formula is unchanged from the previous version.
"""
import logging
import time

from swing_config import (
    EARNINGS_HARD_EXCLUDE_DAYS, MAX_5D_PRIOR_GAIN, MAX_GAIN_PCT,
    MAX_PRICE, MIN_AVG_DOLLAR_VOL, MIN_GAIN_PCT,
    MIN_PRICE, MIN_VOLUME_RATIO, NUM_PICKS,
)
from swing_data import StockData, get_stock_data, get_yahoo_gainers

log = logging.getLogger(__name__)


def _apply_filters(d: StockData) -> None:
    """Set d.excluded / d.exclude_reason on the first hard-filter failure."""
    p = d.price
    if not (MIN_PRICE <= p <= MAX_PRICE):
        d.excluded, d.exclude_reason = True, f"price ${p:.2f} outside ${MIN_PRICE}–${MAX_PRICE}"
        return
    if d.avg_dollar_vol < MIN_AVG_DOLLAR_VOL:
        d.excluded, d.exclude_reason = True, f"avg dollar vol ${d.avg_dollar_vol / 1e6:.1f}M < $5M"
        return
    if d.gain_pct < MIN_GAIN_PCT:
        d.excluded, d.exclude_reason = True, f"only up {d.gain_pct:.1f}% today"
        return
    if d.gain_pct > MAX_GAIN_PCT:
        d.excluded, d.exclude_reason = True, f"already up {d.gain_pct:.1f}% today"
        return
    if d.volume_ratio < MIN_VOLUME_RATIO:
        d.excluded, d.exclude_reason = True, f"volume {d.volume_ratio:.1f}x avg (need {MIN_VOLUME_RATIO}x)"
        return
    if not d.above_ma20:
        d.excluded, d.exclude_reason = True, f"below 20MA ${d.ma20:.2f}"
        return
    if d.prior_5d_gain > MAX_5D_PRIOR_GAIN:
        d.excluded, d.exclude_reason = True, f"already up {d.prior_5d_gain:.1f}% prior 5 days"
        return
    if d.earnings_days_away is not None and 0 <= d.earnings_days_away <= EARNINGS_HARD_EXCLUDE_DAYS:
        d.excluded, d.exclude_reason = (
            True,
            f"earnings in {d.earnings_days_away}d (within {EARNINGS_HARD_EXCLUDE_DAYS}d exclusion window)",
        )
        return


def _score(d: StockData) -> float:
    """Unchanged ranking formula."""
    vol_score = min(d.volume_ratio / 2.0, 2.5)

    g = d.gain_pct
    if 3.0 <= g <= 8.0:
        gain_score = 2.5
    elif g < 3.0:
        gain_score = g / 3.0 * 2.5
    else:
        gain_score = max(0.0, 2.5 - (g - 8.0) * 0.3)

    atr_score = min(d.atr_pct / 3.0 * 1.5, 1.5)
    ext_score = (
        1.5 if d.pct_from_52w_high > -10
        else max(0.0, 1.5 + d.pct_from_52w_high * 0.1)
    )
    return round(vol_score + gain_score + atr_score + ext_score, 2)


def run_screen(
    tickers: list[str] | None = None,
) -> tuple[list[StockData], list[StockData]]:
    """
    Return (picks, excluded).
    Pass tickers to bypass Yahoo gainers (used for --ticker dry-runs).
    """
    if tickers is None:
        tickers = get_yahoo_gainers()
        log.info("Fetched %d gainers from Yahoo", len(tickers))
    else:
        log.info("Analyzing %d provided tickers", len(tickers))

    all_candidates: list[StockData] = []
    for ticker in tickers:
        if any(c in ticker for c in ("-", "^", "/")):
            continue
        d = get_stock_data(ticker)
        if d is None:
            continue
        _apply_filters(d)
        if not d.excluded:
            d.score = _score(d)
        all_candidates.append(d)
        time.sleep(0.2)

    passed = sorted(
        [d for d in all_candidates if not d.excluded],
        key=lambda x: x.score,
        reverse=True,
    )
    excluded = [d for d in all_candidates if d.excluded]
    log.info(
        "Done: %d passed filters, %d excluded, %d picks",
        len(passed), len(excluded), min(len(passed), NUM_PICKS),
    )
    return passed[:NUM_PICKS], excluded

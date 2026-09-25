"""
Simple momentum screener — buy stocks moving up today on high volume.

Filters (any fail → excluded):
  1. Price $10–$200
  2. Avg dollar volume >= $5M/day
  3. Up 2–12% today
  4. Volume >= 1.5× 20-day average
  5. Price above 20-day MA (in an uptrend)
  6. Not already up >15% over the prior 5 days

Scoring rewards: volume surge + gain in sweet spot (3–8%) + volatility + near 52w high
"""
import logging
import time
from dataclasses import dataclass

import pandas as pd
import requests
import yfinance as yf

from swing_config import (
    ATR_STOP_MULT, MAX_5D_PRIOR_GAIN, MAX_GAIN_PCT,
    MAX_PRICE, MIN_AVG_DOLLAR_VOL, MIN_GAIN_PCT,
    MIN_PRICE, MIN_VOLUME_RATIO, NUM_PICKS, RR_TARGET,
)

log = logging.getLogger(__name__)


@dataclass
class Pick:
    ticker: str
    company: str
    price: float
    gain_pct: float
    volume_ratio: float
    stop: float
    target: float
    rr: float
    atr_pct: float
    above_ma20: bool
    score: float = 0.0
    excluded: bool = False
    exclude_reason: str = ""


def _get_yahoo_gainers() -> list[str]:
    url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    params = {"formatted": "false", "scrIds": "day_gainers", "count": 50}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        quotes = r.json()["finance"]["result"][0]["quotes"]
        return [q["symbol"] for q in quotes if "symbol" in q]
    except Exception as exc:
        log.warning("Yahoo gainers fetch failed: %s", exc)
        return []


def _analyze(ticker: str) -> Pick | None:
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="65d")
        if len(hist) < 22:
            return None

        info = tk.fast_info
        price = float(getattr(info, "last_price", None) or hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2])
        gain_pct = (price - prev_close) / prev_close * 100

        # Volume
        today_vol = float(hist["Volume"].iloc[-1])
        avg_vol_20 = float(hist["Volume"].iloc[-21:-1].mean())
        vol_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0.0

        # Dollar volume
        avg_close_20 = float(hist["Close"].iloc[-21:-1].mean())
        avg_dollar_vol = avg_close_20 * avg_vol_20

        # 20-day MA (exclude today)
        ma20 = avg_close_20
        above_ma20 = price > ma20

        # ATR(14)
        tr = pd.concat([
            hist["High"] - hist["Low"],
            (hist["High"] - hist["Close"].shift(1)).abs(),
            (hist["Low"] - hist["Close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr14 = float(tr.iloc[-15:-1].mean())
        atr_pct = atr14 / price * 100 if price > 0 else 0.0

        # Stop / target
        today_low = float(hist["Low"].iloc[-1])
        stop = max(today_low, price - ATR_STOP_MULT * atr14)
        risk = price - stop
        if risk <= 0:
            return None
        target = price + RR_TARGET * risk
        rr = round((target - price) / risk, 2)

        # Prior 5-day gain (before today)
        price_5d_ago = float(hist["Close"].iloc[-7]) if len(hist) >= 7 else prev_close
        prior_5d_gain = (prev_close - price_5d_ago) / price_5d_ago * 100

        company = getattr(info, "long_name", None) or ticker

        p = Pick(
            ticker=ticker,
            company=company,
            price=round(price, 2),
            gain_pct=round(gain_pct, 2),
            volume_ratio=round(vol_ratio, 2),
            stop=round(stop, 2),
            target=round(target, 2),
            rr=rr,
            atr_pct=round(atr_pct, 2),
            above_ma20=above_ma20,
        )

        # --- Hard filters ---
        if not (MIN_PRICE <= price <= MAX_PRICE):
            p.excluded, p.exclude_reason = True, f"price ${price:.2f} outside ${MIN_PRICE}–${MAX_PRICE}"
            return p
        if avg_dollar_vol < MIN_AVG_DOLLAR_VOL:
            p.excluded, p.exclude_reason = True, f"avg dollar vol ${avg_dollar_vol/1e6:.1f}M < $5M"
            return p
        if gain_pct < MIN_GAIN_PCT:
            p.excluded, p.exclude_reason = True, f"only up {gain_pct:.1f}% today"
            return p
        if gain_pct > MAX_GAIN_PCT:
            p.excluded, p.exclude_reason = True, f"already up {gain_pct:.1f}% today (too extended)"
            return p
        if vol_ratio < MIN_VOLUME_RATIO:
            p.excluded, p.exclude_reason = True, f"volume {vol_ratio:.1f}x avg (need {MIN_VOLUME_RATIO}x)"
            return p
        if not above_ma20:
            p.excluded, p.exclude_reason = True, f"below 20MA ${ma20:.2f} (downtrend)"
            return p
        if prior_5d_gain > MAX_5D_PRIOR_GAIN:
            p.excluded, p.exclude_reason = True, f"already up {prior_5d_gain:.1f}% prior 5 days"
            return p

        # --- Score ---
        # Volume surge (cap at 5x → 2.5 pts)
        vol_score = min(vol_ratio / 2.0, 2.5)
        # Gain quality: sweet spot 3–8%
        if 3.0 <= gain_pct <= 8.0:
            gain_score = 2.5
        elif gain_pct < 3.0:
            gain_score = gain_pct / 3.0 * 2.5
        else:
            gain_score = max(0.0, 2.5 - (gain_pct - 8.0) * 0.3)
        # Volatility (ATR): more volatile = better swing candidate (cap at 2.5 pts)
        atr_score = min(atr_pct / 3.0 * 1.5, 1.5)
        # Not too extended from 52w high (max 1.5 pts)
        high_52w = float(hist["High"].max())
        pct_from_high = (price - high_52w) / high_52w * 100  # negative number
        ext_score = 1.5 if pct_from_high > -10 else max(0.0, 1.5 + pct_from_high * 0.1)

        p.score = round(vol_score + gain_score + atr_score + ext_score, 2)
        return p

    except Exception as exc:
        log.debug("%s analysis failed: %s", ticker, exc)
        return None


def run_screen() -> tuple[list[Pick], list[Pick]]:
    tickers = _get_yahoo_gainers()
    log.info("Fetched %d gainers from Yahoo", len(tickers))

    all_picks: list[Pick] = []
    for ticker in tickers:
        if any(c in ticker for c in ("-", "^", "/")):
            continue
        p = _analyze(ticker)
        if p:
            all_picks.append(p)
        time.sleep(0.15)

    passed = sorted([p for p in all_picks if not p.excluded], key=lambda x: x.score, reverse=True)
    excluded = [p for p in all_picks if p.excluded]

    log.info("Done: %d passed filters, %d excluded", len(passed), len(excluded))
    return passed[:NUM_PICKS], excluded

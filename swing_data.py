"""
Data fetching layer — per-stock and market context.
All optional fields default to None; missing values are logged as warnings, never silently zeroed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from swing_config import ATR_STOP_MULT, FLAG_ATR_EXTENSION, FLAG_NEAR_52W_HIGH_PCT, FLAG_STRUCTURAL_RR_MIN, RR_TARGET, SECTOR_ETF

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_NA = "N/A"


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class MarketContext:
    spy_chg: float | None = None
    qqq_chg: float | None = None
    iwm_chg: float | None = None
    vix: float | None = None
    spy_above_ma20: bool | None = None
    spy_above_ma50: bool | None = None
    oil_chg: float | None = None
    yield_10y: float | None = None
    run_time: str = _NA


@dataclass
class StockData:
    ticker: str
    company: str

    # Price action
    price: float = 0.0
    prev_close: float = 0.0
    open_price: float | None = None
    gap_pct: float | None = None          # (open - prev_close) / prev_close * 100
    day_high: float | None = None
    day_low: float | None = None
    close_loc: float | None = None        # (close - low) / (high - low)
    premarket_price: float | None = None
    premarket_volume: float | None = None
    data_timestamp: str = _NA
    gain_pct: float = 0.0

    # Volume / liquidity
    today_volume: float = 0.0
    avg_vol_20: float = 0.0
    volume_ratio: float = 0.0
    avg_dollar_vol: float = 0.0
    float_shares: float | None = None
    shares_short: float | None = None
    short_pct_float: float | None = None  # already converted to %

    # Trend
    ma20: float = 0.0
    ma50: float | None = None
    atr14: float = 0.0
    atr_pct: float = 0.0
    dist_from_ma20_atr: float | None = None  # (price - ma20) / atr14
    rsi14: float | None = None
    above_ma20: bool = False
    above_ma50: bool | None = None

    # Levels
    high_20d: float = 0.0
    low_20d: float = 0.0
    high_52w: float = 0.0
    pct_from_52w_high: float = 0.0
    swing_high: float | None = None
    swing_low: float | None = None
    gap_fill_level: float | None = None

    # Events
    earnings_date: str | None = None
    earnings_days_away: int | None = None
    ex_div_date: str | None = None

    # Analyst activity (last 5 days)
    analyst_actions: list[str] = field(default_factory=list)

    # News (last 48 h)
    news_headlines: list[dict] = field(default_factory=list)

    # Sector
    sector: str | None = None
    sector_etf: str | None = None
    sector_etf_chg_1d: float | None = None
    sector_etf_chg_5d: float | None = None

    # Prior momentum
    prior_5d_gain: float = 0.0

    # Stops / targets
    stop_atr: float = 0.0
    target_atr: float = 0.0
    rr_atr: float = 0.0
    stop_structural: float | None = None
    target_structural: float | None = None
    rr_structural: float | None = None

    # Warning flags
    flag_extended: bool = False
    flag_range_bottom: bool = False
    flag_near_52w_high: bool = False
    flag_low_structural_rr: bool = False

    # Price cross-check
    price_discrepancy: str | None = None

    # Scoring / screening
    score: float = 0.0
    excluded: bool = False
    exclude_reason: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _data_label(hist: pd.DataFrame) -> str:
    if hist.empty:
        return _NA
    last_date = pd.Timestamp(hist.index[-1]).date()
    today = datetime.now(ET).date()
    if last_date == today:
        return f"live ({datetime.now(ET).strftime('%H:%M ET')})"
    return f"as of last close {last_date}"


def _compute_atr(hist: pd.DataFrame, period: int = 14) -> float:
    tr = pd.concat([
        hist["High"] - hist["Low"],
        (hist["High"] - hist["Close"].shift(1)).abs(),
        (hist["Low"] - hist["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    return float(tr.iloc[-(period + 1):-1].mean())


def _compute_rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 2:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 1)


def _find_swing_pivots(hist: pd.DataFrame, window: int = 2) -> tuple[float | None, float | None]:
    """Most recent pivot high/low in the last 30 completed bars (excludes today)."""
    data = hist.iloc[:-1].tail(30)
    n = len(data)
    if n < window * 2 + 1:
        return None, None
    highs = data["High"].values
    lows = data["Low"].values
    swing_high = swing_low = None
    for i in range(n - window - 1, window - 1, -1):
        if swing_high is None:
            if all(highs[i] > highs[i - j] for j in range(1, window + 1)) and \
               all(highs[i] > highs[i + j] for j in range(1, window + 1)):
                swing_high = float(highs[i])
        if swing_low is None:
            if all(lows[i] < lows[i - j] for j in range(1, window + 1)) and \
               all(lows[i] < lows[i + j] for j in range(1, window + 1)):
                swing_low = float(lows[i])
        if swing_high is not None and swing_low is not None:
            break
    return swing_high, swing_low


def _chg_1d(hist: pd.DataFrame) -> float | None:
    if len(hist) < 2:
        return None
    prev, curr = float(hist["Close"].iloc[-2]), float(hist["Close"].iloc[-1])
    return round((curr - prev) / prev * 100, 2) if prev > 0 else None


def _chg_5d(hist: pd.DataFrame) -> float | None:
    if len(hist) < 6:
        return None
    prev, curr = float(hist["Close"].iloc[-6]), float(hist["Close"].iloc[-1])
    return round((curr - prev) / prev * 100, 2) if prev > 0 else None


# ── Per-stock data ────────────────────────────────────────────────────────────

def _fetch_slow(tk: yf.Ticker, d: StockData) -> None:
    """Fetch info/calendar/news/upgrades — each block is independently non-fatal."""

    # Fundamentals + sector
    try:
        info = tk.info
        raw_float = info.get("floatShares")
        raw_short = info.get("sharesShort")
        raw_short_pct = info.get("shortPercentOfFloat")
        d.float_shares = float(raw_float) if raw_float else None
        d.shares_short = float(raw_short) if raw_short else None
        d.short_pct_float = round(float(raw_short_pct) * 100, 1) if raw_short_pct else None
        d.sector = info.get("sector") or None
        d.sector_etf = SECTOR_ETF.get(d.sector) if d.sector else None
        if not d.company or d.company == d.ticker:
            d.company = info.get("longName") or d.ticker
    except Exception as exc:
        log.warning("%s info failed: %s", d.ticker, exc)

    # Calendar: earnings + ex-div
    try:
        cal = tk.calendar
        if cal:
            ed = cal.get("Earnings Date")
            if ed:
                if isinstance(ed, list):
                    ed = ed[0] if ed else None
                if ed is not None:
                    if hasattr(ed, "date"):
                        ed = ed.date()
                    d.earnings_date = str(ed)[:10]
                    days = (datetime.strptime(d.earnings_date, "%Y-%m-%d").date() - date.today()).days
                    d.earnings_days_away = days
            exd = cal.get("Ex-Dividend Date")
            if exd:
                if hasattr(exd, "date"):
                    exd = exd.date()
                d.ex_div_date = str(exd)[:10]
    except Exception as exc:
        log.warning("%s calendar failed: %s", d.ticker, exc)

    # Sector ETF performance
    if d.sector_etf:
        try:
            etf_h = yf.Ticker(d.sector_etf).history(period="10d")
            d.sector_etf_chg_1d = _chg_1d(etf_h)
            d.sector_etf_chg_5d = _chg_5d(etf_h)
        except Exception as exc:
            log.warning("%s sector ETF %s failed: %s", d.ticker, d.sector_etf, exc)

    # Analyst upgrades/downgrades (last 5 days)
    try:
        upg = tk.upgrades_downgrades
        if upg is not None and not upg.empty:
            idx = upg.index
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            else:
                idx = idx.tz_convert("UTC")
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=5)
            for _, row in upg[idx >= cutoff].iterrows():
                action = str(row.get("Action", "")).strip()
                firm = str(row.get("Firm", "")).strip()
                from_g = str(row.get("FromGrade", "")).strip()
                to_g = str(row.get("ToGrade", "")).strip()
                grade = f"{from_g}→{to_g}" if (from_g and to_g and from_g != "nan") else to_g
                parts = [p for p in [action, firm, grade] if p and p != "nan"]
                if parts:
                    d.analyst_actions.append(" | ".join(parts))
    except Exception as exc:
        log.warning("%s upgrades failed: %s", d.ticker, exc)

    # News (last 48 h)
    try:
        news = tk.news or []
        cutoff_ts = datetime.now(ET).timestamp() - 48 * 3600
        for item in news[:10]:
            ts = item.get("providerPublishTime", 0)
            if ts and ts >= cutoff_ts:
                pub_dt = datetime.fromtimestamp(ts, tz=ET).strftime("%Y-%m-%d %H:%M ET")
                d.news_headlines.append({
                    "title": item.get("title", ""),
                    "source": item.get("publisher", ""),
                    "url": item.get("link", ""),
                    "time": pub_dt,
                })
    except Exception as exc:
        log.warning("%s news failed: %s", d.ticker, exc)


def _compute_stops(d: StockData) -> None:
    price = d.price
    atr = d.atr14

    # ATR-based (fixed multipliers)
    risk_atr = ATR_STOP_MULT * atr
    d.stop_atr = round(price - risk_atr, 2)
    d.target_atr = round(price + RR_TARGET * risk_atr, 2)
    d.rr_atr = RR_TARGET

    # Structural: nearest support below, nearest resistance above
    support = [x for x in [d.swing_low, d.low_20d, d.day_low] if x is not None and x < price]
    resistance = [x for x in [d.swing_high, d.high_20d, d.high_52w] if x is not None and x > price]

    if support:
        d.stop_structural = round(max(support), 2)
    if resistance:
        d.target_structural = round(min(resistance), 2)

    if d.stop_structural is not None and d.target_structural is not None:
        struct_risk = price - d.stop_structural
        if struct_risk > 0:
            d.rr_structural = round((d.target_structural - price) / struct_risk, 2)


def _set_flags(d: StockData) -> None:
    if d.dist_from_ma20_atr is not None and d.dist_from_ma20_atr > FLAG_ATR_EXTENSION:
        d.flag_extended = True
    if d.close_loc is not None and d.close_loc < 0.5:
        d.flag_range_bottom = True
    if d.pct_from_52w_high > -FLAG_NEAR_52W_HIGH_PCT:
        d.flag_near_52w_high = True
    if d.rr_structural is not None and d.rr_structural < FLAG_STRUCTURAL_RR_MIN:
        d.flag_low_structural_rr = True


def get_stock_data(ticker: str) -> StockData | None:
    d = StockData(ticker=ticker, company=ticker)
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="65d")
        if len(hist) < 22:
            log.warning("%s: insufficient history (%d bars)", ticker, len(hist))
            return None

        fi = tk.fast_info

        # ── Price ──
        hist_close = float(hist["Close"].iloc[-1])
        fi_price = getattr(fi, "last_price", None)
        price = float(fi_price) if fi_price else hist_close

        # Cross-check
        if hist_close > 0:
            diff = abs(price - hist_close) / hist_close * 100
            if diff > 1.0:
                d.price_discrepancy = (
                    f"fast_info ${price:.2f} vs hist ${hist_close:.2f} ({diff:.1f}% diff)"
                )
                log.warning("%s price discrepancy: %s", ticker, d.price_discrepancy)

        prev_close_fi = getattr(fi, "previous_close", None)
        prev_close = float(prev_close_fi) if prev_close_fi else float(hist["Close"].iloc[-2])

        d.price = round(price, 2)
        d.prev_close = round(prev_close, 2)
        d.gain_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        d.company = getattr(fi, "long_name", None) or ticker
        d.data_timestamp = _data_label(hist)

        # Open / gap / range
        raw_open = getattr(fi, "open", None)
        raw_high = getattr(fi, "day_high", None)
        raw_low = getattr(fi, "day_low", None)

        if raw_open:
            d.open_price = round(float(raw_open), 2)
            if prev_close:
                d.gap_pct = round((d.open_price - prev_close) / prev_close * 100, 2)
        else:
            log.warning("%s: open price N/A", ticker)

        if raw_high and raw_low:
            d.day_high = round(float(raw_high), 2)
            d.day_low = round(float(raw_low), 2)
            rng = d.day_high - d.day_low
            if rng > 0:
                d.close_loc = round((price - d.day_low) / rng, 2)
        else:
            log.warning("%s: day high/low N/A", ticker)

        pm_price = getattr(fi, "pre_market_price", None)
        if pm_price:
            d.premarket_price = round(float(pm_price), 2)

        # ── Volume ──
        raw_vol = getattr(fi, "regular_market_volume", None)
        d.today_volume = float(raw_vol) if raw_vol else float(hist["Volume"].iloc[-1])
        d.avg_vol_20 = float(hist["Volume"].iloc[-21:-1].mean())
        if d.avg_vol_20 > 0:
            d.volume_ratio = round(d.today_volume / d.avg_vol_20, 2)
        avg_close_20 = float(hist["Close"].iloc[-21:-1].mean())
        d.avg_dollar_vol = avg_close_20 * d.avg_vol_20

        # ── Trend ──
        d.ma20 = round(avg_close_20, 2)
        if len(hist) >= 51:
            d.ma50 = round(float(hist["Close"].iloc[-51:-1].mean()), 2)
        else:
            log.warning("%s: not enough history for 50MA (%d bars)", ticker, len(hist))

        d.atr14 = round(_compute_atr(hist), 4)
        d.atr_pct = round(d.atr14 / price * 100, 2) if price > 0 else 0.0
        d.above_ma20 = price > d.ma20
        d.above_ma50 = (price > d.ma50) if d.ma50 is not None else None

        if d.atr14 > 0:
            d.dist_from_ma20_atr = round((price - d.ma20) / d.atr14, 2)

        d.rsi14 = _compute_rsi(hist["Close"])

        # ── Levels ──
        last_20 = hist.tail(21).iloc[:-1]
        d.high_20d = round(float(last_20["High"].max()), 2)
        d.low_20d = round(float(last_20["Low"].min()), 2)
        d.high_52w = round(float(hist["High"].max()), 2)
        if d.high_52w > 0:
            d.pct_from_52w_high = round((price - d.high_52w) / d.high_52w * 100, 2)

        sh, sl = _find_swing_pivots(hist)
        d.swing_high = round(sh, 2) if sh else None
        d.swing_low = round(sl, 2) if sl else None

        if d.gap_pct and d.gap_pct > 1.0:
            d.gap_fill_level = d.prev_close

        # ── Prior 5-day momentum ──
        if len(hist) >= 7:
            p5 = float(hist["Close"].iloc[-7])
            d.prior_5d_gain = round((prev_close - p5) / p5 * 100, 2) if p5 else 0.0

        # ── Slow data (info / calendar / news) ──
        _fetch_slow(tk, d)

        # ── Stops / targets ──
        _compute_stops(d)

        # ── Flags ──
        _set_flags(d)

        return d

    except Exception as exc:
        log.warning("%s get_stock_data failed: %s", ticker, exc)
        return None


# ── Market context ────────────────────────────────────────────────────────────

def get_market_context() -> MarketContext:
    ctx = MarketContext(
        run_time=datetime.now(ET).strftime("%-I:%M %p ET, %B %-d, %Y")
    )

    def _fetch(sym: str, period: str = "5d") -> pd.DataFrame:
        try:
            return yf.Ticker(sym).history(period=period)
        except Exception as exc:
            log.warning("market context %s: %s", sym, exc)
            return pd.DataFrame()

    def _last(h: pd.DataFrame) -> float | None:
        return float(h["Close"].iloc[-1]) if not h.empty else None

    spy_h = _fetch("SPY", "65d")
    ctx.spy_chg = _chg_1d(spy_h)
    if len(spy_h) >= 50:
        spy_price = _last(spy_h)
        if spy_price:
            ctx.spy_above_ma20 = spy_price > float(spy_h["Close"].iloc[-21:-1].mean())
            ctx.spy_above_ma50 = spy_price > float(spy_h["Close"].iloc[-51:-1].mean())

    ctx.qqq_chg = _chg_1d(_fetch("QQQ"))
    ctx.iwm_chg = _chg_1d(_fetch("IWM"))
    ctx.oil_chg = _chg_1d(_fetch("CL=F"))

    vix = _last(_fetch("^VIX"))
    ctx.vix = round(vix, 1) if vix else None

    tny = _last(_fetch("^TNX"))
    ctx.yield_10y = round(tny, 2) if tny else None

    return ctx


# ── Yahoo gainers ─────────────────────────────────────────────────────────────

def get_yahoo_gainers(count: int = 50) -> list[str]:
    url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    params = {"formatted": "false", "scrIds": "day_gainers", "count": count}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        quotes = r.json()["finance"]["result"][0]["quotes"]
        return [q["symbol"] for q in quotes if "symbol" in q]
    except Exception as exc:
        log.warning("Yahoo gainers fetch failed: %s", exc)
        return []


# ── "Why it's moving" ─────────────────────────────────────────────────────────

def why_moving(d: StockData) -> str:
    parts = []
    if d.gap_pct and abs(d.gap_pct) >= 2.0:
        direction = "Gapped up" if d.gap_pct > 0 else "Gapped down"
        parts.append(f"{direction} {abs(d.gap_pct):.1f}% at open")
    if d.news_headlines:
        title = d.news_headlines[0]["title"]
        if len(title) > 80:
            title = title[:77] + "..."
        parts.append(f'News: "{title}"')
    elif d.analyst_actions:
        parts.append(f"Analyst: {d.analyst_actions[0]}")
    if not parts:
        parts.append(f"Up {d.gain_pct:.1f}% on {d.volume_ratio:.1f}x average volume")
    if d.flag_near_52w_high:
        parts.append("near 52-week high")
    return " | ".join(parts)

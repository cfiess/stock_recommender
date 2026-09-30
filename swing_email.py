"""Email formatting and delivery."""
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from swing_config import EMAIL_FROM, EMAIL_TO, GMAIL_APP_PASSWORD
from swing_data import MarketContext, StockData, why_moving

ET = ZoneInfo("America/New_York")
_NA = "N/A"
_W = 52   # column width for separators


def _f(val, fmt=".2f", suffix="", prefix="") -> str:
    """Format a value; return N/A for None."""
    if val is None:
        return _NA
    try:
        return f"{prefix}{val:{fmt}}{suffix}"
    except (TypeError, ValueError):
        return _NA


def _pct(val) -> str:
    if val is None:
        return _NA
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def _market_block(ctx: MarketContext) -> list[str]:
    spy_ma = _NA
    if ctx.spy_above_ma20 is not None and ctx.spy_above_ma50 is not None:
        spy_ma = (
            f"{'above' if ctx.spy_above_ma20 else 'below'} 20d / "
            f"{'above' if ctx.spy_above_ma50 else 'below'} 50d"
        )
    return [
        "MARKET CONTEXT",
        "-" * _W,
        f"  SPY {_pct(ctx.spy_chg)}   QQQ {_pct(ctx.qqq_chg)}   IWM {_pct(ctx.iwm_chg)}",
        f"  VIX {_f(ctx.vix, '.1f')}   Oil {_pct(ctx.oil_chg)}   10yr {_f(ctx.yield_10y, '.2f', '%')}",
        f"  SPY vs MA: {spy_ma}",
        "",
    ]


def _pick_block(i: int, d: StockData) -> list[str]:
    flags = []
    if d.flag_extended:
        flags.append(f"!! EXTENDED: {_f(d.dist_from_ma20_atr, '.1f')} ATR above 20MA (>{2.5})")
    if d.flag_range_bottom:
        flags.append("!! WEAK CLOSE: price in bottom half of today's range")
    if d.flag_near_52w_high:
        flags.append(f"!! NEAR 52W HIGH: {_pct(d.pct_from_52w_high)} away")
    if d.flag_low_structural_rr:
        flags.append(f"!! LOW STRUCTURAL R:R: {_f(d.rr_structural, '.1f')}:1")
    if d.price_discrepancy:
        flags.append(f"!! PRICE CHECK: {d.price_discrepancy}")

    # News lines
    if d.news_headlines:
        news_lines = ["    News (48h):"]
        for h in d.news_headlines[:3]:
            news_lines.append(f"      [{h['time']}] {h['source']}")
            news_lines.append(f"      {h['title']}")
            if h.get("url"):
                news_lines.append(f"      {h['url']}")
    else:
        news_lines = ["    News (48h):    no news found"]

    analyst_line = (
        "    Analyst (5d): " + " | ".join(d.analyst_actions[:3])
        if d.analyst_actions else ""
    )

    sector_line = ""
    if d.sector_etf:
        sector_line = (
            f"    Sector:       {d.sector or _NA} ({d.sector_etf})"
            f"  1d {_pct(d.sector_etf_chg_1d)}  5d {_pct(d.sector_etf_chg_5d)}"
        )

    lines = [
        f"#{i}  {d.ticker}  —  {d.company}",
        f"    Why moving:   {why_moving(d)}",
        "",
        "    -- PRICE ACTION " + "-" * 35,
        f"    Price:        ${d.price:.2f}  ({_pct(d.gain_pct)} today)  [{d.data_timestamp}]",
        f"    Prev close:   ${d.prev_close:.2f}   Open: ${_f(d.open_price)}   Gap: {_pct(d.gap_pct)}",
        f"    Day range:    ${_f(d.day_low)}–${_f(d.day_high)}   Close in range: {_f(d.close_loc, '.0%')}",
        f"    Pre-market:   ${_f(d.premarket_price)}",
        "",
        "    -- TREND & EXTENSION " + "-" * 30,
        f"    20MA / 50MA:  ${d.ma20:.2f} / ${_f(d.ma50)}",
        f"    Above 20MA:   {'Yes' if d.above_ma20 else 'No'}   "
        f"Above 50MA: {('Yes' if d.above_ma50 else 'No') if d.above_ma50 is not None else _NA}",
        f"    ATR(14):      ${d.atr14:.2f} ({d.atr_pct:.1f}%)"
        f"   Dist from 20MA: {_f(d.dist_from_ma20_atr, '.1f')} ATR"
        f"   RSI(14): {_f(d.rsi14, '.0f')}",
        "",
        "    -- LEVELS " + "-" * 41,
        f"    20d range:    ${d.low_20d:.2f}–${d.high_20d:.2f}",
        f"    52w high:     ${d.high_52w:.2f}  ({_pct(d.pct_from_52w_high)} from here)",
        f"    Swing H/L:    ${_f(d.swing_high)} / ${_f(d.swing_low)}",
        f"    Gap fill:     ${_f(d.gap_fill_level)}",
        "",
        "    -- VOLUME & LIQUIDITY " + "-" * 29,
        f"    Vol today:    {d.today_volume:,.0f}  ({d.volume_ratio:.1f}x 20d avg)",
        f"    Avg $vol:     ${d.avg_dollar_vol / 1e6:.1f}M/day",
        f"    Float:        {_f(d.float_shares / 1e6, '.1f', 'M') if d.float_shares else _NA}",
        f"    Short int:    {_f(d.shares_short / 1e6, '.1f', 'M') if d.shares_short else _NA}"
        f"  ({_f(d.short_pct_float, '.1f', '% of float')})",
        "",
        "    -- EVENTS " + "-" * 41,
        f"    Earnings:     {d.earnings_date or _NA}"
        f"  ({_f(d.earnings_days_away, 'd', ' days') if d.earnings_days_away is not None else _NA})",
        f"    Ex-div:       {d.ex_div_date or _NA}",
    ]

    if analyst_line:
        lines.append(analyst_line)
    lines += news_lines

    if sector_line:
        lines.append(sector_line)

    # Trade plan
    atr_risk = d.price - d.stop_atr
    lines += [
        "",
        "    -- TRADE PLAN " + "-" * 37,
        f"    Entry:        near ${d.price:.2f}",
        f"    ATR stop:     ${d.stop_atr:.2f}  (risk ${atr_risk:.2f})   "
        f"Target: ${d.target_atr:.2f}  R:R {d.rr_atr:.1f}:1",
    ]

    if d.stop_structural is not None and d.target_structural is not None:
        struct_risk = d.price - d.stop_structural
        lines.append(
            f"    Struc stop:   ${d.stop_structural:.2f}  (risk ${struct_risk:.2f})   "
            f"Target: ${d.target_structural:.2f}  R:R {_f(d.rr_structural, '.1f')}:1"
        )
    else:
        lines.append(f"    Struc stop:   {_NA}  (no clear support/resistance found)")

    if flags:
        lines.append("")
        for fl in flags:
            lines.append(f"    {fl}")

    lines.append("")
    return lines


def build_body(
    picks: list[StockData],
    excluded: list[StockData],
    ctx: MarketContext,
) -> str:
    now = datetime.now(ET)
    hour = now.hour

    if hour < 9 or (hour == 9 and now.minute < 30):
        entry_note = "Run before market open — consider entry at today's open or an early pullback."
    elif hour < 16:
        entry_note = "Run during market hours — consider entry near current price."
    else:
        entry_note = "Run after market close — consider entry near tomorrow's open."

    lines = [
        f"SWING PICKS  —  {ctx.run_time}",
        "=" * _W,
        "",
    ]
    lines += _market_block(ctx)

    if picks:
        lines += [
            f"TOP {len(picks)} PICKS",
            entry_note,
            "Set your stop BEFORE you enter the trade.",
            "-" * _W,
            "",
        ]
        for i, d in enumerate(picks, 1):
            lines += _pick_block(i, d)
    else:
        lines += ["NO PICKS TODAY", "No stocks passed all filters.", ""]

    if excluded:
        lines += [f"SCREENED OUT  ({len(excluded)} stocks)", "-" * _W]
        for d in excluded[:15]:
            lines.append(
                f"  {d.ticker:<6}  ${d.price:.2f}  {_pct(d.gain_pct)}  —  {d.exclude_reason}"
            )
        lines.append("")

    lines += [
        "─" * _W,
        "Never risk more than 1–2% of your account on one trade.",
        "Take partial profits at 1:1 R:R. Cut losses at your stop.",
    ]
    return "\n".join(lines)


def send_picks(
    picks: list[StockData],
    excluded: list[StockData],
    ctx: MarketContext,
) -> None:
    today = datetime.now(ET).strftime("%Y-%m-%d")
    n = len(picks)
    subject = (
        f"Swing Picks {today} — {n} pick{'s' if n != 1 else ''}"
        if n else f"Swing Picks {today} — No picks today"
    )
    body = build_body(picks, excluded, ctx)
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)

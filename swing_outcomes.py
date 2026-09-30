"""
Outcome tracker.
  log_picks()      — appends today's picks to picks_log.csv
  update_outcomes() — fills in 2/5/10-day returns for past picks
"""
import csv
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf

from swing_config import PICKS_LOG
from swing_data import StockData

log = logging.getLogger(__name__)

FIELDNAMES = [
    "date", "ticker", "company", "entry_price",
    "stop_atr", "target_atr", "stop_structural", "target_structural",
    "rr_atr", "rr_structural", "score",
    "gain_pct_day", "volume_ratio", "atr_pct",
    "ma20", "ma50", "rsi14", "earnings_date", "sector",
    "ret_2d", "ret_5d", "ret_10d",
    "max_gain_5d", "max_dd_5d",
    "stop_hit", "target_hit", "outcome",
]


def _trading_days_since(entry: date) -> int:
    """Approximate trading days from entry to today (no holiday calendar)."""
    count, current = 0, entry
    while current < date.today():
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


def log_picks(picks: list[StockData], excluded: list[StockData] | None = None) -> None:
    today = date.today().isoformat()
    write_header = not Path(PICKS_LOG).exists()
    try:
        with open(PICKS_LOG, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            if write_header:
                w.writeheader()
            for d in picks:
                w.writerow({
                    "date": today,
                    "ticker": d.ticker,
                    "company": d.company,
                    "entry_price": d.price,
                    "stop_atr": d.stop_atr,
                    "target_atr": d.target_atr,
                    "stop_structural": d.stop_structural or "",
                    "target_structural": d.target_structural or "",
                    "rr_atr": d.rr_atr,
                    "rr_structural": d.rr_structural or "",
                    "score": d.score,
                    "gain_pct_day": d.gain_pct,
                    "volume_ratio": d.volume_ratio,
                    "atr_pct": d.atr_pct,
                    "ma20": d.ma20,
                    "ma50": d.ma50 or "",
                    "rsi14": d.rsi14 or "",
                    "earnings_date": d.earnings_date or "",
                    "sector": d.sector or "",
                })
        log.info("Logged %d picks to %s", len(picks), PICKS_LOG)
    except Exception as exc:
        log.warning("log_picks failed: %s", exc)


def update_outcomes() -> None:
    path = Path(PICKS_LOG)
    if not path.exists():
        log.info("No picks log found — nothing to update.")
        return

    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as exc:
        log.warning("Failed to read %s: %s", path, exc)
        return

    changed = False
    for row in rows:
        try:
            entry_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue

        td = _trading_days_since(entry_date)
        if td < 2:
            continue
        if row.get("ret_10d"):
            continue  # already complete

        ticker = row.get("ticker", "")
        try:
            entry = float(row["entry_price"])
            stop = float(row.get("stop_atr") or 0)
            target = float(row.get("target_atr") or 0)
        except (ValueError, TypeError):
            continue

        if not ticker or entry <= 0:
            continue

        try:
            hist = yf.Ticker(ticker).history(
                start=(entry_date + timedelta(days=1)).isoformat(),
                auto_adjust=True,
            )
            if hist.empty:
                continue

            closes = hist["Close"].values
            highs = hist["High"].values
            lows = hist["Low"].values

            def _ret(n: int) -> str:
                if len(closes) >= n:
                    return str(round((closes[n - 1] - entry) / entry * 100, 2))
                return ""

            if td >= 2:
                row["ret_2d"] = _ret(2)
            if td >= 5:
                row["ret_5d"] = _ret(5)
                w5 = min(5, len(closes))
                row["max_gain_5d"] = round((max(highs[:w5]) - entry) / entry * 100, 2)
                row["max_dd_5d"] = round((min(lows[:w5]) - entry) / entry * 100, 2)
            if td >= 10:
                row["ret_10d"] = _ret(10)

            w10 = min(10, len(lows))
            stop_hit = stop > 0 and any(l <= stop for l in lows[:w10])
            target_hit = target > 0 and any(h >= target for h in highs[:w10])
            row["stop_hit"] = "1" if stop_hit else "0"
            row["target_hit"] = "1" if target_hit else "0"

            if stop_hit and target_hit:
                row["outcome"] = "both"
            elif target_hit:
                row["outcome"] = "target"
            elif stop_hit:
                row["outcome"] = "stop"
            elif td >= 10:
                row["outcome"] = "open/expired"
            else:
                row["outcome"] = "open"

            changed = True
        except Exception as exc:
            log.warning("%s outcome update failed: %s", ticker, exc)

    if changed:
        try:
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            log.info("Outcomes updated in %s", path)
        except Exception as exc:
            log.warning("Failed to write %s: %s", path, exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    update_outcomes()

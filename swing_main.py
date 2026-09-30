"""Daily swing trade screener — momentum continuation."""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print email body, don't send")
    parser.add_argument(
        "--ticker",
        help="Comma-separated tickers to analyze directly, bypassing Yahoo gainers (implies --dry-run)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from swing_data import get_market_context
    from swing_screener import run_screen

    tickers = [t.strip().upper() for t in args.ticker.split(",")] if args.ticker else None

    log.info("Fetching market context...")
    ctx = get_market_context()

    log.info("Running screener%s...", f" on {args.ticker}" if args.ticker else "")
    picks, excluded = run_screen(tickers=tickers)

    # --ticker always implies dry-run (never auto-sends on manual ticker runs)
    if args.dry_run or args.ticker:
        from swing_email import build_body
        print(build_body(picks, excluded, ctx))
        return

    from swing_config import EMAIL_FROM, GMAIL_APP_PASSWORD
    if not EMAIL_FROM or not GMAIL_APP_PASSWORD:
        log.error("GMAIL_USER or GMAIL_APP_PASSWORD env vars not set — aborting")
        sys.exit(1)

    from swing_email import send_picks
    from swing_outcomes import log_picks
    log_picks(picks, excluded)
    send_picks(picks, excluded, ctx)
    log.info("Email sent — %d picks.", len(picks))


if __name__ == "__main__":
    main()

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
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from swing_screener import run_screen
    picks, excluded = run_screen()

    if args.dry_run:
        from swing_email import build_body
        print(build_body(picks, excluded))
        return

    from swing_config import EMAIL_FROM, GMAIL_APP_PASSWORD
    if not EMAIL_FROM or not GMAIL_APP_PASSWORD:
        log.error("GMAIL_USER or GMAIL_APP_PASSWORD env vars not set")
        sys.exit(1)

    from swing_email import send_picks
    send_picks(picks, excluded)
    log.info("Email sent — %d picks.", len(picks))


if __name__ == "__main__":
    main()

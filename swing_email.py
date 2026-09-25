import smtplib
from datetime import date
from email.mime.text import MIMEText

from swing_config import EMAIL_FROM, EMAIL_TO, GMAIL_APP_PASSWORD
from swing_screener import Pick


def build_body(picks: list[Pick], excluded: list[Pick]) -> str:
    today = date.today().strftime("%B %d, %Y")
    lines = [f"SWING PICKS  —  {today}", "=" * 52, ""]

    if picks:
        lines += [
            f"TOP {len(picks)} PICKS",
            "Buy near today's close or tomorrow's open.",
            "Set your stop BEFORE you enter the trade.",
            "-" * 52,
        ]
        for i, p in enumerate(picks, 1):
            risk = p.price - p.stop
            lines += [
                f"#{i}  {p.ticker}  —  {p.company}",
                f"    Price   ${p.price:.2f}   up {p.gain_pct:.1f}% today   {p.volume_ratio:.1f}x volume",
                f"    Entry   near ${p.price:.2f}",
                f"    Stop    ${p.stop:.2f}   (risk ${risk:.2f}/share)",
                f"    Target  ${p.target:.2f}   ({p.rr:.1f}:1 reward-to-risk)",
                f"    ATR     {p.atr_pct:.1f}%   Above 20-day MA: {'Yes' if p.above_ma20 else 'No'}",
                "",
            ]
    else:
        lines += ["NO PICKS TODAY", "No stocks passed all filters.", ""]

    if excluded:
        lines += [f"SCREENED OUT  ({len(excluded)} stocks)", "-" * 52]
        for p in excluded[:12]:
            lines.append(f"  {p.ticker:<6}  ${p.price:.2f}  +{p.gain_pct:.1f}%  —  {p.exclude_reason}")
        lines.append("")

    lines += [
        "─" * 52,
        "Never risk more than 1–2% of your account on one trade.",
        "Take partial profits at 1:1 R:R. Cut losses at your stop.",
    ]
    return "\n".join(lines)


def send_picks(picks: list[Pick], excluded: list[Pick]) -> None:
    today = date.today().strftime("%Y-%m-%d")
    n = len(picks)
    subject = (
        f"Swing Picks {today} — {n} pick{'s' if n != 1 else ''}"
        if n else f"Swing Picks {today} — No picks today"
    )
    body = build_body(picks, excluded)
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)

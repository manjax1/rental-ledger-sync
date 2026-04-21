"""
Gmail SMTP email notifier for daily rental ledger sync summaries.
smtplib and email are Python standard library modules — no pip install needed.
"""

import json as jsonlib
import os
import smtplib
import time
import urllib.error
import urllib.request
import warnings
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

warnings.filterwarnings("ignore")

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).parent.parent / ".env"


def _fmt_date(value) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%m/%d/%Y")
    return str(value)


def _fmt_currency(amount) -> str:
    return f"${abs(float(amount)):,.2f}"


def _build_todays_transactions_section(new_auto: list[dict], new_manual: list[dict]) -> str:
    """Build the 'Today's New Transactions' highlight section at the top of the email."""
    if not new_auto and not new_manual:
        return (
            "<h2 style='color:#1F3864;margin-top:20px;'>✨ Today's New Transactions</h2>"
            "<p style='background:#E2EFDA;color:#375623;padding:12px;border-radius:6px;margin:0;'>"
            "✅ No new transactions today — all caught up!</p>"
        )

    parts = ["<h2 style='color:#1F3864;margin-top:20px;'>✨ Today's New Transactions</h2>"]

    if new_auto:
        rows = ""
        for t in new_auto:
            badge_class = "badge-income" if t.get("type") == "Income" else "badge-expense"
            rows += (
                f"<tr>"
                f"<td>{_fmt_date(t['date'])}</td>"
                f"<td>{t.get('name', '')}</td>"
                f"<td>{t.get('property', '')}</td>"
                f"<td>{t.get('category', '')}</td>"
                f"<td><span class='{badge_class}'>{t.get('type', '')}</span></td>"
                f"<td style='text-align:right'>{_fmt_currency(t['amount'])}</td>"
                f"</tr>"
            )
        parts.append(
            "<div style='border-left:3px solid #375623;padding-left:12px;margin:12px 0;'>"
            "<h3 style='color:#375623;margin:0 0 8px 0;'>Auto-Assigned</h3>"
            "<table><thead><tr>"
            "<th>Date</th><th>Description</th><th>Property</th>"
            "<th>Category</th><th>Type</th><th>Amount</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
            "</div>"
        )

    if new_manual:
        rows = ""
        for t in new_manual:
            rows += (
                f"<tr>"
                f"<td>{_fmt_date(t['date'])}</td>"
                f"<td>{t.get('name', '')}</td>"
                f"<td>{t.get('category', '')}</td>"
                f"<td style='text-align:right'>{_fmt_currency(t['amount'])}</td>"
                f"<td style='color:#806000'>{t.get('note', '')}</td>"
                f"</tr>"
            )
        parts.append(
            "<div style='border-left:3px solid #C55A11;padding-left:12px;margin:12px 0;'>"
            "<h3 style='color:#C55A11;margin:0 0 8px 0;'>⚠️ Needs Manual Assignment</h3>"
            "<table><thead>"
            "<tr style='background:#C55A11'>"
            "<th>Date</th><th>Description</th><th>Category</th><th>Amount</th><th>Note</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
            "</div>"
        )

    return "".join(parts)


def _build_auto_assigned_section(transactions: list[dict]) -> str:
    if not transactions:
        return "<p style='color:#999'>No auto-assigned transactions today.</p>"

    rows = ""
    for t in transactions:
        badge_class = "badge-income" if t.get("type") == "Income" else "badge-expense"
        rows += (
            f"<tr>"
            f"<td>{_fmt_date(t['date'])}</td>"
            f"<td>{t.get('property', '')}</td>"
            f"<td>{t.get('category', '')}</td>"
            f"<td><span class='{badge_class}'>{t.get('type', '')}</span></td>"
            f"<td style='text-align:right'>{_fmt_currency(t['amount'])}</td>"
            f"</tr>"
        )

    return (
        "<h3 style='color:#375623'>✅ Auto-Assigned Transactions</h3>"
        "<table><thead><tr>"
        "<th>Date</th><th>Property</th><th>Category</th><th>Type</th><th>Amount</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _build_manual_section(transactions: list[dict]) -> str:
    if not transactions:
        return "<p style='color:#999'>✅ No manual assignments needed today!</p>"

    rows = ""
    for t in transactions:
        rows += (
            f"<tr>"
            f"<td>{_fmt_date(t['date'])}</td>"
            f"<td>{t.get('name', '')}</td>"
            f"<td>{t.get('category', '')}</td>"
            f"<td style='text-align:right'>{_fmt_currency(t['amount'])}</td>"
            f"<td style='color:#806000'>{t.get('note', '')}</td>"
            f"</tr>"
        )

    return (
        "<h3 style='color:#C55A11'>⚠️ Needs Manual Assignment</h3>"
        "<table><thead>"
        "<tr style='background:#C55A11'>"
        "<th>Date</th><th>Description</th><th>Category</th><th>Amount</th><th>Note</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _send_via_sendgrid(sender: str, recipient: str, subject: str, html_body: str, api_key: str) -> int:
    payload = {
        "personalizations": [{"to": [{"email": recipient}]}],
        "from":    {"email": sender},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }
    data = jsonlib.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as response:
        return response.status


def send_sync_summary(summary: dict):
    """
    Send an HTML sync summary email.

    Uses SendGrid HTTP API if SENDGRID_API_KEY is set (recommended for Railway).
    Falls back to Gmail SMTP (port 587 + STARTTLS) for local use.

    Required .env keys: EMAIL_SENDER, EMAIL_RECIPIENT
    SendGrid:  SENDGRID_API_KEY
    Gmail:     EMAIL_APP_PASSWORD
    """
    load_dotenv(_ENV_PATH, override=True)

    sender       = os.getenv("EMAIL_SENDER", "").strip()
    recipient    = os.getenv("EMAIL_RECIPIENT", "").strip()
    sendgrid_key = os.getenv("SENDGRID_API_KEY", "").strip()
    app_password = os.getenv("EMAIL_APP_PASSWORD", "").strip()

    if not all([sender, recipient]):
        print("⚠️  Email not configured - skipping notification")
        return

    if not sendgrid_key and not app_password:
        print("⚠️  Email not configured - skipping notification")
        return

    added              = summary.get("added", 0)
    skipped            = summary.get("skipped", 0)
    manual             = summary.get("manual", 0)
    ledger_path        = summary.get("ledger_path", "")
    token_status       = summary.get("token_status")   # "valid", "refreshed", or None
    auto_assigned      = summary.get("auto_assigned", [])
    needs_manual       = summary.get("needs_manual", [])
    new_auto_assigned  = summary.get("new_auto_assigned", auto_assigned)
    new_needs_manual   = summary.get("new_needs_manual", needs_manual)
    run_datetime       = summary.get("run_datetime", datetime.now().strftime("%B %d, %Y at %I:%M %p"))

    today_str = date.today().strftime("%B %d, %Y")
    subject   = f"🏠 Rental Ledger Sync — {today_str} | {added} added, {manual} need review"

    if token_status == "valid":
        token_css, token_icon, token_status_text = "token-valid", "✅", "Valid (reused)"
    elif token_status == "refreshed":
        token_css, token_icon, token_status_text = "token-refreshed", "🔄", "Refreshed (re-authenticated)"
    else:
        token_css, token_icon, token_status_text = "token-valid", "ℹ️", "N/A (sandbox or CSV mode)"

    todays_section        = _build_todays_transactions_section(new_auto_assigned, new_needs_manual)
    auto_assigned_section = _build_auto_assigned_section(auto_assigned)
    manual_section        = _build_manual_section(needs_manual)

    html_body = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
  h1 {{ color: #1F3864; border-bottom: 2px solid #2E75B6; padding-bottom: 10px; }}
  .kpi-row {{ display: flex; gap: 16px; margin: 20px 0; }}
  .kpi {{ background: #f5f5f5; border-radius: 8px; padding: 16px; flex: 1; text-align: center; }}
  .kpi .number {{ font-size: 32px; font-weight: bold; color: #1F3864; }}
  .kpi .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
  .kpi.green .number {{ color: #375623; }}
  .kpi.orange .number {{ color: #C55A11; }}
  .kpi.blue .number {{ color: #2E75B6; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
  th {{ background: #1F3864; color: white; padding: 10px; text-align: left; font-size: 12px; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 12px; }}
  tr:nth-child(even) {{ background: #f9f9f9; }}
  .footer {{ color: #999; font-size: 11px; margin-top: 30px; border-top: 1px solid #eee; padding-top: 10px; }}
  .badge-income {{ background: #E2EFDA; color: #375623; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
  .badge-expense {{ background: #FCE4D6; color: #843D0B; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
  .badge-manual {{ background: #FFF2CC; color: #806000; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
  .token-status {{ padding: 8px 12px; border-radius: 4px; margin: 10px 0; font-size: 12px; }}
  .token-valid {{ background: #E2EFDA; color: #375623; }}
  .token-refreshed {{ background: #FFF2CC; color: #806000; }}
</style>
</head>
<body>
  <h1>🏠 Rental Ledger Daily Sync</h1>
  <p style="color:#666">Run completed: {run_datetime}</p>

  <div class="kpi-row">
    <div class="kpi green">
      <div class="number">{added}</div>
      <div class="label">New Transactions Added</div>
    </div>
    <div class="kpi blue">
      <div class="number">{skipped}</div>
      <div class="label">Duplicates Skipped</div>
    </div>
    <div class="kpi orange">
      <div class="number">{manual}</div>
      <div class="label">Need Manual Assignment</div>
    </div>
  </div>

  <div class="token-status {token_css}">
    {token_icon} Plaid Token: {token_status_text}
  </div>

  {todays_section}

  <details style="margin-top:24px;">
    <summary style="cursor:pointer;color:#1F3864;font-weight:bold;font-size:14px;padding:8px 0;border-top:1px solid #ddd;">
      📋 Full Run Details (all matched transactions this run)
    </summary>
    <div style="margin-top:10px;">
      {auto_assigned_section}
      {manual_section}
    </div>
  </details>

  <div class="footer">
    📁 Ledger: {ledger_path}<br>
    🔗 Plaid Environment: PRODUCTION<br>
    ⏰ Next sync: Tomorrow at 7:00 AM
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.attach(MIMEText(html_body, "html"))

    max_retries = 3
    retry_delay = 30
    last_error  = None

    for attempt in range(1, max_retries + 1):
        try:
            if sendgrid_key:
                print(f"📧 Sending via SendGrid...")
                _send_via_sendgrid(sender, recipient, subject, html_body, sendgrid_key)
            else:
                print(f"📧 Sending via Gmail SMTP...")
                with smtplib.SMTP("smtp.gmail.com", 587) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(sender, app_password)
                    server.sendmail(sender, recipient, msg.as_string())
            print(f"✅ Summary email sent to {recipient}")
            return
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                print(f"⚠️  Email attempt {attempt} failed: {e}")
                print(f"   Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)

    print(f"❌ Email failed after {max_retries} attempts: {last_error}")


if __name__ == "__main__":
    _TEST_SUMMARY = {
        "added": 5,
        "skipped": 12,
        "manual": 1,
        "ledger_path": "/Users/manjax/Documents/RentalPropertyLedger.xlsx",
        "token_status": "valid",
        "auto_assigned": [
            {
                "date": "2026-04-09",
                "name": "Zelle payment from RUBY ANNETTE ROBERTS",
                "amount": 4100.00,
                "property": "16945 Strauss Court Lathrop CA 95330",
                "category": "Rent",
                "type": "Income",
            },
            {
                "date": "2026-04-07",
                "name": "ROCKET MORTGAGE DES:LOAN ID:565163",
                "amount": 1248.66,
                "property": "6812 Dalmatian Circle Plano TX 75023",
                "category": "Mortgage - P + I",
                "type": "Expense",
            },
        ],
        "needs_manual": [
            {
                "date": "2026-04-01",
                "name": "UTOPIA MGMT TRST",
                "amount": 5787.68,
                "category": "Rent",
                "note": "Split across 6 Utopia properties",
            },
        ],
        "run_datetime": "April 10, 2026 at 7:00 AM",
    }
    print("Sending test email...")
    send_sync_summary(_TEST_SUMMARY)


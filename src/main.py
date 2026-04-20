"""
rental-ledger-sync
Pulls Bank of America transactions via Plaid and writes them to an Excel ledger.
"""

import argparse
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv, set_key

_ENV_PATH = Path(__file__).parent.parent / ".env"

_CLOUD_LEDGER_PATH = "/tmp/RentalPropertyLedger.xlsx"


def _parse_from_date(value: str) -> date:
    """Validate and parse a YYYY-MM-DD date string, then return a date object."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        print("❌ Invalid date format. Please use YYYY-MM-DD (e.g. 2026-01-01)")
        raise SystemExit(1)
    if parsed > date.today():
        print("❌ Start date cannot be in the future")
        raise SystemExit(1)
    if parsed < date.today().replace(year=date.today().year - 2):
        print("⚠️  Warning: Fetching more than 2 years of data may be slow")
    return parsed


from csv_importer import load_bofa_csv
from email_notifier import send_sync_summary
from filters import filter_rental_transactions
from ledger_writer import fix_transaction_category, update_mortgage_category_in_ledger, write_transactions
from link_flow import run_link_flow
from plaid_client import PlaidClient

# Column widths shared across print tables
_W_DATE     = 12
_W_NAME     = 34
_W_AMOUNT   = 10
_W_PROPERTY = 40
_W_CATEGORY = 26
_W_TYPE     = 8


def _print_raw_table(transactions: list[dict]):
    header = f"{'Date':<{_W_DATE}} {'Name':<{_W_NAME}} {'Amount':>{_W_AMOUNT}}"
    print(header)
    print("-" * len(header))
    for t in transactions:
        print(
            f"{str(t['date']):<{_W_DATE}}"
            f" {t['name'][:_W_NAME]:<{_W_NAME}}"
            f" {t['amount']:>{_W_AMOUNT}.2f}"
        )


def _print_assigned_table(transactions: list[dict]):
    header = (
        f"{'Date':<{_W_DATE}} {'Name':<{_W_NAME}} {'Amount':>{_W_AMOUNT}}"
        f"  {'Property':<{_W_PROPERTY}} {'Category':<{_W_CATEGORY}} {'Type':<{_W_TYPE}}"
    )
    print(header)
    print("-" * len(header))
    for t in transactions:
        print(
            f"{str(t['date']):<{_W_DATE}}"
            f" {t['name'][:_W_NAME]:<{_W_NAME}}"
            f" {t['amount']:>{_W_AMOUNT}.2f}"
            f"  {t['property'][:_W_PROPERTY]:<{_W_PROPERTY}}"
            f" {t['category']:<{_W_CATEGORY}}"
            f" {t['type']:<{_W_TYPE}}"
        )


def _print_needs_assignment_table(transactions: list[dict]):
    header = (
        f"{'Date':<{_W_DATE}} {'Name':<{_W_NAME}} {'Amount':>{_W_AMOUNT}}"
        f"  {'Category':<{_W_CATEGORY}} {'Type':<{_W_TYPE}}  Note"
    )
    print(header)
    print("-" * len(header))
    for t in transactions:
        print(
            f"{str(t['date']):<{_W_DATE}}"
            f" {t['name'][:_W_NAME]:<{_W_NAME}}"
            f" {t['amount']:>{_W_AMOUNT}.2f}"
            f"  {t['category']:<{_W_CATEGORY}}"
            f" {t['type']:<{_W_TYPE}}"
            f"  {t.get('note', '')}"
        )


def _run_pipeline(transactions: list[dict], ledger_path: Path, token_status: str | None = None):
    """Shared pipeline: filter → print three tables → write ledger → print summary."""

    # Table 1 — all raw transactions
    print(f"TABLE 1 — ALL TRANSACTIONS ({len(transactions)} total)")
    print("=" * (_W_DATE + _W_NAME + _W_AMOUNT + 2))
    _print_raw_table(transactions)

    matched          = filter_rental_transactions(transactions)
    auto_assigned    = [t for t in matched if not t["needs_assignment"]]
    needs_assignment = [t for t in matched if t["needs_assignment"]]

    # Table 2 — auto-assigned
    print(f"\nTABLE 2 — AUTO-ASSIGNED ({len(auto_assigned)} transaction(s))")
    print("=" * (_W_DATE + _W_NAME + _W_AMOUNT + _W_PROPERTY + _W_CATEGORY + _W_TYPE + 6))
    if auto_assigned:
        _print_assigned_table(auto_assigned)
    else:
        print("  None.")

    # Table 3 — needs manual assignment
    print(f"\nTABLE 3 — NEEDS MANUAL ASSIGNMENT ({len(needs_assignment)} transaction(s))")
    print("=" * (_W_DATE + _W_NAME + _W_AMOUNT + _W_CATEGORY + _W_TYPE + 4))
    if needs_assignment:
        _print_needs_assignment_table(needs_assignment)
    else:
        print("  None.")

    # Write all matched transactions to the ledger
    result = write_transactions(matched, str(ledger_path))

    added_txns        = result.get("added_transactions", [])
    new_auto_assigned = [t for t in added_txns if not t["needs_assignment"]]
    new_needs_manual  = [t for t in added_txns if t["needs_assignment"]]

    divider = "=" * 44
    print(f"\n{divider}")
    print("📊 LEDGER SYNC SUMMARY")
    print(divider)
    print(f"✅ New transactions added   : {result['added']}")
    print(f"⏭️  Duplicates skipped       : {result['skipped']}")
    print(f"⚠️  Needs manual assignment  : {len(needs_assignment)}")
    print(f"📁 Ledger updated           : {ledger_path}")
    if token_status:
        token_display = "✅ Valid (reused)" if token_status == "valid" else "🔄 Refreshed (re-authenticated)"
        print(f"🔑 Token status             : {token_display}")
    print(divider)

    summary = {
        "added":              result["added"],
        "skipped":            result["skipped"],
        "manual":             len(needs_assignment),
        "ledger_path":        str(ledger_path),
        "token_status":       token_status,
        "auto_assigned":      auto_assigned,
        "needs_manual":       needs_assignment,
        "new_auto_assigned":  new_auto_assigned,
        "new_needs_manual":   new_needs_manual,
        "run_datetime":       datetime.now().strftime("%B %d, %Y at %I:%M %p"),
    }
    try:
        send_sync_summary(summary)
    except Exception as e:
        print(f"⚠️  Email notification failed: {e}")

    return summary


def run_csv(csv_path: str):
    """Load transactions from a BofA CSV export and run the pipeline."""
    load_dotenv(_ENV_PATH)
    transactions = load_bofa_csv(csv_path)
    ledger_path  = Path(__file__).resolve().parent.parent / os.environ.get("LEDGER_FILE_PATH", "ledger.xlsx")
    print()
    _run_pipeline(transactions, ledger_path)


def run_sync(from_date: str | date | None = None):
    """
    Fetch transactions via Plaid and sync to ledger.

    In cloud mode (RAILWAY_ENVIRONMENT set): downloads ledger from Google Drive
    before sync, uploads it back after. In local mode: uses LEDGER_FILE_PATH from .env.

    from_date may be a YYYY-MM-DD string, a date object, or None (defaults to 3 days ago).
    """
    load_dotenv(_ENV_PATH)

    is_cloud = bool(os.getenv("RAILWAY_ENVIRONMENT"))

    if is_cloud:
        from drive_sync import download_ledger, upload_ledger
        file_id     = os.environ["GOOGLE_DRIVE_FILE_ID"]
        ledger_path = Path(_CLOUD_LEDGER_PATH)
        print(f"☁️  Cloud mode — downloading ledger from Google Drive (file_id={file_id})")
        download_ledger(file_id, str(ledger_path))
    else:
        ledger_path = Path(__file__).resolve().parent.parent / os.environ.get("LEDGER_FILE_PATH", "ledger.xlsx")

    plaid_env = os.getenv("PLAID_ENV", "sandbox").lower()
    print(f"🔗 Running in {plaid_env.upper()} mode")

    client       = PlaidClient()
    token_status = None

    if plaid_env == "sandbox":
        print("Obtaining sandbox access token...")
        access_token = client.get_sandbox_access_token()
        set_key(str(_ENV_PATH), "PLAID_ACCESS_TOKEN", access_token)
        print(f"Saved PLAID_ACCESS_TOKEN to {_ENV_PATH.name}")

    elif plaid_env == "production":
        access_token = os.getenv("PLAID_ACCESS_TOKEN", "").strip()

        if not access_token:
            print("No PLAID_ACCESS_TOKEN found — launching Plaid Link browser flow...")
            access_token = run_link_flow(client)
            set_key(str(_ENV_PATH), "PLAID_ACCESS_TOKEN", access_token)
            print("✅ Access token saved. Fetching transactions...")
            token_status = "refreshed"
        else:
            print("Verifying existing PLAID_ACCESS_TOKEN...")
            if client.verify_access_token(access_token):
                print("✅ Access token valid — fetching transactions...")
                token_status = "valid"
            else:
                print("⚠️  Access token expired or invalid — launching re-authentication...")
                set_key(str(_ENV_PATH), "PLAID_ACCESS_TOKEN", "")
                access_token = run_link_flow(client)
                set_key(str(_ENV_PATH), "PLAID_ACCESS_TOKEN", access_token)
                print("✅ Access token saved. Fetching transactions...")
                token_status = "refreshed"

    else:
        raise ValueError(f"Unsupported PLAID_ENV value: '{plaid_env}' (expected 'sandbox' or 'production')")

    end_date = date.today()
    if from_date is None:
        start_date = end_date - timedelta(days=3)
    elif isinstance(from_date, str):
        start_date = _parse_from_date(from_date)
    else:
        start_date = from_date

    print(f"Fetching transactions from {start_date} to {end_date}...\n")
    transactions = client.get_transactions(access_token, start_date, end_date)

    token_status = token_status if plaid_env == "production" else None
    _run_pipeline(transactions, ledger_path, token_status)

    if is_cloud:
        print("☁️  Uploading updated ledger to Google Drive...")
        upload_ledger(file_id, str(ledger_path))


# Keep run_plaid as a local-only alias for backwards compatibility
def run_plaid(start_date: date | None = None):
    run_sync(from_date=start_date)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rental ledger sync tool")
    parser.add_argument(
        "--csv",
        metavar="FILE",
        help="Path to a Bank of America CSV export. If provided, skips all Plaid API calls.",
    )
    parser.add_argument(
        "--from-date",
        metavar="YYYY-MM-DD",
        help="Start date for fetching transactions (default: 3 days ago). Ignored when --csv is used.",
    )
    parser.add_argument(
        "--fix-category",
        action="store_true",
        help=(
            "One-time fix: update the John Campbell security deposit row "
            "(2026-04-14, $2350.00) from 'Rent' to 'Security Deposit', then exit."
        ),
    )
    parser.add_argument(
        "--update-mortgage-category",
        action="store_true",
        help=(
            "One-time fix: rename 'Mortgage - Principal' → 'Mortgage - P + I' "
            "in the Categories sheet and all Ledger rows, then exit."
        ),
    )
    args = parser.parse_args()

    if args.update_mortgage_category:
        load_dotenv(_ENV_PATH)
        ledger_path = Path(__file__).resolve().parent.parent / os.environ.get("LEDGER_FILE_PATH", "ledger.xlsx")
        try:
            update_mortgage_category_in_ledger(str(ledger_path))
        except Exception as e:
            print(f"❌ update-mortgage-category failed: {e}")
            raise SystemExit(1)
        raise SystemExit(0)

    if args.fix_category:
        load_dotenv(_ENV_PATH)
        ledger_path = Path(__file__).resolve().parent.parent / os.environ.get("LEDGER_FILE_PATH", "ledger.xlsx")
        try:
            fix_transaction_category(
                ledger_path=str(ledger_path),
                date_str="2026-04-14",
                amount=2350.00,
                old_category="Rent",
                new_category="Security Deposit",
            )
        except Exception as e:
            print(f"❌ fix-category failed: {e}")
            raise SystemExit(1)
        raise SystemExit(0)

    from_date = _parse_from_date(args.from_date) if args.from_date else None

    if args.csv:
        run_csv(args.csv)
    else:
        run_sync(from_date=from_date)

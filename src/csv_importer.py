import csv
from datetime import datetime
from pathlib import Path


def load_bofa_csv(filepath: str) -> list[dict]:
    """
    Load a Bank of America transaction CSV export.

    Expected columns: Date, Description (plus any others which are ignored).
    - Date is parsed from M/D/YY or MM/DD/YY format into a Python date object.
    - Description is used as the transaction name.
    - Amount is set to 0.0 (BofA export has no amount column in this format).
    - Rows with an empty Description are skipped.

    Returns a list of dicts with keys: date, name, amount.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path.resolve()}")

    transactions = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            description = row.get("Description", "").strip()
            if not description:
                continue
            raw_date = row.get("Date", "").strip()
            txn_date = datetime.strptime(raw_date, "%m/%d/%y").date()
            transactions.append({
                "date":   txn_date,
                "name":   description,
                "amount": 0.0,
            })

    print(f"Loaded {len(transactions)} transactions from CSV.")
    return transactions

# 🏠 Rental Property Ledger Sync

An automated tool that syncs bank transactions from your Bank of America account
(via Plaid API) directly into a color-coded Excel ledger — with daily email
summaries and smart rule-based categorization.

## Features

- 🏦 **Live bank connection** via Plaid Production API (Bank of America + others)
- 🎨 **Color-coded Excel ledger** — each property gets a unique color
- 🤖 **Smart transaction filtering** — rule-based matching for tenants, mortgages, utilities
- 📊 **Auto-assignment** — maps transactions to correct properties automatically
- 📧 **Daily email summaries** — HTML report with today's new transactions highlighted
- 🔄 **Duplicate detection** — never double-enters a transaction
- 📅 **Flexible date ranges** — sync last 5 days by default, or specify any start date
- 📥 **CSV import mode** — import directly from a BofA CSV export without using Plaid
- 🔒 **Secure** — credentials stored in `.env`, never committed to Git
- ⏰ **Scheduled daily runs** — macOS launchd integration included

## Project Structure

```
rental-ledger-sync/
├── src/
│   ├── main.py            # Entry point — CLI args, orchestrates the pipeline
│   ├── plaid_client.py    # Plaid API wrapper (sandbox + production)
│   ├── link_flow.py       # Plaid Link browser OAuth flow (Flask local server)
│   ├── filters.py         # Rule-based transaction matching and categorization
│   ├── ledger_writer.py   # Excel ledger writer (openpyxl)
│   ├── csv_importer.py    # BofA CSV import mode
│   └── email_notifier.py  # Gmail HTML email summaries
├── scripts/
│   ├── start_sync.sh          # Shell wrapper (used by launchd)
│   ├── install_scheduler.sh   # Install macOS launchd daily schedule
│   └── uninstall_scheduler.sh # Remove launchd schedule
├── rules.json             # Your personal transaction matching rules (git-ignored)
├── rules.template.json    # Example rules — copy this to rules.json to start
├── .env                   # Your credentials (git-ignored)
├── .env.template          # Credential template — copy this to .env to start
├── requirements.txt       # Python dependencies
└── com.rental.ledger.sync.plist  # macOS launchd plist (git-ignored — has local paths)
```

## Prerequisites

- Python 3.11+
- A [Plaid account](https://dashboard.plaid.com) with Production access enabled
- A Bank of America account connected to Plaid (or any supported institution)
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) for email notifications
- An Excel workbook with a sheet named **`Ledger`** (columns A–J as described below)

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/rental-ledger-sync.git
cd rental-ledger-sync
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.template .env
```

Edit `.env` and fill in your values:

| Variable | Description |
|---|---|
| `PLAID_CLIENT_ID` | From [Plaid Dashboard](https://dashboard.plaid.com) → Team Settings |
| `PLAID_SECRET` | Production secret from Plaid Dashboard |
| `PLAID_ENV` | `production` or `sandbox` |
| `EMAIL_SENDER` | Your Gmail address |
| `EMAIL_APP_PASSWORD` | 16-character Gmail App Password |
| `EMAIL_RECIPIENT` | Where to send daily summaries |
| `LEDGER_FILE_PATH` | Full path to your Excel workbook |

### 3. Set up your rules

```bash
cp rules.template.json rules.json
```

Edit `rules.json` to match your tenants, properties, and servicers. See [Rules Reference](#rules-reference) below.

### 4. Prepare your Excel ledger

Your workbook must have a sheet named **`Ledger`** with headers in row 1:

| Col | Field | Notes |
|---|---|---|
| A | Date | `MM-DD-YYYY` format |
| B | Month # | Auto-filled (1–12) |
| C | MM-YYYY | Auto-filled |
| D | Year | Auto-filled |
| E | Property | Full address string |
| F | Category | e.g. Rent, Mortgage - Principal |
| G | Type | `Income` or `Expense` |
| H | Description | Raw transaction name from bank |
| I | Amount | Dollar amount (always positive) |
| J | Notes | Rule note / manual notes |

Row 2 is reserved for instructions. Data starts at row 3.

## Usage

### Sync via Plaid (recommended)

On first run with `PLAID_ENV=production`, a browser window opens for Plaid Link authentication:

```bash
python src/main.py
```

Subsequent runs reuse the saved `PLAID_ACCESS_TOKEN` in `.env`.

### Specify a custom date range

```bash
python src/main.py --from-date 2026-01-01
```

### Import from a BofA CSV export

```bash
python src/main.py --csv /path/to/export.csv
```

Download a CSV from Bank of America's website: Accounts → Activity → Export.

### Sandbox mode (testing without real bank data)

Set `PLAID_ENV=sandbox` in `.env`. The tool uses Plaid's test institution and generates
synthetic transactions — no real bank connection needed.

```bash
python src/main.py
```

### One-time ledger fixes

```bash
# Fix a specific transaction's category in the Excel ledger
python src/main.py --fix-category
```

> **Note:** The `--fix-category` flag is hardcoded for a specific correction.
> Edit the call in `main.py` before using it for your own fixes.

## Rules Reference

Rules are defined in `rules.json` as a JSON array. Each rule is matched
case-insensitively against the transaction description. **Longer keywords take
priority** — so specific rules always win over generic fallbacks.

### Rule fields

| Field | Required | Description |
|---|---|---|
| `keyword` | ✅ | Substring to match against the transaction name (case-insensitive) |
| `property` | ✅ | Full property address, `"** ASSIGN PROPERTY **"`, `"SKIP"`, or `"AMOUNT_BASED"` |
| `category` | ✅ | e.g. `Rent`, `Mortgage - Principal`, `HOA Fees`, `Utilities`, `Insurance Protection`, `Property Tax`, `Maintenance/Repair`, `Security Deposit` |
| `type` | ✅ | `Income` or `Expense` |
| `note` | | Descriptive note written to Col J of the ledger |

### Special property values

| Value | Behavior |
|---|---|
| `"** ASSIGN PROPERTY **"` | Transaction is written to ledger but flagged for manual property assignment |
| `"SKIP"` | Transaction is silently excluded (personal expenses, primary residence) |
| `"AMOUNT_BASED"` | Property is resolved by looking up the transaction amount in a map defined in `filters.py` |

### Example rules

```json
[
  {"keyword": "Zelle payment from JANE DOE", "property": "123 Main St Anytown CA 90210", "category": "Rent", "type": "Income", "note": "Tenant: Jane Doe"},
  {"keyword": "Zelle payment from", "property": "** ASSIGN PROPERTY **", "category": "Rent", "type": "Income", "note": "Unknown tenant - assign property manually"},
  {"keyword": "ACME MORTGAGE DES:LOAN ID:1234567", "property": "123 Main St Anytown CA 90210", "category": "Mortgage - Principal", "type": "Expense", "note": "Acme Mortgage loan 1234567"},
  {"keyword": "PERSONAL EXPENSE", "property": "SKIP", "category": "", "type": "", "note": "Primary residence expense - not a rental"}
]
```

See `rules.template.json` for a complete starting-point template.

## Scheduling (macOS)

A launchd plist is included to run the sync automatically every morning at 7:00 AM.

### Setup

1. Copy and edit the plist template:
   ```bash
   cp com.rental.ledger.sync.plist.template com.rental.ledger.sync.plist
   # Edit com.rental.ledger.sync.plist — replace /Users/YOUR_USERNAME with your home directory
   ```

2. Install the schedule:
   ```bash
   bash scripts/install_scheduler.sh
   ```

3. To uninstall:
   ```bash
   bash scripts/uninstall_scheduler.sh
   ```

Logs are written to `logs/sync.log` and `logs/sync_error.log`.

> **Note:** `com.rental.ledger.sync.plist` is git-ignored because it contains hardcoded
> local paths. Create your own from the template above.

## Email Notifications

After each sync run, an HTML email is sent to `EMAIL_RECIPIENT` containing:

- **KPI row** — new transactions added, duplicates skipped, items needing manual review
- **Today's New Transactions** — only the transactions written in this run, split into
  auto-assigned (green) and needs-review (orange) sections
- **Full Run Details** — collapsible section with all matched transactions from this run

If `EMAIL_SENDER`, `EMAIL_APP_PASSWORD`, or `EMAIL_RECIPIENT` are not set in `.env`,
email is silently skipped.

## Property Color Coding

Each property address gets a unique fill and font color in the Excel ledger.
Colors are defined in `_PROPERTY_COLORS` in `src/ledger_writer.py`. Edit that dict
to add colors for your own properties.

## Contributing

Pull requests welcome. Please ensure no real names, addresses, account numbers,
or credentials are included in any committed files.

## License

MIT

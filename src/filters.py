import json
import os
from pathlib import Path

_RULES_PATH = Path(__file__).resolve().parent.parent / "rules.json"

# Transactions whose name contains any of these strings are silently skipped —
# they are personal/internal banking movements, not rental-property transactions.
_SKIP_KEYWORDS = [
    "CHASE CREDIT CRD",
    "JPMORGAN CHASE DES:CHASE ACH",
    "Agent Assisted transfer",
    "Guillermina Zacha",
    "hoong greenfield",
    "Rita Rita",
    "XANG VANG",
    "BANK OF AMERICA DES:MORTGAGE",
    "SANTA CLARA COUNTY DTAC",
    "UNITED TAX",
    "PG&E",
    "SAN JOSE WATER COMPANY",
    "LINK2GOV CORPORATION",
]

# Amount-based property lookup tables.
# Used when a matched rule has property="AMOUNT_BASED".
# Key: round(abs(amount), 2)  Value: resolved property address
STOCKTON_UTILITY_MAP: dict[float, str] = {
    54.39: "2516 Mission Rd Stockton CA 95204",
    49.32: "1867 Elmwood Ave Stockton CA 95204",
}

VCN_TAX_MAP: dict[float, str] = {
    6861.21: "2431 Mulholland Drive Lathrop CA 95330",
    3772.73: "2516 Mission Rd Stockton CA 95204",
    2134.99: "807 W. Center St Manteca CA 95337",
    6923.48: "1769 Mulholland Drive Lathrop CA 95330",
    7227.51: "16945 Strauss Court Lathrop CA 95330",
    5310.69: "16150 Sheltered Cove Lathrop CA 95330",
}

# Tenants whose category depends on the transaction description content.
# If any deposit_keyword appears (case-insensitive) in the transaction name,
# use deposit_category; otherwise use default_category.
SPECIAL_CATEGORY_RULES: dict[str, dict] = {
    # Used when the SAME keyword can map to different categories depending on context.
    # Rules with a unique, hardcoded keyword (e.g. "Zelle Transfer Conf# 99CD3K70B")
    # must NOT be listed here — their category is taken directly from rules.json.
    "john campbell": {
        "check_field":      "name",
        "deposit_keywords": ["deposit", "security"],
        "default_category": "Rent",
        "deposit_category": "Security Deposit",
    },
}

# Maps keyword (lowercase) → the amount lookup table to use
_AMOUNT_MAP_BY_KEYWORD: dict[str, dict[float, str]] = {
    "vcn*sjc ttc online":       VCN_TAX_MAP,
    "city of stockton utility": STOCKTON_UTILITY_MAP,
    "city of stockton utility": STOCKTON_UTILITY_MAP,  # covers both case variants via lower()
}


def _load_rules() -> list[dict]:
    rules_json = os.getenv("RULES_JSON")
    if rules_json:
        rules = json.loads(rules_json)
        print(f"✅ Loaded {len(rules)} rules from RULES_JSON environment variable")
    else:
        rules_path = _RULES_PATH
        try:
            with open(rules_path) as f:
                rules = json.load(f)
            print(f"✅ Loaded {len(rules)} rules from {rules_path}")
        except FileNotFoundError:
            print(f"❌ CRITICAL: rules.json not found at {rules_path}")
            print("   On Railway: add RULES_JSON environment variable or commit rules.json")
            return []
    # Longer keywords are more specific and must be evaluated before shorter ones
    # e.g. "ROCKET MORTGAGE DES:LOAN ID:565163" wins over "ROCKET MORTGAGE"
    return sorted(rules, key=lambda r: len(r["keyword"]), reverse=True)


def _resolve_amount_based(txn: dict, matched_rule: dict) -> tuple[str, bool]:
    """
    Resolve a property for rules with property="AMOUNT_BASED" by looking up
    the transaction amount in the appropriate map.

    Returns (property_value, needs_assignment).
    """
    amount_key = round(abs(float(txn.get("amount", 0))), 2)
    keyword_lower = matched_rule["keyword"].lower()
    amount_map = _AMOUNT_MAP_BY_KEYWORD.get(keyword_lower)

    if amount_map is None:
        # No map registered for this keyword — flag for manual assignment
        return "** ASSIGN PROPERTY **", True

    property_val = amount_map.get(amount_key)
    if property_val is None:
        # Amount not in map — unknown, flag for manual assignment
        return "** ASSIGN PROPERTY **", True

    needs_assignment = property_val == "** ASSIGN PROPERTY **"
    return property_val, needs_assignment


def match_truncated_zelle(transaction_name: str, rules: list[dict]) -> dict | None:
    """
    Handle BofA's truncated Zelle format: "Zelle Transfer Conf# XXXXXXX; XX..."

    BofA sometimes truncates the sender name to just 2–3 characters after a semicolon.
    This function extracts that partial name and checks whether it is a prefix of any
    known tenant name in the "Zelle payment from" rules.

    Returns the matching rule dict if found, otherwise None.
    """
    prefix = "zelle transfer conf#"
    if not transaction_name.lower().startswith(prefix):
        return None

    # Extract partial name after the semicolon, e.g. "Zelle Transfer Conf# 99CDW75D0; ME" → "ME"
    semicolon_pos = transaction_name.find(";")
    if semicolon_pos == -1:
        return None
    partial = transaction_name[semicolon_pos + 1:].strip().lower()
    if not partial:
        return None

    for rule in rules:
        kw = rule["keyword"]
        if not kw.lower().startswith("zelle payment from "):
            continue
        tenant_name = kw[len("Zelle payment from "):].strip().lower()
        if tenant_name.startswith(partial):
            return rule

    return None


def filter_rental_transactions(transactions: list[dict]) -> list[dict]:
    """
    Match each transaction against rules loaded from rules.json.

    Matching behaviour:
    - Rules are sorted by keyword length descending so specific keywords
      always take priority over generic prefixes.
    - Matching is case-insensitive substring search against the transaction name.
    - Transactions whose name contains a _SKIP_KEYWORDS entry are excluded entirely.
    - Rules with property="SKIP" are excluded entirely (personal/non-rental).
    - Rules with property="AMOUNT_BASED" resolve the property via an amount lookup
      table; if the amount is not found the transaction is flagged for manual assignment.
    - "WIRE TYPE" rules only match when the transaction name also contains "RENT".

    Each returned dict has the original transaction fields plus:
        property         — resolved address, or "** ASSIGN PROPERTY **"
        category         — from the matched rule
        type             — "Income" or "Expense"
        note             — from the matched rule
        needs_assignment — True when property must be filled in manually
    """
    rules = _load_rules()
    results = []

    for txn in transactions:
        name       = txn.get("name", "")
        name_lower = name.lower()

        # --- Skip personal/banking transactions ---
        if any(skip.lower() in name_lower for skip in _SKIP_KEYWORDS):
            continue

        # --- Special guard: WIRE TYPE without RENT → skip entire transaction ---
        if "wire type" in name_lower and "rent" not in name_lower:
            continue

        # --- Truncated Zelle: "Zelle Transfer Conf# XXX; ME..." → match by partial name ---
        matched_rule = match_truncated_zelle(name, rules)

        # --- Find first matching rule (longest keyword wins due to pre-sort) ---
        if matched_rule is None:
            for rule in rules:
                if rule["keyword"].lower() in name_lower:
                    matched_rule = rule
                    break

        if matched_rule is None:
            continue

        # Rules with property="SKIP" are personal/non-rental — exclude entirely
        if matched_rule["property"] == "SKIP":
            continue

        # --- Resolve property ---
        if matched_rule["property"] == "AMOUNT_BASED":
            property_val, needs_assignment = _resolve_amount_based(txn, matched_rule)
        elif matched_rule["property"] == "** ASSIGN PROPERTY **":
            property_val, needs_assignment = "** ASSIGN PROPERTY **", True
        else:
            property_val, needs_assignment = matched_rule["property"], False

        # --- Override category for tenants with context-dependent categories ---
        # Check against matched_rule["keyword"], NOT name_lower, so that a transaction
        # whose description happens to contain "john campbell" (e.g. a Conf# truncated Zelle)
        # is not misclassified — the override only fires when the matched rule's keyword
        # itself contains the tenant name.
        category = matched_rule["category"]
        matched_keyword_lower = matched_rule["keyword"].lower()
        for tenant_key, scr in SPECIAL_CATEGORY_RULES.items():
            if tenant_key in matched_keyword_lower:
                if any(dk in name_lower for dk in scr["deposit_keywords"]):
                    category = scr["deposit_category"]
                else:
                    category = scr["default_category"]
                break

        results.append({
            **txn,
            "property":         property_val,
            "category":         category,
            "type":             matched_rule["type"],
            "note":             matched_rule.get("note", ""),
            "needs_assignment": needs_assignment,
        })

    return results

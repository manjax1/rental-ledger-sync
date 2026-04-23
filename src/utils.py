def clean_env(value: str | None, name: str = "") -> str:
    """Strip whitespace and surrounding quotes that Railway may add to env vars."""
    if not value:
        return ""
    original = value
    value = value.strip()
    if len(value) >= 2 and (
        (value.startswith("'") and value.endswith("'")) or
        (value.startswith('"') and value.endswith('"'))
    ):
        value = value[1:-1]
        label = f" {name}" if name else ""
        print(f"🔍 Stripped quotes from{label}: was {len(original)} chars, now {len(value)} chars")
    return value

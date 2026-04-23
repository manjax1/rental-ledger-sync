def clean_env(value: str | None) -> str:
    """Strip whitespace and surrounding quotes that Railway may add to env vars."""
    if not value:
        return ""
    value = value.strip()
    if len(value) >= 2 and (
        (value.startswith("'") and value.endswith("'")) or
        (value.startswith('"') and value.endswith('"'))
    ):
        value = value[1:-1]
    return value

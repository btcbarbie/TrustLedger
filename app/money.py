"""Money is stored as integer kobo everywhere. No floats touch amounts."""
import re
from decimal import Decimal, InvalidOperation

_AMOUNT = re.compile(
    r"^\s*(?:₦|NGN|N)?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?\s*(k|m)?\s*$",
    re.IGNORECASE,
)


def parse_naira(text) -> int | None:
    """'₦45,000.00' / '45000' / '50k' / 'NGN 2,000' -> kobo. None if unparseable."""
    if text is None:
        return None
    m = _AMOUNT.match(str(text))
    if not m:
        return None
    whole, frac, suffix = m.group(1).replace(",", ""), m.group(2) or "", (m.group(3) or "").lower()
    try:
        value = Decimal(whole + frac)
    except InvalidOperation:
        return None
    if suffix == "k":
        value *= 1000
    elif suffix == "m":
        value *= 1_000_000
    kobo = int((value * 100).to_integral_value())
    return kobo if kobo > 0 else None


def format_naira(kobo) -> str:
    if kobo is None:
        return "-"
    naira, rem = divmod(int(kobo), 100)
    return f"₦{naira:,}" + (f".{rem:02d}" if rem else "")

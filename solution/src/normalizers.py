import re
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

IST = timezone(timedelta(hours=5, minutes=30))


def normalize_header(value):
    return re.sub(r"[_\s]+", " ", (value or "").strip().lower())


def normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("invalid_phone")
    return "+91" + digits


def parse_date(value):
    value = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("invalid_date")


def parse_decimal(value):
    s = str(value or "").strip()
    s = re.sub(r"^(?:₹|rs\.?|inr)\s*", "", s, flags=re.I)
    s = s.replace(",", "").strip()
    try:
        n = Decimal(s)
    except InvalidOperation:
        raise ValueError("invalid_decimal")
    if n < 0:
        raise ValueError("invalid_decimal")
    return str(n.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalize_value(field, value):
    s = str(value or "").strip()
    if not s:
        return None
    kind = field["type"]
    if kind == "string":
        return s
    if kind == "phone":
        return normalize_phone(s)
    if kind == "date":
        return parse_date(s)
    if kind == "decimal":
        return parse_decimal(s)
    if kind == "enum":
        v = s.lower()
        if v not in [x.lower() for x in field.get("values", [])]:
            raise ValueError("invalid_enum")
        return v
    raise ValueError(f"unsupported_type:{kind}")


def parse_timestamp(value):
    s = str(value or "").strip()
    if s.endswith("Z"):
        dt = datetime.fromisoformat(s[:-1] + "+00:00")
    else:
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def ist_timestamp(utc_iso):
    dt = datetime.fromisoformat(utc_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat(timespec="seconds")


def ist_date(utc_iso):
    return datetime.fromisoformat(utc_iso).astimezone(IST).date().isoformat()

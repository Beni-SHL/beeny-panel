"""Account renewal rules kept independent of Flask and the database."""
from datetime import date, timedelta


def extend_expiry(current, days, mode="extend", today=None):
    """Return an ISO date, or pending-day count before first connection."""
    if not 1 <= days <= 3650 or mode not in ("extend", "from_today"):
        raise ValueError("Invalid renewal")
    today = today or date.today()
    if current and current.isdigit() and mode == "extend":
        return str(int(current) + days)
    old_expiry = None
    if current and current not in ("-", "") and not current.isdigit():
        old_expiry = date.fromisoformat(current)
    base = max(today, old_expiry) if old_expiry and mode == "extend" else today
    return (base + timedelta(days=days)).isoformat()


def activation_error(expiry, limit, usage, today=None):
    today = today or date.today()
    if expiry and expiry not in ("-", "") and not expiry.isdigit():
        try:
            if date.fromisoformat(expiry) < today:
                return "The account is expired. Add renewal days before activating."
        except ValueError:
            return "Stored expiry date is invalid; contact the administrator."
    if limit > 0 and usage >= limit:
        return "The data limit is used up. Raise the limit or select Reset traffic."
    return None

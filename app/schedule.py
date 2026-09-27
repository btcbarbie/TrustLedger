"""Builds the dated periods of a recurring contribution (deterministic, no AI)."""
import calendar
from datetime import date, timedelta

MAX_PERIODS = 104


def periods(frequency: str, first_due: date, count: int) -> list[tuple[str, date]]:
    """[(label, due_date)] e.g. ('Week 3', 2026-10-17) or ('Oct 2026', 2026-10-31)."""
    out = []
    for k in range(count):
        if frequency == "weekly":
            out.append((f"Week {k + 1}", first_due + timedelta(weeks=k)))
        else:
            y, m = divmod(first_due.month - 1 + k, 12)
            y += first_due.year
            day = min(first_due.day, calendar.monthrange(y, m + 1)[1])
            d = date(y, m + 1, day)
            out.append((d.strftime("%b %Y"), d))
    return out


def create_series(conn, group_id: int, series: str, frequency: str, amount_kobo: int,
                  first_due: date, count: int) -> list[int]:
    category = "weekly" if frequency == "weekly" else "monthly"
    ids = []
    for label, due in periods(frequency, first_due, count):
        ids.append(conn.execute(
            "INSERT INTO obligations(group_id,title,category,amount_due_kobo,due_date,series) VALUES (?,?,?,?,?,?)",
            (group_id, f"{series} - {label}", category, amount_kobo, due.isoformat(), series)).lastrowid)
    return ids

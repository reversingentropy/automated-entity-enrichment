"""Month arithmetic, since every source is sliced by month."""

import datetime as dt


def parse(text: str) -> tuple[int, int]:
    y, m = text.split("-")
    return int(y), int(m)


def span(start: str, end: str | None = None) -> list[tuple[int, int]]:
    """Every (year, month) from start to end inclusive; end defaults to now."""
    y, m = parse(start)
    if end:
        ey, em = parse(end)
    else:
        today = dt.date.today()
        ey, em = today.year, today.month
    out = []
    while (y, m) <= (ey, em):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def bounds(y: int, m: int) -> tuple[int, int]:
    """Unix seconds for the first and last instant of the month, UTC."""
    a = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    b = dt.datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=dt.timezone.utc)
    return int(a.timestamp()), int(b.timestamp()) - 1


def label(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"

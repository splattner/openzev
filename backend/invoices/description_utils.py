from datetime import date


def strip_period_suffix(description: str, period_start: date, period_end: date) -> str:
    start = period_start.isoformat()
    end = period_end.isoformat()
    text = (description or "").rstrip()

    suffixes = [
        f" {start} – {end}",
        f" {start} - {end}",
        f" {start} to {end}",
    ]

    for suffix in suffixes:
        if text.endswith(suffix):
            return text[: -len(suffix)].rstrip()

    return text

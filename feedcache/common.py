from datetime import datetime, timezone


def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

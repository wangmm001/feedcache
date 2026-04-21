import tempfile
from pathlib import Path

from feedcache.common import (
    deterministic_gzip,
    download_to,
    today_utc_date,
    update_current,
)

UPSTREAM_URL = "https://downloads.majestic.com/majestic_million.csv"


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        csv_path = Path(tmp.name)
    try:
        download_to(UPSTREAM_URL, csv_path)
        csv_bytes = csv_path.read_bytes()
    finally:
        if csv_path.exists():
            csv_path.unlink()

    date = today_utc_date()
    deterministic_gzip(csv_bytes, out / f"{date}.csv.gz")
    update_current(out, "????-??-??.csv.gz", "current.csv.gz")
    return True

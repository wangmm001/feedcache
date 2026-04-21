import csv
import io
from pathlib import Path

from tranco import Tranco

from feedcache.common import (
    deterministic_gzip,
    today_utc_date,
    update_current,
    write_if_changed,
)

TRANCO_CACHE_DIR = "/tmp/feedcache-tranco-cache"


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    client = Tranco(cache_dir=TRANCO_CACHE_DIR)
    latest = client.list()
    version_id = latest.list_id

    current_version_file = out / "current.version.txt"
    if current_version_file.exists():
        existing = current_version_file.read_text().strip()
        if existing == version_id:
            return True  # no-op, upstream unchanged

    domains = latest.top(1_000_000)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for rank, domain in enumerate(domains, start=1):
        writer.writerow([rank, domain])
    csv_bytes = buf.getvalue().encode("utf-8")

    date = today_utc_date()
    deterministic_gzip(csv_bytes, out / f"{date}_{version_id}.csv.gz")
    write_if_changed((version_id + "\n").encode(), out / f"{date}.version.txt")
    update_current(out, "????-??-??_*.csv.gz", "current.csv.gz")
    write_if_changed((version_id + "\n").encode(), current_version_file)
    return True

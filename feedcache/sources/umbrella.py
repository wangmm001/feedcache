import tempfile
import zipfile
from pathlib import Path

from feedcache.common import (
    deterministic_gzip,
    download_to,
    today_utc_date,
    update_current,
)

UPSTREAM_URL = "https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip"


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        zip_path = Path(tmp.name)
    try:
        download_to(UPSTREAM_URL, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
            if len(csv_names) != 1:
                raise RuntimeError(
                    f"Expected exactly one CSV in Umbrella zip, got {csv_names}"
                )
            csv_bytes = zf.read(csv_names[0])
    finally:
        if zip_path.exists():
            zip_path.unlink()

    date = today_utc_date()
    deterministic_gzip(csv_bytes, out / f"{date}.csv.gz")
    update_current(out, "????-??-??.csv.gz", "current.csv.gz")
    return True

import tempfile
from pathlib import Path

from feedcache.common import (
    deterministic_gzip,
    download_to,
    today_utc_date,
    update_current,
)

UPSTREAM_URL = "https://publicsuffix.org/list/public_suffix_list.dat"


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as tmp:
        dat_path = Path(tmp.name)
    try:
        download_to(UPSTREAM_URL, dat_path)
        content = dat_path.read_bytes()
    finally:
        if dat_path.exists():
            dat_path.unlink()

    date = today_utc_date()
    deterministic_gzip(content, out / f"{date}.dat.gz")
    update_current(out, "????-??-??.dat.gz", "current.dat.gz")
    return True

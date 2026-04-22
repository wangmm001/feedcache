import tempfile
import zipfile
from pathlib import Path

import requests

from feedcache.common import (
    deterministic_gzip,
    today_utc_date,
    update_current,
    write_if_changed,
)

UPSTREAM_URL = "https://www.domcop.com/files/top/top10milliondomains.csv.zip"
TIMEOUT = 600


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lastmod_file = out / "current.last-modified.txt"
    prev_lastmod = (
        lastmod_file.read_text().strip() if lastmod_file.exists() else ""
    )

    headers = {}
    if prev_lastmod:
        headers["If-Modified-Since"] = prev_lastmod

    with requests.get(
        UPSTREAM_URL, headers=headers, stream=True, timeout=TIMEOUT
    ) as r:
        if r.status_code == 304:
            return True
        r.raise_for_status()
        new_lastmod = r.headers.get("Last-Modified", "").strip()

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            zip_path = Path(tmp.name)
        try:
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
            with zipfile.ZipFile(zip_path) as zf:
                members = [n for n in zf.namelist() if n.endswith(".csv")]
                if len(members) != 1:
                    raise RuntimeError(
                        f"unexpected zip contents: {zf.namelist()!r}"
                    )
                with zf.open(members[0]) as cf:
                    csv_bytes = cf.read()
        finally:
            zip_path.unlink(missing_ok=True)

    date = today_utc_date()
    deterministic_gzip(csv_bytes, out / f"{date}.csv.gz")
    update_current(out, "????-??-??.csv.gz", "current.csv.gz")

    if new_lastmod:
        write_if_changed(
            (new_lastmod + "\n").encode("utf-8"), lastmod_file
        )
    return True

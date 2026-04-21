import os
from pathlib import Path

import requests

from feedcache.common import deterministic_gzip, today_utc_date

BUCKETS = (1000, 10000, 100000, 1000000)
RADAR_DATASET_ENDPOINT = "https://api.cloudflare.com/client/v4/radar/datasets/ranking_top_{bucket}"
REQUEST_TIMEOUT = 60


def run(out_dir: str) -> bool:
    token = os.environ.get("CLOUDFLARE_RADAR_API_TOKEN")
    if not token:
        raise RuntimeError("CLOUDFLARE_RADAR_API_TOKEN environment variable not set")

    headers = {"Authorization": f"Bearer {token}"}

    # Download all 4 buckets to memory first.
    # If any one fails, we raise and write nothing — atomic snapshot semantics.
    # Response bodies are single-column CSV (one `domain` header + one domain per line),
    # updated weekly by Cloudflare. Cron runs daily; deterministic gzip + commit-if-changed
    # means unchanged weeks produce no commits.
    payloads: dict[int, bytes] = {}
    for n in BUCKETS:
        url = RADAR_DATASET_ENDPOINT.format(bucket=n)
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            raise RuntimeError(
                f"Radar API {resp.status_code} for bucket={n}: {resp.text[:800]}"
            )
        payloads[n] = resp.content

    out = Path(out_dir)
    date = today_utc_date()
    daily_dir = out / date
    current_dir = out / "current"
    daily_dir.mkdir(parents=True, exist_ok=True)
    current_dir.mkdir(parents=True, exist_ok=True)

    for n, data in payloads.items():
        deterministic_gzip(data, daily_dir / f"top-{n}.csv.gz")
        deterministic_gzip(data, current_dir / f"top-{n}.csv.gz")
    return True

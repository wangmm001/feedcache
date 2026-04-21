import json
import os
from pathlib import Path

import requests

from feedcache.common import deterministic_gzip, today_utc_date

BUCKETS = (1000, 10000, 100000, 1000000)
RADAR_TOP_ENDPOINT = "https://api.cloudflare.com/client/v4/radar/ranking/top"
REQUEST_TIMEOUT = 60


def run(out_dir: str) -> bool:
    token = os.environ.get("CLOUDFLARE_RADAR_API_TOKEN")
    if not token:
        raise RuntimeError("CLOUDFLARE_RADAR_API_TOKEN environment variable not set")

    headers = {"Authorization": f"Bearer {token}"}

    # Download all 4 buckets to memory first.
    # If any one fails, we raise and write nothing — atomic snapshot semantics.
    payloads: dict[int, bytes] = {}
    for n in BUCKETS:
        resp = requests.get(
            RADAR_TOP_ENDPOINT,
            headers=headers,
            params={"limit": n},
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            raise RuntimeError(
                f"Radar API {resp.status_code} for limit={n}: {resp.text[:800]}"
            )
        payloads[n] = json.dumps(resp.json(), sort_keys=True, ensure_ascii=False).encode("utf-8")

    out = Path(out_dir)
    date = today_utc_date()
    daily_dir = out / date
    current_dir = out / "current"
    daily_dir.mkdir(parents=True, exist_ok=True)
    current_dir.mkdir(parents=True, exist_ok=True)

    for n, data in payloads.items():
        deterministic_gzip(data, daily_dir / f"top-{n}.json.gz")
        deterministic_gzip(data, current_dir / f"top-{n}.json.gz")
    return True

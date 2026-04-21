import re
from pathlib import Path

import requests

from feedcache.common import deterministic_gzip, today_utc_date

REQUEST_TIMEOUT = 120

AWS_URL = "https://ip-ranges.amazonaws.com/ip-ranges.json"
GCP_URL = "https://www.gstatic.com/ipranges/cloud.json"
CLOUDFLARE_V4_URL = "https://www.cloudflare.com/ips-v4"
CLOUDFLARE_V6_URL = "https://www.cloudflare.com/ips-v6"

AZURE_CONFIRM_PAGE = "https://www.microsoft.com/en-us/download/confirmation.aspx?id=56519"
AZURE_URL_REGEX = re.compile(
    r"https://download\.microsoft\.com/download/[^\"']*ServiceTags_Public_\d+\.json"
)


def _fetch(url: str) -> bytes:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def _fetch_azure() -> bytes:
    confirm_resp = requests.get(AZURE_CONFIRM_PAGE, timeout=REQUEST_TIMEOUT)
    confirm_resp.raise_for_status()
    m = AZURE_URL_REGEX.search(confirm_resp.text)
    if not m:
        raise RuntimeError(
            f"Could not find Azure ServiceTags JSON URL on {AZURE_CONFIRM_PAGE}"
        )
    json_resp = requests.get(m.group(0), timeout=REQUEST_TIMEOUT)
    json_resp.raise_for_status()
    return json_resp.content


def run(out_dir: str) -> bool:
    # Fetch everything to memory first — atomic semantics.
    payloads: dict[str, bytes] = {}
    payloads["aws.json.gz"] = _fetch(AWS_URL)
    payloads["gcp.json.gz"] = _fetch(GCP_URL)
    payloads["azure.json.gz"] = _fetch_azure()
    payloads["cloudflare-v4.txt.gz"] = _fetch(CLOUDFLARE_V4_URL)
    payloads["cloudflare-v6.txt.gz"] = _fetch(CLOUDFLARE_V6_URL)

    out = Path(out_dir)
    date = today_utc_date()
    daily_dir = out / date
    current_dir = out / "current"
    daily_dir.mkdir(parents=True, exist_ok=True)
    current_dir.mkdir(parents=True, exist_ok=True)

    for filename, data in payloads.items():
        deterministic_gzip(data, daily_dir / filename)
        deterministic_gzip(data, current_dir / filename)
    return True

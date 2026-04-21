from pathlib import Path

import requests

from feedcache.common import write_if_changed


GRAPHINFO_URL = "https://index.commoncrawl.org/graphinfo.json"
BASE_URL = "https://data.commoncrawl.org/projects/hyperlinkgraph"
TOP_N = 1_000_000
TIMEOUT = 600


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    graphinfo_resp = requests.get(GRAPHINFO_URL, timeout=30)
    graphinfo_resp.raise_for_status()
    releases = graphinfo_resp.json()
    if not releases:
        return False
    release_id = releases[0]["id"]

    current_release = out / "host" / "current.release.txt"
    if current_release.exists() and current_release.read_text().strip() == release_id:
        write_if_changed(graphinfo_resp.content, out / "graphinfo.json")
        return True

    # Full download path is implemented in Task 3-5.
    raise NotImplementedError("ranks download path not yet implemented")

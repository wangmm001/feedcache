import csv
import gzip
import io
from pathlib import Path

import requests

from feedcache.common import write_if_changed


GRAPHINFO_URL = "https://index.commoncrawl.org/graphinfo.json"
BASE_URL = "https://data.commoncrawl.org/projects/hyperlinkgraph"
TOP_N = 1_000_000
TIMEOUT = 600


def _ranks_url(release_id: str, level: str) -> str:
    return f"{BASE_URL}/{release_id}/{level}/{release_id}-{level}-ranks.txt.gz"


def _reverse_entity(entity_rev: str) -> str:
    return ".".join(reversed(entity_rev.split(".")))


def _truncate_and_transform(response, entity_col: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["rank", "harmonicc_val", "pr_pos", "pr_val", entity_col])
    with gzip.GzipFile(fileobj=response.raw) as gz:
        reader = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        header = next(reader)
        if not header.startswith("#harmonicc_pos"):
            raise RuntimeError(f"unexpected ranks header: {header!r}")
        for i, line in enumerate(reader, start=1):
            if i > TOP_N:
                break
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 5:
                raise RuntimeError(f"malformed ranks line {i}: {line!r}")
            hc_pos, hc_val, pr_pos, pr_val, entity_rev = fields
            w.writerow([hc_pos, hc_val, pr_pos, pr_val, _reverse_entity(entity_rev)])
    return buf.getvalue().encode("utf-8")


def _download_ranks(release_id: str, level: str, entity_col: str) -> bytes:
    url = _ranks_url(release_id, level)
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        return _truncate_and_transform(r, entity_col)


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

    # Full write path is implemented in Task 5.
    raise NotImplementedError("ranks disk-write path not yet implemented")

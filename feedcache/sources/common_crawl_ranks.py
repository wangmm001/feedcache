from pathlib import Path


GRAPHINFO_URL = "https://index.commoncrawl.org/graphinfo.json"
BASE_URL = "https://data.commoncrawl.org/projects/hyperlinkgraph"
TOP_N = 1_000_000
TIMEOUT = 600


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raise NotImplementedError

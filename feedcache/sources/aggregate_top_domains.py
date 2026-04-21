import csv
import gzip
import io
from pathlib import Path
from urllib.parse import urlparse

import requests

from feedcache.common import (
    deterministic_gzip,
    today_utc_date,
    update_current,
)

REQUEST_TIMEOUT = 180

# (list_name, url, parser_key)
SOURCES: list[tuple[str, str, str]] = [
    (
        "umbrella",
        "https://raw.githubusercontent.com/wangmm001/umbrella-top1m-cache/main/data/current.csv.gz",
        "rank_domain_noheader",
    ),
    (
        "tranco",
        "https://raw.githubusercontent.com/wangmm001/tranco-top1m-cache/main/data/current.csv.gz",
        "rank_domain_noheader",
    ),
    (
        "majestic",
        "https://raw.githubusercontent.com/wangmm001/majestic-million-cache/main/data/current.csv.gz",
        "majestic",
    ),
    (
        "cloudflare-radar",
        "https://raw.githubusercontent.com/wangmm001/cloudflare-radar-rankings-cache/main/data/current/top-1000000.csv.gz",
        "cloudflare",
    ),
    (
        "crux",
        "https://raw.githubusercontent.com/wangmm001/crux-top-lists-mirror/main/data/global/current.csv.gz",
        "crux",
    ),
]


def _parse_rank_domain_noheader(text: str) -> set[str]:
    out: set[str] = set()
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2:
            d = row[1].strip().lower()
            if d:
                out.add(d)
    return out


def _parse_majestic(text: str) -> set[str]:
    out: set[str] = set()
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        d = (row.get("Domain") or "").strip().lower()
        if d:
            out.add(d)
    return out


def _parse_cloudflare(text: str) -> set[str]:
    out: set[str] = set()
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        d = (row.get("domain") or "").strip().lower()
        if d:
            out.add(d)
    return out


def _parse_crux(text: str) -> set[str]:
    out: set[str] = set()
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        origin = (row.get("origin") or "").strip()
        if not origin:
            continue
        host = urlparse(origin).hostname
        if not host:
            continue
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            out.add(host)
    return out


PARSERS = {
    "rank_domain_noheader": _parse_rank_domain_noheader,
    "majestic": _parse_majestic,
    "cloudflare": _parse_cloudflare,
    "crux": _parse_crux,
}


def _fetch_and_parse(url: str, parser_key: str) -> set[str]:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    text = gzip.decompress(resp.content).decode("utf-8", errors="replace")
    return PARSERS[parser_key](text)


def run(out_dir: str) -> bool:
    # Fetch all 5 first; any failure aborts before any file is written.
    lists: dict[str, set[str]] = {}
    for name, url, parser_key in SOURCES:
        lists[name] = _fetch_and_parse(url, parser_key)

    agg: dict[str, list[str]] = {}
    for name, domains in lists.items():
        for d in domains:
            agg.setdefault(d, []).append(name)

    rows = sorted(agg.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["domain", "count", "lists"])
    for domain, src_list in rows:
        writer.writerow([domain, len(src_list), "|".join(sorted(src_list))])
    csv_bytes = buf.getvalue().encode("utf-8")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    date = today_utc_date()
    deterministic_gzip(csv_bytes, out / f"{date}.csv.gz")
    update_current(out, "????-??-??.csv.gz", "current.csv.gz")
    return True

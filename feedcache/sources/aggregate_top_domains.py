import csv
import gzip
import io
from pathlib import Path
from urllib.parse import urlparse

import requests
from publicsuffixlist import PublicSuffixList

from feedcache.common import (
    deterministic_gzip,
    today_utc_date,
    update_current,
)

REQUEST_TIMEOUT = 180

PSL_URL = "https://raw.githubusercontent.com/wangmm001/public-suffix-list-cache/main/data/current.dat.gz"

# (list_name, url, parser_key)  — unchanged
SOURCES: list[tuple[str, str, str]] = [
    ("umbrella",
     "https://raw.githubusercontent.com/wangmm001/umbrella-top1m-cache/main/data/current.csv.gz",
     "rank_domain_noheader"),
    ("tranco",
     "https://raw.githubusercontent.com/wangmm001/tranco-top1m-cache/main/data/current.csv.gz",
     "rank_domain_noheader"),
    ("majestic",
     "https://raw.githubusercontent.com/wangmm001/majestic-million-cache/main/data/current.csv.gz",
     "majestic"),
    ("cloudflare-radar",
     "https://raw.githubusercontent.com/wangmm001/cloudflare-radar-rankings-cache/main/data/current/top-1000000.csv.gz",
     "cloudflare"),
    ("crux",
     "https://raw.githubusercontent.com/wangmm001/crux-top-lists-mirror/main/data/global/current.csv.gz",
     "crux"),
]

UNORDERED_RANK = 1_000_000


def _load_psl() -> PublicSuffixList:
    resp = requests.get(PSL_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    psl_bytes = gzip.decompress(resp.content)
    # PublicSuffixList accepts a source iterable of lines
    return PublicSuffixList(source=io.BytesIO(psl_bytes))


def _normalize(host: str, psl: PublicSuffixList) -> str:
    """Reduce host to registrable domain (eTLD+1). If host is itself a public suffix
    or otherwise un-reducible, fall back to the original host."""
    host = (host or "").strip().lower()
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    try:
        registrable = psl.privatesuffix(host)
    except Exception:
        return host
    return registrable or host


def _parse_rank_domain_noheader(text: str, psl: PublicSuffixList) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2:
            try:
                rank = int(row[0])
            except ValueError:
                continue
            d = _normalize(row[1], psl)
            if d and (d not in out or rank < out[d]):
                out[d] = rank
    return out


def _parse_majestic(text: str, psl: PublicSuffixList) -> dict[str, int]:
    out: dict[str, int] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            rank = int((row.get("GlobalRank") or "").strip())
        except ValueError:
            continue
        d = _normalize(row.get("Domain") or "", psl)
        if d and (d not in out or rank < out[d]):
            out[d] = rank
    return out


def _parse_cloudflare(text: str, psl: PublicSuffixList) -> dict[str, int]:
    out: dict[str, int] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        d = _normalize(row.get("domain") or "", psl)
        if d:
            out[d] = UNORDERED_RANK
    return out


def _parse_crux(text: str, psl: PublicSuffixList) -> dict[str, int]:
    out: dict[str, int] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        origin = (row.get("origin") or "").strip()
        try:
            rank = int((row.get("rank") or "").strip())
        except ValueError:
            continue
        if not origin:
            continue
        host = urlparse(origin).hostname or ""
        d = _normalize(host, psl)
        if d and (d not in out or rank < out[d]):
            out[d] = rank
    return out


PARSERS = {
    "rank_domain_noheader": _parse_rank_domain_noheader,
    "majestic": _parse_majestic,
    "cloudflare": _parse_cloudflare,
    "crux": _parse_crux,
}


def _fetch_and_parse(url: str, parser_key: str, psl: PublicSuffixList) -> dict[str, int]:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    text = gzip.decompress(resp.content).decode("utf-8", errors="replace")
    return PARSERS[parser_key](text, psl)


def run(out_dir: str) -> bool:
    psl = _load_psl()

    per_source: dict[str, dict[str, int]] = {}
    for name, url, parser_key in SOURCES:
        per_source[name] = _fetch_and_parse(url, parser_key, psl)

    agg: dict[str, tuple[list[str], float]] = {}
    for name, domain_rank in per_source.items():
        for d, rank in domain_rank.items():
            if rank <= 0:
                continue
            contrib = 1.0 / rank
            if d in agg:
                sources_list, score = agg[d]
                sources_list.append(name)
                agg[d] = (sources_list, score + contrib)
            else:
                agg[d] = ([name], contrib)

    rows = sorted(
        agg.items(),
        key=lambda kv: (-len(kv[1][0]), -kv[1][1], kv[0]),
    )

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["domain", "count", "score", "lists"])
    for domain, (src_list, score) in rows:
        writer.writerow([
            domain,
            len(src_list),
            f"{score:.6f}",
            "|".join(sorted(src_list)),
        ])
    csv_bytes = buf.getvalue().encode("utf-8")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    date = today_utc_date()
    deterministic_gzip(csv_bytes, out / f"{date}.csv.gz")
    update_current(out, "????-??-??.csv.gz", "current.csv.gz")
    return True

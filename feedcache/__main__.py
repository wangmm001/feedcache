import argparse
import sys
from typing import Callable, Dict

from feedcache.sources import cloud_ip_ranges, cloudflare_radar, majestic, public_suffix_list, tranco, umbrella

SOURCES: Dict[str, Callable[[str], bool]] = {
    "umbrella": umbrella.run,
    "tranco": tranco.run,
    "cloudflare-radar": cloudflare_radar.run,
    "majestic": majestic.run,
    "public-suffix-list": public_suffix_list.run,
    "cloud-ip-ranges": cloud_ip_ranges.run,
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="feedcache",
        description="Mirror public top-list / metadata feeds into git-backed data directories.",
    )
    sub = parser.add_subparsers(dest="source", required=True)
    for name in SOURCES:
        p = sub.add_parser(name)
        p.add_argument("out_dir", help="Target data directory (usually the data/ of a data repo).")

    args = parser.parse_args(argv)
    ok = SOURCES[args.source](args.out_dir)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

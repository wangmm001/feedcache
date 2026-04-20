import fnmatch
import gzip
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def deterministic_gzip(src_bytes: bytes, dest: Path) -> None:
    data = gzip.compress(src_bytes, compresslevel=9, mtime=0)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


def write_if_changed(content: bytes, dest: Path) -> bool:
    dest = Path(dest)
    if dest.exists() and dest.read_bytes() == content:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, dest)
    return True


def update_current(directory: Path, pattern: str, current_name: str) -> Path | None:
    directory = Path(directory)
    matches = sorted(
        p for p in directory.iterdir()
        if p.is_file() and fnmatch.fnmatch(p.name, pattern)
    )
    if not matches:
        return None
    latest = matches[-1]
    dest = directory / current_name
    shutil.copyfile(latest, dest)
    return dest

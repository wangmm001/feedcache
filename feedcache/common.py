import fnmatch
import gzip
import lzma
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests


def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def deterministic_gzip(src_bytes: bytes, dest: Path) -> None:
    data = gzip.compress(src_bytes, compresslevel=9, mtime=0)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


def deterministic_xz(src_bytes: bytes, dest: Path, preset: int = 6) -> None:
    data = lzma.compress(
        src_bytes, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, preset=preset
    )
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


def download_to(url: str, dest: Path, timeout: int = 120) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    os.replace(tmp, dest)
    return dest

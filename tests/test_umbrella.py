import io
import zipfile
from pathlib import Path

import pytest


def _make_fake_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("top-1m.csv", "1,google.com\n2,youtube.com\n3,facebook.com\n")
    return buf.getvalue()


def test_umbrella_run_writes_snapshot_and_current(tmp_path, monkeypatch):
    from feedcache.sources import umbrella
    fake_zip = _make_fake_zip()

    def fake_download(url, dest, timeout=120):
        Path(dest).write_bytes(fake_zip)
        return Path(dest)

    monkeypatch.setattr(umbrella, "download_to", fake_download)

    assert umbrella.run(str(tmp_path)) is True

    files = sorted(p.name for p in tmp_path.iterdir())
    dated = [f for f in files if f.endswith(".csv.gz") and f != "current.csv.gz"]
    assert len(dated) == 1, files
    assert "current.csv.gz" in files

    # current equals the dated file
    import gzip
    assert gzip.decompress((tmp_path / "current.csv.gz").read_bytes()) == (
        b"1,google.com\n2,youtube.com\n3,facebook.com\n"
    )


def test_umbrella_run_idempotent(tmp_path, monkeypatch):
    from feedcache.sources import umbrella
    fake_zip = _make_fake_zip()

    def fake_download(url, dest, timeout=120):
        Path(dest).write_bytes(fake_zip)
        return Path(dest)

    monkeypatch.setattr(umbrella, "download_to", fake_download)

    umbrella.run(str(tmp_path))
    before = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    umbrella.run(str(tmp_path))
    after = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    assert before == after


def test_umbrella_run_rejects_multi_csv_zip(tmp_path, monkeypatch):
    from feedcache.sources import umbrella
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.csv", "")
        zf.writestr("b.csv", "")
    bad_zip = buf.getvalue()

    def fake_download(url, dest, timeout=120):
        Path(dest).write_bytes(bad_zip)
        return Path(dest)

    monkeypatch.setattr(umbrella, "download_to", fake_download)

    with pytest.raises(RuntimeError, match="Expected exactly one CSV"):
        umbrella.run(str(tmp_path))

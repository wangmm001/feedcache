import gzip
from pathlib import Path


_FAKE_CSV = b"GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs\n1,1,google.com,com,500413,2220257\n2,2,facebook.com,com,476437,2243396\n"


def test_majestic_run_writes_snapshot_and_current(tmp_path, monkeypatch):
    from feedcache.sources import majestic

    def fake_download(url, dest, timeout=120):
        assert url == majestic.UPSTREAM_URL
        Path(dest).write_bytes(_FAKE_CSV)
        return Path(dest)

    monkeypatch.setattr(majestic, "download_to", fake_download)

    assert majestic.run(str(tmp_path)) is True

    names = sorted(p.name for p in tmp_path.iterdir())
    dated = [n for n in names if n.endswith(".csv.gz") and n != "current.csv.gz"]
    assert len(dated) == 1, names
    assert "current.csv.gz" in names

    # Current content is byte-equivalent to the fake upstream CSV
    assert gzip.decompress((tmp_path / "current.csv.gz").read_bytes()) == _FAKE_CSV


def test_majestic_run_idempotent(tmp_path, monkeypatch):
    from feedcache.sources import majestic

    def fake_download(url, dest, timeout=120):
        Path(dest).write_bytes(_FAKE_CSV)
        return Path(dest)

    monkeypatch.setattr(majestic, "download_to", fake_download)

    majestic.run(str(tmp_path))
    before = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    majestic.run(str(tmp_path))
    after = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    assert before == after


def test_majestic_run_cleans_up_tempfile_on_download_failure(tmp_path, monkeypatch):
    import pytest
    from feedcache.sources import majestic

    def failing_download(url, dest, timeout=120):
        # Even if the download starts writing, raise to simulate failure
        Path(dest).write_bytes(b"partial")
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(majestic, "download_to", failing_download)

    with pytest.raises(RuntimeError, match="simulated network failure"):
        majestic.run(str(tmp_path))

    # No .csv.gz produced
    gzs = list(tmp_path.glob("*.csv.gz"))
    assert gzs == []

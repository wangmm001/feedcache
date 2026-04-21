import gzip
from pathlib import Path


_FAKE_DAT = b"// ===BEGIN ICANN DOMAINS===\ncom\nnet\nco.uk\n"


def test_public_suffix_list_run_writes_snapshot_and_current(tmp_path, monkeypatch):
    from feedcache.sources import public_suffix_list

    def fake_download(url, dest, timeout=120):
        assert url == public_suffix_list.UPSTREAM_URL
        Path(dest).write_bytes(_FAKE_DAT)
        return Path(dest)

    monkeypatch.setattr(public_suffix_list, "download_to", fake_download)

    assert public_suffix_list.run(str(tmp_path)) is True

    names = sorted(p.name for p in tmp_path.iterdir())
    dated = [n for n in names if n.endswith(".dat.gz") and n != "current.dat.gz"]
    assert len(dated) == 1, names
    assert "current.dat.gz" in names

    # Current content is byte-equivalent to the fake upstream dat
    assert gzip.decompress((tmp_path / "current.dat.gz").read_bytes()) == _FAKE_DAT


def test_public_suffix_list_run_idempotent(tmp_path, monkeypatch):
    from feedcache.sources import public_suffix_list

    def fake_download(url, dest, timeout=120):
        Path(dest).write_bytes(_FAKE_DAT)
        return Path(dest)

    monkeypatch.setattr(public_suffix_list, "download_to", fake_download)

    public_suffix_list.run(str(tmp_path))
    before = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    public_suffix_list.run(str(tmp_path))
    after = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    assert before == after


def test_public_suffix_list_run_cleans_up_tempfile_on_download_failure(tmp_path, monkeypatch):
    import pytest
    from feedcache.sources import public_suffix_list

    def failing_download(url, dest, timeout=120):
        # Even if the download starts writing, raise to simulate failure
        Path(dest).write_bytes(b"partial")
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(public_suffix_list, "download_to", failing_download)

    with pytest.raises(RuntimeError, match="simulated network failure"):
        public_suffix_list.run(str(tmp_path))

    # No .dat.gz produced
    gzs = list(tmp_path.glob("*.dat.gz"))
    assert gzs == []

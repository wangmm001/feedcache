import gzip
import re

from feedcache.common import deterministic_gzip, today_utc_date, update_current, write_if_changed


def test_today_utc_date_format():
    s = today_utc_date()
    assert isinstance(s, str)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s), s


def test_deterministic_gzip_same_input_same_output(tmp_path):
    data = b"rank,domain\n1,google.com\n2,youtube.com\n"
    a = tmp_path / "a.gz"
    b = tmp_path / "b.gz"
    deterministic_gzip(data, a)
    deterministic_gzip(data, b)
    assert a.read_bytes() == b.read_bytes(), "byte-identical output required"
    assert gzip.decompress(a.read_bytes()) == data


def test_write_if_changed_writes_new(tmp_path):
    dest = tmp_path / "f"
    assert write_if_changed(b"abc", dest) is True
    assert dest.read_bytes() == b"abc"


def test_write_if_changed_skips_unchanged(tmp_path):
    dest = tmp_path / "f"
    write_if_changed(b"abc", dest)
    mtime1 = dest.stat().st_mtime_ns
    assert write_if_changed(b"abc", dest) is False
    assert dest.stat().st_mtime_ns == mtime1


def test_write_if_changed_updates_on_diff(tmp_path):
    dest = tmp_path / "f"
    write_if_changed(b"abc", dest)
    assert write_if_changed(b"def", dest) is True
    assert dest.read_bytes() == b"def"


def test_update_current_picks_latest_filename(tmp_path):
    (tmp_path / "2026-01-01.csv.gz").write_bytes(b"a")
    (tmp_path / "2026-04-20.csv.gz").write_bytes(b"b")
    (tmp_path / "2026-03-01.csv.gz").write_bytes(b"c")
    result = update_current(tmp_path, "????-??-??.csv.gz", "current.csv.gz")
    assert result == tmp_path / "current.csv.gz"
    assert (tmp_path / "current.csv.gz").read_bytes() == b"b"


def test_update_current_returns_none_when_no_match(tmp_path):
    (tmp_path / "unrelated.txt").write_bytes(b"x")
    assert update_current(tmp_path, "????-??-??.csv.gz", "current.csv.gz") is None

import gzip
import re

from feedcache.common import deterministic_gzip, today_utc_date


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

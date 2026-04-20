import re

from feedcache.common import today_utc_date


def test_today_utc_date_format():
    s = today_utc_date()
    assert isinstance(s, str)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s), s

from unittest.mock import MagicMock

import pytest


def _make_ok_response(body_text):
    """Return a MagicMock that behaves like a successful requests.Response."""
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.content = body_text.encode() if isinstance(body_text, str) else body_text
    r.text = body_text if isinstance(body_text, str) else body_text.decode()
    return r


def test_cloudflare_radar_writes_four_buckets(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_RADAR_API_TOKEN", "fake-token")

    captured_calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        captured_calls.append({"url": url, "headers": headers})
        # Upstream returns plain CSV text — single "domain" column.
        return _make_ok_response("domain\nexample.com\ntest.com\n")

    import feedcache.sources.cloudflare_radar as cr
    monkeypatch.setattr(cr.requests, "get", fake_get)

    assert cr.run(str(tmp_path)) is True

    # 4 GET calls, one per bucket, each with the dataset-alias URL
    assert len(captured_calls) == 4
    urls_requested = sorted(c["url"] for c in captured_calls)
    assert urls_requested == [
        "https://api.cloudflare.com/client/v4/radar/datasets/ranking_top_1000",
        "https://api.cloudflare.com/client/v4/radar/datasets/ranking_top_10000",
        "https://api.cloudflare.com/client/v4/radar/datasets/ranking_top_100000",
        "https://api.cloudflare.com/client/v4/radar/datasets/ranking_top_1000000",
    ]

    # Bearer auth header present
    for c in captured_calls:
        assert c["headers"]["Authorization"] == "Bearer fake-token"

    # Expect one dated dir with 4 files, plus current/ with the same 4
    dated_dirs = [p for p in tmp_path.iterdir() if p.is_dir() and p.name != "current"]
    assert len(dated_dirs) == 1
    daily_files = sorted(p.name for p in dated_dirs[0].iterdir())
    assert daily_files == [
        "top-1000.csv.gz",
        "top-10000.csv.gz",
        "top-100000.csv.gz",
        "top-1000000.csv.gz",
    ]
    current_files = sorted(p.name for p in (tmp_path / "current").iterdir())
    assert current_files == daily_files


def test_cloudflare_radar_fails_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_RADAR_API_TOKEN", raising=False)

    import feedcache.sources.cloudflare_radar as cr
    with pytest.raises(RuntimeError, match="CLOUDFLARE_RADAR_API_TOKEN"):
        cr.run(str(tmp_path))


def test_cloudflare_radar_partial_failure_no_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_RADAR_API_TOKEN", "fake-token")

    call_count = {"n": 0}

    def flaky_get(url, headers=None, params=None, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 3:  # third bucket fails
            r = MagicMock()
            r.ok = False
            r.status_code = 500
            r.text = '{"errors":[{"code":1,"message":"simulated"}]}'
            return r
        return _make_ok_response("domain\nexample.com\n")

    import feedcache.sources.cloudflare_radar as cr
    monkeypatch.setattr(cr.requests, "get", flaky_get)

    with pytest.raises(RuntimeError, match="Radar API 500"):
        cr.run(str(tmp_path))

    # Nothing persisted — neither dated dir nor current/
    leftover = list(tmp_path.rglob("*.json.gz"))
    assert leftover == [], f"unexpected files: {leftover}"

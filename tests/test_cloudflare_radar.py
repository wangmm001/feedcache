from unittest.mock import MagicMock

import pytest


def _make_ok_response(payload):
    """Return a MagicMock that behaves like a successful requests.Response."""
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = payload
    return r


def test_cloudflare_radar_writes_four_buckets(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_RADAR_API_TOKEN", "fake-token")

    captured_calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        captured_calls.append({"url": url, "headers": headers, "params": params})
        # Return a bucket-specific payload so the 4 files have distinct content
        limit = params["limit"] if params else "unknown"
        return _make_ok_response({"result": {"top_0": [{"domain": "example.com", "rank": 1}], "limit": limit}})

    import feedcache.sources.cloudflare_radar as cr
    monkeypatch.setattr(cr.requests, "get", fake_get)

    assert cr.run(str(tmp_path)) is True

    # 4 GET calls, one per bucket
    assert len(captured_calls) == 4
    limits_requested = sorted(c["params"]["limit"] for c in captured_calls)
    assert limits_requested == [1000, 10000, 100000, 1000000]

    # Bearer auth header present
    for c in captured_calls:
        assert c["headers"]["Authorization"] == "Bearer fake-token"

    # Expect one dated dir with 4 files, plus current/ with the same 4
    dated_dirs = [p for p in tmp_path.iterdir() if p.is_dir() and p.name != "current"]
    assert len(dated_dirs) == 1
    daily_files = sorted(p.name for p in dated_dirs[0].iterdir())
    assert daily_files == [
        "top-1000.json.gz",
        "top-10000.json.gz",
        "top-100000.json.gz",
        "top-1000000.json.gz",
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
            import requests
            r = MagicMock()
            r.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
            return r
        return _make_ok_response({"result": {"top_0": [], "limit": params["limit"]}})

    import feedcache.sources.cloudflare_radar as cr
    monkeypatch.setattr(cr.requests, "get", flaky_get)

    import requests
    with pytest.raises(requests.HTTPError):
        cr.run(str(tmp_path))

    # Nothing persisted — neither dated dir nor current/
    leftover = list(tmp_path.rglob("*.json.gz"))
    assert leftover == [], f"unexpected files: {leftover}"

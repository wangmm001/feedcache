import subprocess
import sys
from unittest.mock import patch


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "feedcache", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "umbrella" in result.stdout
    assert "tranco" in result.stdout
    assert "cloudflare-radar" in result.stdout
    assert "majestic" in result.stdout
    assert "public-suffix-list" in result.stdout
    assert "cloud-ip-ranges" in result.stdout
    assert "aggregate-top-domains" in result.stdout


def test_cli_dispatches_to_source(tmp_path):
    from feedcache import __main__ as main_mod

    called = {}
    def fake_run(out_dir):
        called["out_dir"] = out_dir
        return True

    with patch.dict(main_mod.SOURCES, {"umbrella": fake_run}):
        try:
            main_mod.main(["umbrella", str(tmp_path)])
        except SystemExit as e:
            assert e.code == 0

    assert called["out_dir"] == str(tmp_path)


def test_cli_nonzero_on_source_failure(tmp_path):
    from feedcache import __main__ as main_mod

    def fake_run(out_dir):
        return False

    with patch.dict(main_mod.SOURCES, {"umbrella": fake_run}):
        try:
            main_mod.main(["umbrella", str(tmp_path)])
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert e.code == 1

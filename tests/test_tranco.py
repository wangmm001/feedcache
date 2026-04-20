from unittest.mock import MagicMock


def test_tranco_run_writes_snapshot_and_version(tmp_path, monkeypatch):
    from feedcache.sources import tranco as tranco_mod

    fake_list = MagicMock()
    fake_list.list_id = "X5KNN"
    fake_list.top.return_value = ["google.com", "youtube.com", "facebook.com"]

    fake_client = MagicMock()
    fake_client.list.return_value = fake_list

    # Accept any kwargs (cache_dir=..., etc.)
    monkeypatch.setattr(tranco_mod, "Tranco", lambda **kwargs: fake_client)

    assert tranco_mod.run(str(tmp_path)) is True

    names = {p.name for p in tmp_path.iterdir()}
    dated = [n for n in names if n.endswith("_X5KNN.csv.gz")]
    assert len(dated) == 1, names
    assert "current.csv.gz" in names
    assert "current.version.txt" in names
    assert (tmp_path / "current.version.txt").read_text().strip() == "X5KNN"

    # dated version sidecar also exists
    sidecars = [n for n in names if n.endswith(".version.txt") and n != "current.version.txt"]
    assert len(sidecars) == 1


def test_tranco_run_skips_when_version_unchanged(tmp_path, monkeypatch):
    from feedcache.sources import tranco as tranco_mod

    (tmp_path / "current.version.txt").write_text("X5KNN\n")

    fake_list = MagicMock()
    fake_list.list_id = "X5KNN"
    fake_list.top.return_value = ["google.com"]
    fake_client = MagicMock()
    fake_client.list.return_value = fake_list

    monkeypatch.setattr(tranco_mod, "Tranco", lambda **kwargs: fake_client)

    assert tranco_mod.run(str(tmp_path)) is True
    dated = [p for p in tmp_path.iterdir() if p.name.endswith("_X5KNN.csv.gz")]
    assert dated == []


def test_tranco_run_writes_rank_csv_format(tmp_path, monkeypatch):
    import gzip
    from feedcache.sources import tranco as tranco_mod

    fake_list = MagicMock()
    fake_list.list_id = "ABCDE"
    fake_list.top.return_value = ["a.com", "b.com"]
    fake_client = MagicMock()
    fake_client.list.return_value = fake_list

    monkeypatch.setattr(tranco_mod, "Tranco", lambda **kwargs: fake_client)

    tranco_mod.run(str(tmp_path))

    dated = next(p for p in tmp_path.iterdir() if p.name.endswith("_ABCDE.csv.gz"))
    content = gzip.decompress(dated.read_bytes()).decode()
    assert content == "1,a.com\n2,b.com\n"

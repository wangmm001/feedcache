def test_module_importable_and_exposes_run():
    from feedcache.sources import common_crawl_ranks
    assert callable(common_crawl_ranks.run)

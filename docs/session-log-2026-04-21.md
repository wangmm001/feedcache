# 2026-04-21 工作日志 — Common Crawl 接入

一次会话内完成了两个相互衔接的 milestone:(1) 新建 Common Crawl ranks 数据仓并接上 feedcache 的 reusable workflow;(2) 在此基础上把 CC 作为第 6 个源接入 `top-domains-aggregate`(v2.3)。两者分别走完 brainstorming → spec → plan → subagent-driven 执行 → 部署 + live 验证的完整流程。

## Milestone 1 — `common-crawl-ranks-cache`

**Spec / plan**
- `docs/superpowers/specs/2026-04-21-common-crawl-ranks-cache-design.md`
- `docs/superpowers/plans/2026-04-21-common-crawl-ranks-cache.md`(11 个 TDD task)

**代码落地(`wangmm001/feedcache` main)**
- 新 source:`feedcache/sources/common_crawl_ranks.py`(`run`, `_ranks_url`, `_reverse_entity`, `_truncate_and_transform`, `_download_ranks`)
- CLI 注册:`feedcache common-crawl-ranks <out_dir>`
- 测试:`tests/test_common_crawl_ranks.py`(9 tests)

**数据仓(`wangmm001/common-crawl-ranks-cache` main)**
- `LICENSE` + `README.md` + `.github/workflows/cron.yml`(04:30 UTC)+ `.gitignore`
- GitHub Actions 手动 dispatch 首次运行 42 秒成功。
- 产出:`data/host/current.csv.gz`(~27 MB,Top-1M)、`data/domain/current.csv.gz`(~15 MB,Top-1M + `n_hosts` 列)、`data/graphinfo.json`(上游索引快照)。

**关键设计**
- **流式截断**:原始 CC ranks 文件 host 5.6 GB + domain 2.5 GB 压缩;`_truncate_and_transform` 流式解压到 `TOP_N = 1_000_000` 行即 `break`,`with requests.get(stream=True)` 的 context manager 自动关 TCP 连接。实测每 level ~27.5 MB 实际下载,约 0.5–1.2% of full。
- **幂等早退**:每次先拉 `graphinfo.json`,与 `data/host/current.release.txt` 比对;release id 未变则只刷新 graphinfo.json 快照,零数据下载、零 commit。CC 约每季度发一次,日 cron 约 90% 空转。
- **原子写**:两个 level 先全下载到内存,成功后才落盘。
- **反向还原**:上游 `#host_rev`(`com.facebook.www`)split + reverse 得正向 `www.facebook.com`。

**实测发现与修复**
- 原 spec 假设 host 和 domain ranks 都是 5 列;**实际 domain 是 6 列**(末尾 `#n_hosts`)。首次 workflow 挂在 domain 第一行解析。Hotfix(`10325e4`)让 `_truncate_and_transform` 接受 `extra_cols`,domain 传 `("n_hosts",)`,重跑通过。

## Milestone 2 — `top-domains-aggregate` v2.3(CC 并入)

**Spec / plan**
- `docs/superpowers/specs/2026-04-21-aggregate-common-crawl-integration-design.md`
- `docs/superpowers/plans/2026-04-21-aggregate-common-crawl-integration.md`(5 个 task)

**代码落地(`wangmm001/feedcache` main)**
- `aggregate_top_domains.py` 新增:`SOURCES` 第 6 行、`_parse_common_crawl`(读 `rank` 和 `domain` 列,过 PSL 规范化;忽略 `n_hosts`/`pr_pos`/`harmonicc_val`/`pr_val`)、`PARSERS` 注册。
- `RRF_K = 60` 和整体公式 `1/(60+rank)` 未变;CC 以 `harmonicc_pos` 为 ordinal 传入(非 `UNORDERED_RANK` 兜底)。
- 测试:`test_aggregate_top_domains.py` 加 `_FAKE_COMMON_CRAWL` fixture 和 `test_aggregate_common_crawl_only_domain_lands_with_count_1`,更新 google.com/youtube.com 断言(count 5→6、5→6;score 0.050125→0.066518、0.032946→0.049075)。

**`top-domains-aggregate` 数据仓 README 更新**
- `count` 范围 1–5 → 1–6,样例行切到 6 源实测值 `cloudflare-radar|common-crawl|crux|majestic|tranco|umbrella`(字典序,`cl` < `co`)。
- "How the score is computed" 的叙述公式从 v1 的 `1/rank`(此前一直和 v2.2 smoothed RRF 数值不一致)修正为 `1/(60+rank)`,worked example 算出 `0.066518` 与 sample rows 对齐。
- 顺便修正 "How it works" 里的 cron 时间段落(CC 实际 04:30,不是虚构的 05:15)。

**Live 验证(2026-04-21 09:04 UTC workflow_dispatch,1m26s)**
- `data/current.csv.gz` top-4 全部 `count=6`:google.com 0.065998、microsoft.com 0.059146、facebook.com 0.058801、youtube.com 0.055934。
- `count` 分布:6 → 46,228;5 → 77,936;4 → 136,026;3 → 244,636;2 → 601,104;**1 → 1,846,799**(CC 带来的长尾,如 `kloop.asia`、`san-diego.ca.us`、`keywordseo.com.tw`)。
- 六个 `lists` token 全部出现。

## 跨 milestone 的文档 cleanup

- `docs/design.md`:`§2 topology` 加 `common-crawl-ranks-cache`、`§3 表` 加行 + `top-domains-aggregate` 输入数由 5 改 6、`§4 代码/测试目录` 补 `common_crawl_ranks.py` + `test_common_crawl_ranks.py`、`§5a` 的 "7 direct mirrors" narrative + 新 source 条目、`§5b` 版本表加 v2.3、`§8/§9` 原占位的 "v2.3 top-domains-trends" 重编号为 v2.4 避开与当前 v2.3 冲突。

## 仓库当前状态

| 仓库 | 分支 | HEAD | 备注 |
|---|---|---|---|
| `wangmm001/feedcache` | main | `b069db8` + 本次 README 更新 | v2.3 aggregator + common-crawl-ranks source + design.md 全量同步 |
| `wangmm001/common-crawl-ranks-cache` | main | 含 schema README + daily cron | 首次 live run 已完成 |
| `wangmm001/top-domains-aggregate` | main | 含 v2.3 文档 + cron 时间修正 | 最新 aggregate 已是 6 源数据 |

GitHub Actions cron:04:30 UTC 并发跑 PSL + common-crawl-ranks(不同 VM 无冲突),05:30 UTC aggregate 读全部 6 个 `current.csv.gz` 融合输出。下一次 CC 有新 webgraph(约 2026-07)时,整条流水线自动 pick up,无需人工介入。

## 后续可选工作

记录在 spec `§13 Future work` 里,此处不展开:PageRank 作第二 CC 信号、`n_hosts` 作 tie-breaker、CC webgraph 历史 backfill、CrUX bucket-rank 的 log 化。

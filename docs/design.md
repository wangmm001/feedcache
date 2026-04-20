# feedcache 设计文档

- **日期**:2026-04-20
- **状态**:草案(待用户复核后进入 writing-plans)
- **落地位置**:本文件暂存于 `/home/wangmm/feedcache-spec.md`;待 `feedcache` 代码仓库创建后迁入其 `docs/design.md`,一并 commit。

---

## 1. 背景与目标

### 背景

用户手上已有一个 CrUX top-list 数据缓存仓库 `crux-top-lists`(zakird/crux-top-lists 模式的 fork 样本),用来观摩"github 仓库即数据缓存"的套路。现在希望把同一套路应用到另外几个公开的 top-list / 互联网公开数据源上,形成一组兄弟数据仓库,本地靠 `git pull` 消费。

### 目标

1. 镜像三个公开数据源到独立的 git 仓库:
   - **Cisco Umbrella Top 1M**(每日 CSV,`rank,domain`)
   - **Tranco Top 1M**(每日 CSV,附 version ID 以保证可复现)
   - **Cloudflare Radar DNS rank buckets**(每日 × 4 个 bucket:1k / 10k / 100k / 1M)
2. 代码只写一份(`feedcache` 包),数据仓库各自独立,互不影响。
3. 所有上游拉取由 GitHub Actions cron 自动跑;用户不在本地跑。
4. 用户本地只做 `git pull <data-repo>` 消费。

### 非目标(明确砍掉,未来若要再议)

- AWS IP Ranges(用户暂缓)。
- Cloudflare Radar 的 top-100 榜、逐域名 top countries / top ASes。
- 融合/去重/交叉分析——所有源原样镜像,不做任何数据加工。
- 向 `crux-top-lists` 仓库写入任何代码或数据。
- Slack/Discord 失败通知、Makefile、CI 的 branch protection 等非必要脚手架。

---

## 2. 仓库拓扑

新增四个 git 仓库,全部与 `crux-top-lists` 平级(本地示例):

```
~/feedcache/                              # 代码,1 个 repo(拟公开)
~/umbrella-top1m-cache/                   # 数据
~/tranco-top1m-cache/                     # 数据
~/cloudflare-radar-rankings-cache/        # 数据
~/crux-top-lists/                         # 已存在,本轮不碰
```

**代码与数据分仓**的理由:日常 `git pull` 数据不会被偶发的代码改动污染;`feedcache` 代码仓库升级时,三个数据仓库自动在下一次 cron 使用新代码(因为 workflow 用 `pip install git+https://.../feedcache.git@main`)。

**每个数据仓库一个 cron** 的理由:三个源自治,一个上游挂掉不连累另外两个的 commit 节奏;各数据仓库的 Actions 用自带 `GITHUB_TOKEN` 推自己这个 repo,无需跨仓库凭证。

---

## 3. 数据仓库目录结构与文件命名

### `umbrella-top1m-cache`

```
data/
  YYYY-MM-DD.csv.gz            # 当日 Umbrella top-1m.csv 原样,gzipped
  current.csv.gz               # 指向最新日期的副本,外部固定 URL 下载入口
README.md
LICENSE
.github/workflows/cron.yml
```

- 文件内容是上游 `top-1m.csv.zip` 解压后的两列 CSV(`rank,domain`),不做解析/过滤。
- `current.csv.gz` 每次 cron 成功后从"最大 YYYY-MM-DD"文件复制过来。

### `tranco-top1m-cache`

```
data/
  YYYY-MM-DD_<versionID>.csv.gz    # versionID 是 Tranco 当日列表 ID,如 X5KNN
  YYYY-MM-DD.version.txt           # 单行 sidecar,内容即 versionID
  current.csv.gz
  current.version.txt
README.md
LICENSE
.github/workflows/cron.yml
```

- 版本号写进主文件名,语义自描述:"2026-04-20 当日的 Tranco 列表,版本 X5KNN"。
- sidecar `.version.txt` 冗余存一份 versionID,便于外部脚本不解析文件名即可取得。
- Tranco 上游偶尔当日未发新榜时,`feedcache tranco` 会基于 `list_id` 与 `current.version.txt` 比对决定是否落盘;相同则跳过,不产生重复 commit。

### `cloudflare-radar-rankings-cache`

```
data/
  YYYY-MM-DD/
    top-1000.json.gz
    top-10000.json.gz
    top-100000.json.gz
    top-1000000.json.gz
  current/
    top-1000.json.gz
    top-10000.json.gz
    top-100000.json.gz
    top-1000000.json.gz
README.md
LICENSE
.github/workflows/cron.yml
```

- 每天四个 bucket 作为一个原子快照,同成同败,放在日期子目录下便于一次 `git log -- data/YYYY-MM-DD/` 看全。
- 文件内容为 Cloudflare Radar API `radar.ranking.top` 的原始 JSON,不扁平化。

### 三个仓库共有的约定

- **只增不删**:git log 即变更史。
- **幂等**:同一天重跑覆盖当日文件,最终结果不变。
- **确定性 gzip**:使用 `gzip -n` 等价的参数(Python 侧 `gzip.GzipFile(fileobj=..., mtime=0)` 且不写文件名),确保内容未变时字节等同,避免生成"同内容不同 mtime"的伪 diff。
- **内容未变不 commit**:workflow 中 `git diff --cached --quiet` 命中则跳过 commit。
- **LICENSE**:先以占位文本或 `LICENSE: TBD — 引用上游条款` 起步,推公共数据仓库前再与上游条款核对(Umbrella 受 Cisco TOS、Tranco CC-BY、Cloudflare Radar 各自 terms)。

---

## 4. `feedcache` 代码仓库

### 目录布局

```
feedcache/
├── pyproject.toml
├── README.md
├── LICENSE
├── feedcache/
│   ├── __init__.py
│   ├── __main__.py              # CLI 派发
│   ├── common.py                # 跨源共享工具
│   └── sources/
│       ├── __init__.py
│       ├── umbrella.py
│       ├── tranco.py
│       └── cloudflare_radar.py
├── tests/
│   ├── test_common.py
│   ├── test_umbrella.py
│   ├── test_tranco.py
│   └── test_cloudflare_radar.py
└── .github/
    └── workflows/
        ├── reusable-snapshot.yml
        └── test.yml
```

### `common.py` 核心工具

- `download_to(url, dest) -> Path`:requests 流式下载 + 原子 rename。
- `deterministic_gzip(src, dest)`:生成无时间戳的 gz,保证同输入同输出。
- `write_if_changed(src_bytes, dest_path) -> bool`:字节比较,相同则不写,返回变更标志。
- `update_current(dir, pattern, current_name)`:按 `pattern` 匹配最大文件名并 `shutil.copyfile` 到 `current_name`。
- `today_utc_date() -> str`:统一返回 `YYYY-MM-DD`,避免 runner 时区差异。

### `sources/` 每个源各一个文件

**`umbrella.py`**
- URL:`https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip`
- 流程:download → 内存解压 zip → 提取唯一 CSV → `deterministic_gzip` 写 `data/YYYY-MM-DD.csv.gz` → `update_current`。
- 依赖:`requests`(标准库 `zipfile`)。

**`tranco.py`**
- 依赖:`pip install tranco`(官方客户端)。
- 流程:`Tranco(cache=False).list()` 取最新列表,读 `latest.list_id`;若与 `data/current.version.txt` 相同则直接返回"未变,跳过";否则把 `latest.top(1_000_000)` 写成 `rank,domain` CSV,gzip 后存 `data/YYYY-MM-DD_<list_id>.csv.gz`,同时写 sidecar 和两份 `current.*`。

**`cloudflare_radar.py`**
- 依赖:`pip install cloudflare>=3.0`(官方 Python SDK)。
- 读环境变量 `CLOUDFLARE_RADAR_API_TOKEN`。
- 流程:对 `limit in (1000, 10000, 100000, 1000000)` 串行调 Radar ranking top endpoint(SDK 具体方法名以 `cloudflare` 包当期 API 为准);把响应序列化为 JSON → gzip → 写 `data/YYYY-MM-DD/top-<N>.json.gz`。四次都成功后才落 `current/` 副本。任何一次失败:已下载的 bucket 只存在于临时文件,不 commit,整个 source 宣告失败。

### `__main__.py` CLI

```
feedcache umbrella <out_dir>
feedcache tranco <out_dir>
feedcache cloudflare-radar <out_dir>
```

每个子命令调用对应 `sources/<name>.run(out_dir)`,返回 `bool`,非零退出码让 Actions step 可以失败。

### `pyproject.toml` 依赖

```
requests
tranco
cloudflare>=3.0
```

(`requests` 显式写,避免依赖间接传递的假设。)

---

## 5. GitHub Actions 编排

### 可复用 workflow `feedcache/.github/workflows/reusable-snapshot.yml`

被数据仓库用 `uses:` 调用,接收 `source` 输入和可选 `CLOUDFLARE_RADAR_API_TOKEN` secret。

```yaml
name: snapshot
on:
  workflow_call:
    inputs:
      source:
        required: true
        type: string
    secrets:
      CLOUDFLARE_RADAR_API_TOKEN:
        required: false
jobs:
  snapshot:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11', cache: 'pip' }
      - run: pip install git+https://github.com/wangmm001/feedcache.git@main
      - name: snapshot
        env:
          CLOUDFLARE_RADAR_API_TOKEN: ${{ secrets.CLOUDFLARE_RADAR_API_TOKEN }}
        run: feedcache ${{ inputs.source }} data/
      - name: commit if changed
        run: |
          git config user.name "feedcache-bot"
          git config user.email "feedcache-bot@users.noreply.github.com"
          git add data/
          git diff --cached --quiet && exit 0
          git commit -m "Snapshot: $(date -u +%Y-%m-%dT%H:%MZ)"
          git push
```

- `pip install git+...@main`:浮动引用,代码仓库更新即自动生效;不做 version pin。
- `permissions: contents: write`:允许默认 `GITHUB_TOKEN` 推自己 repo,无需 PAT。**注意**:调用方 (`cron.yml`) 也必须声明 `permissions: contents: write`——reusable workflow 的权限是调用方权限的子集,调用方若是默认 read-only,reusable 内再声明也拿不到写权限。下方 `cron.yml` 模板已包含此声明。
- `git diff --cached --quiet && exit 0`:无变更则早退,保持 git log 干净。
- `wangmm001` 是 GitHub username/org 占位符,writing-plans 阶段敲定具体值(例如 `wangmm`)。

### 各数据仓库 `cron.yml`(每个仓库一份 ~10 行)

```yaml
# umbrella-top1m-cache
on:
  schedule: [{ cron: "30 3 * * *" }]    # 03:30 UTC
  workflow_dispatch:
permissions:
  contents: write
jobs:
  snapshot:
    uses: wangmm001/feedcache/.github/workflows/reusable-snapshot.yml@main
    with: { source: umbrella }

# tranco-top1m-cache
on:
  schedule: [{ cron: "45 3 * * *" }]    # 03:45 UTC
  workflow_dispatch:
permissions:
  contents: write
jobs:
  snapshot:
    uses: wangmm001/feedcache/.github/workflows/reusable-snapshot.yml@main
    with: { source: tranco }

# cloudflare-radar-rankings-cache
on:
  schedule: [{ cron: "0 4 * * *" }]     # 04:00 UTC
  workflow_dispatch:
permissions:
  contents: write
jobs:
  snapshot:
    uses: wangmm001/feedcache/.github/workflows/reusable-snapshot.yml@main
    with: { source: cloudflare-radar }
    secrets:
      CLOUDFLARE_RADAR_API_TOKEN: ${{ secrets.CLOUDFLARE_RADAR_API_TOKEN }}
```

- cron 时间避开 CrUX 原 `02:30 UTC`,三个源各错开 15 分钟,避免同时并发上游。
- 每个仓库 `workflow_dispatch` 支持手动补跑。

### 失败处理

| 情况 | 行为 |
|---|---|
| 上游 5xx / 网络失败 | step 非 0,workflow fail,GitHub 邮件提醒,不 commit |
| Cloudflare Radar 某 bucket 失败 | 整个源失败,已下载的 bucket 在临时文件中随 runner 销毁 |
| 上游内容未变(Tranco 同 list_id / 通用 byte-identical) | 脚本正常退出,`git diff --cached --quiet` 命中,不 commit |
| feedcache 代码推了 bug | 三个数据仓库下一次 cron 同步 fail;回滚靠在代码仓库 revert 或临时把 `@main` pin 到 tag |

---

## 6. 测试

### 范围

data-pipeline 项目的测试容易过度。本项目只做两层:

1. **`common.py` 单元测试**:对 `deterministic_gzip` / `write_if_changed` / `update_current` 等纯函数做小型单测,覆盖率追求高。
2. **每个源一个 smoke CLI 测试**:mock `requests` / `Tranco.list()` / `Cloudflare().radar.ranking.top()` 返回小 fixture,断言:
   - 产物写到预期路径。
   - `current.*` 指针更新。
   - 同输入再跑一次不产生新文件(幂等)。

不追求错误路径覆盖。失败时 GitHub Actions 会 fail 并发邮件,就是运行期反馈。

### 运行

- `pip install -e .[test]`(test extra 包含 `pytest`、`pytest-mock`)。
- `pytest` 一条命令跑全。
- `feedcache/.github/workflows/test.yml` 在每个 push / PR 跑测试(非强制 branch protection)。

---

## 7. 文档

### `feedcache/README.md`

- 项目目的 + 三个源一句话描述。
- 本地跑法(`pip install -e .` + 一个 `feedcache umbrella ./tmp/` 例子)。
- GitHub Actions 复用方式:贴数据仓库 ~10 行 yml 模板。
- "新增源"指南:在 `sources/` 加一个文件、`__main__.py` 注册、写一个 smoke 测试。

### 每个数据仓库 `README.md`

- 上游链接 + 许可 + 更新频率。
- 消费方式:`git clone` / `git pull` / `raw.githubusercontent.com/.../main/data/current.*` 固定 URL。
- 文件命名约定解释。
- 反指 `feedcache` 代码仓库。

### 不写

- 架构文档(本 spec 即是)、贡献指南、行为准则。

---

## 8. 本地开发体验

- `git clone feedcache && cd feedcache && pip install -e .`。
- 设 `CLOUDFLARE_RADAR_API_TOKEN`(仅 Cloudflare 源需要)。
- `feedcache <source> ./tmp/` 在本地产出 `./tmp/` 下的文件,与 Actions 产物结构一致。
- 没 Makefile、没 container、没 DB——三个命令 `pip install -e .` / `pytest` / `feedcache <src> <dir>` 够了。

---

## 9. 未来扩展(非本轮实现)

若后续要加:

- **AWS IP Ranges**:新增 `sources/aws_ip_ranges.py`,按 `syncToken` 变化决定是否落盘;数据仓库 `aws-ip-ranges-cache`;cron 可更频繁(如每 6 小时一次)。
- **Cloudflare Radar 逐域名维度**:在 `cloudflare_radar.py` 扩 subcommand(`feedcache cloudflare-radar-per-domain`),数据仓库独立或在同一 rankings 仓库内加子目录——届时再定。
- **其他互联网公开数据源**(TLS 证书、DNS zone 等):同样套路——代码仓库新增 `sources/<x>.py` + 一个新数据仓库 + 该仓库挂 `reusable-snapshot.yml`。

扩展点主要在**`sources/`** 和**"新建一个数据仓库 + 10 行 cron.yml"**,不需要重构 `common.py` 或 reusable workflow。

---

## 10. 实现前需确认的假设(writing-plans 阶段先行验证)

以下几处依赖上游第三方包的实际 API,spec 写作时未实测,writing-plans 阶段第一步应先做确认,必要时给出 fallback:

1. **`tranco` PyPI 包**是否仍在活跃维护,`Tranco().list().list_id` 与 `.top(N)` API 是否如描述。若不可用,fallback:直接 HTTPS 拉 `https://tranco-list.eu/top-1m.csv.zip`,用 `Content-Disposition` 或 `/list/<listid>/full` 约定拿 version ID。
2. **`cloudflare` Python SDK v3+** 是否确有 `radar.ranking.top(limit=N)` 方法可达 rank bucket 端点。若不可用,fallback:用 `requests` 直接打 REST endpoint `https://api.cloudflare.com/client/v4/radar/ranking/top?limit=N`,Bearer token 放 Authorization header。
3. **reusable workflow 的 secret 透传**语法(`secrets: CLOUDFLARE_RADAR_API_TOKEN: ${{ ... }}` vs `secrets: inherit`)以当期 GitHub Actions 文档为准。

这些不改变设计结构,只影响 `sources/*.py` 和 workflow yml 的具体几行实现。

---

## 11. 交付物清单(本轮 writing-plans 阶段将落实)

1. `feedcache` 代码仓库(git init + 上述全部文件)。
2. `umbrella-top1m-cache`、`tranco-top1m-cache`、`cloudflare-radar-rankings-cache` 三个数据仓库的骨架(README + LICENSE + `.github/workflows/cron.yml`,空 `data/` 目录)。
3. 本 spec 迁入 `feedcache/docs/design.md` 并首次 commit。
4. 执行一次本地验证:对每个源运行 `feedcache <src> /tmp/<repo>/data/`,确认产物结构与本 spec 4/5 节一致。
5. (用户手动)在 GitHub 上创建对应四个 repo,设远端,push;在 Cloudflare 数据仓库 Settings → Secrets 配 `CLOUDFLARE_RADAR_API_TOKEN`;首次 `workflow_dispatch` 触发验证。

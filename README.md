# knowledge-base

团队内部的知识库服务。**一个文件夹就是一个知识库**：里面既有人工维护的知识，也有 agent 沉淀的经验，还有被索引的代码库。组员的 agent 通过 MCP 检索与沉淀，人通过浏览器浏览与维护。

部署在内网的一台 Ubuntu 服务器上，运维在服务器上建一个目录，在里面跑 `knowledge-base server`，就有了：

- 一个网页 UI，给人用
- 一个 MCP 端点，给组员的 agent 用（大多是 opencode）

**服务不做认证**，靠内网隔离。不要把它暴露到公网。它默认监听 `0.0.0.0`，也就是同一局域网里的任何人都能直接连上并读写 `learnings/`——这是被明确接受的前提，前提是这个网段本身可信。不满足就用 `--host` 绑到具体网卡，或者在前面挡一层。

对外要用哪个地址，服务自己算，不看请求里的 `Host`：取默认路由那张网卡的 IPv4。所以网页状态页、`knowledge-base status` 和日志里的 MCP 端点永远是同一个，组员从任何一台机器打开页面，抄到的都是同一段配置。这台机器要是没有默认路由（或者只有 IPv6），它会直说找不到，而不是编一个连不上的地址出来。

## 它解决什么问题

同一个坑，组里每个人都会踩一遍；踩完了结论留在各自的聊天记录里，下一个人还是从零开始。agent 尤其如此：每开一个新会话它就是一张白纸。

这个服务让 agent 在动手之前先问一句「这个问题别人解决过吗」，解决完之后再把结论写回来。同时它把代码库也索引进去，agent 可以直接问「这个符号定义在哪」「谁调用了它」，不必靠通读源码去猜。

对外只有两个门面：网页与 MCP。两个上游（[basic-memory](https://github.com/basicmachines-co/basic-memory) 管文档图谱、[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) 管代码图谱）一行代码都不改，被当作内部实现调用，接口一概不外露。

## 知识库根目录

```text
<root>/                      # 本身是 git 仓库，服务防抖自动提交
├── knowledge/               # 人工维护的知识
├── learnings/               # agent 沉淀的经验
├── codebase/                # 被索引的代码库，git-ignored
├── .knowledge-base/         # 索引与运行时数据，git-ignored，可整体删除重建
└── .gitignore
```

| 目录 | 内容 | 谁能写 |
| --- | --- | --- |
| `knowledge/` | 人工维护的长效知识，自由 Markdown | 人（网页 UI、服务器上直接编辑、git push）。**agent 只读**——MCP 层根本不提供写它的手柄 |
| `learnings/` | agent 沉淀的经验，语义 Markdown | agent（`distill_learning`）与人（网页 UI） |
| `codebase/` | 源码仓库本体 | 运维手工 `git clone` 进去。服务只读它，不改它 |

`codebase/` 与 `.knowledge-base/` 必须留在根目录的 `.gitignore` 里：代码库有自己的 git 历史，索引数据随时可以重建（见 [ADR-0003](docs/adr/0003-git-debounced-autocommit-as-versioning.md)、[ADR-0004](docs/adr/0004-single-basic-memory-project-at-root.md)）。

版本管理是全自动的：写入之后静默 30 秒，同一作者的连续写入聚合成一个 commit。没有人需要手动提交。文档的创建与修改时间一律从 git 历史取，不写进 frontmatter。

## 部署（Ubuntu 原生）

用 pip + systemd，不用 Docker。

### 一步到位

```bash
git clone <本仓库> knowledge-base
cd knowledge-base
sudo ./deploy/install.sh /srv/knowledge-base
```

脚本做的事，按顺序：装系统依赖 → 建 `knowledge-base` 系统用户与根目录 → 把源码放到 `/opt/knowledge-base/src` → 构建前端 → 在 `/opt/knowledge-base/venv` 里 `pip install` → 装 `codebase-memory-mcp` 并关掉它自带的文件监听 → `knowledge-base init` 初始化根目录 → 装 systemd unit 并 enable。可以重复执行，重跑一次就是升级。

### 手工来一遍

如果不想跑脚本，等价的步骤是：

```bash
# 1. 系统依赖。Ubuntu 22.04 的 apt 里没有 python3.12（24.04 起才自带），
#    先加 deadsnakes；它只是多装一个解释器，不会替换系统 python。
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get install -y python3.12 python3.12-venv git curl

# 2. 服务用户与知识库根目录
sudo useradd --system --home-dir /srv/knowledge-base --shell /usr/sbin/nologin knowledge-base
sudo mkdir -p /srv/knowledge-base && sudo chown -R knowledge-base: /srv/knowledge-base

# 3. 源码与 Python 环境
sudo cp -a . /opt/knowledge-base/src
sudo python3.12 -m venv /opt/knowledge-base/venv
sudo /opt/knowledge-base/venv/bin/pip install /opt/knowledge-base/src

# 4. 前端构建产物（不构建也能跑，只是没有网页 UI）
cd /opt/knowledge-base/src/frontend && npm ci && npm run build

# 5. 代码域上游（不装也能跑，只是代码域不可用）
curl -fsSL https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.sh | bash
codebase-memory-mcp config set auto_watch false
codebase-memory-mcp daemon stop

# 6. 初始化根目录布局
sudo -u knowledge-base /opt/knowledge-base/venv/bin/knowledge-base init --root /srv/knowledge-base

# 7. 服务
sudo cp deploy/knowledge-base.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now knowledge-base
```

装完检查一句：

```bash
curl -s localhost:8080/api/system/status
```

### systemd unit 里要注意的两行

- `ExecStopPost=-/usr/local/bin/codebase-memory-mcp daemon stop` —— `codebase-memory-mcp`
  会起一个**按账户共享的协调守护进程**，我们的服务退出时它不会跟着退出，而它只接纳与自己版本完全一致的进程。留一个旧的在那里，下次升级新进程会直接拒绝启动。见
  [ADR-0007](docs/adr/0007-supervise-the-upstream-as-a-long-lived-mcp-server.md)。
- `Environment=CBM_CACHE_DIR=...` —— 那个守护进程是按 cache root 区分的。unit 里声明的值必须和服务进程用的一致（即 `<root>/.knowledge-base/cbm`），否则上面那句 `daemon stop` 停的是另一个守护进程。

`TimeoutStopSec=180` 也不要调小：停止时先把防抖队列里没提交的改动 flush 进 git，再等上游守护进程释放其它会话，后者上游允许自己等到两分钟。

### 代码域会占多少资源

一个 `codebase-memory-mcp` 进程同一时刻只答一个问题——两个调用共用一对管道会互相读到对方的回复。所以服务自己维护一个有界的长驻会话池：

| 上限 | 值 | 什么意思 |
| --- | --- | --- |
| 长驻会话数 | 4 | 最多同时开 4 个上游子进程。按需增长，启动时只开第一个 |
| 每会话在途调用 | 1 | 一条会话同时只服务一个调用，回复不会串台 |
| 池内并发调用 | 20 | 超过就排队；排到 10 分钟还没轮上，明说上游饱和而不是继续堆线程 |

四个会话共用同一个 cache 目录和同一个协调守护进程，这是 [ADR-0007](docs/adr/0007-supervise-the-upstream-as-a-long-lived-mcp-server.md) 的硬约束：池里绝不能混用 cache，也不能混用二进制版本。

只读调用（列项目、搜索、读符号、追调用链、图查询、架构）遇到断连会重连并重试一次。`index_repository` 不重试——它改索引，重放一次可能是半个索引，所以断了就如实返回失败让调用方重来。

## 命令

| 命令 | 作用 |
| --- | --- |
| `knowledge-base server [--root .] [--host 0.0.0.0] [--port 8080] [--frontend DIR]` | 在根目录上启动服务 |
| `knowledge-base init [--root .]` | 只初始化根目录布局，不启动 |
| `knowledge-base reindex documents [--root .]` | 重建文档检索索引与知识图谱 |
| `knowledge-base reindex code [--root .] [--repo NAME]` | 重建代码库索引；不指定 `--repo` 就是全部 |
| `knowledge-base status [--root .] [--host] [--port]` | 打印索引规模、上游状态，以及组员要用的 opencode 接入片段 |

所有命令都接受 `--verbose`。`--frontend` 也可以用环境变量 `KB_FRONTEND_DIST` 给。

## 组员怎么接入

在自己的 `opencode.json`（项目级）或 `~/.config/opencode/opencode.json`（全局）里加一段：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kb": {
      "type": "remote",
      "url": "http://<服务器地址>:8080/mcp",
      "enabled": true,
      "oauth": false
    }
  }
}
```

`oauth: false` 是显式关掉 opencode 的 OAuth 自动探测——服务没有认证，不关的话它会先撞一次 401 再打印一行警告。

不用记这段，网页首页与 `knowledge-base status` 都会把填好地址的片段直接打出来。

服务名叫 `kb`，所以 agent 看到的工具名是 `kb_search_knowledge`、`kb_distill_learning` 这样。连上之后服务会把使用说明连同这个库的**内容提纲**（有哪些一级分类、多少篇文档、索引了哪些代码库、最常见的标签）一起交给 agent，不需要在自己的 AGENTS.md 里再写一遍。

## agent 能用的十个工具

前四个是文档侧，后六个是代码侧。工具描述与下面的说明同源，都来自 `src/knowledge_base/mcp/instructions.py`。

**检索知识**

| 工具 | 干什么 | 什么时候用 |
| --- | --- | --- |
| `search_knowledge` | 检索知识库，只返回标题、摘要、大纲与命中的观察原句，不返回全文 | 动手排查之前先搜一次。可以用 `scope` 限定在知识或经验里、用 `tags` 收窄、用 `category` 只要某一类观察（如 `pitfall`） |
| `read_knowledge` | 读一篇文档的全文，传 `section` 只读其中一节 | 检索结果看着有用之后，再花上下文取全文。节名来自检索给的大纲 |
| `explore_links` | 沿文档之间的关系游走 | 想知道这篇经验引用了什么、又被什么引用 |

检索与阅读分开是刻意的：全文很贵，先看摘要和命中的那一句，判断值不值得再读——这就是**渐进式披露**。

**沉淀经验**

| 工具 | 干什么 |
| --- | --- |
| `distill_learning` | 往 `learnings/` 写一条经验。四种形态由参数决定：不传 `target` 是**新建**（需要 `folder`、`title`、`summary`、`observations`）；传 `target` 是向那条经验**追加**观察；再传 `replaces`（要被替换的观察原句，逐字）是**修订**；传 `target` 加 `delete=true` 是**删除** |

什么时候该沉淀：调试花了不少时间、行为与直觉相反、做法在官方文档里查不到。一条观察写一句话。发现旧结论已经腐烂就用 `replaces` 覆盖它，正文里不留失效的旧结论，变迁去 git 历史查。

`author` 填当前使用者的名字，它会写进 frontmatter 与 git 历史。

**检索代码**

| 工具 | 干什么 | 什么时候用 |
| --- | --- | --- |
| `list_repos` | 列出已纳管的代码库，以及各自是否**现在就查得动** | 不知道有哪些库时 |
| `get_architecture` | 一个代码库的整体结构：语言、包、入口、热点 | 面对陌生仓库的第一步 |
| `search_code` | 找代码。`mode=symbol` 按声明名逐字匹配（默认），`mode=keyword` 按关键词排序（驼峰会拆词），`mode=text` 搜源码全文，`mode=regex` 才把输入当正则 | 记得名字用 symbol，记不清拼写用 keyword，要搜注释或未解析语言用 text，确实要写模式才用 regex |
| `read_symbol` | 按限定名读一个符号的源码 | 限定名用 `search_code` 结果里的 `canonical_qn` |
| `trace_calls` | 沿调用图走，`direction=inbound` 看谁调用它，`outbound` 看它调用谁 | 评估改动影响面 |
| `query_code_graph` | 对某个代码库的图跑只读 openCypher 查询 | 只在上面几个都问不出来时用，它耦合上游的图结构；**必须指定 `repo`** |

四件事值得单独记住：

- **上游一次只查一个代码库**。它的每个读取工具都要求指定项目，所以不指定代码库的检索是网关**逐个问一遍**再把结果按代码库先后排开的，不做跨库排序——相关度是各库自己算的，混排等于凭空发明第三种顺序。`query_code_graph` 无法这样兜底，因此必须指定代码库。
- **上游给代码库起的名字不是目录名**。它把索引时拿到的整条路径打平：`/home/mdc/kb/codebase/ops-nn` 被记成 `home-mdc-kb-codebase-ops-nn`。这个拼法猜不出来，网关靠 `list_projects` 一并返回的 `root_path` 与磁盘目录对上号，你不需要知道它。
- **`indexed: true` 表示现在就能查**，不只是上游记得建过。上游列得出来但答不上来（图建了一半、cache 被挪走、版本对不上）一律算未索引——显示成已索引，只会让人对着搜索框浪费二十分钟。
- **符号有两个名字**：`display_qn` 给人读，`canonical_qn` 给机器用。后续 `read_symbol`、`trace_calls` 一律传 `canonical_qn`；重名时短名会带一个稳定后缀 `#xxxxxx`，那种名字传回来会被直接拒绝并告诉你该用哪个。
- **调用链只收能唯一确证的关系，而且只有第 1 跳是边**。上游给的是每一跳距离起点多远、以及这一跳是怎么解析出来的（类型解析 / 语言规则 / 启发式），**它不说第二跳是经由谁抵达的**，所以第 2 跳起页面上不画符号之间的连线——要看中间那一段，从对应符号继续追。解析不出唯一符号的跳不进结果，只记进「未解析」计数。调用图本身还**可能有漏边**：上游只对 12 种语言做类型解析，其余语言按文本匹配。没有边不等于没有调用——每个读调用图的答案都会带上这句提醒。
- **读源码可能只读到前 500 行**。上游会截断长实现，页面会明说截在第几行。把截断的实现当完整的看，是「这个函数没处理某情况」这类误判最常见的来源。

搜索失败会分成四类回给你：查询本身有问题（自己改）、上游拒绝（换个问法）、上游不可用（找运维）、网关内部出错（报 bug）。每条都带一个诊断编号，和日志里那行是同一个。

## 运维日常

**加一个代码库**

```bash
sudo -u knowledge-base git clone <仓库> /srv/knowledge-base/codebase/<名字>
sudo -u knowledge-base /opt/knowledge-base/venv/bin/knowledge-base \
    reindex code --root /srv/knowledge-base --repo <名字>
```

也可以在网页上点，或者 `curl -X POST localhost:8080/api/code/repos/<名字>/index`。代码库不进知识库的 git 历史，它有自己的。

**重建索引**

文档索引在内存里，服务启动时会重建一次，平时靠文件监听增量维护。手工改了很多文件、或者觉得它跟磁盘不同步了：

```bash
sudo systemctl stop knowledge-base
sudo -u knowledge-base /opt/knowledge-base/venv/bin/knowledge-base reindex documents --root /srv/knowledge-base
sudo systemctl start knowledge-base
```

彻底重来就把 `.knowledge-base/` 整个删掉再启动，里面没有任何不能重建的东西。

**看历史与回滚**

根目录就是普通 git 仓库，`git log`、`git show`、`git diff` 都能直接用：

```bash
cd /srv/knowledge-base
git log --oneline -- learnings/ascendc/对齐要求.md
git show <commit>
```

网页上每篇文档都有历史页，可以看某个版本的原文并一键回滚（回滚是一次新的提交，不改写历史）。想异地备份就加一个 remote 定期 push。

**看服务状态**

```bash
systemctl status knowledge-base
journalctl -u knowledge-base -f
curl -s localhost:8080/api/system/status
```

**降级行为**（这两种情况都不影响服务启动）

- 没装 `codebase-memory-mcp`：文档域一切照常，代码域的接口一律返回 `ok=false` 并说明原因，状态页显示上游不可用。装好之后 `systemctl restart knowledge-base` 即可。
- 没构建前端：日志里会有一行 `The web UI is not built at ...; serving the API and the MCP endpoint only`，`/api` 与 `/mcp` 照常工作，只是浏览器打开是 404。

## 发布前的真实上游门禁

常规 CI 不需要 `codebase-memory-mcp`：并发、故障与前端验收全部跑在假二进制上，是确定性的。但「假二进制答得对」和「真二进制答得对」是两件事，所以上线前要在**装了目标版本二进制的那台机器**上跑一遍真实门禁。

**升级了上游就先对一遍工具契约和报文形状。** 参数表在 `tests/upstream_schema.py`，逐字抄自某个版本的 `tools/list`；报文样本在 `tests/upstream_replies.py`，逐字采自真二进制的回答。前者不更新，测试固定的是上一版的参数表，而真二进制对不认识的参数是**静默忽略**；后者不更新，解析器会照着旧形状读，**一条都读不出来也不会报错**——页面只是空的（见 ADR-0008）。门禁里有一组用例专门查这个：它们断言的是解析出来的结果，不是报文。

```bash
# 0. 升级过上游的话，把这两份输出分别与 tests/upstream_schema.py、tests/upstream_replies.py 对一遍
codebase-memory-mcp cli tools list
codebase-memory-mcp cli call search_graph '{"project":"<某个已索引项目>","name_pattern":"a","limit":3,"format":"json"}'

# 1. 确认装的是要上线的那个版本
codebase-memory-mcp --version

# 2. CBM 的协调守护进程每账户只认一个 cache 目录，门禁用的是自己的临时目录，
#    所以同账户下正在跑的知识库服务必须先停，否则上游会直接拒绝、门禁只能跳过。
sudo systemctl stop knowledge-base

# 3. 一条命令跑完
cd /opt/knowledge-base/src
/opt/knowledge-base/venv/bin/python -m pytest -m upstream_binary -v -rs

sudo systemctl start knowledge-base
```

这一轮覆盖：20 个并发读取各自拿到自己的答案（回复不串台）、守护进程被中途停掉后调用仍能重连答出来、`indexed` 确实等于「现在查得动」、检索给的 `canonical_qn` 能原样读回源码、调用链是真符号之间的边、以及这台机器算出来的对外地址就是状态页交出去的那个。

全绿之前不要发布。跳过时 `-rs` 会打出原因，两种：`codebase-memory-mcp` 不在 `PATH` 上，或者同账户下还有别的 CBM 守护进程占着 cache（`codebase-memory-mcp daemon stop` 之后重试）。这两种都不是代码缺陷，但**也不算通过**。

门禁里有一条格外容易被忽略：关掉上游自带文件监听的那个配置键（`auto_watch`）在当前安装的版本里必须真实存在。上游对未知的键只是非零退出、打一行 `unknown config key`，抓不到任何可捕获的失败——键名不对等于监听根本没关，它会在服务背后重建索引。`tests/test_code_process.py` 里那条测试就是专门盯这件事的，跟着 `-m upstream_binary` 一起跑。

想用真实 agent 再走一遍：在 opencode 里连上 kb，依次问「kb 里有哪些代码库」→「demo 的架构是什么样」→「找一下 XXX 这个函数」→「读一下它的源码」→「谁调用了它」。

## 开发

需要 **Python 3.12 或更高**——这是上游 basic-memory 的硬性要求，不是本项目的偏好。手上只有 3.11 时，用 `uv python install 3.12 && uv venv --python 3.12` 装一个独立解释器，或者走上面 deadsnakes 那条路。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
.venv/bin/pyright
```

浏览器验收另装一份 Playwright，并且要先有前端构建产物；缺哪一样就跳过哪一样，并在跳过原因里写清楚补哪条命令：

```bash
.venv/bin/pip install -e ".[dev,browser]"
.venv/bin/playwright install chromium
(cd frontend && npm ci && npm run build)
.venv/bin/pytest tests/test_browser.py
```

CI 每次改动跑后端测试、类型、格式、前端构建和浏览器验收，全部基于假二进制。真实上游的门禁见上一节，另有一个夜间入口（`workflow_dispatch` 也能手动触发）跑完整套件。

本地跑服务：在任意目录 `knowledge-base server --root .`，前端构建产物默认从源码树的 `frontend/dist` 找。

## 文档

- [`CONTEXT.md`](CONTEXT.md) —— 领域词汇表
- [`docs/adr/`](docs/adr/) —— 架构决策记录

## 许可证

AGPL-3.0，见 [`LICENSE`](LICENSE)。

本服务把 [basic-memory](https://github.com/basicmachines-co/basic-memory)（AGPL-3.0）以库的形式装进同一个进程调用（见 `src/knowledge_base/docs/graph.py`），因此整体只能以 AGPL-3.0 发布。AGPL 与 GPL 的区别在于：通过网络提供服务也构成分发，所以任何人部署本服务，都应当向其使用者提供对应版本的源码。

代码域上游 [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) 是 MIT，且以独立子进程运行，不影响本仓库的许可证选择。

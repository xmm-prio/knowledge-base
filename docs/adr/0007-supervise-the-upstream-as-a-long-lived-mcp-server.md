# 以长驻 MCP 子进程而非一次性 CLI 命令驱动 codebase-memory-mcp

codebase-memory-mcp 提供两种等价的调用方式：作为 MCP server 常驻，通过标准流收发 JSON-RPC；或者以 `cli <工具名> --参数` 的形式，一条命令跑一次。两者能调用的工具集完全相同。我们选择**常驻子进程**，由 supervisor 守护。

理由是每次调用的固定开销与共享状态。CLI 模式每条命令都要重新起进程、重新打开 SQLite、重新进入它的准入屏障；而检索是本服务最高频的动作，问一次「这个函数被谁调用」不该付一次进程启动的代价。常驻还让健康检查、崩溃重启、以及索引期间的进度通知有地方落脚——进度是以 JSON-RPC 通知的形式与回复共用同一条流的，一次性命令只能把它写到 stderr。

代价是我们必须自己承担进程生命周期，包括上游那个**无法禁用**的 per-account 协调守护进程。CLI 模式恰恰不会启动它，而常驻模式会。

## Consequences

- supervisor 的停止逻辑必须执行 `codebase-memory-mcp daemon stop`。该守护进程要求同账户下所有 CBM 进程版本完全一致，残留一个旧版本会让升级后的新进程直接拒绝启动。systemd unit 里需要对应的 `ExecStopPost`。
- 守护进程是按 cache root 区分的，不是每账户一个。服务进程的 cache root 被指到 `<root>/.knowledge-base/cbm`，因此 `ExecStopPost` 必须在同一个 `CBM_CACHE_DIR` 下执行，否则停掉的是默认 `~/.cache` 下的另一个守护进程，等于没停。
- 启动时先 `config set auto_watch false` 再 `daemon stop`，然后才拉起子进程：这个开关只在它的守护进程启动时读一次，不先停掉旧守护进程就不会生效。索引时机由本服务决定，它自己的文件监听会在我们背后重建索引。上游对未知的配置键只是以非零码退出并打一行 `unknown config key`，不会报出任何我们能捕获的失败，所以键名写错等于什么都没关掉——已知可用的键只有 `auto_index`、`auto_index_limit`、`auto_watch`、`ui-lang`、`ui_enabled`、`ui_port`。
- 与上游的全部交互收敛在 `code/upstream.py` 的一个 Channel 接缝上。真实二进制按平台编译，开发机上通常没有，因此协议层的测试一律走进程内的假 Channel，只有一条集成测试要求二进制真实存在（pytest 标记 `upstream_binary`，缺失时跳过）。
- `CBM_ALLOWED_ROOT` 指向 `codebase/`：调用方只能报仓库名，但请求要穿过好几层，这是最后一道兜底，防止上游被引导去索引根目录之外的任何路径。

# basic-memory 用单个 project 指向知识库根目录

`knowledge/` 与 `learnings/` 映射到 **一个** basic-memory project，该 project 指向知识库根目录，靠根目录的 `.gitignore` 把 `codebase/` 排除在索引之外。

替代方案是两个平级 project 各管一个目录，被否决：basic-memory **显式禁止 project 嵌套**（`Projects cannot share directory trees`），而且**跨 project 的 `[[WikiLink]]` 永远无法解析**——关系行会建出来但目标为空，后台重试也只在同 project 内查找。经验要能链接到知识，就只能同处一个 project。

## Consequences

- basic-memory 索引目录下的**所有文件**（不只 `.md`），且每个文件都会被完整读入内存算校验和。`codebase/` 里成千上万的源码文件必须被挡住，否则每次同步都会全量读盘。
- 它的排除机制很弱：只读**根目录那一个** `.gitignore` 加一个全局 `.bmignore`，子目录里的 `.gitignore` 完全不读，也没有 `!` 否定模式和 `**` 层级语义。所以排除规则必须写在根目录的 `.gitignore` 里，且只能用朴素的目录名模式。
- `.knowledge-base/` 因为以 `.` 开头会被 basic-memory 自动跳过，但仍需 git 忽略。
- 「知识只能人工写」这条边界不靠 project 隔离实现，而靠工具层的能力边界：MCP 根本不提供写 `knowledge/` 的手柄。

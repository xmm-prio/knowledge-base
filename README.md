# knowledge-base

团队内部的知识库服务。一个文件夹就是一个知识库：里面既有人工维护的**知识**，也有 agent 沉淀的**经验**，还有被索引的**代码库**。组员的 agent 通过 MCP 检索与沉淀，人通过网页浏览与维护。

## 它是什么

本服务是一个**编排器 + 网关**。两个上游一行代码都不改，只作为内部实现被调用：

- [basic-memory](https://github.com/basicmachines-co/basic-memory) —— Markdown 文档的索引与知识图谱
- [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) —— 代码库的符号级图谱

对外只有两个门面：一个网页 UI，一个 MCP 端点。上游的接口一概不外露。

## 知识库根目录

```text
<root>/                      # 本身是 git 仓库，服务自动提交
├── knowledge/               # 人工维护，自由 Markdown，agent 只读
├── learnings/               # agent 沉淀的经验，语义 Markdown
├── codebase/                # 手工放入的代码库本体，被索引
├── .knowledge-base/         # 索引与运行时数据，可整体删除重建
└── .gitignore
```

## 开发

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## 文档

- [`CONTEXT.md`](CONTEXT.md) —— 领域词汇表
- [`docs/adr/`](docs/adr/) —— 架构决策记录

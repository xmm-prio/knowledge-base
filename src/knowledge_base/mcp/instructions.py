"""What the server tells an agent the moment it connects.

opencode injects the `instructions` from the initialize response into the agent's context, so
the usage manual ships with the service instead of with every member's own configuration. Two
parts, for two different reasons:

- the static part says when to search and when to distil. It never changes.
- the outline says what this particular knowledge base holds, and is generated per connection
  because a knowledge base grows. It stops at the granularity an agent needs to decide whether
  searching is worth a call: no document titles. Titles are what search is for, and this text
  is paid for by every member in every session.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from knowledge_base.code.engine import CodeEngine
from knowledge_base.docs.documents import load_document
from knowledge_base.docs.store import INDEXED_DIRECTORIES, MARKDOWN_SUFFIX
from knowledge_base.layout import KnowledgeBaseRoot

TOP_TAGS = 20
"""Enough to show what the library is about, few enough to stay inside the outline's budget."""

STATIC = """\
这是团队共享的知识库，用它检索别人已经解决过的问题，也把你解决的问题沉淀回来。

什么时候检索：动手排查之前先 search_knowledge 搜一次，别人可能已经踩过这个坑；面对陌生代码库先 \
get_architecture 看结构，再 search_code 找符号。检索只给标题、摘要、大纲与命中的观察原句，\
判断有用之后再用 read_knowledge 取全文或某一节。

什么时候沉淀：调试花了不少时间、行为与直觉相反、做法在官方文档里查不到——这三种情况用 \
distill_learning 把结论写下来，一条观察一句话。已有相近的经验就传 target 追加；发现旧结论\
已经腐烂，就连 replaces 一起传，用新结论覆盖它。

author 填当前使用者的名字，它会写进文档与 git 历史；确实问不到就填 agent。"""


@dataclass(frozen=True)
class Snapshot:
    """What the knowledge base holds, at the moment an agent connected."""

    documents: int = 0
    knowledge_folders: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    tags: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    """The most used tags, most used first, with how many documents carry each."""


def survey(root: KnowledgeBaseRoot, code: CodeEngine) -> Snapshot:
    """Look over the whole knowledge base. Synchronous, and reads every document."""
    counted: Counter[str] = Counter()
    documents = 0
    for relative in _markdown(root.path):
        documents += 1
        counted.update(load_document(root.path, relative).tags)

    return Snapshot(
        documents=documents,
        knowledge_folders=tuple(sorted(_folders(root.knowledge_dir))),
        repos=tuple(repo.name for repo in code.list_repos() if repo.indexed),
        tags=tuple(counted.most_common(TOP_TAGS)),
    )


def outline(snapshot: Snapshot) -> str:
    """The generated half of the instructions: what is in this library right now."""
    return "\n".join(
        [
            "## 这个库里有什么",
            "- knowledge/：人工维护的长效知识，只读。一级分类："
            f"{_listed(snapshot.knowledge_folders)}",
            "- learnings/：agent 沉淀的经验，可读可写，靠检索而不是靠目录找。"
            f"全库共 {snapshot.documents} 篇文档",
            f"- codebase/：已索引的代码库：{_listed(snapshot.repos)}",
            f"- 最常见的标签：{_tags(snapshot.tags)}",
        ]
    )


def compose(snapshot: Snapshot) -> str:
    """The whole of what an agent is told on connecting."""
    return f"{STATIC}\n\n{outline(snapshot)}"


def _markdown(root: Path) -> list[str]:
    return [
        path.relative_to(root).as_posix()
        for directory in INDEXED_DIRECTORIES
        for path in sorted((root / directory).rglob(f"*{MARKDOWN_SUFFIX}"))
        if path.is_file()
    ]


def _folders(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return [entry.name for entry in directory.iterdir() if entry.is_dir()]


def _listed(names: tuple[str, ...]) -> str:
    return "、".join(names) if names else "（暂无）"


def _tags(tags: tuple[tuple[str, int], ...]) -> str:
    return "、".join(f"{tag} {count}" for tag, count in tags) if tags else "（暂无）"

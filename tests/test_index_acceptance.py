"""Whether the knowledge base gives the same answer today as it did yesterday.

The index is in memory and holds nothing the files do not (ADR-0006), so every answer it gives
is only as good as the reading that filled it. These tests run a real knowledge base on disk
through the whole service and ask the same questions after a startup, after an edit, after a
deletion, after a restart and after a rebuild by hand -- because a retrieval that drifts with
uptime is worse than one that is merely narrow.

The narrowness is deliberate and stays out of scope: jieba matches terms, not meanings, so
searching 尾块数据不对 will not find 读到脏数据. That is ADR-0006's stated gap, not a defect
for a test to discover.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

import httpx

from service_harness import assembled

PATIENCE = 20.0
"""Seconds to wait for a change on disk to reach the index. The watcher debounces."""

ALIGNMENT = """\
---
title: DataCopy 的对齐要求
summary: 搬运长度不按 32 字节对齐时尾块会读到脏数据
tags: [ascendc, datacopy]
---

## Observations
- [pitfall] blockLen 非 32B 对齐时，尾块会读到脏数据 #ascendc
- [verified] DataCopyPad 会按 padParams 补齐尾块 #datacopy
"""

DOUBLE_BUFFER = """\
---
title: TQue 的双缓冲深度
summary: 双缓冲深度设为 2 时流水最稳
tags: [ascendc]
---

## Observations
- [decision] TQue 的双缓冲深度设为 2，再深收益递减 #ascendc
"""

HANDBOOK = """\
---
title: 上板调试手册
summary: MC62 上采集性能数据的四段流程
tags: [mdc]
---

板上 msprof 没有 export，必须回传后再解析。
"""


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def found(client: httpx.AsyncClient, query: str) -> list[str]:
    """The documents one query reaches, by path."""
    reply = await client.get("/api/search", params={"q": query})
    return sorted({hit["path"] for hit in reply.json()["documents"]["hits"]})


async def settles_at(client: httpx.AsyncClient, query: str, expected: Iterable[str]) -> list[str]:
    """Wait for a query to reach exactly these documents, then say what it reached.

    Changes made on disk arrive through a debounced watcher, so the first answer after a write
    is allowed to be the old one. Never settling is the failure.
    """
    wanted = sorted(expected)
    async with asyncio.timeout(PATIENCE):
        while (paths := await found(client, query)) != wanted:
            await asyncio.sleep(0.1)
    return paths


class TestWhatStartupReads:
    async def test_both_knowledge_and_learnings_are_searchable_at_once(
        self, tmp_path: Path
    ) -> None:
        """Two folders, two kinds of writing, one index. A member searches without choosing."""
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)
        write(tmp_path, "knowledge/上板调试手册.md", HANDBOOK)

        async with assembled(tmp_path) as running:
            assert await found(running.client, "对齐") == ["learnings/对齐要求.md"]
            assert await found(running.client, "msprof") == ["knowledge/上板调试手册.md"]

    async def test_the_index_reports_the_size_of_what_it_read(self, tmp_path: Path) -> None:
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)
        write(tmp_path, "learnings/双缓冲.md", DOUBLE_BUFFER)

        async with assembled(tmp_path) as running:
            size = (await running.client.get("/api/system/status")).json()["documents"]

        assert (size["documents"], size["observations"]) == (2, 3)
        assert size["tags"] == 2


class TestKeepingUpWithTheFiles:
    async def test_a_document_written_after_startup_becomes_searchable(
        self, tmp_path: Path
    ) -> None:
        """A git pull is the ordinary case: files change without anyone telling the service."""
        async with assembled(tmp_path) as running:
            write(tmp_path, "learnings/双缓冲.md", DOUBLE_BUFFER)

            assert await settles_at(running.client, "双缓冲", ["learnings/双缓冲.md"]) == [
                "learnings/双缓冲.md"
            ]

    async def test_a_revised_document_stops_matching_what_it_no_longer_says(
        self, tmp_path: Path
    ) -> None:
        """A rotten conclusion is overwritten, not kept beside the new one."""
        write(tmp_path, "learnings/双缓冲.md", DOUBLE_BUFFER)

        async with assembled(tmp_path) as running:
            await settles_at(running.client, "双缓冲", ["learnings/双缓冲.md"])
            write(tmp_path, "learnings/双缓冲.md", DOUBLE_BUFFER.replace("双缓冲", "三缓冲"))

            await settles_at(running.client, "双缓冲", [])
            assert await found(running.client, "三缓冲") == ["learnings/双缓冲.md"]

    async def test_a_deleted_document_leaves_nothing_behind(self, tmp_path: Path) -> None:
        write(tmp_path, "learnings/双缓冲.md", DOUBLE_BUFFER)

        async with assembled(tmp_path) as running:
            await settles_at(running.client, "双缓冲", ["learnings/双缓冲.md"])
            (tmp_path / "learnings" / "双缓冲.md").unlink()

            assert await settles_at(running.client, "双缓冲", []) == []


class TestAgreeingWithItself:
    async def test_a_restart_answers_exactly_as_the_first_run_did(self, tmp_path: Path) -> None:
        """Nothing an agent retrieves may depend on how long the service has been up."""
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)
        write(tmp_path, "knowledge/上板调试手册.md", HANDBOOK)

        async with assembled(tmp_path) as first:
            before = [await found(first.client, term) for term in ("对齐", "脏数据", "msprof")]

        async with assembled(tmp_path) as second:
            after = [await found(second.client, term) for term in ("对齐", "脏数据", "msprof")]

        assert after == before
        assert before[0] == ["learnings/对齐要求.md"]

    async def test_rebuilding_by_hand_agrees_with_what_the_watcher_took_in(
        self, tmp_path: Path
    ) -> None:
        """Two ways in, one index. If they disagree, one of them is quietly wrong."""
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)

        async with assembled(tmp_path) as running:
            write(tmp_path, "learnings/双缓冲.md", DOUBLE_BUFFER)
            incremental = await settles_at(running.client, "对齐", ["learnings/对齐要求.md"])
            watched = await settles_at(running.client, "双缓冲", ["learnings/双缓冲.md"])

            await running.client.post("/api/system/reindex/documents")

            assert await found(running.client, "对齐") == incremental
            assert await found(running.client, "双缓冲") == watched

    async def test_rebuilding_reports_every_document_it_read(self, tmp_path: Path) -> None:
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)
        write(tmp_path, "knowledge/上板调试手册.md", HANDBOOK)

        async with assembled(tmp_path) as running:
            reply = await running.client.post("/api/system/reindex/documents")

        assert reply.json()["indexed"] == 2


class TestAwkwardFiles:
    async def test_one_unreadable_file_does_not_cost_the_others(self, tmp_path: Path) -> None:
        """A knowledge base is a git repository people put things into by hand."""
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)
        (tmp_path / "learnings" / "损坏.md").write_bytes(b"\xff\xfe\x00title\x00")
        (tmp_path / "learnings" / "空.md").write_text("", encoding="utf-8")
        write(tmp_path, "learnings/坏头.md", "---\ntitle: [未闭合\ntags: {{{\n---\n\n尾块要补齐。")

        async with assembled(tmp_path) as running:
            assert await found(running.client, "对齐") == ["learnings/对齐要求.md"]

    async def test_markdown_that_is_not_semantic_is_still_searchable(self, tmp_path: Path) -> None:
        """Only learnings must be semantic; knowledge is written by people, however they like."""
        write(
            tmp_path,
            "knowledge/随手记.md",
            "# 随手记\n\n没有 frontmatter，也没有观察小节。尾块要补齐。",
        )

        async with assembled(tmp_path) as running:
            assert await found(running.client, "尾块") == ["knowledge/随手记.md"]

    async def test_two_documents_with_the_same_title_stay_two_documents(
        self, tmp_path: Path
    ) -> None:
        write(tmp_path, "learnings/一.md", ALIGNMENT)
        write(tmp_path, "knowledge/二.md", ALIGNMENT)

        async with assembled(tmp_path) as running:
            assert await found(running.client, "对齐") == ["knowledge/二.md", "learnings/一.md"]


class TestWhatAQueryReaches:
    async def test_a_term_in_the_middle_of_a_chinese_sentence_is_found(
        self, tmp_path: Path
    ) -> None:
        """The whole reason this index exists: upstream's tokenizer cannot reach mid-sentence."""
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)

        async with assembled(tmp_path) as running:
            assert await found(running.client, "脏数据") == ["learnings/对齐要求.md"]

    async def test_a_two_character_term_is_found(self, tmp_path: Path) -> None:
        """Trigram tokenizers need three characters; 尾块 and 对齐 are the core vocabulary."""
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)

        async with assembled(tmp_path) as running:
            assert await found(running.client, "尾块") == ["learnings/对齐要求.md"]

    async def test_an_english_identifier_matches_exactly(self, tmp_path: Path) -> None:
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)

        async with assembled(tmp_path) as running:
            assert await found(running.client, "DataCopyPad") == ["learnings/对齐要求.md"]

    async def test_a_mixed_query_needs_both_halves_to_match(self, tmp_path: Path) -> None:
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)
        write(tmp_path, "learnings/双缓冲.md", DOUBLE_BUFFER)

        async with assembled(tmp_path) as running:
            assert await found(running.client, "DataCopyPad 尾块") == ["learnings/对齐要求.md"]

    async def test_a_query_nothing_discusses_answers_nothing(self, tmp_path: Path) -> None:
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)

        async with assembled(tmp_path) as running:
            assert await found(running.client, "根本没人写过的词") == []


class TestProgressiveDisclosure:
    async def test_a_hit_on_one_observation_is_reported_as_that_observation(
        self, tmp_path: Path
    ) -> None:
        """An agent gets the sentence that matched, not the file it came from."""
        write(tmp_path, "learnings/对齐要求.md", ALIGNMENT)

        async with assembled(tmp_path) as running:
            reply = await running.client.get("/api/search", params={"q": "padParams"})

        hits = reply.json()["documents"]["hits"]
        assert [one["kind"] for one in hits] == ["observation"]
        assert "DataCopyPad 会按 padParams 补齐尾块" in hits[0]["snippet"]

    async def test_no_hit_carries_the_whole_document(self, tmp_path: Path) -> None:
        """The first layer is title, summary and the line that matched. The body comes later."""
        write(tmp_path, "knowledge/上板调试手册.md", HANDBOOK)

        async with assembled(tmp_path) as running:
            reply = await running.client.get("/api/search", params={"q": "msprof"})

        hits = reply.json()["documents"]["hits"]
        assert hits
        assert all("板上 msprof 没有 export" not in one["snippet"] for one in hits)

    async def test_the_document_behind_a_hit_can_then_be_read_whole(self, tmp_path: Path) -> None:
        write(tmp_path, "knowledge/上板调试手册.md", HANDBOOK)

        async with assembled(tmp_path) as running:
            hits = (await running.client.get("/api/search", params={"q": "msprof"})).json()
            path = hits["documents"]["hits"][0]["path"]
            whole = await running.client.get(f"/api/documents/{path}")

        assert "板上 msprof 没有 export" in whole.json()["text"]

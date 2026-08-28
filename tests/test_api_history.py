"""Tests for version history and rollback.

Rollback is the one destructive thing a browser can do here, so the shape of it matters as
much as the fact of it: one document at a time, never a whole commit, and always forwards --
the old text comes back as a new commit rather than by rewriting what happened.
"""

from api_harness import ApiHarness
from conftest import commits, files_in

OVERVIEW = "knowledge/搬运 API 概览.md"
OTHER = "knowledge/双缓冲.md"


async def revise(api: ApiHarness, path: str, *texts: str) -> list[str]:
    """Write a document once per text, each in its own commit. Newest revision first."""
    for text in texts:
        await api.client.put(f"/api/documents/{path}", json={"text": text, "author": "dyq"})
        await api.go_quiet()
    body = (await api.client.get("/api/history", params={"path": path})).json()
    return [revision["revision"] for revision in body["revisions"]]


class TestReadingHistory:
    async def test_it_reports_the_whole_knowledge_bases_history_newest_first(
        self, api: ApiHarness
    ) -> None:
        await revise(api, OVERVIEW, "# 概览\n")
        await revise(api, OTHER, "# 双缓冲\n")

        body = (await api.client.get("/api/history")).json()

        assert [r["author"] for r in body["revisions"]] == ["dyq", "dyq"]
        assert body["revisions"][0]["message"] == "dyq 沉淀了 1 处改动"
        assert len(body["revisions"][0]["revision"]) == 40
        assert body["revisions"][0]["at"].startswith("20")

    async def test_it_can_be_narrowed_to_one_document_with_a_chinese_name(
        self, api: ApiHarness
    ) -> None:
        """git escapes non-ASCII paths unless told otherwise, and every title here is Chinese."""
        await revise(api, OVERVIEW, "# 概览\n")
        await revise(api, OTHER, "# 双缓冲\n")

        body = (await api.client.get("/api/history", params={"path": OVERVIEW})).json()

        assert len(body["revisions"]) == 1
        assert body["path"] == OVERVIEW

    async def test_it_stops_at_the_limit_it_was_given(self, api: ApiHarness) -> None:
        await revise(api, OVERVIEW, "# 甲\n", "# 乙\n", "# 丙\n")

        body = (await api.client.get("/api/history", params={"limit": 2})).json()

        assert len(body["revisions"]) == 2

    async def test_one_commit_says_which_documents_it_touched(self, api: ApiHarness) -> None:
        newest = (await revise(api, OVERVIEW, "# 概览\n"))[0]

        body = (await api.client.get(f"/api/history/{newest}")).json()

        assert body == {"revision": newest, "paths": [OVERVIEW]}

    async def test_a_document_can_be_read_as_it_was_at_a_revision(self, api: ApiHarness) -> None:
        _, first = await revise(api, OVERVIEW, "# 概览\n\n旧结论。\n", "# 概览\n\n新结论。\n")

        body = (
            await api.client.get(f"/api/history/{first}/document", params={"path": OVERVIEW})
        ).json()

        assert body["text"] == "# 概览\n\n旧结论。\n"
        assert body["revision"] == first

    async def test_a_revision_that_is_not_a_commit_id_is_refused(self, api: ApiHarness) -> None:
        """A caller-supplied revision reaches a process that reads leading dashes as options."""
        response = await api.client.get(
            "/api/history/--upload-pack=touch/document", params={"path": OVERVIEW}
        )

        assert response.status_code == 404


class TestRollingBack:
    async def test_it_puts_back_the_text_that_revision_held(self, api: ApiHarness) -> None:
        _, first = await revise(api, OVERVIEW, "# 概览\n\n旧结论。\n", "# 概览\n\n新结论。\n")

        response = await api.client.post(
            f"/api/history/{first}/restore", json={"path": OVERVIEW, "author": "ops"}
        )

        assert response.status_code == 200
        assert (await api.client.get(f"/api/documents/{OVERVIEW}")).json()["text"] == (
            "# 概览\n\n旧结论。\n"
        )

    async def test_it_appends_a_commit_instead_of_rewriting_history(self, api: ApiHarness) -> None:
        _, first = await revise(api, OVERVIEW, "# 概览\n\n旧结论。\n", "# 概览\n\n新结论。\n")

        body = (
            await api.client.post(
                f"/api/history/{first}/restore", json={"path": OVERVIEW, "author": "ops"}
            )
        ).json()

        assert body["restored_from"] == first
        assert body["revision"] not in (first, None)
        assert len(commits(api.root.path)) == 3
        assert commits(api.root.path)[0].startswith("ops|")
        assert files_in(api.root.path, "HEAD") == [OVERVIEW]

    async def test_it_touches_only_the_document_it_was_asked_about(self, api: ApiHarness) -> None:
        """A commit here aggregates a quiet period's writes, so it is not a unit to undo."""
        await revise(api, OTHER, "# 双缓冲\n\n深度 2。\n")
        _, first = await revise(api, OVERVIEW, "# 概览\n\n旧结论。\n", "# 概览\n\n新结论。\n")

        await api.client.post(
            f"/api/history/{first}/restore", json={"path": OVERVIEW, "author": "ops"}
        )

        assert (api.root.path / OTHER).read_text(encoding="utf-8") == "# 双缓冲\n\n深度 2。\n"

    async def test_the_restored_text_is_searchable_at_once(self, api: ApiHarness) -> None:
        _, first = await revise(api, OVERVIEW, "# 概览\n\n旧结论。\n", "# 概览\n\n新结论。\n")

        await api.client.post(
            f"/api/history/{first}/restore", json={"path": OVERVIEW, "author": "ops"}
        )

        found = (await api.client.get("/api/search", params={"q": "旧结论"})).json()
        assert sorted({hit["path"] for hit in found["documents"]["hits"]}) == [OVERVIEW]

    async def test_restoring_text_the_document_already_holds_makes_no_commit(
        self, api: ApiHarness
    ) -> None:
        """Nothing changed, so nothing is recorded -- and the caller is told so."""
        newest, _ = await revise(api, OVERVIEW, "# 概览\n\n旧结论。\n", "# 概览\n\n新结论。\n")

        body = (
            await api.client.post(
                f"/api/history/{newest}/restore", json={"path": OVERVIEW, "author": "ops"}
            )
        ).json()

        assert body["revision"] is None
        assert len(commits(api.root.path)) == 2

    async def test_rolling_back_to_before_a_document_existed_is_refused(
        self, api: ApiHarness
    ) -> None:
        """That would be a deletion in disguise, and deletion has its own endpoint."""
        first = (await revise(api, OTHER, "# 双缓冲\n"))[0]
        await revise(api, OVERVIEW, "# 概览\n")

        response = await api.client.post(
            f"/api/history/{first}/restore", json={"path": OVERVIEW, "author": "ops"}
        )

        assert response.status_code == 404
        assert (api.root.path / OVERVIEW).read_text(encoding="utf-8") == "# 概览\n"

    async def test_rolling_back_something_outside_the_document_directories_is_refused(
        self, api: ApiHarness
    ) -> None:
        first = (await revise(api, OVERVIEW, "# 概览\n"))[0]

        response = await api.client.post(
            f"/api/history/{first}/restore",
            json={"path": "codebase/mops/README.md", "author": "ops"},
        )

        assert response.status_code == 400

    async def test_a_rollback_without_an_author_is_refused(self, api: ApiHarness) -> None:
        first = (await revise(api, OVERVIEW, "# 概览\n"))[0]

        response = await api.client.post(
            f"/api/history/{first}/restore", json={"path": OVERVIEW, "author": ""}
        )

        assert response.status_code == 422

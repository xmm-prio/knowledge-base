"""Tests for browsing and editing documents over HTTP.

The web UI is for people, so its boundary is wider than an agent's -- knowledge/ is
maintained by hand -- and it is still a boundary: nothing outside knowledge/ and learnings/
may be read or written through it, and the text crosses unparsed in both directions.
"""

from api_harness import ApiHarness

OVERVIEW = "knowledge/搬运 API 概览.md"
LEARNING = "learnings/ascendc/对齐要求.md"

SOURCE = (
    "---\ntitle: 对齐要求\nsummary: 尾块会读到脏数据\ntags: [ascendc, datacopy]\n---\n\n"
    "# 对齐要求\n\n## Observations\n\n- [pitfall] 非对齐搬运时会读到脏数据 #ascendc\n"
)


async def put(api: ApiHarness, path: str, text: str, author: str = "dyq"):
    return await api.client.put(f"/api/documents/{path}", json={"text": text, "author": author})


class TestReading:
    async def test_it_hands_back_the_raw_markdown_byte_for_byte(self, api: ApiHarness) -> None:
        """The editor is a source editor (ADR-0005); a round trip may not touch a byte."""
        await put(api, LEARNING, SOURCE)

        body = (await api.client.get(f"/api/documents/{LEARNING}")).json()

        assert body["text"] == SOURCE

    async def test_it_also_hands_back_what_the_page_shows_around_the_text(
        self, api: ApiHarness
    ) -> None:
        await put(api, LEARNING, SOURCE)

        body = (await api.client.get(f"/api/documents/{LEARNING}")).json()

        assert body["path"] == LEARNING
        assert body["title"] == "对齐要求"
        assert body["summary"] == "尾块会读到脏数据"
        assert body["tags"] == ["ascendc", "datacopy"]
        assert body["observations"] == [
            {"category": "pitfall", "content": "非对齐搬运时会读到脏数据", "tags": ["ascendc"]}
        ]

    async def test_timestamps_come_from_git_and_are_absent_until_it_has_them(
        self, api: ApiHarness
    ) -> None:
        """Documents carry no timestamp of their own -- there is one truth (ADR-0003)."""
        await put(api, LEARNING, SOURCE)

        waiting = (await api.client.get(f"/api/documents/{LEARNING}")).json()
        await api.go_quiet()
        committed = (await api.client.get(f"/api/documents/{LEARNING}")).json()

        assert (waiting["created_at"], waiting["updated_at"]) == (None, None)
        assert committed["created_at"] == committed["updated_at"]
        assert committed["updated_at"].startswith("20")

    async def test_a_document_that_is_not_there_is_a_404(self, api: ApiHarness) -> None:
        assert (await api.client.get("/api/documents/knowledge/没有.md")).status_code == 404

    async def test_reading_source_through_the_document_endpoint_is_refused(
        self, api: ApiHarness
    ) -> None:
        """codebase/ has its own history and its own domain. This one must not reach it."""
        api.place_repo("mops")
        api.write("codebase/mops/README.md", "# 源码\n")

        response = await api.client.get("/api/documents/codebase/mops/README.md")

        assert response.status_code == 400


class TestWriting:
    async def test_a_person_may_create_a_document_under_knowledge(self, api: ApiHarness) -> None:
        """knowledge/ is maintained by hand; only the MCP tools are kept out of it."""
        response = await put(api, OVERVIEW, "# 概览\n\n地址对齐。\n")

        assert response.status_code == 201
        assert (api.root.path / OVERVIEW).read_text(encoding="utf-8") == "# 概览\n\n地址对齐。\n"

    async def test_rewriting_an_existing_document_answers_200(self, api: ApiHarness) -> None:
        await put(api, OVERVIEW, "# 概览\n")

        response = await put(api, OVERVIEW, "# 概览\n\n改过了。\n")

        assert response.status_code == 200
        assert response.json()["text"] == "# 概览\n\n改过了。\n"

    async def test_what_was_written_is_searchable_at_once(self, api: ApiHarness) -> None:
        await put(api, OVERVIEW, "# 概览\n\n非对齐搬运会读到脏数据。\n")

        body = (await api.client.get("/api/search", params={"q": "脏数据"})).json()

        assert sorted({hit["path"] for hit in body["documents"]["hits"]}) == [OVERVIEW]

    async def test_it_reaches_git_under_the_name_of_whoever_wrote_it(self, api: ApiHarness) -> None:
        from conftest import commits

        await put(api, OVERVIEW, "# 概览\n", author="dyq")
        await api.go_quiet()

        assert commits(api.root.path) == ["dyq|dyq 沉淀了 1 处改动"]

    async def test_writing_into_the_codebase_is_refused(self, api: ApiHarness) -> None:
        response = await put(api, "codebase/mops/README.md", "偷渡")

        assert response.status_code == 400

    async def test_writing_at_the_root_of_the_knowledge_base_is_refused(
        self, api: ApiHarness
    ) -> None:
        """The root holds the repository's own machinery, starting with .gitignore."""
        response = await put(api, ".gitignore", "learnings/\n")

        assert response.status_code == 400
        assert "learnings/" not in (api.root.path / ".gitignore").read_text(encoding="utf-8")

    async def test_writing_something_that_is_not_a_document_is_refused(
        self, api: ApiHarness
    ) -> None:
        """A browser that can place any file at all is a different power entirely."""
        assert (await put(api, "knowledge/deploy.sh", "rm -rf /")).status_code == 400

    async def test_a_write_without_an_author_is_refused(self, api: ApiHarness) -> None:
        """History is only worth keeping if it says who concluded what."""
        response = await api.client.put(
            f"/api/documents/{OVERVIEW}", json={"text": "# 概览\n", "author": ""}
        )

        assert response.status_code == 422


class TestDeleting:
    async def test_it_removes_the_document_and_forgets_it(self, api: ApiHarness) -> None:
        await put(api, OVERVIEW, "# 概览\n\n脏数据。\n")

        response = await api.client.delete(f"/api/documents/{OVERVIEW}", params={"author": "dyq"})

        assert response.status_code == 204
        assert not (api.root.path / OVERVIEW).exists()
        assert (await api.client.get(f"/api/documents/{OVERVIEW}")).status_code == 404

    async def test_deleting_something_that_is_not_there_is_a_404(self, api: ApiHarness) -> None:
        response = await api.client.delete(
            "/api/documents/knowledge/没有.md", params={"author": "dyq"}
        )

        assert response.status_code == 404


class TestTree:
    async def test_both_document_directories_are_always_roots(self, api: ApiHarness) -> None:
        """An empty knowledge base still has somewhere to put the first document."""
        body = (await api.client.get("/api/tree")).json()

        assert [node["name"] for node in body["directories"]] == ["knowledge", "learnings"]

    async def test_it_nests_documents_under_the_folders_they_live_in(self, api: ApiHarness) -> None:
        await put(api, LEARNING, SOURCE)
        await put(api, OVERVIEW, "# 概览\n")

        body = (await api.client.get("/api/tree")).json()
        knowledge, learnings = body["directories"]

        assert [d["path"] for d in knowledge["documents"]] == [OVERVIEW]
        assert knowledge["directories"] == []
        assert [node["path"] for node in learnings["directories"]] == ["learnings/ascendc"]
        assert [d["path"] for d in learnings["directories"][0]["documents"]] == [LEARNING]

    async def test_a_listed_document_carries_what_a_card_shows(self, api: ApiHarness) -> None:
        await put(api, LEARNING, SOURCE)

        body = (await api.client.get("/api/tree")).json()
        listed = body["directories"][1]["directories"][0]["documents"][0]

        assert listed == {
            "path": LEARNING,
            "title": "对齐要求",
            "summary": "尾块会读到脏数据",
            "tags": ["ascendc", "datacopy"],
        }


class TestTagCloud:
    async def test_it_counts_how_many_documents_carry_each_tag(self, api: ApiHarness) -> None:
        await put(api, LEARNING, SOURCE)
        await put(api, OVERVIEW, "---\ntitle: 概览\ntags: [ascendc]\n---\n\n# 概览\n")

        body = (await api.client.get("/api/tags")).json()

        assert body["tags"] == [
            {"tag": "ascendc", "count": 2},
            {"tag": "datacopy", "count": 1},
        ]

    async def test_a_tag_can_be_opened_into_the_documents_that_carry_it(
        self, api: ApiHarness
    ) -> None:
        await put(api, LEARNING, SOURCE)
        await put(api, OVERVIEW, "---\ntitle: 概览\ntags: [ascendc]\n---\n\n# 概览\n")

        body = (await api.client.get("/api/documents", params={"tag": "datacopy"})).json()

        assert [document["path"] for document in body["documents"]] == [LEARNING]


class TestLinks:
    async def test_it_follows_a_relation_to_the_document_it_cites(self, api: ApiHarness) -> None:
        api.write(OVERVIEW, "---\ntitle: 搬运 API 概览\n---\n\n# 搬运 API 概览\n")
        api.write(
            LEARNING,
            "---\ntitle: 对齐要求\n---\n\n# 对齐要求\n\n"
            "## Relations\n\n- relates_to [[搬运 API 概览]]\n",
        )
        await api.documents.rebuild()

        body = (await api.client.get(f"/api/documents/{LEARNING}/links")).json()

        assert body["origin"] == LEARNING
        assert [document["path"] for document in body["documents"]] == [OVERVIEW]
        assert body["links"][0]["type"] == "relates_to"

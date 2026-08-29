"""Tests for unified search.

The two domains are independent all the way down -- separate indexes, separate upstreams --
so the one thing this endpoint must never do is merge or rank them against each other. It
answers with two groups the page shows side by side, and one of them failing leaves the
other intact.
"""

from api_harness import ApiHarness

LEARNING = "learnings/ascendc/对齐要求.md"


async def distil(api: ApiHarness) -> None:
    api.write(
        LEARNING,
        "---\ntitle: 对齐要求\nsummary: 尾块会读到脏数据\ntags: [ascendc]\n---\n\n"
        "# 对齐要求\n\n## Observations\n\n- [pitfall] 非对齐搬运时会读到脏数据 #ascendc\n",
    )
    await api.indexed(LEARNING)


async def test_it_answers_with_the_two_domains_grouped(api: ApiHarness) -> None:
    await distil(api)

    body = (await api.client.get("/api/search", params={"q": "脏数据"})).json()

    assert body["query"] == "脏数据"
    assert sorted({hit["path"] for hit in body["documents"]["hits"]}) == [LEARNING]
    assert body["code"]["ok"] is True


async def test_a_document_hit_carries_what_progressive_disclosure_needs(api: ApiHarness) -> None:
    """Title, summary and the matching sentence -- never the whole file."""
    await distil(api)

    body = (await api.client.get("/api/search", params={"q": "脏数据"})).json()
    hit = body["documents"]["hits"][0]

    assert hit["kind"] == "observation"
    assert hit["title"] == "对齐要求"
    assert hit["summary"] == "尾块会读到脏数据"
    assert hit["snippet"] == "非对齐搬运时会读到脏数据"
    assert "text" not in hit


async def test_the_code_group_names_its_hits_twice(api: ApiHarness) -> None:
    """A hit has to be readable on screen and still usable as the next question."""
    api.place_repo("mops")
    api.upstream.answers["search_graph"] = {
        "matches": [{"qualified_name": "_srv_kb_mops_src.copy.DataCopyPad", "project": "mops"}]
    }

    body = (await api.client.get("/api/search", params={"q": "DataCopy"})).json()

    (one,) = body["code"]["payload"]["matches"]
    assert one["canonical_qn"] == "_srv_kb_mops_src.copy.DataCopyPad"
    assert one["display_qn"] == "mops.copy.DataCopyPad"


async def test_code_search_can_be_narrowed_to_one_repository_and_switched_to_text(
    api: ApiHarness,
) -> None:
    api.place_repo("mops")

    await api.client.get("/api/search", params={"q": "DataCopy", "mode": "text", "repo": "mops"})

    assert api.upstream.arguments_for("search_code") == [{"query": "DataCopy", "project": "mops"}]


async def test_a_code_upstream_that_is_down_does_not_take_the_documents_with_it(
    api: ApiHarness,
) -> None:
    """Two domains, two failure modes. One page still has half its answer."""
    await distil(api)
    api.place_repo("mops")
    api.upstream.failing.add("search_graph")

    response = await api.client.get("/api/search", params={"q": "脏数据"})
    body = response.json()

    assert response.status_code == 200
    assert sorted({hit["path"] for hit in body["documents"]["hits"]}) == [LEARNING]
    assert body["code"]["ok"] is False
    assert body["code"]["error"]


async def test_an_unknown_repository_is_refused(api: ApiHarness) -> None:
    response = await api.client.get("/api/search", params={"q": "x", "repo": "nope"})

    assert response.status_code == 404


async def test_an_empty_query_is_refused(api: ApiHarness) -> None:
    assert (await api.client.get("/api/search", params={"q": "  "})).status_code == 422

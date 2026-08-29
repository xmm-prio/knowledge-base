"""Nothing a tool runs into may reach the connection as an exception.

opencode has no reconnection logic of any kind: a session that drops stays dropped until a
person restarts it. So every failure -- a refused write, a graph that is not answering, a
binary that died -- comes back as tool content the agent can read and act on, and the
connection stays up.

The wording is the agent's, not the developer's: it says what to do next.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from knowledge_base.code.engine import UnknownRepo
from knowledge_base.code.failures import InvalidQuery, classify
from knowledge_base.code.upstream import UpstreamError
from knowledge_base.docs.graph import GraphUnavailable, NoSuchDocument
from knowledge_base.docs.store import LearningExists, NoSuchLearning
from knowledge_base.layout import OutsideLearnings

logger = logging.getLogger(__name__)

_EXPLANATIONS: tuple[tuple[type[BaseException], str], ...] = (
    (LearningExists, "这条经验已经存在：补充内容请传 target 追加，纠正结论请再传 replaces 修订"),
    (NoSuchLearning, "找不到这条经验或这句观察，先用 search_knowledge 确认 uri 与观察原句"),
    (OutsideLearnings, "只能写 learnings/ 下的经验，knowledge/ 与 codebase/ 由人维护"),
    (NoSuchDocument, "知识库里没有这篇文档，先用 search_knowledge 找到它的 uri"),
    (FileNotFoundError, "知识库里没有这篇文档，先用 search_knowledge 找到它的 uri"),
    (UnknownRepo, "没有这个代码库，用 list_repos 看有哪些"),
    (GraphUnavailable, "文档关系图暂时不可用，检索与读取不受影响"),
)
"""Ordered: the first entry a failure is an instance of explains it."""

UPSTREAM_FAILED = "上游暂时没能给出结果，可以稍后重试或换一种问法"


class ToolFailures(Middleware):
    """Turns every failure into an answer, in the vocabulary the tools are described in."""

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        try:
            return await call_next(context)
        except Exception as failure:
            raise ToolError(explain(failure)) from failure


def explain(failure: BaseException) -> str:
    """What an agent should be told about a failure, and what it can do about it.

    A failure the tools raise on purpose already speaks to the agent. Everything else is a
    domain refusal -- possibly already wrapped by the framework, hence the cause -- or
    something nobody foresaw, which is logged here and summarized there.
    """
    for candidate in (failure, failure.__cause__):
        if candidate is None:
            continue
        for kind, explanation in _EXPLANATIONS:
            if isinstance(candidate, kind):
                return f"{explanation}（{candidate}）"
        if isinstance(candidate, UpstreamError | InvalidQuery):
            # The code domain classifies its own failures, so an agent and a browser are told
            # the same thing about the same failure and quote the same diagnostic for it.
            trouble = classify(candidate)
            return f"{trouble.message}（诊断 {trouble.diagnostic}）"
    if isinstance(failure, ToolError):
        return str(failure)
    logger.error("Tool call failed", exc_info=failure)
    return f"{UPSTREAM_FAILED}（{failure}）"

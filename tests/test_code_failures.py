"""Tests for classifying what went wrong with a code question.

The distinction being defended: a member who mistyped a pattern must not be told to go and
find an operator, and an operator whose upstream is down must not be told it was a typo.
"""

import logging

from knowledge_base.code.failures import FailureKind, InvalidQuery, classify
from knowledge_base.code.upstream import UpstreamFailed, UpstreamRefused, UpstreamUnavailable


class TestWhoHasToAct:
    def test_a_query_the_gateway_will_not_send_is_the_members_to_fix(self) -> None:
        assert classify(InvalidQuery("这不是一个有效的正则")).kind == FailureKind.BAD_REQUEST

    def test_a_missing_upstream_is_not_the_members_problem(self) -> None:
        assert classify(UpstreamUnavailable("the binary is gone")).kind == FailureKind.UNAVAILABLE

    def test_an_upstream_that_ran_it_and_said_no_is_its_own_kind(self) -> None:
        assert classify(UpstreamRefused("pattern is required")).kind == FailureKind.REFUSED

    def test_anything_unrecognised_is_ours_until_proven_otherwise(self) -> None:
        assert classify(RuntimeError("boom")).kind == FailureKind.INTERNAL

    def test_a_plain_bad_value_is_still_a_bad_request(self) -> None:
        assert classify(ValueError("depth must be 1..5")).kind == FailureKind.BAD_REQUEST

    def test_an_upstream_failure_with_no_finer_reading_is_not_called_a_typo(self) -> None:
        assert classify(UpstreamFailed("unparseable frame")).kind == FailureKind.INTERNAL


class TestWhatIsShown:
    def test_the_message_says_what_happened_in_chinese(self) -> None:
        trouble = classify(InvalidQuery("检索词不能为空"))

        assert "检索词不能为空" in trouble.message
        assert "上游" not in trouble.message

    def test_a_failure_can_be_quoted_to_an_operator(self, caplog) -> None:
        """The identifier on screen and the one in the log are the same by construction."""
        with caplog.at_level(logging.WARNING):
            trouble = classify(UpstreamUnavailable("the binary is gone"))

        assert trouble.diagnostic
        assert trouble.diagnostic in caplog.text

    def test_two_failures_are_not_confused_for_one(self) -> None:
        first = classify(UpstreamUnavailable("gone"))
        second = classify(UpstreamUnavailable("gone"))

        assert first.diagnostic != second.diagnostic

    def test_what_a_member_typed_is_not_written_to_the_log(self, caplog) -> None:
        """Search terms are the member's, and the log is not the place for them."""
        with caplog.at_level(logging.WARNING):
            classify(UpstreamRefused("upstream said no"))

        assert "code request" in caplog.text

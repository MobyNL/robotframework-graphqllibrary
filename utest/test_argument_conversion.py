"""Argument conversion, driven through Robot Framework's own parser.

These annotations are the ones most likely to break across Robot Framework versions, and a
break shows up as a keyword that cannot be called from a suite while every unit test that
calls it as a Python method still passes. Driving the parser is what catches that without a
full Robot Framework run.
"""

import pytest
from robot.running.arguments import PythonArgumentParser

from GraphQLLibrary.keywords.connection import ConnectionKeywords
from GraphQLLibrary.keywords.query import QueryKeywords


def convert(method, positional, named):
    spec = PythonArgumentParser(method.__name__).parse(method)
    return spec.convert(positional, named)


class TestQueryArguments:
    def test_a_query_given_as_a_list_stays_a_list(self):
        """The inline form: Robot Framework collapses runs of spaces inside one cell."""
        positional, _ = convert(QueryKeywords.execute_query, [["query {", "}"]], [])
        assert positional == [["query {", "}"]]

    def test_a_query_given_as_text_stays_text(self):
        positional, _ = convert(QueryKeywords.execute_query, ["{ ping }"], [])
        assert positional == ["{ ping }"]

    def test_variables_are_converted_from_a_dictionary_literal(self):
        _, named = convert(QueryKeywords.execute_query, ["{ ping }"], [("variables", '{"id": "1"}')])
        assert named == [("variables", {"id": "1"})]

    def test_expect_errors_is_converted_to_a_boolean(self):
        _, named = convert(QueryKeywords.execute_query, ["{ ping }"], [("expect_errors", "True")])
        assert named == [("expect_errors", True)]

    def test_an_assertion_operator_is_converted_from_its_symbol(self):
        _, named = convert(
            QueryKeywords.check_query_result, ["{ ping }", "ping"], [("assertion_operator", "==")]
        )
        assert named[0][1].name == "equal"


class TestConnectionArguments:
    def test_headers_are_converted_from_a_dictionary_literal(self):
        _, named = convert(ConnectionKeywords.create_graphql_session, ["url"], [("headers", '{"A": "b"}')])
        assert named == [("headers", {"A": "b"})]

    def test_verify_and_timeout_are_converted(self):
        _, named = convert(
            ConnectionKeywords.create_graphql_session, ["url"], [("verify", "False"), ("timeout", "5")]
        )
        assert named == [("verify", False), ("timeout", 5)]

    def test_a_token_is_accepted_as_plain_text(self):
        _, named = convert(ConnectionKeywords.create_graphql_session, ["url"], [("token", "abc")])
        assert named == [("token", "abc")]


class TestSecretCredentials:
    """Robot Framework 7.4 and later, where a Secret keeps a token out of the log."""

    def test_a_secret_is_revealed_before_it_is_used(self):
        secret_type = pytest.importorskip("robot.api.types", reason="Robot Framework 7.4 and later")
        if not hasattr(secret_type, "Secret"):
            pytest.skip("Robot Framework below 7.4 has no Secret type")
        from GraphQLLibrary._types import reveal

        assert reveal(secret_type.Secret("abc")) == "abc"

    def test_plain_text_passes_through_reveal(self):
        from GraphQLLibrary._types import reveal

        assert reveal("abc") == "abc"
        assert reveal(None) is None

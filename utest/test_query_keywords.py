import pytest
from assertionengine import AssertionOperator

from GraphQLLibrary import GraphQLLibrary, GraphQLResponseError
from utest.conftest import reply, sent_body, sent_query, URL

QUERY = "{ user { name } }"
# gql reprints the document it parsed, so what reaches the wire is the query in the standard
# layout rather than the text a suite wrote.
NORMALISED = "{\n  user {\n    name\n  }\n}"


class TestErrorHandling:
    """The reason the library exists: a failed operation answers HTTP 200."""

    def test_errors_in_a_two_hundred_response_fail_the_keyword(self, library, mocked_responses):
        reply(mocked_responses, data=None, errors=[{"message": "Not authenticated"}])
        with pytest.raises(GraphQLResponseError, match="Not authenticated"):
            library.execute_query(QUERY)

    def test_expect_errors_returns_the_response_instead_of_failing(self, library, mocked_responses):
        reply(mocked_responses, data=None, errors=[{"message": "Not authenticated"}])
        response = library.execute_query(QUERY, expect_errors=True)
        assert response.errors[0]["message"] == "Not authenticated"

    def test_partial_data_fails_by_default(self, library, mocked_responses):
        """Data alongside errors is the case a status code hides most thoroughly."""
        reply(
            mocked_responses,
            data={"user": {"name": "Alice", "avatar": None}},
            errors=[{"message": "Denied", "path": ["user", "avatar"]}],
        )
        with pytest.raises(GraphQLResponseError):
            library.execute_query(QUERY)

    def test_the_failure_message_names_the_path_and_the_code(self, library, mocked_responses):
        reply(
            mocked_responses,
            errors=[{"message": "Denied", "path": ["user", "avatar"], "extensions": {"code": "FORBIDDEN"}}],
        )
        with pytest.raises(GraphQLResponseError) as failure:
            library.execute_query(QUERY)
        assert "at path user.avatar" in str(failure.value)
        assert "code FORBIDDEN" in str(failure.value)

    def test_the_exception_carries_the_whole_response(self, library, mocked_responses):
        reply(mocked_responses, data={"user": None}, errors=[{"message": "Denied"}], extensions={"cost": 3})
        with pytest.raises(GraphQLResponseError) as failure:
            library.execute_query(QUERY)
        assert failure.value.data == {"user": None}
        assert failure.value.errors[0]["message"] == "Denied"

    def test_an_empty_errors_array_is_not_a_failure(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {"name": "Alice"}}, errors=[])
        assert library.execute_query(QUERY).data.user.name == "Alice"


class TestExecuting:
    def test_data_is_reachable_with_a_dot(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        assert library.execute_query(QUERY).data.user.name == "Alice"

    def test_the_three_top_level_fields_are_always_present(self, library, mocked_responses):
        reply(mocked_responses, data={"user": None})
        response = library.execute_query(QUERY)
        assert response.errors == [] and response.extensions == {}

    def test_variables_are_sent(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.execute_query("query Q($id: ID!) { user(id: $id) { name } }", variables={"id": "1"})
        assert sent_body(mocked_responses)["variables"] == {"id": "1"}

    def test_extensions_are_returned(self, library, mocked_responses):
        reply(mocked_responses, data={"ping": "pong"}, extensions={"cost": {"actual": 7}})
        assert library.execute_query("{ ping }").extensions.cost.actual == 7

    def test_a_mutation_is_sent_by_the_mutation_keyword(self, library, mocked_responses):
        reply(mocked_responses, data={"createUser": {"id": "1"}})
        response = library.execute_mutation("mutation { createUser { id } }")
        assert response.data.createUser.id == "1"

    def test_a_query_passed_to_the_mutation_keyword_is_refused(self, library):
        with pytest.raises(ValueError, match="but a mutation was expected"):
            library.execute_mutation(QUERY)

    def test_a_mutation_passed_to_the_query_keyword_is_refused(self, library):
        with pytest.raises(ValueError, match="but a query was expected"):
            library.execute_query("mutation { createUser { id } }")

    def test_a_syntax_error_names_the_position(self, library):
        with pytest.raises(ValueError, match=r"1:16"):
            library.execute_query("{ user { name }")

    def test_executing_without_a_session_says_how_to_open_one(self, library_without_session, mocked_responses):
        reply(mocked_responses, data={})
        with pytest.raises(KeyError, match="Create Graphql Session"):
            library_without_session.execute_query(QUERY)


class TestQuerySources:
    """All three ways of giving a query, because none alone covers how suites are written."""

    def test_a_query_can_be_given_as_text(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.execute_query(QUERY)
        assert sent_query(mocked_responses) == NORMALISED

    def test_a_query_can_be_given_as_a_list_of_lines(self, library, mocked_responses):
        """Robot Framework collapses runs of spaces in a cell, so a list is the inline form."""
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.execute_query(["query {", "  user {", "    name", "  }", "}"])
        assert sent_query(mocked_responses) == NORMALISED

    def test_a_query_can_be_given_as_a_file_path(self, library, mocked_responses, tmp_path):
        path = tmp_path / "get_user.graphql"
        path.write_text(QUERY, encoding="utf-8")
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.execute_query(str(path))
        assert sent_query(mocked_responses) == NORMALISED

    def test_a_query_can_be_given_as_a_file_name_under_the_query_path(self, mocked_responses, tmp_path):
        (tmp_path / "get_user.graphql").write_text(QUERY, encoding="utf-8")
        # Schema validation off for the same reason the shared fixture has it off: it would
        # put an introspection request in front of the one this test reads back.
        library = GraphQLLibrary(query_path=str(tmp_path), validate_against_schema=False)
        library.create_graphql_session(URL)
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.execute_query("get_user.graphql")
        assert sent_query(mocked_responses) == NORMALISED
        library.delete_all_graphql_sessions()

    def test_a_missing_query_file_is_reported_as_such(self, library):
        """Sending the name would produce a server-side syntax error that hides the cause."""
        with pytest.raises(ValueError, match="was not found"):
            library.execute_query("nope.graphql")

    def test_load_query_reads_a_file(self, library, tmp_path):
        (tmp_path / "get_user.graphql").write_text(QUERY, encoding="utf-8")
        assert library.load_query(str(tmp_path / "get_user.graphql")) == QUERY

    def test_load_query_refuses_something_that_is_not_a_query_file(self, library):
        with pytest.raises(ValueError, match="not a query file"):
            library.load_query("get_user.txt")

    def test_a_query_text_ending_in_a_suffix_like_word_is_not_treated_as_a_file(self, library, mocked_responses):
        reply(mocked_responses, data={"files": []})
        library.execute_query("{\n  files\n}")
        assert "files" in sent_query(mocked_responses)


class TestNamedOperations:
    DOCUMENT = "query GetUser { user { name } }\nquery GetTeam { team { name } }"

    def test_an_operation_is_chosen_by_name(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.execute_query(self.DOCUMENT, operation_name="GetUser")
        assert sent_body(mocked_responses)["operationName"] == "GetUser"

    def test_a_document_with_several_operations_needs_a_name(self, library):
        with pytest.raises(ValueError, match="GetUser, GetTeam"):
            library.execute_query(self.DOCUMENT)

    def test_an_unknown_operation_name_lists_the_available_ones(self, library):
        with pytest.raises(ValueError, match="Available operations: GetUser, GetTeam"):
            library.execute_query(self.DOCUMENT, operation_name="GetNothing")

    def test_get_query_operations_lists_the_names(self, library):
        assert library.get_query_operations(self.DOCUMENT) == ["GetUser", "GetTeam"]


class TestValidation:
    def test_validate_query_returns_the_text(self, library):
        assert library.validate_query(QUERY) == QUERY

    def test_validate_query_fails_on_a_syntax_error(self, library):
        with pytest.raises(ValueError, match="could not be parsed"):
            library.validate_query("{ user { name }")

    def test_validation_can_be_switched_off(self, mocked_responses):
        """Switching it off drops this library's checks, not gql's own parse."""
        library = GraphQLLibrary(validate_queries=False)
        library.create_graphql_session(URL)
        reply(mocked_responses, data={"createUser": {"id": "1"}})
        library.execute_query("mutation { createUser { id } }")  # no operation type check
        assert sent_query(mocked_responses).startswith("mutation")
        library.delete_all_graphql_sessions()

    def test_gql_still_refuses_a_query_it_cannot_parse(self, mocked_responses):
        """The upstream parse cannot be skipped, so the message is gql's rather than ours."""
        library = GraphQLLibrary(validate_queries=False)
        library.create_graphql_session(URL)
        with pytest.raises(Exception, match="Syntax Error"):
            library.execute_query("{ user { name }")
        library.delete_all_graphql_sessions()


class TestRawRequest:
    def test_a_raw_request_returns_errors_without_failing(self, library, mocked_responses):
        reply(mocked_responses, data=None, errors=[{"message": "Denied"}])
        response = library.execute_raw_request(QUERY)
        assert response.errors[0]["message"] == "Denied"

    def test_a_raw_request_sends_an_operation_type_the_other_keywords_refuse(self, library, mocked_responses):
        reply(mocked_responses, data={"ticks": 1})
        library.execute_raw_request("subscription { ticks }")
        assert sent_query(mocked_responses).startswith("subscription")


class TestCheckQueryResult:
    def test_it_passes_when_the_assertion_holds(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.check_query_result(QUERY, "user.name", AssertionOperator["=="], "Alice")

    def test_it_fails_naming_the_field_and_both_values(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {"name": "Bob"}})
        with pytest.raises(AssertionError, match="user.name"):
            library.check_query_result(QUERY, "user.name", AssertionOperator["=="], "Alice")

    def test_it_re_sends_the_query_until_the_assertion_holds(self, library, mocked_responses):
        """The point of retrying: the read model catches up between attempts."""
        reply(mocked_responses, data={"user": {"name": "Bob"}})
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.check_query_result(QUERY, "user.name", AssertionOperator["=="], "Alice", retry_timeout="5s", retry_pause="0s")
        assert len(mocked_responses.calls) == 2

    def test_errors_are_retried_rather_than_raised(self, library, mocked_responses):
        reply(mocked_responses, data=None, errors=[{"message": "Service starting"}])
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.check_query_result(QUERY, "user.name", AssertionOperator["=="], "Alice", retry_timeout="5s", retry_pause="0s")
        assert len(mocked_responses.calls) == 2

    def test_a_field_that_is_not_there_yet_is_retried(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {}})
        reply(mocked_responses, data={"user": {"name": "Alice"}})
        library.check_query_result(QUERY, "user.name", AssertionOperator["=="], "Alice", retry_timeout="5s", retry_pause="0s")
        assert len(mocked_responses.calls) == 2

    def test_it_sends_once_when_no_timeout_is_given(self, library, mocked_responses):
        reply(mocked_responses, data={"user": {"name": "Bob"}})
        with pytest.raises(AssertionError):
            library.check_query_result(QUERY, "user.name", AssertionOperator["=="], "Alice")
        assert len(mocked_responses.calls) == 1

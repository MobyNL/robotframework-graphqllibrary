import pytest
from assertionengine import AssertionOperator

from GraphQLLibrary.keywords.response import ResponseKeywords
from GraphQLLibrary.response import build_response

EQ = AssertionOperator["=="]
CONTAINS = AssertionOperator["contains"]


@pytest.fixture
def keywords():
    return ResponseKeywords()


@pytest.fixture
def response():
    return build_response(
        data={"user": {"name": "Alice", "avatar": None, "friends": [{"name": "Bob"}, {"name": "Carol"}]}},
        errors=[
            {"message": "Denied", "path": ["user", "avatar"], "extensions": {"code": "FORBIDDEN"}},
            {"message": "Slow down", "extensions": {"code": "THROTTLED"}},
        ],
        extensions={"cost": {"actual": 7}},
    )


class TestReadingData:
    def test_a_field_is_read_by_path(self, keywords, response):
        assert keywords.get_graphql_data(response, "user.name") == "Alice"

    def test_a_list_position_is_a_number_in_the_path(self, keywords, response):
        assert keywords.get_graphql_data(response, "user.friends.1.name") == "Carol"

    def test_the_whole_data_field_is_returned_without_a_path(self, keywords, response):
        assert keywords.get_graphql_data(response)["user"]["name"] == "Alice"

    def test_a_value_can_be_asserted_in_the_same_step(self, keywords, response):
        keywords.get_graphql_data(response, "user.name", EQ, "Alice")

    def test_a_failing_assertion_names_the_path(self, keywords, response):
        with pytest.raises(AssertionError, match="user.name"):
            keywords.get_graphql_data(response, "user.name", EQ, "Bob")

    def test_a_missing_field_reports_what_was_available(self, keywords, response):
        """In GraphQL a missing field usually means the query did not ask for it."""
        with pytest.raises(ValueError, match="Available: name, avatar, friends"):
            keywords.get_graphql_data(response, "user.email")

    def test_reading_through_a_null_says_so(self, keywords, response):
        with pytest.raises(ValueError, match="is null"):
            keywords.get_graphql_data(response, "user.avatar.url")

    def test_an_index_beyond_the_end_is_reported(self, keywords, response):
        with pytest.raises(ValueError, match="out of range"):
            keywords.get_graphql_data(response, "user.friends.9.name")

    def test_a_word_where_an_index_belongs_is_reported(self, keywords, response):
        with pytest.raises(ValueError, match="has to be a number"):
            keywords.get_graphql_data(response, "user.friends.first.name")


class TestReadingErrors:
    def test_the_errors_array_is_returned(self, keywords, response):
        assert len(keywords.get_graphql_errors(response)) == 2

    def test_messages_are_returned(self, keywords, response):
        assert keywords.get_graphql_error_messages(response) == ["Denied", "Slow down"]

    def test_codes_are_returned(self, keywords, response):
        assert keywords.get_graphql_error_codes(response) == ["FORBIDDEN", "THROTTLED"]

    def test_codes_can_be_asserted_on(self, keywords, response):
        keywords.get_graphql_error_codes(response, CONTAINS, "THROTTLED")

    def test_an_error_without_a_code_is_skipped(self, keywords):
        response = build_response(None, [{"message": "Boom"}], None)
        assert keywords.get_graphql_error_codes(response) == []

    def test_a_response_without_errors_gives_an_empty_list(self, keywords):
        assert keywords.get_graphql_errors(build_response({"ping": "pong"}, None, None)) == []

    def test_something_that_is_not_a_response_is_reported(self, keywords):
        with pytest.raises(ValueError, match="Pass the value returned by"):
            keywords.get_graphql_errors("Alice")


class TestReadingExtensions:
    def test_extensions_are_read_by_path(self, keywords, response):
        assert keywords.get_graphql_extensions(response, "cost.actual") == 7

    def test_extensions_can_be_asserted_on(self, keywords, response):
        keywords.get_graphql_extensions(response, "cost.actual", EQ, 7)


class TestAsserting:
    def test_no_errors_passes_on_a_clean_response(self, keywords):
        keywords.response_should_have_no_errors(build_response({"ping": "pong"}, None, None))

    def test_no_errors_lists_the_errors_it_found(self, keywords, response):
        with pytest.raises(AssertionError, match="code FORBIDDEN"):
            keywords.response_should_have_no_errors(response)

    def test_should_have_errors_passes(self, keywords, response):
        keywords.response_should_have_errors(response)

    def test_should_have_errors_can_check_the_count(self, keywords, response):
        keywords.response_should_have_errors(response, count=2)
        with pytest.raises(AssertionError, match="Expected 1 GraphQL error"):
            keywords.response_should_have_errors(response, count=1)

    def test_should_have_errors_fails_on_a_clean_response(self, keywords):
        with pytest.raises(AssertionError, match="carried none"):
            keywords.response_should_have_errors(build_response({"ping": "pong"}, None, None))

    def test_an_error_is_found_by_the_field_it_happened_at(self, keywords, response):
        assert keywords.error_should_exist_at_path(response, "user.avatar")["message"] == "Denied"

    def test_an_error_can_be_matched_on_its_code(self, keywords, response):
        keywords.error_should_exist_at_path(response, "user.avatar", code="FORBIDDEN")

    def test_a_wrong_code_at_the_right_path_fails(self, keywords, response):
        with pytest.raises(AssertionError, match="none of them matched"):
            keywords.error_should_exist_at_path(response, "user.avatar", code="THROTTLED")

    def test_a_path_with_no_error_lists_the_paths_that_had_one(self, keywords, response):
        with pytest.raises(AssertionError, match="user.avatar"):
            keywords.error_should_exist_at_path(response, "user.name")

    def test_an_error_can_be_matched_on_its_message(self, keywords, response):
        keywords.error_should_exist_at_path(response, "user.avatar", message_contains="Deni")

    def test_partial_data_is_recognised(self, keywords, response):
        keywords.response_should_have_partial_data(response)

    def test_partial_data_fails_when_data_is_null(self, keywords):
        with pytest.raises(AssertionError, match="'data' is null"):
            keywords.response_should_have_partial_data(build_response(None, [{"message": "Boom"}], None))

    def test_partial_data_fails_without_errors(self, keywords):
        with pytest.raises(AssertionError, match="no errors"):
            keywords.response_should_have_partial_data(build_response({"ping": "pong"}, None, None))


class TestErrorNormalisation:
    def test_a_graphql_core_error_object_is_turned_into_the_spec_shape(self, keywords):
        """Results parsed against a schema carry objects rather than dictionaries."""
        from graphql import GraphQLError

        response = build_response(None, [GraphQLError("Boom")], None)
        assert response.errors[0]["message"] == "Boom"

    def test_an_error_reported_as_text_still_has_a_message(self, keywords):
        assert build_response(None, ["Boom"], None).errors[0] == {"message": "Boom"}

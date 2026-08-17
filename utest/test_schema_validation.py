"""Tests for the schema check that is on by default.

The shared ``library`` fixture switches it off, because it puts an introspection request in
front of every query. These use ``validating_library``, which is configured the way a user who
passes nothing gets it.
"""

import pytest

from GraphQLLibrary import GraphQLLibrary
from GraphQLLibrary.keywords.query import MAX_SCHEMA_ATTEMPTS
from GraphQLLibrary.schema import SchemaUnavailable
from utest.conftest import introspection, reply, sent_query, URL


def open_session(library, mocked_responses, sdl=None):
    """Open a session and queue the introspection reply its first query will ask for."""
    library.create_graphql_session(URL)
    reply(mocked_responses, introspection(sdl) if sdl else introspection())


class TestAValidQueryIsUnaffected:
    def test_it_is_sent_after_the_schema_was_read(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        reply(mocked_responses, {"ping": "pong"})
        response = validating_library.execute_query("{ ping }")
        assert response.data["ping"] == "pong"

    def test_the_introspection_goes_first_and_the_query_second(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        reply(mocked_responses, {"ping": "pong"})
        validating_library.execute_query("{ ping }")
        assert "IntrospectionQuery" in sent_query(mocked_responses, 0)
        assert "ping" in sent_query(mocked_responses, 1)


class TestInvalidQueriesAreCaughtBeforeSending:
    def test_an_unknown_root_field(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        with pytest.raises(ValueError, match="Cannot query field 'nope' on type 'Query'"):
            validating_library.execute_query("{ nope }")

    def test_an_unknown_field_on_a_type_suggests_the_right_one(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        with pytest.raises(ValueError, match="Did you mean 'name'"):
            validating_library.execute_query('{ user(id: "1") { nickname } }')

    def test_a_missing_required_argument(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        with pytest.raises(ValueError, match="argument 'id' of type 'ID!' is required"):
            validating_library.execute_query("{ user { name } }")

    def test_nothing_is_sent_when_the_query_is_invalid(self, validating_library, mocked_responses):
        """Only the introspection request should have gone out."""
        open_session(validating_library, mocked_responses)
        with pytest.raises(ValueError):
            validating_library.execute_query("{ nope }")
        assert len(mocked_responses.calls) == 1

    def test_every_problem_is_reported_at_once(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        with pytest.raises(ValueError, match="2 problem"):
            validating_library.execute_query("{ nope alsoNope }")

    def test_a_mutation_is_checked_too(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        with pytest.raises(ValueError, match="Cannot query field 'nickname'"):
            validating_library.execute_mutation('mutation { createUser(name: "Ada") { nickname } }')


class TestTheSchemaIsReadOnce:
    def test_several_queries_share_one_introspection(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        for _ in range(3):
            reply(mocked_responses, {"ping": "pong"})
        for _ in range(3):
            validating_library.execute_query("{ ping }")
        introspections = [
            call for call in mocked_responses.calls if "IntrospectionQuery" in (call.request.body or b"").decode()
        ]
        assert len(introspections) == 1

    def test_refreshing_causes_exactly_one_more(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        reply(mocked_responses, {"ping": "pong"})
        validating_library.execute_query("{ ping }")
        validating_library.refresh_graphql_schema()
        reply(mocked_responses, introspection())
        reply(mocked_responses, {"ping": "pong"})
        validating_library.execute_query("{ ping }")
        introspections = [
            call for call in mocked_responses.calls if "IntrospectionQuery" in (call.request.body or b"").decode()
        ]
        assert len(introspections) == 2


class TestIntrospectionUnavailableDegrades:
    def test_the_query_is_still_sent_when_the_schema_cannot_be_read(self, validating_library, mocked_responses):
        """A server with introspection off is a normal thing to test against."""
        validating_library.create_graphql_session(URL)
        reply(mocked_responses, None, errors=[{"message": "GraphQL introspection is not allowed"}])
        reply(mocked_responses, {"ping": "pong"})
        response = validating_library.execute_query("{ ping }")
        assert response.data["ping"] == "pong"

    def test_it_gives_up_after_a_bounded_number_of_attempts(self, validating_library, mocked_responses):
        """Twice, not once and not forever.

        Once would be wrong because the first query on a session is often the login, and a
        schema behind authentication is unreadable until that has run. Forever would mean a
        failing request in front of every query for the rest of the suite.
        """
        validating_library.create_graphql_session(URL)
        refused = [{"message": "GraphQL introspection is not allowed"}]
        # Replies are consumed in order, so this queues exactly what six queries will ask for:
        # an introspection attempt before each of the first two, and nothing before the rest.
        queries = 6
        for _ in range(MAX_SCHEMA_ATTEMPTS):
            reply(mocked_responses, None, errors=refused)
            reply(mocked_responses, {"ping": "pong"})
        for _ in range(queries - MAX_SCHEMA_ATTEMPTS):
            reply(mocked_responses, {"ping": "pong"})
        for _ in range(queries):
            validating_library.execute_query("{ ping }")
        introspections = [
            call for call in mocked_responses.calls if "IntrospectionQuery" in (call.request.body or b"").decode()
        ]
        assert len(introspections) == MAX_SCHEMA_ATTEMPTS

    def test_a_schema_behind_authentication_is_picked_up_after_the_login(self, validating_library, mocked_responses):
        """The case a real endpoint showed: introspection 401s before the login mutation runs.

        Latching on that first failure left validation off for the whole session, which is
        exactly where it was wanted. The retry after a successful operation is what fixes it.
        """
        validating_library.create_graphql_session(URL)
        # First query is the login: introspection is refused, the login itself succeeds.
        reply(mocked_responses, None, errors=[{"message": "Unauthorized"}])
        reply(mocked_responses, {"login": "a-token"})
        validating_library.execute_mutation("mutation { login }")

        # Now authenticated, so the retry gets a schema and the next query is checked against it.
        reply(mocked_responses, introspection())
        with pytest.raises(ValueError, match="Cannot query field 'nope'"):
            validating_library.execute_query("{ nope }")

    def test_the_explicit_keyword_fails_instead(self, validating_library, mocked_responses):
        """Asked for a schema check directly, silence would be the wrong answer."""
        validating_library.create_graphql_session(URL)
        reply(mocked_responses, None, errors=[{"message": "GraphQL introspection is not allowed"}])
        with pytest.raises(SchemaUnavailable, match="disable introspection"):
            validating_library.query_should_be_valid_against_schema("{ ping }")


class TestSwitchingItOff:
    def test_nothing_is_introspected_when_it_is_off(self, library, mocked_responses):
        reply(mocked_responses, {"ping": "pong"})
        library.execute_query("{ ping }")
        assert len(mocked_responses.calls) == 1
        assert "IntrospectionQuery" not in sent_query(mocked_responses, 0)

    def test_an_invalid_query_is_sent_when_it_is_off(self, library, mocked_responses):
        """Off means off: the server gets to reject it instead."""
        reply(mocked_responses, None, errors=[{"message": "Cannot query field 'nope'"}])
        with pytest.raises(Exception, match="Cannot query field"):
            library.execute_query("{ nope }")

    def test_validate_queries_false_also_skips_the_schema_check(self, mocked_responses):
        """That flag already means "do no local checking", so it covers this too."""
        library = GraphQLLibrary(validate_queries=False)
        library.create_graphql_session(URL)
        reply(mocked_responses, {"nope": None})
        library.execute_query("{ nope }")
        assert len(mocked_responses.calls) == 1
        library.delete_all_graphql_sessions()


class TestExecuteRawRequestIsNotValidated:
    def test_it_sends_an_invalid_query_untouched(self, validating_library, mocked_responses):
        """Documented as unchecked, so the schema must not get in the way."""
        validating_library.create_graphql_session(URL)
        reply(mocked_responses, None, errors=[{"message": "Cannot query field 'nope'"}])
        response = validating_library.execute_raw_request("{ nope }")
        assert response.errors
        assert len(mocked_responses.calls) == 1


class TestTheExplicitKeyword:
    def test_a_valid_query_passes_without_being_sent(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        validating_library.query_should_be_valid_against_schema('{ user(id: "1") { name } }')
        assert len(mocked_responses.calls) == 1

    def test_an_invalid_query_raises(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        with pytest.raises(ValueError, match="does not match the schema"):
            validating_library.query_should_be_valid_against_schema("{ nope }")

    def test_it_reports_the_line_and_column(self, validating_library, mocked_responses):
        open_session(validating_library, mocked_responses)
        with pytest.raises(ValueError, match=r"line \d+, column \d+"):
            validating_library.query_should_be_valid_against_schema("{ nope }")

    def test_it_works_when_automatic_validation_is_off(self, library, mocked_responses):
        """The reason it exists: a suite that turned the automatic check off still wants this."""
        reply(mocked_responses, introspection())
        with pytest.raises(ValueError, match="does not match the schema"):
            library.query_should_be_valid_against_schema("{ nope }")

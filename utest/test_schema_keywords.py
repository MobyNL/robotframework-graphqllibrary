import pytest
from assertionengine import AssertionOperator

from GraphQLLibrary.schema import SchemaUnavailable
from utest.conftest import introspection, reply, sent_query, URL

READ_ONLY_SDL = """
type Query {
    ping: String!
}
"""

NOTHING_DEPRECATED_SDL = """
type User {
    id: ID!
}

type Query {
    user(id: ID!): User
}
"""


class TestReadingTheSchema:
    def test_queries_are_listed(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        assert library.get_schema_queries() == ["ping", "user"]

    def test_mutations_are_listed(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        assert library.get_schema_mutations() == ["createUser"]

    def test_a_read_only_schema_has_no_mutations(self, library, mocked_responses):
        reply(mocked_responses, introspection(READ_ONLY_SDL))
        assert library.get_schema_mutations() == []

    def test_deprecated_fields_are_reported_as_type_dot_field(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        assert library.get_deprecated_fields() == ["User.email"]

    def test_introspection_types_are_not_reported(self, library, mocked_responses):
        """Every server carries __Type and friends; they are not the schema being asked about."""
        reply(mocked_responses, introspection())
        assert not any(field.startswith("__") for field in library.get_deprecated_fields())

    def test_nothing_deprecated_is_an_empty_list(self, library, mocked_responses):
        reply(mocked_responses, introspection(NOTHING_DEPRECATED_SDL))
        assert library.get_deprecated_fields() == []

    def test_deprecated_fields_are_requested_from_the_server(self, library, mocked_responses):
        """Without includeDeprecated the server omits them, so the list would always be empty."""
        reply(mocked_responses, introspection())
        library.get_deprecated_fields()
        assert "includeDeprecated: true" in sent_query(mocked_responses)


class TestSchemaCaching:
    def test_the_schema_is_introspected_once_for_several_keywords(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        library.get_schema_queries()
        library.get_schema_mutations()
        library.get_deprecated_fields()
        assert len(mocked_responses.calls) == 1

    def test_refreshing_makes_the_next_call_introspect_again(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        reply(mocked_responses, introspection())
        library.get_schema_queries()
        library.refresh_graphql_schema()
        library.get_schema_queries()
        assert len(mocked_responses.calls) == 2

    def test_two_aliases_on_one_endpoint_share_the_schema(self, library, mocked_responses):
        """The schema is cached on the same key as the client, which aliases already share."""
        reply(mocked_responses, introspection())
        library.create_graphql_session(URL, alias="second")
        library.get_schema_queries(alias="default")
        library.get_schema_queries(alias="second")
        assert len(mocked_responses.calls) == 1


class TestAssertionOperators:
    def test_queries_take_an_operator(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        library.get_schema_queries(AssertionOperator["contains"], "user")

    def test_a_failing_assertion_names_the_subject(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        with pytest.raises(AssertionError, match="GraphQL schema queries"):
            library.get_schema_queries(AssertionOperator["contains"], "absent")

    def test_deprecated_fields_take_an_operator(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        library.get_deprecated_fields(AssertionOperator["=="], ["User.email"])


class TestFieldShouldNotBeDeprecated:
    def test_a_current_field_passes(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        library.field_should_not_be_deprecated("User.id")

    def test_a_deprecated_field_fails_with_the_reason(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        with pytest.raises(AssertionError, match="Use contact instead."):
            library.field_should_not_be_deprecated("User.email")

    def test_an_unknown_type_is_a_bad_call_not_a_failed_check(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        with pytest.raises(ValueError, match="no type 'Absent'"):
            library.field_should_not_be_deprecated("Absent.id")

    def test_an_unknown_field_lists_the_fields_that_exist(self, library, mocked_responses):
        reply(mocked_responses, introspection())
        with pytest.raises(ValueError, match="has no field 'absent'.*email, id, name"):
            library.field_should_not_be_deprecated("User.absent")

    def test_a_value_that_is_not_type_dot_field_is_refused(self, library, mocked_responses):
        with pytest.raises(ValueError, match="Type.field"):
            library.field_should_not_be_deprecated("email")


class TestIntrospectionUnavailable:
    def test_a_disabled_schema_says_so(self, library, mocked_responses):
        """Apollo reports a disabled introspection as an ordinary GraphQL error on a 200."""
        reply(mocked_responses, None, errors=[{"message": "GraphQL introspection is not allowed"}])
        with pytest.raises(SchemaUnavailable, match="disable introspection"):
            library.get_schema_queries()

    def test_the_servers_own_message_is_kept(self, library, mocked_responses):
        reply(mocked_responses, None, errors=[{"message": "GraphQL introspection is not allowed"}])
        with pytest.raises(SchemaUnavailable, match="introspection is not allowed"):
            library.get_schema_queries()

    def test_a_response_without_a_schema_field_fails(self, library, mocked_responses):
        reply(mocked_responses, {"somethingElse": True})
        with pytest.raises(SchemaUnavailable, match="without a '__schema' field"):
            library.get_schema_mutations()

    def test_a_partial_introspection_result_is_reported(self, library, mocked_responses):
        """A gateway that filters introspection answers something build_client_schema refuses."""
        reply(mocked_responses, {"__schema": {"types": [{"name": "User"}]}})
        with pytest.raises(SchemaUnavailable, match="could not be turned into a schema"):
            library.get_schema_queries()

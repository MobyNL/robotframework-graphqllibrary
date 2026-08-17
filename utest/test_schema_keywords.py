import pytest
from assertionengine import AssertionOperator

from GraphQLLibrary.errors import GraphQLResponseError
from utest.conftest import reply, sent_query


def schema(
    queries=("ping", "user"),
    mutations=("createUser",),
    types=None,
):
    """Build an introspection reply body in the shape a server sends one."""
    return {
        "__schema": {
            "queryType": {"fields": [{"name": name} for name in queries]} if queries is not None else None,
            "mutationType": {"fields": [{"name": name} for name in mutations]} if mutations is not None else None,
            "types": types
            if types is not None
            else [
                {
                    "name": "User",
                    "fields": [
                        {"name": "id", "isDeprecated": False, "deprecationReason": None},
                        {"name": "email", "isDeprecated": True, "deprecationReason": "Use contact instead."},
                    ],
                },
                # Every server carries these, and they are not what a suite is asking about.
                {
                    "name": "__Type",
                    "fields": [{"name": "legacy", "isDeprecated": True, "deprecationReason": "internal"}],
                },
            ],
        }
    }


class TestReadingTheSchema:
    def test_queries_are_listed(self, library, mocked_responses):
        reply(mocked_responses, schema())
        assert library.get_schema_queries() == ["ping", "user"]

    def test_mutations_are_listed(self, library, mocked_responses):
        reply(mocked_responses, schema())
        assert library.get_schema_mutations() == ["createUser"]

    def test_a_read_only_schema_has_no_mutations(self, library, mocked_responses):
        reply(mocked_responses, schema(mutations=None))
        assert library.get_schema_mutations() == []

    def test_deprecated_fields_are_reported_as_type_dot_field(self, library, mocked_responses):
        reply(mocked_responses, schema())
        assert library.get_deprecated_fields() == ["User.email"]

    def test_introspection_types_are_not_reported(self, library, mocked_responses):
        """__Type.legacy is deprecated in the fixture, and must not be reported as schema."""
        reply(mocked_responses, schema())
        assert "__Type.legacy" not in library.get_deprecated_fields()

    def test_nothing_deprecated_is_an_empty_list(self, library, mocked_responses):
        reply(mocked_responses, schema(types=[{"name": "User", "fields": [{"name": "id", "isDeprecated": False}]}]))
        assert library.get_deprecated_fields() == []

    def test_deprecated_fields_are_requested_from_the_server(self, library, mocked_responses):
        """Without includeDeprecated the server omits them, so the list would always be empty."""
        reply(mocked_responses, schema())
        library.get_deprecated_fields()
        assert "includeDeprecated: true" in sent_query(mocked_responses)


class TestAssertionOperators:
    def test_queries_take_an_operator(self, library, mocked_responses):
        reply(mocked_responses, schema())
        library.get_schema_queries(AssertionOperator["contains"], "user")

    def test_a_failing_assertion_names_the_subject(self, library, mocked_responses):
        reply(mocked_responses, schema())
        with pytest.raises(AssertionError, match="GraphQL schema queries"):
            library.get_schema_queries(AssertionOperator["contains"], "absent")

    def test_deprecated_fields_take_an_operator(self, library, mocked_responses):
        reply(mocked_responses, schema())
        library.get_deprecated_fields(AssertionOperator["=="], ["User.email"])


class TestFieldShouldNotBeDeprecated:
    def test_a_current_field_passes(self, library, mocked_responses):
        reply(mocked_responses, schema())
        library.field_should_not_be_deprecated("User.id")

    def test_a_deprecated_field_fails_with_the_reason(self, library, mocked_responses):
        reply(mocked_responses, schema())
        with pytest.raises(AssertionError, match="Use contact instead."):
            library.field_should_not_be_deprecated("User.email")

    def test_a_deprecated_field_without_a_reason_still_fails(self, library, mocked_responses):
        reply(
            mocked_responses,
            schema(types=[{"name": "User", "fields": [{"name": "email", "isDeprecated": True}]}]),
        )
        with pytest.raises(AssertionError, match="no reason given"):
            library.field_should_not_be_deprecated("User.email")

    def test_an_unknown_type_is_a_bad_call_not_a_failed_check(self, library, mocked_responses):
        reply(mocked_responses, schema())
        with pytest.raises(ValueError, match="no type 'Absent'"):
            library.field_should_not_be_deprecated("Absent.id")

    def test_an_unknown_field_lists_the_fields_that_exist(self, library, mocked_responses):
        reply(mocked_responses, schema())
        with pytest.raises(ValueError, match="has no field 'absent'.*email, id"):
            library.field_should_not_be_deprecated("User.absent")

    def test_a_value_that_is_not_type_dot_field_is_refused(self, library, mocked_responses):
        with pytest.raises(ValueError, match="Type.field"):
            library.field_should_not_be_deprecated("email")


class TestIntrospectionUnavailable:
    def test_a_disabled_schema_says_so(self, library, mocked_responses):
        """Apollo reports a disabled introspection as an ordinary GraphQL error on a 200."""
        reply(mocked_responses, None, errors=[{"message": "GraphQL introspection is not allowed"}])
        with pytest.raises(GraphQLResponseError, match="disable introspection"):
            library.get_schema_queries()

    def test_the_servers_own_message_is_kept(self, library, mocked_responses):
        reply(mocked_responses, None, errors=[{"message": "GraphQL introspection is not allowed"}])
        with pytest.raises(GraphQLResponseError, match="introspection is not allowed"):
            library.get_schema_queries()

    def test_a_response_without_a_schema_field_fails(self, library, mocked_responses):
        reply(mocked_responses, {"somethingElse": True})
        with pytest.raises(GraphQLResponseError, match="without a '__schema' field"):
            library.get_schema_mutations()

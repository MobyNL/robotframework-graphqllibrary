import json
from typing import Any, Optional

import pytest
import responses
from graphql import build_schema, get_introspection_query, graphql_sync

from GraphQLLibrary import GraphQLLibrary

URL = "http://graphql.test/graphql"

SCHEMA_SDL = """
type User {
    id: ID!
    name: String!
    email: String @deprecated(reason: "Use contact instead.")
}

type Query {
    ping: String!
    user(id: ID!): User
}

type Mutation {
    createUser(name: String!): User!
}
"""


def introspection(sdl: str = SCHEMA_SDL) -> dict:
    """Return a real introspection result for an SDL string.

    Hand-writing one is not an option: ``build_client_schema`` needs every part of the
    introspection system, and rejects anything partial. Running graphql-core's own
    introspection query against a schema built from SDL gives exactly what a server sends.
    """
    result = graphql_sync(build_schema(sdl), get_introspection_query())
    assert result.errors is None, result.errors
    assert result.data is not None
    return dict(result.data)


@pytest.fixture
def mocked_responses():
    """Intercept HTTP at the requests layer, so the real gql transport is exercised.

    Mocking the transport itself would hide everything worth testing here: the request body
    gql builds, and the way it turns a body carrying ``errors`` into an exception.
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def library(mocked_responses):
    """A library instance with one session open, torn down afterwards.

    Schema validation is off here deliberately. It is on by default, but it makes every
    executing keyword introspect first, which would put an extra request in front of the one
    each of these tests is about and shift every ``sent_query`` index. The default path has its
    own tests in ``test_schema_validation.py``, using the fixture below.
    """
    library = GraphQLLibrary(validate_against_schema=False)
    library.create_graphql_session(URL)
    yield library
    library.delete_all_graphql_sessions()


@pytest.fixture
def validating_library(mocked_responses):
    """A library with schema validation left on, as it is for a user who configures nothing.

    The session is opened lazily by the test, after it has queued an introspection reply.
    """
    library = GraphQLLibrary()
    yield library
    library.delete_all_graphql_sessions()


@pytest.fixture
def library_without_session(mocked_responses):
    library = GraphQLLibrary(validate_against_schema=False)
    yield library
    library.delete_all_graphql_sessions()


def reply(
    mocked_responses,
    data: Any = None,
    errors: Optional[list] = None,
    extensions: Optional[dict] = None,
    status: int = 200,
    url: str = URL,
) -> None:
    """Queue one GraphQL response body.

    Defaults to status 200 even when errors are given, which is what a server answering
    ``application/json`` does and the reason this library exists.
    """
    body: dict = {"data": data}
    if errors is not None:
        body["errors"] = errors
    if extensions is not None:
        body["extensions"] = extensions
    mocked_responses.add(responses.POST, url, json=body, status=status)


def sent_body(mocked_responses, index: int = 0) -> dict:
    """Return the JSON body of a request the library sent."""
    return json.loads(mocked_responses.calls[index].request.body)


def sent_query(mocked_responses, index: int = 0) -> str:
    """Return the query text of a request the library sent."""
    return sent_body(mocked_responses, index)["query"]

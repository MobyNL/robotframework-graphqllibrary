import json
from typing import Any, Optional

import pytest
import responses

from GraphQLLibrary import GraphQLLibrary

URL = "http://graphql.test/graphql"


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
    """A library instance with one session open, torn down afterwards."""
    library = GraphQLLibrary()
    library.create_graphql_session(URL)
    yield library
    library.delete_all_graphql_sessions()


@pytest.fixture
def library_without_session(mocked_responses):
    library = GraphQLLibrary()
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

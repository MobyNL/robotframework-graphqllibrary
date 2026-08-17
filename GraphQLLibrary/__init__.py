from importlib.metadata import PackageNotFoundError, version
from typing import Optional

from robotlibcore import DynamicCore

from GraphQLLibrary.errors import GraphQLResponseError
from GraphQLLibrary.keywords.connection import ConnectionKeywords
from GraphQLLibrary.keywords.query import QueryKeywords
from GraphQLLibrary.keywords.response import ResponseKeywords
from GraphQLLibrary.session_pool import SessionManager

try:
    __version__ = version("robotframework-graphql")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "unknown"

__all__ = ["GraphQLLibrary", "GraphQLResponseError"]


class GraphQLLibrary(DynamicCore):
    """GraphQL Library for Robot Framework.

    GraphQL Library provides keywords for testing GraphQL APIs: opening endpoints, sending
    queries and mutations, and asserting on what comes back.

    = Table of Contents =

    - Introduction
    - Usage
    - Why Not Plain HTTP Keywords
    - Writing Queries
    - Errors
    - Sessions
    - Beyond These Keywords

    == Introduction ==

    Robot Framework 6.1.1 and later are supported, on Python 3.10 and later. The transport
    is the synchronous ``requests`` transport of the
    [https://github.com/graphql-python/gql|gql] library.

    == Usage ==

    Example:

    | *** Settings ***
    | Library    GraphQLLibrary    query_path=${CURDIR}/queries
    | Suite Teardown    Delete All Graphql Sessions
    |
    | *** Test Cases ***
    | A User Can Be Read Back
    |     Create Graphql Session    https://api.example.com/graphql    token=${API_TOKEN}
    |     ${response}    Execute Query    get_user.graphql    variables={"id": "1"}
    |     Should Be Equal    ${response.data.user.name}    Alice

    Responses are returned as dictionaries with the three fields the specification defines,
    ``data``, ``errors`` and ``extensions``, and are reachable with a dot, as in
    ``${response.data.user.name}``.

    == Why Not Plain HTTP Keywords ==

    A GraphQL endpoint is one HTTP POST, so a general HTTP library can send one. What it
    cannot do is tell whether the operation worked. A server answering
    ``application/json`` returns *HTTP 200 even when the operation failed*, and reports the
    failure in an ``errors`` array in the body. A suite that checks the status code passes
    on a request that returned nothing.

    Every keyword here that sends an operation checks the ``errors`` array and fails on it,
    including the partial case where ``data`` came back alongside errors because a nullable
    field failed. That is the default; `Execute Query` takes ``expect_errors=True`` when the
    errors are what the test is about.

    == Writing Queries ==

    Robot Framework collapses runs of spaces inside a cell, which breaks a query written
    across several lines. Three ways around it are supported, and the keywords take any of
    them wherever a query is accepted:

    - A file: ``Execute Query    get_user.graphql``. Set ``query_path`` on import to name the
      directory, or pass a path. This keeps queries in real ``.graphql`` files, which stay
      readable and reviewable.
    - A named operation: one file may hold several named operations, chosen with
      ``operation_name=GetUser``. `Get Query Operations` lists what a document holds.
    - Inline: pass the query as a list of lines, or as a ``VAR`` with escaped newlines. The
      list is joined with newlines.

    Queries are parsed before they are sent, so a syntax error is reported with its line and
    column instead of arriving as a server error. The parse is also what lets a keyword
    refuse a mutation handed to `Execute Query`, and what makes ``operation_name`` fail with
    the names a document does hold. Pass ``validate_queries=False`` on import to skip those
    checks.

    Note that the query reaching the server is the parsed document printed back out, so it
    arrives in the standard layout rather than exactly as it was written.

    == Errors ==

    Failures raise `GraphQLResponseError`, whose message lists every error with its ``path``
    and its ``extensions.code`` where the server sent them.

    == Sessions ==

    Sessions are held in a pool and identified by an alias. Keywords called without an
    ``alias`` use the active session, which is the one most recently created or selected
    with `Switch Graphql Session`. Sessions opened against the same endpoint with the same
    headers share one HTTP connection pool.

    `Create Graphql Session` also accepts an existing ``requests.Session``, which is the way
    to share cookies or authentication with HTTP calls made elsewhere in a suite.

    == Beyond These Keywords ==

    Deliberately not wrapped: subscriptions, file uploads, request batching, persisted
    queries, and schema introspection assertions. `Execute Raw Request` sends an operation
    with no checking at all, for cases this library does not model.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"
    ROBOT_LIBRARY_VERSION = __version__

    def __init__(self, query_path: Optional[str] = None, validate_queries: bool = True) -> None:
        """Import the library.

        Arguments:
        - ``query_path``: Directory that queries given by file name are looked up in. A path
          passed to a keyword still works without it; this only removes the repetition.
        - ``validate_queries``: Whether queries are checked locally before they are sent, so a
          syntax error is reported with its line and column. Turning it off skips this
          library's checks, including the one that `Execute Query` was not handed a mutation.
          A query still has to parse: gql parses every document it sends, and reports a
          syntax error in its own words.

        Robot Framework creates one instance per distinct set of import arguments, so
        importing with two different ``query_path`` values gives two separate session pools.
        """
        self.session_manager = SessionManager()
        connection = ConnectionKeywords(self.session_manager)
        libraries = [
            connection,
            QueryKeywords(self.session_manager, connection, query_path, validate_queries),
            ResponseKeywords(),
        ]
        DynamicCore.__init__(self, libraries)

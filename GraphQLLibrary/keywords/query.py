import time
from pathlib import Path
from typing import Any, Callable, Optional, Union

from assertionengine import AssertionOperator, verify_assertion
from gql import GraphQLRequest
from gql.transport.exceptions import TransportQueryError
from graphql import (
    DocumentNode,
    GraphQLSchema,
    GraphQLSyntaxError,
    OperationDefinitionNode,
    OperationType,
    parse,
    validate,
)
from robot.api import logger
from robot.api.deco import keyword
from robot.libraries.BuiltIn import BuiltIn
from robot.utils import DotDict, timestr_to_secs

from GraphQLLibrary.errors import GraphQLResponseError
from GraphQLLibrary.keywords.connection import ConnectionKeywords
from GraphQLLibrary.response import build_response, describe_errors, normalise_errors, resolve_path
from GraphQLLibrary.schema import describe_validation_errors, fetch_schema, SchemaUnavailable
from GraphQLLibrary.session_pool import GraphQLSession, SessionManager

QUERY_SUFFIXES = (".graphql", ".gql")

# How often automatic validation introspects a session that refuses before it gives up. Two,
# because the first query on a session is often the login and a schema behind authentication is
# unreadable until that has run - but a server with introspection switched off should not be
# asked before every query for the rest of the suite.
MAX_SCHEMA_ATTEMPTS = 2


class QueryKeywords:
    """
    Keywords for sending operations to a GraphQL endpoint.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        connection: ConnectionKeywords,
        query_path: Optional[str] = None,
        validate_queries: bool = True,
        validate_against_schema: bool = True,
    ) -> None:
        """
        Initializes the query keywords.

        Arguments:
        - ``session_manager``: Holds the pool of open endpoints.
        - ``connection``: Resolves aliases to sessions.
        - ``query_path``: Directory queries given by file name are looked up in.
        - ``validate_queries``: Whether queries are parsed before they are sent.
        - ``validate_against_schema``: Whether queries are also checked against the endpoint's
          schema before they are sent.
        """
        self.session_manager = session_manager
        self.connection = connection
        self.query_path = Path(query_path) if query_path else None
        self.validate_queries = validate_queries
        self.validate_against_schema = validate_against_schema

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _resolve_query(self, query: Union[str, list[str]]) -> str:
        """Turn whatever a suite passed as ``query`` into the query text.

        Three forms are accepted, because none of them alone covers how suites are written:
        a list of lines, a file name or path, and the query itself. A list is joined with
        newlines, which is what makes an inline ``VAR`` block or `Catenate` work despite
        Robot Framework collapsing runs of spaces inside a single cell.
        """
        if isinstance(query, (list, tuple)):
            return "\n".join(str(line) for line in query)
        path = self._as_query_file(query)
        if path is not None:
            return path.read_text(encoding="utf-8")
        return query

    def _as_query_file(self, query: str) -> Optional[Path]:
        """Return the file ``query`` names, or None when it is a query rather than a name.

        Only a value ending in ``.graphql`` or ``.gql`` is treated as a file, so a query
        text can never be mistaken for a path. A value that does end that way but resolves
        to nothing is an error, not a query: sending it would produce a syntax error from
        the server that says nothing about the missing file.
        """
        if "\n" in query or not query.strip().lower().endswith(QUERY_SUFFIXES):
            return None
        candidates = [Path(query)]
        if self.query_path is not None:
            candidates.insert(0, self.query_path / query)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        searched = ", ".join(str(candidate) for candidate in candidates)
        raise ValueError(f"Query file '{query}' was not found. Looked in: {searched}.")

    def _parse(self, query: str) -> DocumentNode:
        """Parse the query, reporting a syntax error with its line and column."""
        try:
            return parse(query)
        except GraphQLSyntaxError as error:
            raise ValueError(f"The query could not be parsed. {error}") from error

    def _operations(self, document: DocumentNode) -> list[OperationDefinitionNode]:
        """Return the operation definitions in a document, ignoring fragments."""
        return [node for node in document.definitions if isinstance(node, OperationDefinitionNode)]

    def _select_operation(
        self, document: DocumentNode, operation_name: Optional[str]
    ) -> OperationDefinitionNode:
        """Return the operation to execute, failing on anything the server would reject.

        A document holding several operations needs a name to pick one, and a name that is
        not in the document is a typo worth reporting here with the names that are, rather
        than as whatever the server chooses to say.
        """
        operations = self._operations(document)
        if not operations:
            raise ValueError("The query contains no operation to execute.")
        available = [node.name.value for node in operations if node.name]
        if operation_name is not None:
            for node in operations:
                if node.name and node.name.value == operation_name:
                    return node
            raise ValueError(
                f"Operation '{operation_name}' is not in this query. "
                f"Available operations: {', '.join(available) or 'none are named'}."
            )
        if len(operations) > 1:
            raise ValueError(
                f"This query holds {len(operations)} operations, so one has to be chosen with "
                f"`operation_name`. Available operations: {', '.join(available) or 'none are named'}."
            )
        return operations[0]

    def _execute(
        self,
        query: Union[str, list[str]],
        variables: Optional[dict],
        operation_name: Optional[str],
        alias: Optional[str],
        expect_errors: bool,
        expected_type: Optional[OperationType],
    ) -> DotDict:
        """Send one operation and turn the response into the object suites work with."""
        query_text = self._resolve_query(query)
        document: Optional[DocumentNode] = None
        if self.validate_queries or expected_type is not None or operation_name is not None:
            document = self._parse(query_text)
            operation = self._select_operation(document, operation_name)
            if expected_type is not None and operation.operation is not expected_type:
                raise ValueError(
                    f"This is a {operation.operation.value}, but a {expected_type.value} was expected. "
                    f"Use `Execute {operation.operation.value.capitalize()}` instead."
                )

        session = self.connection.get_session(alias)
        # After the session is resolved, because the schema is read from the endpoint, and only
        # when local checking is on at all: validate_queries=False means do nothing locally.
        if document is not None and self.validate_queries:
            self._validate_with_schema_if_enabled(session, document)
        request = GraphQLRequest(query_text, variable_values=variables, operation_name=operation_name)
        logger.debug(f"Executing on '{session.alias}' ({session.url}):\n{query_text}")

        try:
            result = session.execute(request)
            response = build_response(result.data, result.errors, result.extensions)
        except TransportQueryError as error:
            # gql raises as soon as the response carries errors, which is exactly the case
            # this library has to be able to hand back intact. Everything the response held
            # is on the exception, so nothing is lost by rebuilding it here.
            response = build_response(error.data, error.errors, error.extensions)

        if not response.errors:
            self._reconsider_schema_after_success(session)

        if response.errors and not expect_errors:
            raise GraphQLResponseError(
                f"The GraphQL response contains {len(response.errors)} error(s):\n"
                f"{describe_errors(response.errors)}\n"
                f"Pass expect_errors=True to assert on them instead of failing here.",
                errors=response.errors,
                data=response.data,
                extensions=response.extensions,
            )
        return response

    def _validate_against_schema(self, schema: GraphQLSchema, document: DocumentNode) -> None:
        """Check a parsed document against a schema, failing with every error it found."""
        errors = validate(schema, document)
        if errors:
            raise ValueError(
                f"The query does not match the schema. {len(errors)} problem(s) found:\n"
                f"{describe_validation_errors(errors)}"
            )

    def _validate_with_schema_if_enabled(self, session: GraphQLSession, document: DocumentNode) -> None:
        """Validate against the schema when that is switched on, skipping if it cannot be read.

        A server with introspection disabled is a normal thing to test against, so it must not
        turn every query into a failure. `Query Should Be Valid Against Schema` fails instead,
        because there the schema is the point of the call.
        """
        if not self.validate_against_schema or session.schema_unavailable:
            return
        try:
            schema = fetch_schema(self.session_manager, session)
        except SchemaUnavailable as error:
            session.schema_attempts += 1
            session.schema_unavailable = True
            remaining = MAX_SCHEMA_ATTEMPTS - session.schema_attempts
            retry = (
                " It will be tried once more after an operation succeeds, in case the schema is "
                "behind authentication this session has not completed yet."
                if remaining > 0
                else ""
            )
            logger.warn(
                f"Queries on '{session.alias}' are not being checked against the schema. {error}{retry}\n"
                f"Pass validate_against_schema=False on import to stop looking, or use "
                f"`Query Should Be Valid Against Schema` where a schema is required."
            )
            return
        self._validate_against_schema(schema, document)

    def _reconsider_schema_after_success(self, session: GraphQLSession) -> None:
        """Allow one more introspection attempt once an operation has worked.

        The first query on a session is very often the login itself, and an endpoint that keeps
        introspection behind authentication answers 401 until that has run. Latching on the first
        failure would therefore leave validation off for the whole suite, exactly where it is
        wanted. Attempts are capped so a server that genuinely refuses introspection is asked
        twice, not before every query.
        """
        if not session.schema_unavailable or session.schema_attempts >= MAX_SCHEMA_ATTEMPTS:
            return
        session.schema_unavailable = False

    def _retry_until_no_assertion_error(self, check: Callable[[], None], retry_timeout: str, retry_pause: str) -> None:
        """
        Run ``check`` until it stops raising AssertionError or ``retry_timeout`` elapses.

        The deadline is measured against a real clock, so the loop terminates even when
        ``retry_pause`` is zero and regardless of how long ``check`` itself takes.
        """
        deadline = time.monotonic() + timestr_to_secs(retry_timeout)
        pause = timestr_to_secs(retry_pause)
        while True:
            try:
                check()
                return
            except AssertionError:
                if time.monotonic() >= deadline:
                    logger.info(f"Timeout '{retry_timeout}' reached")
                    raise
                BuiltIn().sleep(pause)

    # ----------------------------------------------------------------- #
    # Queries
    # ----------------------------------------------------------------- #

    @keyword
    def load_query(self, path: str) -> str:
        """Read a query from a ``.graphql`` file and return it.

        Useful when the same query is sent more than once, or when it is edited before
        sending. `Execute Query` accepts a file name directly, so loading is not a required
        step.

        Arguments:
        - ``path``: File to read, either absolute, relative to the working directory, or
          relative to the ``query_path`` given when the library was imported.

        Returns: The query text.

        Example:
        | ${query}    Load Query    queries/get_user.graphql
        """
        resolved = self._as_query_file(path)
        if resolved is None:
            raise ValueError(f"'{path}' is not a query file. Expected a name ending in .graphql or .gql.")
        return resolved.read_text(encoding="utf-8")

    @keyword
    def execute_query(
        self,
        query: Union[str, list[str]],
        variables: Optional[dict] = None,
        operation_name: Optional[str] = None,
        alias: Optional[str] = None,
        expect_errors: bool = False,
    ) -> DotDict:
        """Send a query and return the response, failing when the server reports errors.

        A GraphQL server answers a failed operation with HTTP 200 and an ``errors`` array,
        so a status code says nothing about whether the operation worked. This keyword
        checks the array instead: any error fails the test, including the partial case where
        ``data`` came back alongside errors because a nullable field failed. Set
        ``expect_errors`` to assert on the errors rather than fail on them.

        The query may be given as the query text, as the name of a ``.graphql`` file, or as
        a list of lines. The list form exists because Robot Framework collapses runs of
        spaces inside a cell, which breaks a query written across several lines.

        Arguments:
        - ``query``: Query text, a ``.graphql`` file name, or a list of lines.
        - ``variables``: Variable values for the operation.
        - ``operation_name``: Which operation to run, when the document holds several.
        - ``alias``: Session to send on. Defaults to the active session.
        - ``expect_errors``: Return the response instead of failing when it carries errors.

        Returns: The response as a dictionary with ``data``, ``errors`` and ``extensions``.
        Fields are reachable with a dot, as in ``${response.data.user.name}``.

        Raises: ``GraphQLResponseError`` when the response carries errors and
        ``expect_errors`` is false. ``ValueError`` when the query cannot be parsed.

        Example:
        | ${response}    Execute Query    queries/get_user.graphql    variables={"id": "1"}
        | Should Be Equal    ${response.data.user.name}    Alice
        |
        | ${response}    Execute Query    {ping}
        |
        | VAR    ${query}    query GetUser($id: ID!) {\\n    user(id: $id) {\\n        name\\n    }\\n}
        | ${response}    Execute Query    ${query}
        """
        return self._execute(
            query,
            variables,
            operation_name,
            alias,
            expect_errors,
            expected_type=OperationType.QUERY if self.validate_queries else None,
        )

    @keyword
    def execute_mutation(
        self,
        query: Union[str, list[str]],
        variables: Optional[dict] = None,
        operation_name: Optional[str] = None,
        alias: Optional[str] = None,
        expect_errors: bool = False,
    ) -> DotDict:
        """Send a mutation and return the response, failing when the server reports errors.

        Behaves exactly like `Execute Query`, and additionally refuses to send anything that
        is not a mutation. Keeping the two apart is what makes a suite readable about which
        steps change state, and catches a copied query that was never edited.

        Arguments:
        - ``query``: Mutation text, a ``.graphql`` file name, or a list of lines.
        - ``variables``: Variable values for the operation.
        - ``operation_name``: Which operation to run, when the document holds several.
        - ``alias``: Session to send on. Defaults to the active session.
        - ``expect_errors``: Return the response instead of failing when it carries errors.

        Returns: The response as a dictionary with ``data``, ``errors`` and ``extensions``.

        Example:
        | ${response}    Execute Mutation    mutations/create_user.graphql    variables={"name": "Alice"}
        | Should Be Equal    ${response.data.createUser.id}    1
        """
        return self._execute(
            query,
            variables,
            operation_name,
            alias,
            expect_errors,
            expected_type=OperationType.MUTATION,
        )

    @keyword
    def validate_query(self, query: Union[str, list[str]]) -> str:
        """Check that a query parses, without sending anything and without a schema.

        This is a syntax check only. It contacts no server, so it cannot know whether the fields
        the query selects exist: a query naming a field the schema does not have passes here.
        Use `Query Should Be Valid Against Schema` for that.

        The failure names the line and column, which a server's error message usually does
        not. Use it on queries built at runtime, or as a check over the query files a suite
        ships.

        Arguments:
        - ``query``: Query text, a ``.graphql`` file name, or a list of lines.

        Returns: The query text, so the keyword can replace `Load Query` where both are wanted.

        Raises: ``ValueError`` when the query cannot be parsed.

        Example:
        | Validate Query    queries/get_user.graphql
        """
        query_text = self._resolve_query(query)
        self._parse(query_text)
        return query_text

    @keyword
    def query_should_be_valid_against_schema(
        self,
        query: Union[str, list[str]],
        alias: Optional[str] = None,
        operation_name: Optional[str] = None,
    ) -> None:
        """Check a query against the endpoint's schema without sending the query itself.

        This is what `Validate Query` cannot do: catch a field that does not exist, an argument
        that is misspelled, or a selection that is missing its subfields, before any request goes
        out. The schema is read from the endpoint by introspection once and then held, so
        checking many queries costs one round trip.

        Queries executed through `Execute Query` and `Execute Mutation` are already checked this
        way unless ``validate_against_schema=False`` was passed on import. Use this keyword when
        that is switched off, or to check a query a suite never sends.

        Unlike the automatic check, this keyword *fails* when the schema cannot be read, because
        a schema is what it was asked for. Automatic validation warns and carries on instead.

        Arguments:
        - ``query``: Query text, a ``.graphql`` file name, or a list of lines.
        - ``alias``: Session whose schema to check against. Defaults to the active session.
        - ``operation_name``: Which operation to check, when the document holds several.

        Raises: ``ValueError`` when the query does not match the schema, listing every problem
        with its line and column, or when the query cannot be parsed.
        `GraphQLLibrary.schema.SchemaUnavailable` when the schema cannot be read.

        Example:
        | Query Should Be Valid Against Schema    queries/get_user.graphql
        """
        document = self._parse(self._resolve_query(query))
        if operation_name is not None:
            self._select_operation(document, operation_name)
        session = self.connection.get_session(alias)
        self._validate_against_schema(fetch_schema(self.session_manager, session), document)

    @keyword
    def refresh_graphql_schema(self, alias: Optional[str] = None) -> None:
        """Drop the schema held for a session so the next check introspects again.

        The schema is read once per endpoint and kept, which is what makes validation affordable.
        Call this after a deployment that changed the schema mid-suite, or a suite will keep
        checking against the schema as it was.

        Arguments:
        - ``alias``: Session whose schema to drop. Defaults to the active session.

        Example:
        | Refresh Graphql Schema
        """
        session = self.connection.get_session(alias)
        self.session_manager.forget_schema(session)
        logger.info(f"Dropped the cached schema for '{session.alias}'.")

    @keyword
    def get_query_operations(self, query: Union[str, list[str]]) -> list[str]:
        """Return the names of the operations in a query document.

        Useful for a document holding several named operations, where `Execute Query` needs
        one of the names in ``operation_name``.

        Arguments:
        - ``query``: Query text, a ``.graphql`` file name, or a list of lines.

        Returns: List of operation names. Unnamed operations are not listed.

        Example:
        | ${operations}    Get Query Operations    queries/user.graphql
        | Should Contain    ${operations}    GetUser
        """
        document = self._parse(self._resolve_query(query))
        return [node.name.value for node in self._operations(document) if node.name]

    @keyword
    def check_query_result(
        self,
        query: Union[str, list[str]],
        path: str,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        variables: Optional[dict] = None,
        operation_name: Optional[str] = None,
        alias: Optional[str] = None,
        retry_timeout: str = "0s",
        retry_pause: str = "0.5s",
        message: Optional[str] = None,
    ) -> None:
        """Send a query and assert on a field of the result, retrying until it holds.

        The keyword re-sends the query on each attempt, which is what makes it the tool for
        a read model that is filled in asynchronously: a mutation returns, and the query
        that should observe it only answers correctly a moment later. Errors in the response
        are retried too, since a service that is not ready yet reports them.

        Prefer this over wrapping `Execute Query` in `Wait Until Keyword Succeeds`: the
        failure that is reported at timeout is the assertion's own, naming the field and both
        values, rather than a generic one.

        Arguments:
        - ``query``: Query text, a ``.graphql`` file name, or a list of lines.
        - ``path``: Dotted path below ``data``, as in ``user.name``.
        - ``assertion_operator``: Operator to check the value with, such as ``==``.
        - ``assertion_expected``: Value the operator compares against.
        - ``variables``: Variable values for the operation.
        - ``operation_name``: Which operation to run, when the document holds several.
        - ``alias``: Session to send on. Defaults to the active session.
        - ``retry_timeout``: How long to keep retrying, as a Robot Framework time string.
          The default sends once.
        - ``retry_pause``: How long to wait between attempts.
        - ``message``: Custom message used when the assertion fails.

        Example:
        | Check Query Result    get_user.graphql    user.name    ==    Alice    retry_timeout=10s
        """

        def check() -> None:
            response = self._execute(
                query, variables, operation_name, alias, expect_errors=True, expected_type=None
            )
            if response.errors:
                raise AssertionError(
                    f"The GraphQL response contains {len(response.errors)} error(s):\n"
                    f"{describe_errors(response.errors)}"
                )
            try:
                value = resolve_path(response.data, path)
            except ValueError as error:
                # A field that is not there yet is exactly what retrying is for, so this is
                # an assertion failure rather than a bad call.
                raise AssertionError(str(error)) from error
            verify_assertion(value, assertion_operator, assertion_expected, f"GraphQL data '{path}'", message)

        self._retry_until_no_assertion_error(check, retry_timeout, retry_pause)

    @keyword
    def execute_raw_request(
        self,
        query: Union[str, list[str]],
        variables: Optional[dict] = None,
        operation_name: Optional[str] = None,
        alias: Optional[str] = None,
    ) -> DotDict:
        """Send an operation and return the response without checking it in any way.

        The escape hatch for what this library does not model: a server that answers in a
        shape the spec does not describe, an operation type it will not send, or a case
        where the errors are the point and even the parse should be skipped.

        Arguments:
        - ``query``: Query text, a ``.graphql`` file name, or a list of lines.
        - ``variables``: Variable values for the operation.
        - ``operation_name``: Which operation to run, when the document holds several.
        - ``alias``: Session to send on. Defaults to the active session.

        Returns: The response as a dictionary with ``data``, ``errors`` and ``extensions``.

        Example:
        | ${response}    Execute Raw Request    subscription { ticks }
        """
        session = self.connection.get_session(alias)
        request = GraphQLRequest(
            self._resolve_query(query), variable_values=variables, operation_name=operation_name
        )
        try:
            result = session.execute(request)
            return build_response(result.data, result.errors, result.extensions)
        except TransportQueryError as error:
            return build_response(error.data, normalise_errors(error.errors), error.extensions)

from pathlib import Path
from typing import Any, Optional

from assertionengine import AssertionOperator, verify_assertion
from graphql import (
    build_schema,
    find_breaking_changes,
    find_dangerous_changes,
    GraphQLInterfaceType,
    GraphQLObjectType,
    GraphQLSchema,
    print_schema,
)
from robot.api import logger
from robot.api.deco import keyword

from GraphQLLibrary.keywords.connection import ConnectionKeywords
from GraphQLLibrary.schema import fetch_schema
from GraphQLLibrary.session_pool import SessionManager


class SchemaKeywords:
    """
    Keywords for reading a schema through introspection, and for noticing when it changes.

    These answer the question the GraphiQL or Apollo Sandbox page at an endpoint answers: what
    operations does this server offer, and what has been deprecated. Introspection is an
    ordinary query, so nothing here reaches past the transport the other keywords use.

    The schema is introspected once per endpoint and then held, because a real schema runs to
    hundreds of kilobytes. `Refresh Graphql Schema` drops it when a deployment changes it
    mid-suite.

    Servers commonly disable introspection outside development, Apollo Server among them. When
    it is off, these keywords fail saying so rather than reporting an empty schema.
    """

    def __init__(self, session_manager: SessionManager, connection: ConnectionKeywords) -> None:
        """
        Initializes the schema keywords.

        Arguments:
        - ``session_manager``: Holds the pool of open endpoints and the schemas read from them.
        - ``connection``: Resolves aliases to sessions.
        """
        self.session_manager = session_manager
        self.connection = connection

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _schema(self, alias: Optional[str]) -> GraphQLSchema:
        """Return the endpoint's schema, introspecting it if it is not held yet."""
        return fetch_schema(self.session_manager, self.connection.get_session(alias))

    @staticmethod
    def _root_fields(schema: GraphQLSchema, root: str) -> list[str]:
        """Return the field names of a root type, which is None when the schema has none."""
        root_type = getattr(schema, root)
        if root_type is None:
            return []
        return list(root_type.fields)

    @staticmethod
    def _type_fields(schema: GraphQLSchema) -> list[tuple[str, str, Any]]:
        """Return every (type name, field name, field) triple a suite could ask about.

        The ``__``-prefixed types are part of the introspection system rather than the schema a
        suite is asking about, and every server carries the same ones. Only objects and
        interfaces have fields; input objects and enums are excluded, which is the same limit
        the introspection query itself carries.
        """
        triples = []
        for name, type_ in schema.type_map.items():
            if name.startswith("__"):
                continue
            if not isinstance(type_, (GraphQLObjectType, GraphQLInterfaceType)):
                continue
            for field_name, field in type_.fields.items():
                triples.append((name, field_name, field))
        return triples

    def _load_snapshot(self, path: str) -> GraphQLSchema:
        """Read a schema from an SDL file written by `Save Schema Snapshot`."""
        file = Path(path)
        if not file.is_file():
            raise ValueError(f"Schema snapshot '{path}' was not found. Write one with `Save Schema Snapshot`.")
        try:
            return build_schema(file.read_text(encoding="utf-8"))
        except Exception as error:
            raise ValueError(f"Schema snapshot '{path}' could not be read as SDL. {error}") from error

    def _compared_pair(self, path: str, alias: Optional[str]) -> tuple[GraphQLSchema, GraphQLSchema]:
        """Return the snapshot and the live schema, both built the same way.

        The live schema comes from introspection; the snapshot comes from SDL. Comparing those
        two directly reports differences that are not schema changes at all: a server built on
        graphql-js describes ``@deprecated`` with four locations, while graphql-core's own
        built-in adds ``DIRECTIVE_DEFINITION``, so every comparison against a real JS server
        claimed a directive location had been removed. Printing the live schema and reading it
        back puts both sides through the same builder, which leaves only real differences.
        """
        return self._load_snapshot(path), build_schema(print_schema(self._schema(alias)))

    def _changes(self, path: str, alias: Optional[str], finder: Any) -> list[str]:
        """Run one of graphql-core's change finders over the snapshot and the live schema."""
        old, new = self._compared_pair(path, alias)
        return [f"{change.type.name}: {change.description}" for change in finder(old, new)]

    # ----------------------------------------------------------------- #
    # Reading
    # ----------------------------------------------------------------- #

    @keyword
    def get_schema_queries(
        self,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        alias: Optional[str] = None,
        message: Optional[str] = None,
    ) -> list[str]:
        """Return the names of every query the schema offers, optionally asserting on them.

        Arguments:
        - ``assertion_operator``: Operator to check the list with, such as ``contains``. Omit it
          to only read the names.
        - ``assertion_expected``: Value the operator compares against.
        - ``alias``: Session to introspect. Defaults to the active session.
        - ``message``: Custom message used when the assertion fails.

        Returns: List of query field names, empty only for a schema with no query type.

        Example:
        | ${queries}    Get Schema Queries
        | Get Schema Queries    contains    user
        """
        queries = self._root_fields(self._schema(alias), "query_type")
        return verify_assertion(queries, assertion_operator, assertion_expected, "GraphQL schema queries", message)

    @keyword
    def get_schema_mutations(
        self,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        alias: Optional[str] = None,
        message: Optional[str] = None,
    ) -> list[str]:
        """Return the names of every mutation the schema offers, optionally asserting on them.

        Arguments:
        - ``assertion_operator``: Operator to check the list with, such as ``contains``.
        - ``assertion_expected``: Value the operator compares against.
        - ``alias``: Session to introspect. Defaults to the active session.
        - ``message``: Custom message used when the assertion fails.

        Returns: List of mutation field names, empty for a read-only schema.

        Example:
        | Get Schema Mutations    contains    createUser
        """
        mutations = self._root_fields(self._schema(alias), "mutation_type")
        return verify_assertion(mutations, assertion_operator, assertion_expected, "GraphQL schema mutations", message)

    @keyword
    def get_deprecated_fields(
        self,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        alias: Optional[str] = None,
        message: Optional[str] = None,
    ) -> list[str]:
        """Return every deprecated field in the schema as ``Type.field``, optionally asserting.

        Use it as a guard on a suite: assert the list against the deprecations a suite knows
        about, so a newly deprecated field the tests still rely on shows up as a failure here
        rather than as a removal months later.

        Only object and interface fields are reported. Deprecated input fields and enum values
        are deliberately not requested, because asking for them errors on older servers.

        Arguments:
        - ``assertion_operator``: Operator to check the list with, such as ``==`` or ``contains``.
        - ``assertion_expected``: Value the operator compares against.
        - ``alias``: Session to introspect. Defaults to the active session.
        - ``message``: Custom message used when the assertion fails.

        Returns: Sorted list of ``Type.field`` names, empty when nothing is deprecated.

        Example:
        | Get Deprecated Fields    ==    ${{ ['User.email'] }}
        | ${deprecated}    Get Deprecated Fields
        """
        deprecated = sorted(
            f"{type_name}.{field_name}"
            for type_name, field_name, field in self._type_fields(self._schema(alias))
            if field.deprecation_reason is not None
        )
        return verify_assertion(
            deprecated, assertion_operator, assertion_expected, "GraphQL deprecated fields", message
        )

    # ----------------------------------------------------------------- #
    # Asserting
    # ----------------------------------------------------------------- #

    @keyword
    def field_should_not_be_deprecated(self, field: str, alias: Optional[str] = None) -> None:
        """Fail when ``field`` is deprecated, naming the reason the schema gave.

        The check a suite wants on the fields it selects: a deprecation is the warning that a
        field is going away, and it is only useful if something reads it.

        Arguments:
        - ``field``: Field to check, as ``Type.field``, such as ``User.email``.
        - ``alias``: Session to introspect. Defaults to the active session.

        Raises: ``AssertionError`` when the field is deprecated. ``ValueError`` when the schema
        holds no such type or field, since that is a bad call rather than a failed check.

        Example:
        | Field Should Not Be Deprecated    User.email
        """
        type_name, _, field_name = field.rpartition(".")
        if not type_name or not field_name:
            raise ValueError(f"Expected a field as 'Type.field', got '{field}'.")

        triples = self._type_fields(self._schema(alias))
        known_types = {name for name, _, _ in triples}
        if type_name not in known_types:
            raise ValueError(
                f"The schema holds no type '{type_name}'. Types with fields: "
                f"{', '.join(sorted(known_types)) or 'none'}."
            )

        for name, found_name, found in triples:
            if name != type_name or found_name != field_name:
                continue
            if found.deprecation_reason is not None:
                raise AssertionError(f"Field '{field}' is deprecated: {found.deprecation_reason}")
            return

        available = sorted(found_name for name, found_name, _ in triples if name == type_name)
        raise ValueError(f"Type '{type_name}' has no field '{field_name}'. Fields: {', '.join(available)}.")

    # ----------------------------------------------------------------- #
    # Drift
    # ----------------------------------------------------------------- #

    @keyword
    def save_schema_snapshot(self, path: str, alias: Optional[str] = None) -> str:
        """Write the endpoint's schema to a file as SDL, to compare against later.

        SDL rather than the introspection JSON, because a committed snapshot is only useful if a
        person can read the diff. Commit the file, and a schema change shows up in review.

        Arguments:
        - ``path``: File to write. Existing content is replaced.
        - ``alias``: Session to introspect. Defaults to the active session.

        Returns: The path written, so it can be assigned in one line.

        Example:
        | Save Schema Snapshot    ${CURDIR}/schema.graphql
        """
        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(print_schema(self._schema(alias)), encoding="utf-8")
        logger.info(f"Wrote the schema of '{self.connection.get_session(alias).alias}' to {path}.")
        return path

    @keyword
    def get_schema_breaking_changes(
        self,
        path: str,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        alias: Optional[str] = None,
        message: Optional[str] = None,
    ) -> list[str]:
        """Return the changes since a snapshot that would break an existing client.

        A removed field, a removed type, a field whose type changed incompatibly, or an argument
        that became required. These are the changes that break a suite whether or not it was
        warned, which is what makes them worth asserting on in CI.

        Arguments:
        - ``path``: Snapshot written earlier by `Save Schema Snapshot`.
        - ``assertion_operator``: Operator to check the list with, such as ``==``.
        - ``assertion_expected``: Value the operator compares against.
        - ``alias``: Session to introspect. Defaults to the active session.
        - ``message``: Custom message used when the assertion fails.

        Returns: List of ``CHANGE_TYPE: description`` strings, empty when nothing broke.

        Example:
        | Get Schema Breaking Changes    ${CURDIR}/schema.graphql    ==    ${{ [] }}
        """
        changes = self._changes(path, alias, find_breaking_changes)
        return verify_assertion(
            changes, assertion_operator, assertion_expected, "GraphQL breaking changes", message
        )

    @keyword
    def get_schema_dangerous_changes(
        self,
        path: str,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        alias: Optional[str] = None,
        message: Optional[str] = None,
    ) -> list[str]:
        """Return the changes since a snapshot that may break a client, without certainly doing so.

        A new value added to an enum a suite switches on, an optional argument added, a type
        added to a union. Nothing here breaks a query outright, which is why it is reported
        apart from the breaking changes rather than mixed in with them.

        Arguments:
        - ``path``: Snapshot written earlier by `Save Schema Snapshot`.
        - ``assertion_operator``: Operator to check the list with, such as ``==``.
        - ``assertion_expected``: Value the operator compares against.
        - ``alias``: Session to introspect. Defaults to the active session.
        - ``message``: Custom message used when the assertion fails.

        Returns: List of ``CHANGE_TYPE: description`` strings.

        Example:
        | Get Schema Dangerous Changes    ${CURDIR}/schema.graphql
        """
        changes = self._changes(path, alias, find_dangerous_changes)
        return verify_assertion(
            changes, assertion_operator, assertion_expected, "GraphQL dangerous changes", message
        )

    @keyword
    def schema_should_have_no_breaking_changes(self, path: str, alias: Optional[str] = None) -> None:
        """Fail when the schema has changed since a snapshot in a way that breaks clients.

        The assertion form of `Get Schema Breaking Changes`, for a suite that wants the schema
        checked as a test rather than read as a value.

        Arguments:
        - ``path``: Snapshot written earlier by `Save Schema Snapshot`.
        - ``alias``: Session to introspect. Defaults to the active session.

        Raises: ``AssertionError`` listing every breaking change.

        Example:
        | Schema Should Have No Breaking Changes    ${CURDIR}/schema.graphql
        """
        changes = self._changes(path, alias, find_breaking_changes)
        if changes:
            newline = "\n"
            raise AssertionError(
                f"The schema has {len(changes)} breaking change(s) since {path}:\n"
                f"{newline.join('- ' + change for change in changes)}"
            )

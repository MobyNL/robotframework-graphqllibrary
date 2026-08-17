from typing import Any, Optional

from assertionengine import AssertionOperator, verify_assertion
from robot.api.deco import keyword

from GraphQLLibrary.errors import GraphQLResponseError
from GraphQLLibrary.keywords.query import QueryKeywords

# `includeDeprecated: true` matters: introspection omits deprecated fields unless it is asked
# for them, so without it `Get Deprecated Fields` would always answer with an empty list.
# Only object and interface fields are requested. Deprecated input fields and enum values are
# also introspectable, but `inputFields(includeDeprecated:)` and
# `enumValues(includeDeprecated:)` are later additions that older servers reject outright,
# which would turn every keyword here into an error against them.
INTROSPECTION_QUERY = """
query GraphQLLibraryIntrospection {
  __schema {
    queryType {
      fields(includeDeprecated: true) {
        name
      }
    }
    mutationType {
      fields(includeDeprecated: true) {
        name
      }
    }
    types {
      name
      fields(includeDeprecated: true) {
        name
        isDeprecated
        deprecationReason
      }
    }
  }
}
"""


class SchemaKeywords:
    """
    Keywords for reading a schema through introspection.

    These answer the question the GraphiQL or Apollo Sandbox page at an endpoint answers: what
    operations does this server offer, and what has been deprecated. Introspection is an
    ordinary query, so nothing here reaches past the transport the other keywords use.

    Each keyword performs one introspection query. Nothing is cached, because a suite that
    checks a schema is usually checking a deployment that just changed.

    Servers commonly disable introspection outside development, Apollo Server among them. When
    it is off, these keywords fail saying so rather than reporting an empty schema.
    """

    def __init__(self, query: QueryKeywords) -> None:
        """
        Initializes the schema keywords.

        Arguments:
        - ``query``: Used to send the introspection query on the session.
        """
        self.query = query

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _introspect(self, alias: Optional[str]) -> dict:
        """Return the ``__schema`` field, or fail explaining why it could not be read."""
        try:
            response = self.query.execute_query(INTROSPECTION_QUERY, alias=alias)
        except GraphQLResponseError as error:
            raise GraphQLResponseError(
                f"The schema could not be introspected. Servers often disable introspection "
                f"outside development, which is reported as an ordinary GraphQL error. The "
                f"server said:\n{error}",
                errors=error.errors,
                data=error.data,
                extensions=error.extensions,
            ) from error
        schema = (response.get("data") or {}).get("__schema")
        if not schema:
            raise GraphQLResponseError(
                "The server answered the introspection query without a '__schema' field, so the "
                "schema cannot be read. Introspection may be disabled or filtered by a gateway."
            )
        return dict(schema)

    @staticmethod
    def _root_fields(schema: dict, root: str) -> list[str]:
        """Return the field names of a root type, which is null when the schema has none."""
        root_type = schema.get(root)
        if not root_type:
            return []
        return [str(field["name"]) for field in root_type.get("fields") or []]

    @staticmethod
    def _type_fields(schema: dict) -> list[tuple[str, dict]]:
        """Return every (type name, field) pair, skipping the introspection types themselves.

        The ``__``-prefixed types are part of the introspection system rather than the schema a
        suite is asking about, and every server carries the same ones.
        """
        pairs = []
        for type_ in schema.get("types") or []:
            name = str(type_.get("name") or "")
            if name.startswith("__"):
                continue
            for field in type_.get("fields") or []:
                pairs.append((name, dict(field)))
        return pairs

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
        queries = self._root_fields(self._introspect(alias), "queryType")
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
        mutations = self._root_fields(self._introspect(alias), "mutationType")
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
            f"{type_name}.{field['name']}"
            for type_name, field in self._type_fields(self._introspect(alias))
            if field.get("isDeprecated")
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

        pairs = self._type_fields(self._introspect(alias))
        known_types = {name for name, _ in pairs}
        if type_name not in known_types:
            raise ValueError(
                f"The schema holds no type '{type_name}'. Types with fields: "
                f"{', '.join(sorted(known_types)) or 'none'}."
            )

        for name, found in pairs:
            if name != type_name or found["name"] != field_name:
                continue
            if found.get("isDeprecated"):
                reason = found.get("deprecationReason") or "no reason given"
                raise AssertionError(f"Field '{field}' is deprecated: {reason}")
            return

        available = sorted(found["name"] for name, found in pairs if name == type_name)
        raise ValueError(f"Type '{type_name}' has no field '{field_name}'. Fields: {', '.join(available)}.")

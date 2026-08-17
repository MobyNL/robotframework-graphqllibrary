from typing import Any, Optional

from gql import GraphQLRequest
from gql.transport.exceptions import TransportQueryError
from graphql import build_client_schema, get_introspection_query, GraphQLSchema
from robot.api import logger

from GraphQLLibrary.response import describe_errors, normalise_errors
from GraphQLLibrary.session_pool import GraphQLSession, SessionManager

# graphql-core builds this, rather than this library hand-writing one, because
# `build_client_schema` needs every part of the introspection system: each type's `kind`, the
# `ofType` chain that carries nullability and lists, field types, arguments, interfaces and
# possible types. A query missing any of them is rejected outright with "Invalid or incomplete
# introspection result".
#
# The defaults are deliberate. `input_value_deprecation=True` would additionally report
# deprecated input fields and enum values, but it is a later addition to the specification that
# older servers reject, which would turn every schema keyword into an error against them. The
# cost of leaving it off is that those deprecations are not reported; the library documents that.
FULL_INTROSPECTION_QUERY = get_introspection_query()


class SchemaUnavailable(Exception):
    """Raised when a schema could not be read from an endpoint.

    Separate from `GraphQLResponseError` so callers can choose what it means. Automatic
    validation treats it as a reason to skip, since introspection is commonly disabled outside
    development and a suite should not fail for asking. A keyword whose whole purpose is the
    schema treats it as a failure.
    """


def build_schema_from_introspection(data: Optional[dict]) -> GraphQLSchema:
    """Turn the ``data`` of an introspection response into a schema object.

    Arguments:
    - ``data``: The ``data`` field of the response to `FULL_INTROSPECTION_QUERY`, which holds
      the ``__schema`` key that ``build_client_schema`` expects. Note it wants this whole
      mapping, not the inner ``__schema`` value.

    Raises: `SchemaUnavailable` when the response carries no usable schema.
    """
    if not data or not data.get("__schema"):
        raise SchemaUnavailable(
            "The server answered the introspection query without a '__schema' field, so the "
            "schema cannot be read. Introspection may be disabled or filtered by a gateway."
        )
    try:
        # build_client_schema wants the full result, so `data` is passed as-is rather than
        # unwrapped to data["__schema"].
        return build_client_schema(data)  # type: ignore[arg-type]
    except (TypeError, KeyError) as error:
        raise SchemaUnavailable(
            f"The introspection result could not be turned into a schema. The server may have "
            f"answered a filtered or partial introspection query. {error}"
        ) from error


def fetch_schema(session_manager: SessionManager, session: GraphQLSession) -> GraphQLSchema:
    """Return the endpoint's schema, introspecting it once and holding it afterwards.

    Introspecting a real schema runs to hundreds of kilobytes, so the result is cached for every
    session sharing the same connection parameters. `Refresh Graphql Schema` drops it.

    Lives here rather than on either keyword class because both the executing keywords and the
    schema keywords need it, and neither owns the other.

    Raises: `SchemaUnavailable` when the endpoint will not answer an introspection query.
    """
    cached = session_manager.get_cached_schema(session)
    if cached is not None:
        return cached

    disabled = (
        "The schema could not be introspected. Servers often disable introspection outside "
        "development, which is reported as an ordinary GraphQL error. The server said:\n"
    )
    try:
        result = session.execute(GraphQLRequest(FULL_INTROSPECTION_QUERY))
    except TransportQueryError as error:
        raise SchemaUnavailable(f"{disabled}{describe_errors(normalise_errors(error.errors))}") from error
    except Exception as error:
        # A transport-level refusal, such as the 401 a gateway answers when introspection sits
        # behind authentication, arrives as gql's own exception rather than as an errors array.
        raise SchemaUnavailable(f"The schema could not be introspected. {error}") from error

    if result.errors:
        raise SchemaUnavailable(f"{disabled}{describe_errors(normalise_errors(result.errors))}")

    schema = build_schema_from_introspection(result.data)
    session_manager.cache_schema(session, schema)
    logger.debug(f"Introspected the schema of '{session.alias}' ({session.url}).")
    return schema


def describe_validation_errors(errors: Any) -> str:
    """Render validation errors as one line each, with their location where there is one.

    graphql-core already writes "Did you mean ..." into these messages, which is the same habit
    the rest of this library follows of naming the valid alternatives.
    """
    lines = []
    for error in errors:
        location = ""
        locations = getattr(error, "locations", None)
        if locations:
            first = locations[0]
            location = f" (line {first.line}, column {first.column})"
        lines.append(f"- {getattr(error, 'message', error)}{location}")
    return "\n".join(lines)

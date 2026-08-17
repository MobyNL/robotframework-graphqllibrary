from typing import Any, Optional

from robot.utils import DotDict


def normalise_errors(errors: Optional[list]) -> list:
    """
    Return the ``errors`` array as plain dictionaries.

    Entries arrive as raw dictionaries from the transport, but graphql-core objects turn up
    on the paths that parse a result against a schema. ``GraphQLError.formatted`` gives the
    spec shape for those, so suites see one shape either way.

    :param errors: Errors as returned by gql, or None
    :return: List of error dictionaries
    """
    normalised = []
    for error in errors or []:
        if isinstance(error, dict):
            normalised.append(error)
        elif hasattr(error, "formatted"):
            normalised.append(dict(error.formatted))
        else:  # a transport that reports errors as bare strings
            normalised.append({"message": str(error)})
    return normalised


def build_response(data: Any, errors: Optional[list], extensions: Optional[dict]) -> DotDict:
    """
    Build the response object keywords hand back to suites.

    Wrapped in `robot.utils.DotDict` so a suite can write ``${response.data.user.name}``
    instead of chaining `Get From Dictionary` calls. The three spec-defined top-level fields
    are always present, so a suite never has to guard on their absence.

    :param data: The ``data`` field of the response, which may be None
    :param errors: The ``errors`` array, which may be None or empty
    :param extensions: The top-level ``extensions`` map, which may be None
    :return: DotDict with ``data``, ``errors`` and ``extensions``
    """
    return DotDict(
        {
            "data": DotDict(data) if isinstance(data, dict) else data,
            "errors": normalise_errors(errors),
            "extensions": DotDict(extensions or {}),
        }
    )


def resolve_path(value: Any, path: Optional[str]) -> Any:
    """
    Follow a dotted ``path`` into a response fragment.

    List positions are written as numbers, as in ``user.friends.0.name``, so one syntax
    covers both objects and lists. A missing step is reported with what was available at
    that point, because in GraphQL it usually means the query did not ask for the field.

    :param value: Fragment to walk, normally the ``data`` field
    :param path: Dotted path, or None to return the fragment unchanged
    :return: The value at the path
    """
    if not path:
        return value
    current = value
    walked: list[str] = []
    for step in path.split("."):
        if current is None:
            raise ValueError(f"'{'.'.join(walked) or 'data'}' is null, so '{path}' cannot be read.")
        if isinstance(current, list):
            try:
                current = current[int(step)]
            except ValueError:
                raise ValueError(f"'{'.'.join(walked)}' is a list, so '{step}' has to be a number.")
            except IndexError:
                raise ValueError(f"'{'.'.join(walked)}' holds {len(current)} items, so index {step} is out of range.")
        elif isinstance(current, dict):
            if step not in current:
                available = ", ".join(current.keys()) or "nothing"
                raise ValueError(f"'{step}' is not in '{'.'.join(walked) or 'data'}'. Available: {available}.")
            current = current[step]
        else:
            raise ValueError(f"'{'.'.join(walked)}' is a {type(current).__name__}, so '{step}' cannot be read from it.")
        walked.append(step)
    return current


def format_error_path(error: dict) -> str:
    """
    Return an error's ``path`` in the dotted form the keywords accept.

    :param error: One entry of the ``errors`` array
    :return: Dotted path, empty when the error has none
    """
    return ".".join(str(step) for step in error.get("path") or [])


def describe_errors(errors: list) -> str:
    """
    Render an ``errors`` array as one readable line per error, for failure messages.

    Includes ``path`` and ``extensions.code`` when the server sent them, because those are
    what identifies which field failed and why, and neither is in ``message``.

    :param errors: Normalised list of error dictionaries
    :return: Human readable description
    """
    lines = []
    for error in errors:
        parts = [str(error.get("message", error))]
        path = error.get("path")
        if path:
            parts.append(f"at path {'.'.join(str(step) for step in path)}")
        code = (error.get("extensions") or {}).get("code")
        if code:
            parts.append(f"code {code}")
        lines.append(" ".join(parts))
    return "\n".join(f"- {line}" for line in lines)

from typing import Any, Optional

from assertionengine import AssertionOperator, verify_assertion
from robot.api.deco import keyword

from GraphQLLibrary.response import describe_errors, format_error_path, resolve_path


class ResponseKeywords:
    """
    Keywords for reading and asserting on a GraphQL response.

    Every getter takes an optional assertion operator and expected value, so a value can be
    read and checked in one step, in the style the Browser library established.
    """

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    @staticmethod
    def _errors(response: dict) -> list:
        """Return the ``errors`` array of a response, whatever shape it arrived in."""
        if not isinstance(response, dict):
            raise ValueError(
                f"Expected a GraphQL response, got a {type(response).__name__}. "
                f"Pass the value returned by `Execute Query`."
            )
        return response.get("errors") or []

    # ----------------------------------------------------------------- #
    # Reading
    # ----------------------------------------------------------------- #

    @keyword
    def get_graphql_data(
        self,
        response: dict,
        path: Optional[str] = None,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        message: Optional[str] = None,
    ) -> Any:
        """Return a value out of the ``data`` field, optionally asserting on it.

        Arguments:
        - ``response``: Response returned by `Execute Query` or `Execute Mutation`.
        - ``path``: Dotted path below ``data``, with list positions as numbers, as in
          ``user.friends.0.name``. Omit it to get the whole ``data`` field.
        - ``assertion_operator``: Operator to check the value with, such as ``==`` or
          ``contains``. Omit it to only read the value.
        - ``assertion_expected``: Value the operator compares against.
        - ``message``: Custom message used when the assertion fails.

        Returns: The value at the path.

        Example:
        | Get Graphql Data    ${response}    user.name    ==    Alice
        | ${friends}    Get Graphql Data    ${response}    user.friends
        """
        value = resolve_path(response.get("data"), path)
        return verify_assertion(
            value, assertion_operator, assertion_expected, f"GraphQL data '{path or 'data'}'", message
        )

    @keyword
    def get_graphql_errors(
        self,
        response: dict,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        message: Optional[str] = None,
    ) -> list:
        """Return the whole ``errors`` array, optionally asserting on it.

        Arguments:
        - ``response``: Response returned by an executing keyword with ``expect_errors=True``.
        - ``assertion_operator``: Operator to check the array with, such as ``==`` for a count
          via ``len``, or ``contains``.
        - ``assertion_expected``: Value the operator compares against.
        - ``message``: Custom message used when the assertion fails.

        Returns: List of error dictionaries, empty when the response carried none.

        Example:
        | ${errors}    Get Graphql Errors    ${response}
        | Length Should Be    ${errors}    1
        """
        errors = self._errors(response)
        return verify_assertion(errors, assertion_operator, assertion_expected, "GraphQL errors", message)

    @keyword
    def get_graphql_error_messages(
        self,
        response: dict,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        message: Optional[str] = None,
    ) -> list[str]:
        """Return the ``message`` of every error, optionally asserting on the list.

        Arguments:
        - ``response``: Response returned by an executing keyword with ``expect_errors=True``.
        - ``assertion_operator``: Operator to check the list with.
        - ``assertion_expected``: Value the operator compares against.
        - ``message``: Custom message used when the assertion fails.

        Returns: List of error messages.

        Example:
        | Get Graphql Error Messages    ${response}    contains    User is not authenticated
        """
        messages = [str(error.get("message", "")) for error in self._errors(response)]
        return verify_assertion(messages, assertion_operator, assertion_expected, "GraphQL error messages", message)

    @keyword
    def get_graphql_error_codes(
        self,
        response: dict,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        message: Optional[str] = None,
    ) -> list[str]:
        """Return the ``extensions.code`` of every error, optionally asserting on the list.

        The code is the part of an error worth asserting on: it is the piece servers keep
        stable, while the message is prose that changes. Errors without a code are skipped.

        Arguments:
        - ``response``: Response returned by an executing keyword with ``expect_errors=True``.
        - ``assertion_operator``: Operator to check the list with.
        - ``assertion_expected``: Value the operator compares against.
        - ``message``: Custom message used when the assertion fails.

        Returns: List of error codes.

        Example:
        | Get Graphql Error Codes    ${response}    ==    ['UNAUTHENTICATED']
        """
        codes = [
            str((error.get("extensions") or {}).get("code"))
            for error in self._errors(response)
            if (error.get("extensions") or {}).get("code") is not None
        ]
        return verify_assertion(codes, assertion_operator, assertion_expected, "GraphQL error codes", message)

    @keyword
    def get_graphql_extensions(
        self,
        response: dict,
        path: Optional[str] = None,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        message: Optional[str] = None,
    ) -> Any:
        """Return a value out of the top-level ``extensions`` map, optionally asserting on it.

        Servers use ``extensions`` for tracing, query cost and cache hints. It is the part of
        a response nothing else reads, and the only place those live.

        Arguments:
        - ``response``: Response returned by an executing keyword.
        - ``path``: Dotted path below ``extensions``. Omit it to get the whole map.
        - ``assertion_operator``: Operator to check the value with.
        - ``assertion_expected``: Value the operator compares against.
        - ``message``: Custom message used when the assertion fails.

        Returns: The value at the path.

        Example:
        | Get Graphql Extensions    ${response}    cost.actual    <    100
        """
        value = resolve_path(response.get("extensions"), path)
        return verify_assertion(
            value, assertion_operator, assertion_expected, f"GraphQL extensions '{path or 'extensions'}'", message
        )

    # ----------------------------------------------------------------- #
    # Asserting
    # ----------------------------------------------------------------- #

    @keyword
    def response_should_have_no_errors(self, response: dict) -> None:
        """Fail when the response carries any error.

        Only needed after an executing keyword was given ``expect_errors=True``, since
        otherwise the executing keyword has already failed on them.

        Arguments:
        - ``response``: Response to check.

        Example:
        | Response Should Have No Errors    ${response}
        """
        errors = self._errors(response)
        if errors:
            raise AssertionError(f"Expected no GraphQL errors, but got {len(errors)}:\n{describe_errors(errors)}")

    @keyword
    def response_should_have_errors(self, response: dict, count: Optional[int] = None) -> None:
        """Fail unless the response carries errors.

        Arguments:
        - ``response``: Response to check.
        - ``count``: Exact number of errors expected, or None for at least one.

        Example:
        | Response Should Have Errors    ${response}
        | Response Should Have Errors    ${response}    count=2
        """
        errors = self._errors(response)
        if not errors:
            raise AssertionError("Expected the GraphQL response to carry errors, but it carried none.")
        if count is not None and len(errors) != count:
            raise AssertionError(
                f"Expected {count} GraphQL error(s), but got {len(errors)}:\n{describe_errors(errors)}"
            )

    @keyword
    def error_should_exist_at_path(
        self,
        response: dict,
        path: str,
        code: Optional[str] = None,
        message_contains: Optional[str] = None,
    ) -> dict:
        """Fail unless an error names ``path`` as the field it happened at.

        The ``path`` of an error is what identifies which field failed, and it is the only
        part of a partial response that says why ``data`` has a null in it. Neither the
        message nor the status code carries that.

        Arguments:
        - ``response``: Response to check.
        - ``path``: Dotted field path, as in ``user.avatar``. List positions are numbers.
        - ``code``: Value ``extensions.code`` has to have, when given.
        - ``message_contains``: Text the error message has to contain, when given.

        Returns: The matching error, so further checks can be made on it.

        Example:
        | Error Should Exist At Path    ${response}    user.avatar    code=FORBIDDEN
        """
        errors = self._errors(response)
        at_path = [error for error in errors if format_error_path(error) == path]
        if not at_path:
            seen = ", ".join(format_error_path(error) or "(no path)" for error in errors) or "none"
            raise AssertionError(f"No GraphQL error at path '{path}'. Errors were reported at: {seen}.")
        for error in at_path:
            if code is not None and (error.get("extensions") or {}).get("code") != code:
                continue
            if message_contains is not None and message_contains not in str(error.get("message", "")):
                continue
            return error
        raise AssertionError(
            f"An error was reported at path '{path}', but none of them matched.\n{describe_errors(at_path)}"
        )

    @keyword
    def response_should_have_partial_data(self, response: dict) -> None:
        """Fail unless the response carries both data and errors.

        A partial response is the case a status code hides most thoroughly: the server
        answered 200, filled in every field it could, and nulled the one that failed. Use
        this where that is the documented behaviour rather than a fault.

        Arguments:
        - ``response``: Response to check.

        Example:
        | ${response}    Execute Query    get_user.graphql    expect_errors=True
        | Response Should Have Partial Data    ${response}
        | Error Should Exist At Path    ${response}    user.avatar
        """
        errors = self._errors(response)
        data = response.get("data")
        if data is None:
            raise AssertionError("Expected partial data, but 'data' is null.")
        if not errors:
            raise AssertionError("Expected partial data, but the response carried no errors.")

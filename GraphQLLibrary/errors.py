from typing import Any, Optional


class GraphQLResponseError(RuntimeError):
    """Raised when a GraphQL response carries a non-empty ``errors`` array.

    Named for the response rather than the protocol so it does not read as, or shadow,
    ``graphql.GraphQLError`` from graphql-core, which models a single error entry.

    The whole response is kept on the exception. A test that wants to inspect the errors
    instead of failing on them passes ``expect_errors=True`` to the executing keyword, but
    a suite that catches this exception in Python still has everything the server sent.
    """

    def __init__(
        self,
        message: str,
        errors: Optional[list] = None,
        data: Optional[Any] = None,
        extensions: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.errors: list = errors or []
        self.data = data
        self.extensions: dict = extensions or {}

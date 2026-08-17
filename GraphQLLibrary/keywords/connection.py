from typing import Any, cast, Optional

from assertionengine import AssertionOperator, verify_assertion
from gql import Client
from gql.transport.requests import RequestsHTTPTransport
from robot.api import logger
from robot.api.deco import keyword

from GraphQLLibrary._types import OptionalCredential, reveal
from GraphQLLibrary.session_pool import GraphQLSession, SessionManager


class ConnectionKeywords:
    """
    Keywords for opening, selecting and closing GraphQL endpoints.
    """

    def __init__(self, session_manager: SessionManager) -> None:
        """
        Initializes the connection keywords.

        Arguments:
        - ``session_manager``: Holds the pool of open endpoints.
        """
        self.session_manager = session_manager

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _build_headers(self, headers: Optional[dict], token: Optional[str]) -> dict:
        """Merge an explicit header dictionary with a bearer token, token last."""
        merged = dict(headers or {})
        if token is not None:
            merged["Authorization"] = f"Bearer {token}"
        return merged

    # ----------------------------------------------------------------- #
    # Sessions
    # ----------------------------------------------------------------- #

    @keyword
    def create_graphql_session(
        self,
        url: str,
        alias: str = "default",
        headers: Optional[dict] = None,
        token: OptionalCredential = None,
        timeout: Optional[int] = None,
        verify: bool = True,
        retries: int = 0,
        http_session: Optional[Any] = None,
    ) -> str:
        """Open a GraphQL endpoint and store it in the session pool under ``alias``.

        The endpoint is contacted lazily: this keyword builds the client and the HTTP
        session, but the first request is only sent when a query is executed. A wrong URL
        therefore fails on `Execute Query`, not here.

        Arguments:
        - ``url``: Full URL of the GraphQL endpoint, including the path, usually ``/graphql``.
        - ``alias``: Name this session is addressed by. Reusing a name replaces the session.
        - ``headers``: Headers sent with every request on this session.
        - ``token``: Bearer token, added as an ``Authorization`` header. Accepts a Robot
          Framework ``Secret`` on Robot Framework 7.4 and later, which keeps it out of the log.
        - ``timeout``: Seconds to wait for a response, or None for no timeout.
        - ``verify``: Whether TLS certificates are verified. Only turn this off against a
          test server using a self-signed certificate.
        - ``retries``: How often a failed request is retried, with backoff. Applies to
          connection errors and to 429, 500, 502, 503 and 504.
        - ``http_session``: An existing ``requests.Session`` to send on. Use it to share
          cookies, authentication or adapters with HTTP calls made elsewhere. The session is
          left open when this session is deleted, because this library did not open it.

        Returns: The alias, so it can be assigned in one line.

        Example:
        | Create Graphql Session    https://api.example.com/graphql    token=${API_TOKEN}
        | Create Graphql Session    http://localhost:8000/graphql    alias=local
        """
        plain_token = reveal(token)
        all_headers = self._build_headers(headers, plain_token)

        # A caller-supplied session carries state this library knows nothing about, so it is
        # never shared between aliases implicitly. None as the key means "always build one".
        cache_key = (
            None
            if http_session is not None
            else (url, tuple(sorted(all_headers.items())), timeout, verify, retries)
        )

        def create_client() -> Client:
            transport = RequestsHTTPTransport(
                url=url,
                headers=all_headers,
                timeout=timeout,
                verify=verify,
                retries=retries,
            )
            client = Client(transport=transport)
            # Connect once here rather than per request. Client.execute would otherwise open
            # and close a requests.Session around every call, discarding the connection pool
            # and any cookie the server set.
            client.connect_sync()
            if http_session is not None:
                # connect_sync just created a session; swap in the caller's. It cannot be set
                # beforehand, because RequestsHTTPTransport.connect raises when it finds one.
                if transport.session is not None:
                    transport.session.close()
                transport.session = http_session
            return client

        client = self.session_manager.get_or_create_client(cache_key, create_client)
        session = GraphQLSession(
            alias=alias,
            url=url,
            client=client,
            headers=all_headers,
            owns_http_session=http_session is None,
            cache_key=cache_key,
        )
        self.session_manager.add_to_session_pool(session)
        self.session_manager.active_alias = alias
        logger.info(f"Created GraphQL session '{alias}' for {url}.")
        return alias

    @keyword
    def delete_graphql_session(self, alias: Optional[str] = None) -> None:
        """Close one session and remove it from the pool.

        The underlying client stays open when another alias still shares it.

        Arguments:
        - ``alias``: Session to delete. Defaults to the active session.

        Example:
        | Delete Graphql Session
        | Delete Graphql Session    alias=local
        """
        self.session_manager.remove_from_session_pool(self._resolve(alias))

    @keyword
    def delete_all_graphql_sessions(self) -> None:
        """Close every session in the pool.

        Suitable as a suite teardown.

        Example:
        | Delete All Graphql Sessions
        """
        self.session_manager.clear_session_pool()

    @keyword
    def switch_graphql_session(self, alias: str) -> str:
        """Make ``alias`` the session that keywords use when they are called without one.

        Arguments:
        - ``alias``: Session to switch to. It has to be in the pool already.

        Returns: The alias that was active before the switch, so it can be restored.

        Raises: ``KeyError`` when the alias is not in the pool.

        Example:
        | ${previous}    Switch Graphql Session    local
        """
        if alias not in self.session_manager.session_pool:
            raise KeyError(f"Alias '{alias}' not found in the session pool.")
        previous = self.session_manager.active_alias
        self.session_manager.active_alias = alias
        logger.info(f"Switched the active GraphQL session to '{alias}'.")
        return previous

    @keyword
    def list_graphql_sessions(
        self,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        message: Optional[str] = None,
    ) -> list[str]:
        """Return the aliases of every session in the pool, optionally asserting on them.

        Arguments:
        - ``assertion_operator``: Operator to check the list with, such as ``contains``.
        - ``assertion_expected``: Value the operator compares against.
        - ``message``: Custom message used when the assertion fails.

        Example:
        | ${aliases}    List Graphql Sessions
        | List Graphql Sessions    contains    local
        """
        aliases = self.session_manager.list_session_pool()
        return verify_assertion(aliases, assertion_operator, assertion_expected, "GraphQL sessions", message)

    @keyword
    def get_active_graphql_session(
        self,
        assertion_operator: Optional[AssertionOperator] = None,
        assertion_expected: Any = None,
        message: Optional[str] = None,
    ) -> str:
        """Return the alias keywords use when they are called without one.

        The alias is returned whether or not a session is open under it, which is what makes
        it usable in a teardown that has to cope with a failed setup.

        Arguments:
        - ``assertion_operator``: Operator to check the alias with, such as ``==``.
        - ``assertion_expected``: Value the operator compares against.
        - ``message``: Custom message used when the assertion fails.

        Example:
        | ${alias}    Get Active Graphql Session
        | Get Active Graphql Session    ==    local
        """
        alias = self.session_manager.active_alias
        return verify_assertion(alias, assertion_operator, assertion_expected, "Active GraphQL session", message)

    @keyword
    def graphql_session_should_exist(self, alias: Optional[str] = None) -> None:
        """Fail unless a session is open under ``alias``.

        Arguments:
        - ``alias``: Session to check. Defaults to the active session.

        Example:
        | Graphql Session Should Exist    local
        """
        resolved = self._resolve(alias)
        if resolved not in self.session_manager.session_pool:
            raise AssertionError(f"No GraphQL session is open under alias '{resolved}'.")

    @keyword
    def set_graphql_headers(self, headers: dict, alias: Optional[str] = None) -> dict:
        """Merge ``headers`` into the headers sent on a session from now on.

        Use it for a token obtained by a login mutation, rather than opening a second
        session against the same endpoint.

        Arguments:
        - ``headers``: Headers to add or replace. Existing headers not named here are kept.
        - ``alias``: Session to change. Defaults to the active session.

        Returns: The full header dictionary after the merge.

        Example:
        | ${token}    Get Graphql Data    ${response}    login.token
        | Set Graphql Headers    {"Authorization": "Bearer ${token}"}

        *Note*: the headers belong to the client, so a session sharing its client with
        another alias changes both. Pass a distinct ``token`` or header set to
        `Create Graphql Session` when the two have to stay separate.
        """
        session = self.get_session(alias)
        session.headers.update(headers)
        transport = cast(RequestsHTTPTransport, session.client.transport)
        transport.headers = session.headers
        return session.headers

    # ----------------------------------------------------------------- #
    # Shared with the other keyword classes
    # ----------------------------------------------------------------- #

    def _resolve(self, alias: Optional[str] = None) -> str:
        """Return ``alias``, or the active alias when None."""
        return self.session_manager.active_alias if alias is None else alias

    def get_session(self, alias: Optional[str] = None) -> GraphQLSession:
        """Return the pooled session for ``alias``, raising if nothing is open under it."""
        resolved = self._resolve(alias)
        try:
            return self.session_manager.session_pool[resolved]
        except KeyError:
            raise KeyError(
                f"Alias '{resolved}' not found in the session pool. "
                f"Open it with `Create Graphql Session` first."
            )

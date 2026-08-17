from dataclasses import dataclass, field
from typing import Any, Callable

from gql import Client
from robot.api import logger


@dataclass
class GraphQLSession:
    """One pooled endpoint: the alias a suite refers to, and the client behind it."""

    alias: str
    url: str
    client: Client
    headers: dict = field(default_factory=dict)
    owns_http_session: bool = True
    """False when the caller supplied their own ``requests.Session``, which this library
    must then leave open on teardown. See `SessionManager.close_client`."""

    def execute(self, request: Any) -> Any:
        """Send one request over the connection opened when this session was created.

        Deliberately not ``client.execute``, which opens and closes a connection around
        every call and would therefore reject the already-connected transport this library
        keeps. ``client.session`` is the connected session ``connect_sync`` installed.

        :param request: GraphQLRequest to send
        :return: ExecutionResult, including any ``errors`` and ``extensions``
        """
        return self.client.session.execute(request, get_execution_result=True)


class SessionManager:
    """
    Manages the pool of GraphQL endpoints.

    Aliases map to sessions, and several aliases may share one underlying ``gql.Client``.
    A client is only closed once no pooled session still uses it.
    """

    def __init__(self) -> None:
        self.session_pool: dict[str, GraphQLSession] = {}
        self.active_alias: str = "default"
        self.client_cache: dict[Any, Client] = {}

    def get_or_create_client(self, cache_key: Any, create_client: Callable[[], Client]) -> Client:
        """
        Return the client for ``cache_key``, creating it with ``create_client`` if needed.

        Reusing a client means several aliases against the same endpoint share one HTTP
        connection pool, and one set of cookies, instead of opening one each.

        :param cache_key: Value identifying the connection parameters, or None to never reuse
        :param create_client: Callable building a new client when none is cached
        :return: Client instance
        """
        if cache_key is None:  # a caller-supplied http session is never shared implicitly
            return create_client()
        client = self.client_cache.get(cache_key)
        if client is not None:
            logger.debug(f"Reusing the existing client for {cache_key!r}.")
            return client
        client = create_client()
        self.client_cache[cache_key] = client
        return client

    def add_to_session_pool(self, session: GraphQLSession) -> None:
        """
        Add a session to the pool under its alias, replacing any session already there.

        :param session: GraphQLSession to store
        """
        existing = self.session_pool.pop(session.alias, None)
        if existing is not None:
            logger.warn(f"Session with alias '{session.alias}' already exists. Overwriting it.")
            self._close_if_unused(existing)
        self.session_pool[session.alias] = session
        logger.info(f"Added session with alias '{session.alias}' to the pool.")

    def remove_from_session_pool(self, alias: str) -> None:
        """
        Remove a session from the pool using its alias, closing it if nothing else shares it.

        :param alias: Alias of the session to remove
        """
        try:
            session = self.session_pool.pop(alias)
        except KeyError:
            raise KeyError(f"Alias '{alias}' not found in the session pool.")
        self._close_if_unused(session)
        logger.info(f"Removed session with alias '{alias}' from the pool.")

    def clear_session_pool(self) -> None:
        """
        Close and drop every session in the pool.
        """
        sessions = list(self.session_pool.values())
        self.session_pool.clear()
        seen: list[Client] = []
        for session in sessions:
            if any(session.client is other for other in seen):
                continue
            seen.append(session.client)
            self.close_client(session)
        logger.info("Cleared all sessions from the pool.")

    def list_session_pool(self) -> list[str]:
        """
        List all aliases in the session pool.

        :return: List of aliases
        """
        return list(self.session_pool.keys())

    def close_client(self, session: GraphQLSession) -> None:
        """
        Close the session's client and drop it from the cache.

        When the caller supplied the underlying ``requests.Session``, it is detached first.
        ``RequestsHTTPTransport.close`` closes whatever session it holds, and closing a
        session this library did not open would break the code that did.

        :param session: GraphQLSession whose client should be closed
        """
        if not session.owns_http_session:
            transport = getattr(session.client, "transport", None)
            if transport is not None:
                transport.session = None
        self._forget_client(session.client)
        session.client.close_sync()

    def _close_if_unused(self, session: GraphQLSession) -> None:
        """Close the session's client unless another pooled alias still shares it."""
        if any(other.client is session.client for other in self.session_pool.values()):
            logger.debug("Client left open because another alias still uses it.")
            return
        self.close_client(session)

    def _forget_client(self, client: Client) -> None:
        for key, cached in list(self.client_cache.items()):
            if cached is client:
                del self.client_cache[key]

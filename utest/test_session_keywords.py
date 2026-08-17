import pytest
import requests

from GraphQLLibrary import GraphQLLibrary
from utest.conftest import reply, URL

OTHER_URL = "http://other.test/graphql"


class TestSessionPool:
    def test_a_session_is_created_under_the_default_alias(self, library_without_session):
        assert library_without_session.create_graphql_session(URL) == "default"
        assert library_without_session.list_graphql_sessions() == ["default"]

    def test_several_endpoints_can_be_open_at_once(self, library_without_session):
        library_without_session.create_graphql_session(URL, alias="one")
        library_without_session.create_graphql_session(OTHER_URL, alias="two")
        assert library_without_session.list_graphql_sessions() == ["one", "two"]

    def test_the_newest_session_becomes_the_active_one(self, library_without_session):
        library_without_session.create_graphql_session(URL, alias="one")
        library_without_session.create_graphql_session(OTHER_URL, alias="two")
        assert library_without_session.get_active_graphql_session() == "two"

    def test_switching_returns_the_previous_alias(self, library_without_session):
        library_without_session.create_graphql_session(URL, alias="one")
        library_without_session.create_graphql_session(OTHER_URL, alias="two")
        assert library_without_session.switch_graphql_session("one") == "two"
        assert library_without_session.get_active_graphql_session() == "one"

    def test_switching_to_an_alias_that_is_not_open_fails(self, library_without_session):
        with pytest.raises(KeyError, match="nope"):
            library_without_session.switch_graphql_session("nope")

    def test_a_session_can_be_deleted(self, library_without_session):
        library_without_session.create_graphql_session(URL, alias="one")
        library_without_session.delete_graphql_session("one")
        assert library_without_session.list_graphql_sessions() == []

    def test_deleting_an_alias_that_is_not_open_fails(self, library_without_session):
        with pytest.raises(KeyError, match="nope"):
            library_without_session.delete_graphql_session("nope")

    def test_all_sessions_can_be_deleted_at_once(self, library_without_session):
        library_without_session.create_graphql_session(URL, alias="one")
        library_without_session.create_graphql_session(OTHER_URL, alias="two")
        library_without_session.delete_all_graphql_sessions()
        assert library_without_session.list_graphql_sessions() == []

    def test_reusing_an_alias_replaces_the_session(self, library_without_session):
        library_without_session.create_graphql_session(URL, alias="one")
        library_without_session.create_graphql_session(OTHER_URL, alias="one")
        assert library_without_session.list_graphql_sessions() == ["one"]

    def test_the_active_alias_is_returned_even_with_nothing_open(self, library_without_session):
        """A teardown has to be able to run after a setup that never connected."""
        assert library_without_session.get_active_graphql_session() == "default"

    def test_session_should_exist_fails_when_nothing_is_open(self, library_without_session):
        with pytest.raises(AssertionError, match="No GraphQL session"):
            library_without_session.graphql_session_should_exist()

    def test_session_should_exist_passes_for_an_open_session(self, library):
        library.graphql_session_should_exist()


class TestClientSharing:
    def test_two_aliases_on_the_same_endpoint_share_one_client(self, library_without_session):
        """Sharing is what keeps one connection pool, and one cookie jar, per endpoint."""
        library_without_session.create_graphql_session(URL, alias="one")
        library_without_session.create_graphql_session(URL, alias="two")
        pool = library_without_session.session_manager.session_pool
        assert pool["one"].client is pool["two"].client

    def test_different_headers_get_different_clients(self, library_without_session):
        library_without_session.create_graphql_session(URL, alias="one", token="a")
        library_without_session.create_graphql_session(URL, alias="two", token="b")
        pool = library_without_session.session_manager.session_pool
        assert pool["one"].client is not pool["two"].client

    def test_a_shared_client_survives_deleting_one_of_its_aliases(self, library_without_session, mocked_responses):
        library_without_session.create_graphql_session(URL, alias="one")
        library_without_session.create_graphql_session(URL, alias="two")
        library_without_session.delete_graphql_session("one")
        reply(mocked_responses, data={"ping": "pong"})
        assert library_without_session.execute_query("{ ping }", alias="two").data.ping == "pong"


class TestHeaders:
    def test_a_token_becomes_a_bearer_header(self, library_without_session, mocked_responses):
        library_without_session.create_graphql_session(URL, token="abc123")
        reply(mocked_responses, data={"ping": "pong"})
        library_without_session.execute_query("{ ping }")
        assert mocked_responses.calls[0].request.headers["Authorization"] == "Bearer abc123"

    def test_headers_can_be_added_after_the_session_was_created(self, library, mocked_responses):
        library.set_graphql_headers({"X-Tenant": "acme"})
        reply(mocked_responses, data={"ping": "pong"})
        library.execute_query("{ ping }")
        assert mocked_responses.calls[0].request.headers["X-Tenant"] == "acme"

    def test_setting_headers_keeps_the_ones_already_there(self, library_without_session):
        library_without_session.create_graphql_session(URL, headers={"X-One": "1"})
        merged = library_without_session.set_graphql_headers({"X-Two": "2"})
        assert merged == {"X-One": "1", "X-Two": "2"}


class TestSuppliedHttpSession:
    """Interop: the caller's requests.Session, so cookies and adapters can be shared."""

    def test_the_supplied_session_is_used(self, library_without_session, mocked_responses):
        http_session = requests.Session()
        http_session.headers["X-From-Caller"] = "yes"
        library_without_session.create_graphql_session(URL, http_session=http_session)
        reply(mocked_responses, data={"ping": "pong"})
        library_without_session.execute_query("{ ping }")
        assert mocked_responses.calls[0].request.headers["X-From-Caller"] == "yes"

    def test_the_supplied_session_is_left_open_on_teardown(self, library_without_session):
        """Closing a session this library did not open would break whatever else uses it."""
        http_session = requests.Session()
        library_without_session.create_graphql_session(URL, http_session=http_session)
        library_without_session.delete_all_graphql_sessions()
        assert http_session.adapters, "the caller's session was closed"

    def test_a_supplied_session_is_never_shared_between_aliases(self, library_without_session):
        http_session = requests.Session()
        library_without_session.create_graphql_session(URL, alias="one", http_session=http_session)
        library_without_session.create_graphql_session(URL, alias="two", http_session=http_session)
        pool = library_without_session.session_manager.session_pool
        assert pool["one"].client is not pool["two"].client


class TestOwnedHttpSession:
    def test_the_libraries_own_session_is_closed_on_teardown(self, library_without_session):
        library_without_session.create_graphql_session(URL)
        transport = library_without_session.session_manager.session_pool["default"].client.transport
        library_without_session.delete_all_graphql_sessions()
        assert transport.session is None


class TestLibraryInstance:
    def test_the_library_reports_its_scope_and_version(self):
        assert GraphQLLibrary.ROBOT_LIBRARY_SCOPE == "GLOBAL"
        assert GraphQLLibrary.ROBOT_LIBRARY_VERSION

    def test_every_keyword_is_documented(self):
        """libdoc is the only manual this library ships, so an undocumented keyword is a gap."""
        library = GraphQLLibrary()
        undocumented = [name for name in library.get_keyword_names() if not library.get_keyword_documentation(name)]
        assert undocumented == []

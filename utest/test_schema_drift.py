"""Tests for comparing a live schema against a committed snapshot."""

import pytest
from assertionengine import AssertionOperator

from utest.conftest import introspection, reply, SCHEMA_SDL

# The live schema with User.name taken away, standing in for a snapshot written before the
# field was removed. `find_breaking_changes` reads it in that direction: snapshot, then live.
SDL_WITH_EXTRA_FIELD = SCHEMA_SDL.replace("    name: String!\n", "    name: String!\n    wasHere: String\n")
SDL_WITHOUT_PING = SCHEMA_SDL.replace("    ping: String!\n", "")


@pytest.fixture
def snapshot(tmp_path):
    """A path to write snapshots to, per test."""
    return str(tmp_path / "schema.graphql")


class TestSavingASnapshot:
    def test_it_writes_readable_sdl(self, library, mocked_responses, snapshot):
        reply(mocked_responses, introspection())
        library.save_schema_snapshot(snapshot)
        with open(snapshot, encoding="utf-8") as file:
            sdl = file.read()
        assert "type User" in sdl
        assert 'deprecated(reason: "Use contact instead.")' in sdl

    def test_it_returns_the_path(self, library, mocked_responses, snapshot):
        reply(mocked_responses, introspection())
        assert library.save_schema_snapshot(snapshot) == snapshot

    def test_it_creates_missing_directories(self, library, mocked_responses, tmp_path):
        reply(mocked_responses, introspection())
        nested = str(tmp_path / "a" / "b" / "schema.graphql")
        library.save_schema_snapshot(nested)
        assert library.get_schema_breaking_changes(nested) == []


class TestNothingChanged:
    def test_a_round_trip_reports_no_changes(self, library, mocked_responses, snapshot):
        reply(mocked_responses, introspection())
        library.save_schema_snapshot(snapshot)
        assert library.get_schema_breaking_changes(snapshot) == []
        assert library.get_schema_dangerous_changes(snapshot) == []
        library.schema_should_have_no_breaking_changes(snapshot)


class TestBreakingChanges:
    def test_a_removed_field_is_breaking(self, library, mocked_responses, snapshot):
        reply(mocked_responses, introspection())
        with open(snapshot, "w", encoding="utf-8") as file:
            file.write(SDL_WITH_EXTRA_FIELD)
        changes = library.get_schema_breaking_changes(snapshot)
        assert any("FIELD_REMOVED" in change and "wasHere" in change for change in changes)

    def test_the_assertion_keyword_lists_them(self, library, mocked_responses, snapshot):
        reply(mocked_responses, introspection())
        with open(snapshot, "w", encoding="utf-8") as file:
            file.write(SDL_WITH_EXTRA_FIELD)
        with pytest.raises(AssertionError, match="wasHere"):
            library.schema_should_have_no_breaking_changes(snapshot)

    def test_an_added_field_is_not_breaking(self, library, mocked_responses, snapshot):
        """The snapshot lacks ping, so the live schema only gained a field."""
        reply(mocked_responses, introspection())
        with open(snapshot, "w", encoding="utf-8") as file:
            file.write(SDL_WITHOUT_PING)
        assert library.get_schema_breaking_changes(snapshot) == []

    def test_changes_take_an_assertion_operator(self, library, mocked_responses, snapshot):
        reply(mocked_responses, introspection())
        library.save_schema_snapshot(snapshot)
        library.get_schema_breaking_changes(snapshot, AssertionOperator["=="], [])

    def test_a_failing_assertion_names_the_subject(self, library, mocked_responses, snapshot):
        reply(mocked_responses, introspection())
        library.save_schema_snapshot(snapshot)
        with pytest.raises(AssertionError, match="GraphQL breaking changes"):
            library.get_schema_breaking_changes(snapshot, AssertionOperator["contains"], "absent")


class TestDangerousChanges:
    def test_a_new_enum_value_is_dangerous_not_breaking(self, library, mocked_responses, snapshot):
        """A suite switching on the enum may not handle the new value, but nothing breaks."""
        live = """
        enum Sport { CYCLING RUNNING }
        type Query { sport: Sport }
        """
        older = """
        enum Sport { CYCLING }
        type Query { sport: Sport }
        """
        reply(mocked_responses, introspection(live))
        with open(snapshot, "w", encoding="utf-8") as file:
            file.write(older)
        assert library.get_schema_breaking_changes(snapshot) == []
        dangerous = library.get_schema_dangerous_changes(snapshot)
        assert any("VALUE_ADDED_TO_ENUM" in change and "RUNNING" in change for change in dangerous)


class TestABadSnapshot:
    def test_a_missing_file_is_a_bad_call(self, library, mocked_responses, tmp_path):
        reply(mocked_responses, introspection())
        with pytest.raises(ValueError, match="not found"):
            library.get_schema_breaking_changes(str(tmp_path / "absent.graphql"))

    def test_a_file_that_is_not_sdl_is_a_bad_call(self, library, mocked_responses, snapshot):
        reply(mocked_responses, introspection())
        with open(snapshot, "w", encoding="utf-8") as file:
            file.write("this is not a schema")
        with pytest.raises(ValueError, match="could not be read as SDL"):
            library.get_schema_breaking_changes(snapshot)

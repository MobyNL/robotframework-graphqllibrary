"""Tests for the tool that builds the published documentation index.

This code runs once per release, in a workflow, where a mistake is only noticed after the
fact and shows up as a broken or misleading documentation site. That is a good reason to
test it here rather than by publishing and looking.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_docs_index  # noqa: E402 - needs the path above


class TestUpdateVersions:
    def test_the_first_release_becomes_the_latest(self):
        versions = build_docs_index.update_versions([], "0.1.0", is_release=True)
        assert versions[0]["version"] == "0.1.0"
        assert versions[0]["tags"] == ["latest"]

    def test_a_newer_release_takes_the_latest_tag_over(self):
        versions = build_docs_index.update_versions([], "0.1.0", is_release=True)
        versions = build_docs_index.update_versions(versions, "0.2.0", is_release=True)
        tags = {version["path"]: version["tags"] for version in versions}
        assert tags["0.2.0"] == ["latest"]
        assert tags["0.1.0"] == []

    def test_an_older_release_published_late_does_not_steal_latest(self):
        """Backfilling 0.1.0 after 0.2.0 is out must not move the latest tag back."""
        versions = build_docs_index.update_versions([], "0.2.0", is_release=True)
        versions = build_docs_index.update_versions(versions, "0.1.0", is_release=True)
        tags = {version["path"]: version["tags"] for version in versions}
        assert tags["0.2.0"] == ["latest"]
        assert tags["0.1.0"] == []

    def test_versions_are_compared_as_numbers_not_as_text(self):
        """As text, '0.10.0' sorts before '0.9.0', which would be wrong."""
        versions = build_docs_index.update_versions([], "0.9.0", is_release=True)
        versions = build_docs_index.update_versions(versions, "0.10.0", is_release=True)
        tags = {version["path"]: version["tags"] for version in versions}
        assert tags["0.10.0"] == ["latest"]
        assert tags["0.9.0"] == []

    def test_the_development_build_is_never_the_latest(self):
        versions = build_docs_index.update_versions([], "0.2.0", is_release=True)
        versions = build_docs_index.update_versions(versions, "dev", is_release=False)
        tags = {version["path"]: version["tags"] for version in versions}
        assert tags["dev"] == ["unreleased"]
        assert tags["0.2.0"] == ["latest"]

    def test_publishing_the_same_path_twice_replaces_its_entry(self):
        """main is published on every push, and must not accumulate entries."""
        versions = build_docs_index.update_versions([], "dev", is_release=False)
        versions = build_docs_index.update_versions(versions, "dev", is_release=False)
        assert len(versions) == 1

    def test_a_release_published_twice_replaces_its_entry(self):
        versions = build_docs_index.update_versions([], "0.2.0", is_release=True)
        versions = build_docs_index.update_versions(versions, "0.2.0", is_release=True)
        assert len(versions) == 1
        assert versions[0]["tags"] == ["latest"]


class TestIsLatest:
    def test_the_newest_release_is_the_latest(self):
        versions = build_docs_index.update_versions([], "0.2.0", is_release=True)
        assert build_docs_index.is_latest(versions, "0.2.0")

    def test_an_older_release_is_not(self):
        versions = build_docs_index.update_versions([], "0.2.0", is_release=True)
        versions = build_docs_index.update_versions(versions, "0.1.0", is_release=True)
        assert not build_docs_index.is_latest(versions, "0.1.0")

    def test_the_development_build_is_not(self):
        versions = build_docs_index.update_versions([], "dev", is_release=False)
        assert not build_docs_index.is_latest(versions, "dev")

    def test_a_path_that_was_never_published_is_not(self):
        assert not build_docs_index.is_latest([], "0.2.0")


class TestRendering:
    def test_versions_are_listed_newest_first_with_development_above_them(self):
        versions = [
            {"version": "0.1.0", "path": "0.1.0", "tags": []},
            {"version": "main (unreleased)", "path": "dev", "tags": ["unreleased"]},
            {"version": "0.2.0", "path": "0.2.0", "tags": ["latest"]},
        ]
        versions.sort(key=build_docs_index._sort_key)
        assert [version["path"] for version in versions] == ["dev", "0.2.0", "0.1.0"]

    def test_each_version_links_to_its_own_page(self):
        page = build_docs_index.render([{"version": "0.2.0", "path": "0.2.0", "tags": ["latest"]}])
        assert 'href="0.2.0/GraphQLLibraryKeywords.html"' in page
        assert "latest" in page

    def test_an_empty_site_says_so_rather_than_rendering_nothing(self):
        assert "No documentation has been published" in build_docs_index.render([])

    def test_the_page_says_the_keyword_surface_can_still_change(self):
        """The library is below 1.0.0, and a reader on an older page should know that."""
        assert "below 1.0.0" in build_docs_index.render([])

    def test_version_names_are_escaped(self):
        """The name comes from a tag, and a tag can contain anything."""
        page = build_docs_index.render([{"version": "<script>", "path": "x", "tags": []}])
        assert "<script>" not in page
        assert "&lt;script&gt;" in page


class TestCommandLine:
    def test_a_first_run_creates_both_files(self, tmp_path):
        """The very first publish has no versions.json to read."""
        versions, index = tmp_path / "versions.json", tmp_path / "index.html"
        build_docs_index.main([str(versions), str(index), "--add", "0.2.0", "--release"])
        assert index.exists()
        assert json.loads(versions.read_text())[0]["path"] == "0.2.0"

    def test_a_later_run_keeps_what_was_published_before(self, tmp_path):
        versions, index = tmp_path / "versions.json", tmp_path / "index.html"
        build_docs_index.main([str(versions), str(index), "--add", "0.2.0", "--release"])
        build_docs_index.main([str(versions), str(index), "--add", "dev"])
        paths = {entry["path"] for entry in json.loads(versions.read_text())}
        assert paths == {"0.2.0", "dev"}
        assert 'href="0.2.0/GraphQLLibraryKeywords.html"' in index.read_text()

    def test_rendering_without_adding_anything_leaves_the_list_alone(self, tmp_path):
        versions, index = tmp_path / "versions.json", tmp_path / "index.html"
        build_docs_index.main([str(versions), str(index), "--add", "0.2.0", "--release"])
        before = versions.read_text()
        build_docs_index.main([str(versions), str(index)])
        assert versions.read_text() == before

    def test_asking_whether_a_version_is_the_latest_answers_through_the_exit_code(self, tmp_path):
        """The workflow branches on this, so the exit code is the interface."""
        versions, index = tmp_path / "versions.json", tmp_path / "index.html"
        build_docs_index.main([str(versions), str(index), "--add", "0.2.0", "--release"])
        build_docs_index.main([str(versions), str(index), "--add", "0.1.0", "--release"])
        assert build_docs_index.main([str(versions), "--is-latest", "0.2.0"]) == 0
        assert build_docs_index.main([str(versions), "--is-latest", "0.1.0"]) == 1

    def test_asking_writes_nothing(self, tmp_path):
        versions, index = tmp_path / "versions.json", tmp_path / "index.html"
        build_docs_index.main([str(versions), str(index), "--add", "0.2.0", "--release"])
        index.unlink()
        build_docs_index.main([str(versions), "--is-latest", "0.2.0"])
        assert not index.exists()

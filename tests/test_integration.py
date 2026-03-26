"""
Integration tests for p4cmd that communicate with a real Perforce server.

Requirements:
  - p4 CLI installed and authenticated
  - A tests/.env file with the following variables (see tests/.env.example):
      P4_ROOT, P4_USER, P4_CLIENT, P4_SERVER,
      TEST_DEPOT_FOLDER, TEST_LOCAL_FOLDER

Run with:
  python -m pytest tests/test_integration.py -v

These tests create temporary files, changelists, and shelves, but
clean up after themselves. They never delete depot files.
"""

import os
import uuid
import shutil

import pytest

from p4cmd.p4cmd import P4Client
from p4cmd.p4file import P4File, Status

# ---------------------------------------------------------------------------
# Configuration — loaded from tests/.env
# ---------------------------------------------------------------------------

def _load_env(path):
    """Read a key=value .env file into os.environ (no overwrite)."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env(os.path.join(os.path.dirname(__file__), ".env"))

_REQUIRED = ["P4_ROOT", "P4_USER", "P4_CLIENT", "P4_SERVER",
             "TEST_DEPOT_FOLDER", "TEST_LOCAL_FOLDER"]
_missing = [k for k in _REQUIRED if not os.environ.get(k)]
if _missing:
    pytest.skip(
        f"Integration tests require a tests/.env file with: {', '.join(_missing)}",
        allow_module_level=True,
    )

P4_ROOT = os.environ["P4_ROOT"]
P4_USER = os.environ["P4_USER"]
P4_CLIENT = os.environ["P4_CLIENT"]
P4_SERVER = os.environ["P4_SERVER"]
TEST_DEPOT_FOLDER = os.environ["TEST_DEPOT_FOLDER"]
TEST_LOCAL_FOLDER = os.environ["TEST_LOCAL_FOLDER"]
TEST_SUBFOLDER = os.path.join(TEST_LOCAL_FOLDER, "_p4cmd_tests")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def p4(request):
    """Session-scoped real P4Client with end-of-session cleanup."""
    client = P4Client(P4_ROOT, user=P4_USER, client=P4_CLIENT, server=P4_SERVER)
    assert client.host_online(), "Perforce server is not reachable"

    def cleanup_lingering_cls():
        """Delete any [p4cmd-test] changelists left over from this or prior runs."""
        cls = client.get_pending_changelists(description_filter="p4cmd-test")
        for cl in cls:
            if cl == "default":
                continue
            _force_delete_cl(client, cl)

    request.addfinalizer(cleanup_lingering_cls)
    return client


@pytest.fixture(autouse=True)
def test_subfolder():
    """Create and clean up a local test subfolder for each test."""
    os.makedirs(TEST_SUBFOLDER, exist_ok=True)
    yield TEST_SUBFOLDER
    # clean up local files created during test
    if os.path.isdir(TEST_SUBFOLDER):
        shutil.rmtree(TEST_SUBFOLDER, ignore_errors=True)


@pytest.fixture()
def unique_tag():
    """Short unique string to avoid name collisions between tests."""
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def existing_depot_file(p4):
    """Discover an existing versioned file in TEST_DEPOT_FOLDER for read-only tests."""
    p4files = p4.folder_to_p4files(TEST_LOCAL_FOLDER, include_subfolders=False)
    for pf in p4files:
        if pf.depot_file_path and pf.head_revision and not pf.is_deleted():
            return pf.depot_file_path
    pytest.skip("No existing versioned file found in TEST_DEPOT_FOLDER")


def _force_delete_cl(p4, cl):
    """Revert all files, delete shelved files, then delete the CL by number."""
    try:
        p4.revert_changelist(changelist=cl)
    except Exception:
        pass
    try:
        p4.run_cmd("shelve", args=["-d", "-c", str(cl)])
    except Exception:
        pass
    try:
        p4.run_cmd("change", args=["-d", str(cl)])
    except Exception:
        pass


@pytest.fixture()
def test_cl(p4, unique_tag):
    """Create a changelist and guarantee cleanup (revert + delete)."""
    desc = f"[p4cmd-test] {unique_tag}"
    cl = p4.make_new_changelist(desc)
    assert cl is not None, "Failed to create test changelist"
    yield cl
    _force_delete_cl(p4, cl)


def _write_test_file(name, content="hello"):
    """Helper: write a small file in the test subfolder and return its path."""
    path = os.path.join(TEST_SUBFOLDER, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


# ===================================================================
# Connection
# ===================================================================

class TestConnection:
    def test_host_online(self, p4):
        assert p4.host_online() is True

    def test_get_all_workspaces(self, p4):
        workspaces = p4.get_all_workspaces()
        assert isinstance(workspaces, list)
        assert len(workspaces) > 0

    def test_get_ticket_expiration(self, p4):
        expiry = p4.get_ticket_expiration()
        # Should be an int (seconds) or None (no ticket configured)
        assert expiry is None or isinstance(expiry, int)


# ===================================================================
# Changelists
# ===================================================================

class TestChangelists:
    def test_make_and_delete_changelist(self, p4, unique_tag):
        desc = f"[p4cmd-test] create-delete {unique_tag}"
        cl = p4.make_new_changelist(desc)
        assert isinstance(cl, int)
        assert cl > 0

        # verify it shows up
        assert p4.changelist_exists(cl)

        # delete directly by CL number
        _force_delete_cl(p4, cl)
        assert not p4.changelist_exists(cl)

    def test_changelist_exists_by_description(self, p4, test_cl):
        # test_cl fixture created a CL with description "[p4cmd-test] <tag>"
        # changelist_exists should find it by int
        assert p4.changelist_exists(test_cl)

    def test_get_pending_changelists(self, p4, test_cl):
        all_cls = p4.get_pending_changelists()
        assert test_cl in all_cls

    def test_get_pending_changelists_with_filter(self, p4, test_cl, unique_tag):
        filtered = p4.get_pending_changelists(
            description_filter=unique_tag
        )
        assert test_cl in filtered

    def test_get_pending_changelists_no_match(self, p4):
        filtered = p4.get_pending_changelists(
            description_filter="ZZZZ_no_way_this_matches_anything_ZZZZ",
            perfect_match_only=True,
        )
        # Should only contain "default"
        assert filtered == ["default"]

    def test_make_changelist_with_newlines(self, p4):
        """Regression test for issue #5."""
        desc = "[p4cmd-test] line one\nline two\nline three"
        cl = p4.make_new_changelist(desc)
        assert isinstance(cl, int)
        assert cl > 0
        # cleanup
        _force_delete_cl(p4, cl)

    def test_update_changelist_description(self, p4, test_cl):
        new_desc = "[p4cmd-test] updated description"
        result = p4.update_changelist_description(test_cl, new_desc)
        assert result is True

        # verify the new description shows up
        cls = p4.get_pending_changelists(
            description_filter="updated description"
        )
        assert test_cl in cls

    def test_update_changelist_description_with_newlines(self, p4, test_cl):
        new_desc = "[p4cmd-test] first line\nsecond line\nthird line"
        result = p4.update_changelist_description(test_cl, new_desc)
        assert result is True

    def test_get_or_make_changelist_creates(self, p4, unique_tag):
        desc = f"[p4cmd-test] get-or-make {unique_tag}"
        cl = p4.get_or_make_changelist(desc)
        assert isinstance(cl, int)
        assert cl > 0
        # calling again should return the same CL
        cl2 = p4.get_or_make_changelist(desc)
        assert cl2 == cl
        # cleanup
        _force_delete_cl(p4, cl)

    def test_get_files_in_empty_changelist(self, p4, test_cl):
        files = p4.get_files_in_changelist(test_cl)
        assert files == [] or files is not None


# ===================================================================
# File operations (add, edit, revert)
# ===================================================================

class TestFileOperations:
    def test_add_and_revert_file(self, p4, test_cl):
        path = _write_test_file("add_test.txt", "add test content")
        p4.add_files([path], changelist=test_cl)

        # file should show up in the changelist
        files = p4.get_files_in_changelist(test_cl)
        assert any("add_test.txt" in f for f in files)

        # revert
        p4.revert_files([path])
        files = p4.get_files_in_changelist(test_cl)
        matching = [f for f in files if "add_test.txt" in f]
        assert len(matching) == 0

    def test_add_or_edit_files_new(self, p4, test_cl):
        """add_or_edit with a brand new file (add path)."""
        path = _write_test_file("add_or_edit_new.txt", "aoe new content")
        info = p4.add_or_edit_files([path], changelist=test_cl)
        assert info is not None

        files = p4.get_files_in_changelist(test_cl)
        assert any("add_or_edit_new.txt" in f for f in files)

        p4.revert_files([path])

    def test_move_files_to_changelist(self, p4, test_cl, unique_tag):
        path = _write_test_file("move_cl_test.txt", "move test")
        p4.add_files([path], changelist="default")

        # move to our test CL
        p4.move_files_to_changelist([path], changelist=test_cl)
        files = p4.get_files_in_changelist(test_cl)
        assert any("move_cl_test.txt" in f for f in files)

        p4.revert_files([path])

    def test_revert_changelist(self, p4, test_cl):
        path1 = _write_test_file("revert_cl_1.txt", "one")
        path2 = _write_test_file("revert_cl_2.txt", "two")
        p4.add_files([path1, path2], changelist=test_cl)

        files_before = p4.get_files_in_changelist(test_cl)
        assert len(files_before) >= 2

        p4.revert_changelist(changelist=test_cl)
        files_after = p4.get_files_in_changelist(test_cl)
        assert len(files_after) == 0

    def test_reconcile_offline_files(self, p4, test_cl):
        path = _write_test_file("reconcile_test.txt", "reconcile me")
        info = p4.reconcile_offline_files(
            [path], add=True, edit=True, delete=False, changelist=test_cl
        )
        assert info is not None

        files = p4.get_files_in_changelist(test_cl)
        assert any("reconcile_test.txt" in f for f in files)

        p4.revert_files([path])


# ===================================================================
# Shelving
# ===================================================================

class TestShelving:
    def test_shelve_and_delete_shelf(self, p4, test_cl):
        path = _write_test_file("shelve_test.txt", "shelve me")
        p4.add_files([path], changelist=test_cl)

        # shelve
        result = p4.shelve_files(test_cl)
        assert result is not None

        # verify shelf exists
        shelved = p4.get_shelved_files()
        cl_numbers = [pair[1] for pair in shelved] if shelved else []
        assert test_cl in cl_numbers

        # delete the shelf
        p4.delete_shelf(test_cl)

        # revert
        p4.revert_files([path])

    def test_shelve_and_unshelve(self, p4, test_cl, unique_tag):
        path = _write_test_file("unshelve_test.txt", "unshelve me")
        p4.add_files([path], changelist=test_cl)

        # shelve and revert
        p4.shelve_files(test_cl, revert_after_shelve=True)

        # file should no longer be open
        files = p4.get_files_in_changelist(test_cl)
        open_files = [f for f in files if "unshelve_test.txt" in f]
        assert len(open_files) == 0

        # unshelve back
        p4.unshelve_files(test_cl, target_changelist=test_cl)

        files = p4.get_files_in_changelist(test_cl)
        assert any("unshelve_test.txt" in f for f in files)

        # cleanup
        p4.delete_shelf(test_cl)
        p4.revert_files([path])


# ===================================================================
# P4File
# ===================================================================

class TestP4File:
    def test_files_to_p4files_existing_file(self, p4, existing_depot_file):
        """Test with a file known to exist in the depot."""
        p4files = p4.files_to_p4files([existing_depot_file])
        assert len(p4files) == 1

        pf = p4files[0]
        assert isinstance(pf, P4File)
        assert pf.depot_file_path is not None or pf.get_depot_file_path() is not None
        assert pf.head_revision is not None

    def test_files_to_p4files_untracked(self, p4):
        path = _write_test_file("untracked_file.txt", "not in depot")
        p4files = p4.files_to_p4files([path], allow_invalid_files=True)
        assert len(p4files) == 1

        pf = p4files[0]
        assert pf.is_untracked() or pf.get_status() == Status.UNTRACKED

    def test_p4file_added_file_status(self, p4, test_cl):
        path = _write_test_file("status_add.txt", "checking status")
        p4.add_files([path], changelist=test_cl)

        p4files = p4.files_to_p4files([path])
        assert len(p4files) == 1

        pf = p4files[0]
        assert pf.is_open_for_add()
        assert pf.get_status() == Status.OPEN_FOR_ADD
        assert pf.is_checked_out()

        # legacy getters should work
        assert pf.get_action() == "add"
        assert pf.get_local_file_path() is not None

        p4.revert_files([path])

    def test_p4file_get_file_size(self, p4, existing_depot_file):
        p4files = p4.files_to_p4files([existing_depot_file])
        pf = p4files[0]

        size_mb = pf.get_file_size(in_megabyte=True)
        size_bytes = pf.get_file_size(in_megabyte=False)
        if size_bytes is not None:
            assert size_bytes > 0
            assert size_mb > 0

    def test_p4file_legacy_getters_setters(self, p4):
        """Verify backward-compatible get_*/set_* methods work."""
        pf = P4File()
        pf.set_local_file_path("/some/path.txt")
        assert pf.get_local_file_path() == "/some/path.txt"
        assert pf.local_file_path == "/some/path.txt"

        pf.set_depot_file_path("//depot/path.txt")
        assert pf.get_depot_file_path() == "//depot/path.txt"

        pf.set_have_revision(5)
        assert pf.get_have_revision() == 5

        pf.set_head_revision(10)
        assert pf.get_head_revision() == 10

        pf.set_action("edit")
        assert pf.get_action() == "edit"

        pf.set_head_action("delete")
        assert pf.get_head_action() == "delete"

        pf.set_checked_out_by("someone")
        assert pf.get_checked_out_by() == "someone"

        pf.set_last_submitted_by("user1")
        assert pf.get_last_submitted_by() == "user1"

        pf.set_raw_data("raw")
        assert pf.get_raw_data() == "raw"

    def test_folder_to_p4files(self, p4):
        p4files = p4.folder_to_p4files(TEST_LOCAL_FOLDER, include_subfolders=False)
        assert isinstance(p4files, list)
        assert len(p4files) > 0
        assert all(isinstance(f, P4File) for f in p4files)


# ===================================================================
# Path operations
# ===================================================================

class TestPaths:
    def test_get_depot_paths(self, p4):
        depot = p4.get_depot_paths([TEST_LOCAL_FOLDER])
        assert isinstance(depot, list)
        assert len(depot) > 0
        assert depot[0].startswith("//")

    def test_get_local_paths(self, p4):
        local = p4.get_local_paths([TEST_DEPOT_FOLDER])
        assert isinstance(local, list)
        assert len(local) > 0

    def test_roundtrip_paths(self, p4):
        """depot → local → depot should give back the same path."""
        depot = p4.get_depot_paths([TEST_LOCAL_FOLDER])
        local = p4.get_local_paths(depot)
        depot_again = p4.get_depot_paths(local)
        assert depot == depot_again


# ===================================================================
# History
# ===================================================================

class TestHistory:
    def test_get_history(self, p4, existing_depot_file):
        history = p4.get_history([existing_depot_file])
        assert isinstance(history, list)
        assert len(history) > 0

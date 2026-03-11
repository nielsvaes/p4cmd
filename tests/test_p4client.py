"""Tests for p4cmd/p4cmd.py — P4Client with run_cmd mocked."""
import socket
from unittest.mock import MagicMock, patch

import pytest

from p4cmd.p4cmd import P4Client
from p4cmd.p4file import P4File, Status
from tests.conftest import make_fstat_dict


# ---------------------------------------------------------------------------
# _normalize_folder (static)
# ---------------------------------------------------------------------------

def test_normalize_folder_windows_path():
    result = P4Client._normalize_folder("C:\\projects\\game\\content")
    assert result == "C:/projects/game/content/..."


def test_normalize_folder_already_clean():
    result = P4Client._normalize_folder("//depot/project")
    assert result == "//depot/project/..."


def test_normalize_folder_trailing_slash_removed():
    result = P4Client._normalize_folder("/depot/project/")
    assert result == "/depot/project/..."


# ---------------------------------------------------------------------------
# _build_reconcile_args (instance, but no server calls)
# ---------------------------------------------------------------------------

def test_build_reconcile_args_all_true(p4client):
    args = p4client._build_reconcile_args(123, add=True, edit=True, delete=True)
    # When all are True, no individual flags (-a/-e/-d) added, just -c <cl>
    assert args == ["-c", 123]
    assert "-a" not in args
    assert "-e" not in args
    assert "-d" not in args


def test_build_reconcile_args_none_enabled(p4client):
    assert p4client._build_reconcile_args(123, add=False, edit=False, delete=False) is None


def test_build_reconcile_args_add_only(p4client):
    args = p4client._build_reconcile_args(123, add=True, edit=False, delete=False)
    assert "-a" in args
    assert "-e" not in args
    assert "-d" not in args


def test_build_reconcile_args_edit_delete(p4client):
    args = p4client._build_reconcile_args(123, add=False, edit=True, delete=True)
    assert "-a" not in args
    assert "-e" in args
    assert "-d" in args


# ---------------------------------------------------------------------------
# __get_dict_value (name-mangled)
# ---------------------------------------------------------------------------

def test_get_dict_value_bytes_key(p4client):
    d = {b"depotFile": b"//depot/file.txt"}
    result = p4client._P4Client__get_dict_value(d, "depotFile")
    assert result == "//depot/file.txt"


def test_get_dict_value_str_key_fallback(p4client):
    # dict with str key — should fall back to str lookup
    d = {"depotFile": "//depot/file.txt"}
    result = p4client._P4Client__get_dict_value(d, "depotFile")
    assert result == "//depot/file.txt"


def test_get_dict_value_default(p4client):
    d = {b"other": b"value"}
    result = p4client._P4Client__get_dict_value(d, "missing", default_value="FALLBACK")
    assert result == "FALLBACK"


def test_get_dict_value_returns_str_not_bytes(p4client):
    d = {b"key": b"value"}
    result = p4client._P4Client__get_dict_value(d, "key")
    assert isinstance(result, str)
    assert result == "value"


# ---------------------------------------------------------------------------
# __ensure_changelist (name-mangled)
# ---------------------------------------------------------------------------

def test_ensure_changelist_int(p4client):
    assert p4client._P4Client__ensure_changelist(123) == 123


def test_ensure_changelist_str_numeric(p4client):
    assert p4client._P4Client__ensure_changelist("123") == 123


def test_ensure_changelist_bytes(p4client):
    assert p4client._P4Client__ensure_changelist(b"123") == 123


def test_ensure_changelist_float(p4client):
    assert p4client._P4Client__ensure_changelist(1.5) == 1


def test_ensure_changelist_default_str(p4client):
    # "default" triggers get_or_make_changelist which returns "default"
    with patch.object(p4client, "get_or_make_changelist", return_value="default") as mock_gomc:
        result = p4client._P4Client__ensure_changelist("default")
    mock_gomc.assert_called_once_with("default")
    assert result == "default"


# ---------------------------------------------------------------------------
# fstat_to_p4_files
# ---------------------------------------------------------------------------

def test_fstat_basic(p4client):
    fstat = [
        make_fstat_dict(
            depotFile="//depot/project/art/texture.png",
            clientFile="/fake/project/art/texture.png",
            haveRev="3",
            headRev="3",
            headTime="1700000000",
        )
    ]
    with patch.object(p4client, "find_p4_client", return_value="testclient"):
        files = p4client.fstat_to_p4_files(fstat)

    assert len(files) == 1
    f = files[0]
    assert f.depot_file_path == "//depot/project/art/texture.png"
    assert f.local_file_path == "/fake/project/art/texture.png"
    assert f.have_revision == 3
    assert f.head_revision == 3


def test_fstat_deleted_excluded_by_default(p4client):
    fstat = [
        make_fstat_dict(
            depotFile="//depot/project/old.txt",
            clientFile="/fake/project/old.txt",
            haveRev="2",
            headRev="2",
            headAction="delete",
        )
    ]
    with patch.object(p4client, "find_p4_client", return_value="testclient"):
        files = p4client.fstat_to_p4_files(fstat, allow_invalid_files=False)
    assert files == []


def test_fstat_deleted_included_when_allowed(p4client):
    fstat = [
        make_fstat_dict(
            depotFile="//depot/project/old.txt",
            clientFile="/fake/project/old.txt",
            haveRev="2",
            headRev="2",
            headAction="delete",
        )
    ]
    with patch.object(p4client, "find_p4_client", return_value="testclient"):
        files = p4client.fstat_to_p4_files(fstat, allow_invalid_files=True)
    assert len(files) == 1


def test_fstat_otheropen_fields(p4client):
    fstat = [
        {
            b"depotFile": b"//depot/project/shared.txt",
            b"clientFile": b"/fake/project/shared.txt",
            b"haveRev": b"1",
            b"headRev": b"1",
            b"otherOpen": b"2",
            b"otherOpen0": b"alice@ws1",
            b"otherOpen1": b"bob@ws2",
        }
    ]
    with patch.object(p4client, "find_p4_client", return_value="testclient"):
        files = p4client.fstat_to_p4_files(fstat)
    assert "alice@ws1" in files[0].checked_out_by
    assert "bob@ws2" in files[0].checked_out_by


def test_fstat_actionowner_field(p4client):
    fstat = [
        {
            b"depotFile": b"//depot/project/file.txt",
            b"clientFile": b"/fake/project/file.txt",
            b"haveRev": b"1",
            b"headRev": b"1",
            b"action": b"edit",
            b"actionOwner": b"charlie",
        }
    ]
    with patch.object(p4client, "find_p4_client", return_value="testclient"):
        files = p4client.fstat_to_p4_files(fstat)
    assert any("charlie@testclient" in entry for entry in files[0].checked_out_by)


def test_fstat_invalid_revision_becomes_none(p4client):
    fstat = [
        make_fstat_dict(
            depotFile="//depot/project/file.txt",
            clientFile="/fake/project/file.txt",
            haveRev="none",
            headRev="5",
        )
    ]
    with patch.object(p4client, "find_p4_client", return_value="testclient"):
        files = p4client.fstat_to_p4_files(fstat)
    assert files[0].have_revision is None
    assert files[0].head_revision == 5


# ---------------------------------------------------------------------------
# get_files_in_changelist
# ---------------------------------------------------------------------------

def test_get_files_in_changelist(p4client):
    opened_output = [
        {b"depotFile": b"//depot/project/a.txt", b"change": b"123"},
        {b"depotFile": b"//depot/project/b.txt", b"change": b"123"},
    ]
    with patch.object(p4client, "run_cmd", return_value=opened_output):
        result = p4client.get_files_in_changelist(123)

    assert result == ["//depot/project/a.txt", "//depot/project/b.txt"]


def test_get_files_in_changelist_default(p4client):
    opened_output = [{b"depotFile": b"//depot/project/c.txt", b"change": b"default"}]
    with patch.object(p4client, "run_cmd", return_value=opened_output):
        result = p4client.get_files_in_changelist("default")
    assert "//depot/project/c.txt" in result


# ---------------------------------------------------------------------------
# get_pending_changelists
# ---------------------------------------------------------------------------

def _make_cl_dicts(*pairs):
    """pairs: list of (change_number_str, description_str)"""
    return [
        {b"change": num.encode(), b"desc": desc.encode()}
        for num, desc in pairs
    ]


def test_get_pending_changelists_no_filter(p4client):
    raw = _make_cl_dicts(("123", "Fix bug\n"), ("456", "Add feature\n"))
    with patch.object(p4client, "run_cmd", return_value=raw):
        result = p4client.get_pending_changelists()
    assert 123 in result
    assert 456 in result
    assert "default" in result


def test_get_pending_changelists_description_filter(p4client):
    raw = _make_cl_dicts(("123", "Fix bug\n"), ("456", "Add feature\n"))
    with patch.object(p4client, "run_cmd", return_value=raw):
        result = p4client.get_pending_changelists(description_filter="fix")
    assert 123 in result
    assert 456 not in result


def test_get_pending_changelists_perfect_match_only(p4client):
    raw = _make_cl_dicts(("123", "Fix bug\n"), ("456", "Fix bug and more\n"))
    with patch.object(p4client, "run_cmd", return_value=raw):
        result = p4client.get_pending_changelists(
            description_filter="fix bug", perfect_match_only=True
        )
    assert 123 in result
    assert 456 not in result


def test_get_pending_changelists_descriptions_mode(p4client):
    raw = _make_cl_dicts(("123", "My task\n"),)
    with patch.object(p4client, "run_cmd", return_value=raw):
        result = p4client.get_pending_changelists(descriptions=True)
    assert "my task" in result
    assert "default" in result


# ---------------------------------------------------------------------------
# files_to_p4files — offline path
# ---------------------------------------------------------------------------

def test_files_to_p4files_offline(p4client):
    with patch.object(p4client, "host_online", return_value=False):
        files = p4client.files_to_p4files(["/local/file.txt"])

    assert len(files) == 1
    f = files[0]
    assert f.local_file_path == "/local/file.txt"
    assert f._status_override == Status.UNKNOWN


def test_files_to_p4files_offline_multiple(p4client):
    paths = ["/local/a.txt", "/local/b.txt", "/local/c.txt"]
    with patch.object(p4client, "host_online", return_value=False):
        files = p4client.files_to_p4files(paths)

    assert len(files) == 3
    assert all(f._status_override == Status.UNKNOWN for f in files)
    local_paths = [f.local_file_path for f in files]
    for p in paths:
        assert p in local_paths


# ---------------------------------------------------------------------------
# add_or_edit_files — routing regression test
# ---------------------------------------------------------------------------

def test_add_or_edit_files_routes_correctly(p4client):
    """
    Local-only files → add_files (with local_file_path).
    Depot files → edit_files (with depot_file_path, not original path).
    Already checked-out files → skipped entirely.
    """
    local_file = P4File()
    local_file._local_file_path = "/fake/project/new_file.txt"
    local_file._raw_data = "- no such file(s)"

    depot_file = P4File()
    depot_file._local_file_path = "/fake/project/existing.txt"
    depot_file._depot_file_path = "//depot/project/existing.txt"

    checked_out_file = P4File()
    checked_out_file._local_file_path = "/fake/project/open.txt"
    checked_out_file._depot_file_path = "//depot/project/open.txt"
    checked_out_file._action = "edit"

    with patch.object(
        p4client, "files_to_p4files",
        return_value=[local_file, depot_file, checked_out_file]
    ):
        with patch.object(p4client, "add_files", return_value=[]) as mock_add:
            with patch.object(p4client, "edit_files", return_value=[]) as mock_edit:
                p4client.add_or_edit_files([
                    "/fake/project/new_file.txt",
                    "/fake/project/existing.txt",
                    "/fake/project/open.txt",
                ])

    mock_add.assert_called_once_with(["/fake/project/new_file.txt"], changelist="default")
    mock_edit.assert_called_once_with(["//depot/project/existing.txt"], changelist="default")


def test_add_or_edit_files_skips_all_checked_out(p4client):
    """If all files are already checked out, neither add nor edit is called."""
    checked_out = P4File()
    checked_out._action = "edit"
    checked_out._depot_file_path = "//depot/project/file.txt"

    with patch.object(p4client, "files_to_p4files", return_value=[checked_out]):
        with patch.object(p4client, "add_files", return_value=[]) as mock_add:
            with patch.object(p4client, "edit_files", return_value=[]) as mock_edit:
                p4client.add_or_edit_files(["//depot/project/file.txt"])

    mock_add.assert_not_called()
    mock_edit.assert_not_called()


# ---------------------------------------------------------------------------
# reconcile_offline_files
# ---------------------------------------------------------------------------

def test_reconcile_offline_files_default(p4client):
    with patch.object(p4client, "run_cmd", return_value=[]) as mock_cmd:
        p4client.reconcile_offline_files(["/fake/project/file.txt"])

    args_passed = mock_cmd.call_args
    # Should use "reconcile" command
    assert args_passed[0][0] == "reconcile"
    reconcile_args = args_passed[1].get("args", args_passed[0][1] if len(args_passed[0]) > 1 else [])
    assert "-c" in reconcile_args


def test_reconcile_offline_files_none_enabled(p4client):
    result = p4client.reconcile_offline_files(
        ["/fake/file.txt"], add=False, edit=False, delete=False
    )
    assert result == []


def test_reconcile_offline_files_add_only(p4client):
    with patch.object(p4client, "run_cmd", return_value=[]) as mock_cmd:
        p4client.reconcile_offline_files(["/fake/file.txt"], add=True, edit=False, delete=False)

    args_passed = mock_cmd.call_args[1].get("args") or mock_cmd.call_args[0][1]
    assert "-a" in args_passed
    assert "-e" not in args_passed
    assert "-d" not in args_passed


# ---------------------------------------------------------------------------
# reconcile_offline_folders
# ---------------------------------------------------------------------------

def test_reconcile_offline_folders_normalizes_path(p4client):
    with patch.object(p4client, "run_cmd", return_value=[]) as mock_cmd:
        p4client.reconcile_offline_folders(["C:\\projects\\game"])

    file_list_passed = mock_cmd.call_args[1].get("file_list", mock_cmd.call_args[0][2] if len(mock_cmd.call_args[0]) > 2 else [])
    assert any("/..." in f for f in file_list_passed)
    assert not any("\\" in f for f in file_list_passed)


# ---------------------------------------------------------------------------
# revert_folders / sync_folders — path normalization
# ---------------------------------------------------------------------------

def test_revert_folders_normalizes_path(p4client):
    with patch.object(p4client, "run_cmd", return_value=[]) as mock_cmd:
        p4client.revert_folders(["C:\\depot\\art"])

    file_list = mock_cmd.call_args[1].get("file_list", [])
    assert all("/..." in f for f in file_list)
    assert all("\\" not in f for f in file_list)


def test_sync_folders_normalizes_path(p4client):
    with patch.object(p4client, "run_cmd", return_value=[]) as mock_cmd:
        p4client.sync_folders(["C:\\depot\\content"])

    file_list = mock_cmd.call_args[1].get("file_list", [])
    assert all("/..." in f for f in file_list)
    assert all("\\" not in f for f in file_list)


# ---------------------------------------------------------------------------
# host_online
# ---------------------------------------------------------------------------

def test_host_online_success(p4client):
    with patch("p4cmd.p4cmd.socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__ = MagicMock(return_value=None)
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        assert p4client.host_online() is True


def test_host_online_timeout(p4client):
    with patch("p4cmd.p4cmd.socket.create_connection", side_effect=socket.timeout):
        assert p4client.host_online() is False


def test_host_online_connection_refused(p4client):
    with patch("p4cmd.p4cmd.socket.create_connection", side_effect=ConnectionRefusedError):
        assert p4client.host_online() is False


def test_host_online_oserror(p4client):
    with patch("p4cmd.p4cmd.socket.create_connection", side_effect=OSError("Network unreachable")):
        assert p4client.host_online() is False


# ---------------------------------------------------------------------------
# changelist_exists
# ---------------------------------------------------------------------------

def test_changelist_exists_int_found(p4client):
    with patch.object(p4client, "get_pending_changelists", return_value=[123, 456, "default"]):
        assert p4client.changelist_exists(123) is True


def test_changelist_exists_int_not_found(p4client):
    with patch.object(p4client, "get_pending_changelists", return_value=[123, 456, "default"]):
        # int not found: returns None (implicit), which is falsy
        result = p4client.changelist_exists(999)
        assert not result


def test_changelist_exists_description_found(p4client):
    with patch.object(
        p4client, "get_pending_changelists",
        return_value=[123, "default"]
    ):
        assert p4client.changelist_exists("My task") is True


def test_changelist_exists_description_not_found(p4client):
    # get_pending_changelists always appends "default"; only ["default"] means no real match
    with patch.object(
        p4client, "get_pending_changelists",
        return_value=["default"]
    ):
        assert p4client.changelist_exists("Nonexistent task") is False


# ---------------------------------------------------------------------------
# Robustness fixes
# ---------------------------------------------------------------------------

def test_run_cmd_no_chdir(p4client):
    """os.chdir must NOT be called during run_cmd — cwd= is used on Popen instead."""
    with patch("p4cmd.p4cmd.os.chdir") as mock_chdir, \
         patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen, \
         patch.object(p4client, "host_online", return_value=True):
        # Simulate an empty marshal stream (EOF immediately)
        import io
        mock_pipe = MagicMock()
        mock_pipe.stdout = io.BytesIO(b"")
        mock_pipe.__enter__ = lambda s: s
        mock_pipe.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = mock_pipe

        p4client.run_cmd("changes", args=[], online_check=False)

        mock_chdir.assert_not_called()
        # cwd should have been passed to Popen
        _, kwargs = mock_popen.call_args
        assert kwargs.get("cwd") == p4client.perforce_root


def test_get_p4_setting_malformed_output(p4client):
    """get_p4_setting returns None instead of crashing on output with no '='."""
    bad_dict = {"raw_output": b"P4CLIENT (no equals sign here)"}
    with patch.object(p4client, "run_cmd", return_value=[bad_dict]):
        result = p4client.get_p4_setting("P4CLIENT")
    assert result is None


def test_make_new_changelist_malformed_output(p4client):
    """make_new_changelist returns None instead of crashing on unexpected p4 output."""
    with patch("p4cmd.p4cmd.subprocess.check_output", return_value=b"Unexpected output with no number\n"), \
         patch.object(p4client, "host_online", return_value=True):
        result = p4client.make_new_changelist("test description")
    assert result is None


def test_get_pending_changelists_none_desc(p4client):
    """get_pending_changelists raises P4cmdError when desc key is missing."""
    from p4cmd import p4errors
    info_dicts = [{b"change": b"123", b"status": b"pending"}]  # no "desc" key
    with patch.object(p4client, "run_cmd", return_value=info_dicts):
        with pytest.raises(p4errors.P4cmdError):
            p4client.get_pending_changelists()


def test_get_depot_paths_missing_depot_file(p4client):
    """get_depot_paths skips entries where depotFile is missing instead of crashing."""
    info_dicts = [
        {b"depotFile": b"//depot/project/file.txt", b"path": b"C:/workspace/file.txt"},
        {b"path": b"C:/workspace/other.txt"},  # no depotFile key
    ]
    with patch.object(p4client, "run_cmd", return_value=info_dicts):
        result = p4client.get_depot_paths(["C:/workspace/file.txt", "C:/workspace/other.txt"])
    assert result == ["//depot/project/file.txt"]

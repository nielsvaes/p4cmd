"""Tests for p4cmd/p4cmd.py — P4Client with run_cmd mocked."""
import logging
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from p4cmd.p4cmd import P4Client, _p4port_address, _run_command
from p4cmd.p4errors import P4CommandError, ServerOffline, WorkSpaceError
from p4cmd.p4file import P4File, Status
from tests.conftest import fake_p4_popen, make_fstat_dict


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


def test_ensure_changelist_none(p4client):
    assert p4client._P4Client__ensure_changelist(None) == "default"


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


def test_fstat_file_gone_from_disk_needs_force_syncing(p4client, tmp_path):
    """fstat gives have == head for a file deleted outside Perforce: only the disk tells it apart."""
    (tmp_path / "here.png").write_text("")
    fstat = [
        make_fstat_dict(depotFile="//depot/project/gone.png", clientFile=str(tmp_path / "gone.png"),
                        haveRev="1", headRev="1", headAction="add"),
        make_fstat_dict(depotFile="//depot/project/here.png", clientFile=str(tmp_path / "here.png"),
                        haveRev="1", headRev="1", headAction="add"),
    ]
    with patch.object(p4client, "find_p4_client", return_value="testclient"):
        gone, here = p4client.fstat_to_p4_files(fstat)

    assert gone.needs_force_syncing() is True
    assert here.needs_force_syncing() is False


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


def test_fstat_untracked_file_with_dash_in_name(p4client):
    """fstat_to_p4_files correctly parses untracked file paths containing ' - '."""
    fstat = [
        {
            b"code": b"error",
            b"data": b"D:/p4/games/Animations/my_clip - Copy.pose - no such file(s).",
        }
    ]
    with patch.object(p4client, "find_p4_client", return_value="testclient"):
        files = p4client.fstat_to_p4_files(fstat)
    assert len(files) == 1
    assert files[0].local_file_path == "D:/p4/games/Animations/my_clip - Copy.pose"


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


@pytest.mark.parametrize("p4port, address", [
    ("ssl64:perforce.example.com:1666", ("perforce.example.com", 1666)),
    ("perforce:1666", ("perforce", 1666)),
    ("1666", ("localhost", 1666)),
    ("ssl:1666", ("localhost", 1666)),
    ("tcp6:[::1]:1666", ("::1", 1666)),
    ("[fe80::1]:1666", ("fe80::1", 1666)),
    ("rsh:p4d -r /depot -i", None),
])
def test_p4port_address(p4port, address):
    assert _p4port_address(p4port) == address


def test_host_online_without_a_host_to_check(p4client):
    """A P4PORT that runs a command (rsh:) has no host to connect to: commands run and p4 reports."""
    p4client.server = "rsh:p4d -r /depot -i"
    with patch("p4cmd.p4cmd.socket.create_connection") as mock_conn:
        assert p4client.host_online() is True
    mock_conn.assert_not_called()


def test_run_cmd_does_not_run_p4_when_the_server_is_unreachable(p4client):
    """p4 would only fail the same way after its own connection timeout (about 21 s on Windows)."""
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen, \
         patch.object(p4client, "host_online", return_value=False):
        fake_p4_popen(mock_popen, b"")
        assert p4client.run_cmd("sync", file_list=["//depot/file.txt"]) == []
        with pytest.raises(ServerOffline):
            p4client.run_cmd("sync", file_list=["//depot/file.txt"], raise_on_errors=True)
    mock_popen.assert_not_called()


def test_run_cmd_without_online_check_runs_p4(p4client):
    """online_check=False skips the check, so p4 runs whatever it would say."""
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen, \
         patch.object(p4client, "host_online", return_value=False) as mock_online:
        fake_p4_popen(mock_popen, b"")
        p4client.run_cmd("sync", file_list=["//depot/file.txt"], online_check=False)
    mock_online.assert_not_called()
    assert mock_popen.call_count == 1


def test_init_finds_p4port_before_the_client(tmp_path):
    """Without P4CLIENT, finding the client runs `p4 clients`, and run_cmd() checks P4PORT before that.
    With P4PORT still unset, host_online() raised AttributeError."""
    import marshal
    (tmp_path / ".p4config").write_text("P4PORT=ssl:perforce.example.com:1666\n")
    settings = {"P4PORT": "ssl:perforce.example.com:1666", "P4CLIENT": None}
    outputs = [
        marshal.dumps({b"client": b"testclient"}),  # p4 clients -u testuser
        marshal.dumps({b"depotFile": b"//depot/project/...", b"path": b"/fake/project/..."}),  # p4 where
    ]
    with patch.object(P4Client, "get_p4_setting", side_effect=settings.get), \
         patch("p4cmd.p4cmd.socket.create_connection") as mock_conn, \
         patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, outputs)
        client = P4Client(str(tmp_path), user="testuser")
    assert client.server == "ssl:perforce.example.com:1666"
    assert client.client == "testclient"
    mock_conn.assert_called_with(("perforce.example.com", 1666), timeout=2.0)


def test_get_ticket_expiration_checks_the_server_once(p4client):
    """It checks the server itself. A second check in run_cmd() that failed on its own left no result,
    and result[0] raised IndexError instead of ServerOffline."""
    import marshal
    with patch.object(p4client, "host_online", side_effect=[True, False]) as mock_online, \
         patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, marshal.dumps({b"code": b"stat", b"TicketExpiration": b"3600"}))
        assert p4client.get_ticket_expiration() == 3600
    assert mock_online.call_count == 1


@pytest.mark.parametrize("call", [
    lambda client: client.files_to_p4files(["/fake/project/a.txt"]),
    lambda client: client.folder_to_p4files("/fake/project"),
], ids=["files_to_p4files", "folder_to_p4files"])
def test_files_to_p4files_checks_the_server_once(p4client, call):
    """They check the server themselves. A second check in run_cmd() that failed on its own gave no
    files at all, not even the HOST OFFLINE placeholders."""
    import marshal
    fstat = marshal.dumps(make_fstat_dict(depotFile="//depot/project/a.txt", clientFile="/fake/project/a.txt",
                                          haveRev="1", headRev="1", headTime="1700000000"))
    with patch.object(p4client, "host_online", side_effect=[True, False]) as mock_online, \
         patch.object(p4client, "find_p4_client", return_value="testclient"), \
         patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, fstat)
        files = call(p4client)
    assert [f.depot_file_path for f in files] == ["//depot/project/a.txt"]
    assert mock_online.call_count == 1


def test_get_or_make_changelist_makes_none_when_it_cannot_look(p4client):
    """When the server can't be reached to look for the changelist, it raises. Taking that as "there
    is none" made a second changelist with the same description once the next check passed."""
    with patch.object(p4client, "host_online", side_effect=[False, True]), \
         patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen)
        with pytest.raises(ServerOffline):
            p4client.get_or_make_changelist("Export")
    mock_popen.assert_not_called()


def test_get_pending_changelists_raises_p4_errors(p4client):
    """An error from p4, like an expired login, raises P4CommandError with p4's message."""
    import marshal
    error = marshal.dumps({b"code": b"error", b"data": b"Perforce password (P4PASSWD) invalid or unset.\n"})
    with patch.object(p4client, "host_online", return_value=True), \
         patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, error)
        with pytest.raises(P4CommandError) as excinfo:
            p4client.get_pending_changelists()
    assert excinfo.value.messages == ["Perforce password (P4PASSWD) invalid or unset."]


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
        fake_p4_popen(mock_popen)

        p4client.run_cmd("changes", args=[], online_check=False)

        mock_chdir.assert_not_called()
        # cwd should have been passed to Popen
        _, kwargs = mock_popen.call_args
        assert kwargs.get("cwd") == p4client.perforce_root
        assert kwargs["stdin"] is subprocess.DEVNULL


def test_run_command_does_not_wait_for_processes_holding_its_output():
    """
    A process that outlives the command and holds its output (here one the command leaves running;
    in practice one that inherited it when something else started it at the same moment) doesn't
    keep _run_command waiting. Read from a pipe until it closes, this took the 3 s of that process.
    """
    if sys.platform == "win32":
        command = "echo hi& start /b ping -n 4 127.0.0.1 > NUL"
    else:
        command = "echo hi; sleep 3 &"
    start = time.perf_counter()
    output = _run_command(command, tempfile.gettempdir())
    assert output.strip() == b"hi"
    assert time.perf_counter() - start < 2.0


def test_run_command_gives_the_command_its_input():
    """input reaches the command as its stdin (the form for `p4 change -i`), and its output comes back."""
    command = f'"{sys.executable}" -c "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())"'
    assert _run_command(command, tempfile.gettempdir(), input=b"change form\n") == b"CHANGE FORM\n"


def test_get_p4_setting_malformed_output(p4client):
    """get_p4_setting returns None instead of crashing on output with no '='."""
    bad_dict = {"raw_output": b"P4CLIENT (no equals sign here)"}
    with patch.object(p4client, "run_cmd", return_value=[bad_dict]):
        result = p4client.get_p4_setting("P4CLIENT")
    assert result is None


def test_make_new_changelist_malformed_output(p4client):
    """make_new_changelist returns None instead of crashing on unexpected p4 output."""
    template = b"Change: new\n\nDescription:\n\t<enter description here>\n\nFiles:\n"
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen, \
         patch.object(p4client, "host_online", return_value=True):
        fake_p4_popen(mock_popen, [template, b"Unexpected output\n"])
        result = p4client.make_new_changelist("test description")
    assert result is None


def test_make_new_changelist_preserves_newlines(p4client):
    """make_new_changelist correctly handles descriptions containing newlines."""
    template = b"Change: new\n\nDescription:\n\t<enter description here>\n\nFiles:\n"
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen, \
         patch.object(p4client, "host_online", return_value=True):
        fake_p4_popen(mock_popen, [template, b"Change 12345 created.\n"])
        result = p4client.make_new_changelist("Line one.\nLine two.")

    assert result == 12345
    # Verify the description sent to p4 change -i has tab-indented lines
    change_o_stdin, change_i_stdin = mock_popen.stdin_received
    assert change_o_stdin is subprocess.DEVNULL
    input_data = change_i_stdin.decode()
    assert "\tLine one." in input_data
    assert "\tLine two." in input_data
    # In the workspace root, like run_cmd, so both use its .p4config
    assert all(call.kwargs["cwd"] == p4client.perforce_root for call in mock_popen.call_args_list)


def test_make_new_changelist_raises_when_p4_fails(p4client):
    """A failing p4 raises CalledProcessError with what p4 said, and no form is sent to `change -i`."""
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen, \
         patch.object(p4client, "host_online", return_value=True):
        fake_p4_popen(mock_popen, b"Perforce password (P4PASSWD) invalid or unset.\n", returncode=1)
        with pytest.raises(subprocess.CalledProcessError) as error:
            p4client.make_new_changelist("test description")
    assert b"P4PASSWD" in error.value.output
    assert mock_popen.call_count == 1


def test_update_changelist_description_sends_the_new_description(p4client):
    """The changelist's form goes back to `change -i` with the new description in place of the old."""
    template = (b"Change: 12345\n\nClient: testclient\n\nUser: testuser\n\nStatus: pending\n\n"
                b"Description:\n\tOld description\n\nFiles:\n")
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, [template, b"Change 12345 updated.\n"])
        result = p4client.update_changelist_description(12345, "New description")

    assert result is True
    change_o_stdin, change_i_stdin = mock_popen.stdin_received
    assert change_o_stdin is subprocess.DEVNULL
    assert "\tNew description" in change_i_stdin.decode()
    assert "Old description" not in change_i_stdin.decode()


def test_update_changelist_description_returns_false_when_p4_fails(p4client, caplog):
    """A failing p4 is logged and gives False."""
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, b"", returncode=1)
        with caplog.at_level(logging.ERROR):
            result = p4client.update_changelist_description(12345, "New description")
    assert result is False
    assert "Failed to update changelist description" in caplog.text


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


# ---------------------------------------------------------------------------
# run_cmd error handling
# ---------------------------------------------------------------------------

def test_run_cmd_logs_warning_on_error_dicts(p4client, caplog):
    """run_cmd logs a warning for each error dict returned by p4."""
    error_dict = {b"code": b"error", b"data": b"//depot/file.txt - file(s) not on client.\n"}
    ok_dict = {b"code": b"stat", b"depotFile": b"//depot/other.txt"}
    with patch("subprocess.Popen") as mock_popen:
        import marshal as _m, io as _io
        buf = _io.BytesIO()
        _m.dump(error_dict, buf)
        _m.dump(ok_dict, buf)
        fake_p4_popen(mock_popen, buf.getvalue())
        with caplog.at_level(logging.WARNING):
            result = p4client.run_cmd("sync", file_list=["//depot/file.txt", "//depot/other.txt"], online_check=False)
    assert len(result) == 2  # both dicts still returned
    assert "file(s) not on client" in caplog.text


def test_run_cmd_raise_on_errors(p4client):
    """run_cmd raises P4CommandError when raise_on_errors=True and errors are present."""
    error_dict = {b"code": b"error", b"data": b"//depot/file.txt - file(s) not on client.\n"}
    with patch("subprocess.Popen") as mock_popen:
        import marshal as _m, io as _io
        buf = _io.BytesIO()
        _m.dump(error_dict, buf)
        fake_p4_popen(mock_popen, buf.getvalue())
        with pytest.raises(P4CommandError, match="file\\(s\\) not on client"):
            p4client.run_cmd("sync", file_list=["//depot/file.txt"], raise_on_errors=True, online_check=False)


def test_run_cmd_no_raise_without_errors(p4client):
    """run_cmd doesn't raise when raise_on_errors=True but no errors are present."""
    ok_dict = {b"code": b"stat", b"depotFile": b"//depot/file.txt"}
    with patch("subprocess.Popen") as mock_popen:
        import marshal as _m, io as _io
        buf = _io.BytesIO()
        _m.dump(ok_dict, buf)
        fake_p4_popen(mock_popen, buf.getvalue())
        result = p4client.run_cmd("sync", file_list=["//depot/file.txt"], raise_on_errors=True, online_check=False)
    assert result == [ok_dict]


def test_run_cmd_handles_string_key_error_dicts(p4client, caplog):
    """run_cmd handles error dicts with string keys (from ValueError fallback)."""
    # String-keyed error dicts come from the ValueError handler in run_cmd
    error_dict = {b"code": b"error", b"data": b"some error\n"}
    with patch("subprocess.Popen") as mock_popen:
        import marshal as _m, io as _io
        buf = _io.BytesIO()
        _m.dump(error_dict, buf)
        fake_p4_popen(mock_popen, buf.getvalue())
        with caplog.at_level(logging.WARNING):
            p4client.run_cmd("sync", file_list=["//depot/file.txt"], online_check=False)
    assert "some error" in caplog.text


def test_run_cmd_value_error_returns_the_output_once(p4client):
    """
    Output that isn't all marshaled dicts gives one raw entry with all of it, without the dicts
    read before the error, and p4 isn't run again (that would repeat a sync or submit).
    """
    import marshal as _m
    output = _m.dumps({b"code": b"stat", b"depotFile": b"//depot/file.txt"}) + b"not marshal data\n"
    with patch("subprocess.Popen") as mock_popen, \
         patch("p4cmd.p4cmd.subprocess.check_output") as mock_check_output:
        fake_p4_popen(mock_popen, output)
        result = p4client.run_cmd("sync", file_list=["//depot/file.txt"], online_check=False)

    assert len(result) == 1
    assert result[0]["code"] == "raw"
    assert result[0]["raw_output"] == output
    assert mock_popen.call_count == 1
    mock_check_output.assert_not_called()


def test_run_cmd_value_error_fallback_no_warning(p4client, caplog):
    """The marshal_output=False path (e.g. `p4 set`) must not log spurious error warnings."""
    with patch("subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, b"P4USER=niels.vaes (set)\n")
        with caplog.at_level(logging.WARNING):
            result = p4client.get_p4_setting("P4USER")
    assert result == "niels.vaes"
    assert caplog.records == []


def test_run_cmd_no_global_options_does_not_spawn_second_subprocess(p4client):
    """
    Regression test for issue #13. When marshal_output=False (e.g. `p4 set`),
    p4 outputs plain text — marshal.load is guaranteed to fail. The old fallback
    spawned a second subprocess via check_output without pinning stdin, which
    triggered OSError(WinError 50) on DuplicateHandle in non-interactive sessions
    (UE commandlets, scheduled tasks, CI). The fix uses the output of the one
    subprocess, whose stdin is NUL.
    """
    p4_set_output = b"P4USER=niels.vaes (set)\r\n"
    with patch("subprocess.Popen") as mock_popen, \
         patch("p4cmd.p4cmd.subprocess.check_output") as mock_check_output:
        fake_p4_popen(mock_popen, p4_set_output)

        result = p4client.get_p4_setting("P4USER")

    assert result == "niels.vaes"
    mock_check_output.assert_not_called()


def test_run_cmd_use_global_options_deprecation_alias(p4client):
    """The old `use_global_options` kwarg is accepted but emits DeprecationWarning."""
    import warnings as _warnings
    with patch("subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, b"P4USER=niels.vaes (set)\n")

        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            result = p4client.run_cmd("set", ["P4USER"], use_global_options=False, online_check=False)

    assert result[0]["raw_output"] == b"P4USER=niels.vaes (set)\n"
    assert any(issubclass(w.category, DeprecationWarning) and "use_global_options" in str(w.message)
               for w in caught), f"expected DeprecationWarning for use_global_options, got: {[str(w.message) for w in caught]}"


def test_run_cmd_unknown_kwarg_raises(p4client):
    """Unknown kwargs should raise TypeError, not be silently accepted."""
    with pytest.raises(TypeError, match="unexpected keyword arguments"):
        p4client.run_cmd("set", ["P4USER"], totally_made_up=True, online_check=False)


def test_get_local_paths_missing_path(p4client):
    """get_local_paths skips entries where path is missing (e.g. unmapped paths from p4 where)."""
    info_dicts = [
        {b"depotFile": b"//depot/project/file.txt", b"path": b"C:/workspace/file.txt"},
        {b"depotFile": b"//depot/project/unmapped.txt"},  # no path key — unmapped
    ]
    with patch.object(p4client, "run_cmd", return_value=info_dicts):
        result = p4client.get_local_paths(
            ["//depot/project/file.txt", "//depot/project/unmapped.txt"]
        )
    assert result == ["C:/workspace/file.txt"]


# ---------------------------------------------------------------------------
# Regression: issue #14 — files mapped from outside perforce_root/depot_root
# must not raise on edit (previously failed when silent=False due to a buggy
# prefix-based pre-validation that ignored multi-mapping client views).
# ---------------------------------------------------------------------------

def test_edit_files_accepts_paths_outside_perforce_root_prefix(p4client):
    """A file mapped from a different depot path (e.g. shared Raw assets) must
    not be rejected before p4 sees it. perforce_root is /fake/project and
    depot_root is //depot/project — neither prefix matches this file."""
    outside_file = "//depot/shared_audio/Raw/voice_line.wav"
    with patch.object(p4client, "_P4Client__ensure_changelist", return_value="default"):
        with patch.object(p4client, "run_cmd", return_value=[]) as mock_cmd:
            p4client.edit_files([outside_file])
    mock_cmd.assert_called_once()
    args, kwargs = mock_cmd.call_args
    assert outside_file in kwargs["file_list"]


# ---------------------------------------------------------------------------
# silent kwarg — deprecated
# ---------------------------------------------------------------------------

def test_silent_kwarg_emits_deprecation_warning(tmp_path):
    """Passing silent= (True or False) emits DeprecationWarning."""
    import warnings as _warnings
    (tmp_path / ".p4config").write_text("P4PORT=ssl:example:1666\n")
    with patch.object(P4Client, "host_online", return_value=True):
        with patch.object(P4Client, "run_cmd", return_value=[{b"depotFile": b"//depot/x/...", b"path": b"/fake/...", b"unmap": b""}]):
            with _warnings.catch_warnings(record=True) as caught:
                _warnings.simplefilter("always")
                P4Client(str(tmp_path), user="u", client="c", server="s", silent=True)
    assert any(issubclass(w.category, DeprecationWarning) and "silent" in str(w.message)
               for w in caught), f"expected DeprecationWarning, got: {[str(w.message) for w in caught]}"


def test_silent_kwarg_default_no_warning(tmp_path):
    """Not passing silent at all must not emit a DeprecationWarning."""
    import warnings as _warnings
    (tmp_path / ".p4config").write_text("P4PORT=ssl:example:1666\n")
    with patch.object(P4Client, "host_online", return_value=True):
        with patch.object(P4Client, "run_cmd", return_value=[{b"depotFile": b"//depot/x/...", b"path": b"/fake/...", b"unmap": b""}]):
            with _warnings.catch_warnings(record=True) as caught:
                _warnings.simplefilter("always")
                P4Client(str(tmp_path), user="u", client="c", server="s")
    assert not any(issubclass(w.category, DeprecationWarning) and "silent" in str(w.message)
                   for w in caught), f"unexpected silent warning: {[str(w.message) for w in caught]}"


# ---------------------------------------------------------------------------
# sync_files verify — must not warn on files p4 itself deleted
# ---------------------------------------------------------------------------

def test_sync_files_no_warning_when_p4_deleted_file(p4client, caplog):
    """If p4 sync reports action=deleted for a file, the post-sync verify
    must not warn that the file is missing — its absence is expected."""
    deleted_path = "C:/workspace/path/to/file.txt"
    sync_result = [
        {b"action": b"deleted", b"clientFile": deleted_path.encode(), b"code": b"stat"}
    ]
    with patch.object(p4client, "run_cmd", return_value=sync_result):
        with patch.object(p4client, "get_local_paths", return_value=[deleted_path]):
            with patch("p4cmd.p4cmd.os.path.isfile", return_value=False):
                with caplog.at_level("WARNING", logger="p4cmd.p4cmd"):
                    p4client.sync_files([deleted_path])
    assert "didn't exist after syncing" not in caplog.text, (
        f"unexpected verify warning: {caplog.text}"
    )


def test_sync_files_warns_when_file_missing_unexpectedly(p4client, caplog):
    """Regression guard: when p4 did NOT delete the file but it's still missing
    on disk, the existing 'try force syncing' warning must still fire."""
    path = "C:/workspace/path/to/file.txt"
    sync_result = [
        {b"action": b"updated", b"clientFile": path.encode(), b"code": b"stat"}
    ]
    with patch.object(p4client, "run_cmd", return_value=sync_result):
        with patch.object(p4client, "get_local_paths", return_value=[path]):
            with patch("p4cmd.p4cmd.os.path.isfile", return_value=False):
                with caplog.at_level("WARNING", logger="p4cmd.p4cmd"):
                    p4client.sync_files([path])
    assert "didn't exist after syncing" in caplog.text


# ---------------------------------------------------------------------------
# __init__ depot-root resolution
# ---------------------------------------------------------------------------

def test_init_raises_workspace_error_when_depot_root_unresolvable(tmp_path):
    """An unresolvable depot root must raise WorkSpaceError, not IndexError.

    ``p4 where`` returns nothing when the client is not authenticated
    (expired ticket), so ``get_depot_paths(...)[0]`` blew up with a bare
    ``IndexError: list index out of range``. Callers that retry the
    constructor to recover a dropped connection then log that meaningless
    message instead of "you need to log in", and cannot distinguish an
    auth failure from a real bug.
    """
    (tmp_path / ".p4config").write_text("P4PORT=ssl:perforce.example.com:1666\n")
    with patch.object(P4Client, "host_online", return_value=True):
        with patch.object(P4Client, "run_cmd", return_value=[]):
            with pytest.raises(WorkSpaceError):
                P4Client(
                    str(tmp_path),
                    user="testuser",
                    client="testclient",
                    server="ssl:perforce.example.com:1666",
                )


def test_init_error_message_mentions_login(tmp_path):
    """The raised message must point at the likely cause (auth/reachability)."""
    (tmp_path / ".p4config").write_text("P4PORT=ssl:perforce.example.com:1666\n")
    with patch.object(P4Client, "host_online", return_value=True):
        with patch.object(P4Client, "run_cmd", return_value=[]):
            with pytest.raises(WorkSpaceError) as excinfo:
                P4Client(
                    str(tmp_path),
                    user="testuser",
                    client="testclient",
                    server="ssl:perforce.example.com:1666",
                )
    message = str(excinfo.value).lower()
    assert "login" in message or "ticket" in message


# ---------------------------------------------------------------------------
# max_wait: -vnet.maxwait on every p4 command
# ---------------------------------------------------------------------------

def _run_cmd_command(p4client, **run_cmd_kwargs):
    """The command line run_cmd starts p4 with, with p4 imitated by fake_p4_popen."""
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen)
        p4client.run_cmd("info", online_check=False, **run_cmd_kwargs)
    return mock_popen.call_args.args[0]


def test_max_wait_off_by_default_keeps_command_lines(p4client):
    assert p4client.max_wait is None
    assert _run_cmd_command(p4client).startswith("p4 -G -u testuser -c testclient info ")
    assert _run_cmd_command(p4client, marshal_output=False).startswith("p4 info ")


@pytest.mark.parametrize("marshal_output, start", [
    (True, "p4 -vnet.maxwait=30 -G -u testuser -c testclient info "),
    (False, "p4 -vnet.maxwait=30 info "),
])
def test_run_cmd_passes_max_wait(p4client, marshal_output, start):
    p4client.set_max_wait(30)
    assert _run_cmd_command(p4client, marshal_output=marshal_output).startswith(start)


@pytest.mark.parametrize("value", [0, -1, 2147483648, 0.5, 30.0, True, "30"])
def test_set_max_wait_rejects_anything_but_an_int_in_range(p4client, value):
    """p4 reads values under 1 as no limit and wraps those from 2**31 around; the rest aren't ints."""
    with pytest.raises(ValueError):
        p4client.set_max_wait(value)


def test_init_commands_pass_max_wait(tmp_path):
    """Every command the constructor runs has the limit: p4 set and p4 clients to find the client, then p4 where."""
    import marshal
    (tmp_path / ".p4config").write_text("P4PORT=ssl:perforce.example.com:1666\n")
    outputs = [
        b"",  # p4 set P4CLIENT: not set
        marshal.dumps({b"client": b"testclient"}),  # p4 clients -u testuser
        marshal.dumps({b"depotFile": b"//depot/project/...", b"path": b"/fake/project/..."}),  # p4 where
    ]
    with patch.object(P4Client, "host_online", return_value=True), \
         patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, outputs)
        client = P4Client(str(tmp_path), user="testuser", server="ssl:perforce.example.com:1666", max_wait=10)
    commands = [c.args[0] for c in mock_popen.call_args_list]
    assert all(command.startswith("p4 -vnet.maxwait=10 ") for command in commands), commands
    assert len(commands) == 3
    assert " set P4CLIENT " in commands[0] and " clients -u testuser " in commands[1] and " where " in commands[2]
    assert client.client == "testclient"
    assert client.depot_root == "//depot/project"


def test_make_new_changelist_passes_max_wait(p4client):
    """Both of make_new_changelist's commands get the limit."""
    p4client.set_max_wait(30)
    template = b"Change: new\n\nDescription:\n\t<enter description here>\n\nFiles:\n"
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen, \
         patch.object(p4client, "host_online", return_value=True):
        fake_p4_popen(mock_popen, [template, b"Change 12345 created.\n"])
        assert p4client.make_new_changelist("test description") == 12345
    commands = [c.args[0] for c in mock_popen.call_args_list]
    assert len(commands) == 2
    assert all(command.startswith("p4 -vnet.maxwait=30 -u testuser -c testclient ") for command in commands)


def test_update_changelist_description_passes_max_wait(p4client):
    """Both of update_changelist_description's commands get the limit."""
    p4client.set_max_wait(30)
    template = b"Change: 123\n\nDescription:\n\told\n\nFiles:\n"
    with patch("p4cmd.p4cmd.subprocess.Popen") as mock_popen:
        fake_p4_popen(mock_popen, [template, b"Change 123 updated.\n"])
        assert p4client.update_changelist_description(123, "new") is True
    commands = [c.args[0] for c in mock_popen.call_args_list]
    assert len(commands) == 2
    assert all(command.startswith("p4 -vnet.maxwait=30 -u testuser -c testclient ") for command in commands)

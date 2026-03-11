"""Tests for p4cmd/p4file.py — P4File and Status."""
import datetime

import pytest

from p4cmd.p4file import P4File, Status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_file(**kwargs):
    f = P4File()
    for attr, val in kwargs.items():
        setattr(f, attr, val)
    return f


# ---------------------------------------------------------------------------
# have_revision / head_revision setters
# ---------------------------------------------------------------------------

def test_have_revision_int_coercion():
    f = P4File()
    f.have_revision = "5"
    assert f.have_revision == 5


def test_have_revision_invalid_becomes_none():
    f = P4File()
    f.have_revision = "bad"
    assert f.have_revision is None


def test_head_revision_int_coercion():
    f = P4File()
    f.head_revision = "12"
    assert f.head_revision == 12


def test_head_revision_invalid_becomes_none():
    f = P4File()
    f.head_revision = "x"
    assert f.head_revision is None


# ---------------------------------------------------------------------------
# last_submit_time setter
# ---------------------------------------------------------------------------

def test_last_submit_time_parses_timestamp():
    f = P4File()
    f.last_submit_time = "0"  # Unix epoch
    expected = datetime.datetime.fromtimestamp(0.0).strftime("%Y-%m-%d %H:%M:%S")
    assert f.last_submit_time == expected


def test_last_submit_time_valid_timestamp():
    f = P4File()
    ts = "1700000000"
    f.last_submit_time = ts
    expected = datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    assert f.last_submit_time == expected


def test_last_submit_time_invalid_passthrough():
    f = P4File()
    f.last_submit_time = "not-a-timestamp"
    assert f.last_submit_time == "not-a-timestamp"


# ---------------------------------------------------------------------------
# file_size / get_file_size
# ---------------------------------------------------------------------------

def test_get_file_size_in_mb():
    f = P4File()
    f.file_size = 1048576
    assert f.get_file_size(in_megabyte=True) == 1.0


def test_get_file_size_in_bytes():
    f = P4File()
    f.file_size = 2097152
    assert f.get_file_size(in_megabyte=False) == 2097152


def test_get_file_size_none_on_none():
    f = P4File()
    f.file_size = None
    assert f.get_file_size() is None


def test_get_file_size_none_on_invalid_string():
    f = P4File()
    f.file_size = "not-a-number"
    assert f.get_file_size() is None


# ---------------------------------------------------------------------------
# Status predicates
# ---------------------------------------------------------------------------

def test_is_open_for_add():
    f = P4File()
    f.action = "add"
    assert f.is_open_for_add() is True
    f.action = "edit"
    assert f.is_open_for_add() is False


def test_is_open_for_edit():
    f = P4File()
    f.action = "edit"
    assert f.is_open_for_edit() is True
    f.action = "add"
    assert f.is_open_for_edit() is False


def test_is_untracked_true():
    f = P4File()
    f._raw_data = "//depot/file.txt - no such file(s)."
    assert f.is_untracked() is True


def test_is_untracked_false():
    f = P4File()
    f._raw_data = "{'depotFile': '//depot/file.txt'}"
    assert f.is_untracked() is False


def test_is_untracked_none_raw_data():
    f = P4File()
    f._raw_data = None
    assert f.is_untracked() is False


def test_is_checked_out_true():
    f = P4File()
    f.action = "edit"
    assert f.is_checked_out() is True


def test_is_checked_out_false():
    f = P4File()
    assert f.is_checked_out() is False


def test_is_depot_only_true():
    f = P4File()
    f._have_revision = None
    f.head_revision = "5"
    assert f.is_depot_only() is True


def test_is_depot_only_false_have_rev_set():
    f = P4File()
    f.have_revision = "3"
    f.head_revision = "5"
    assert f.is_depot_only() is False


def test_is_deleted_true():
    f = P4File()
    f.head_action = "delete"
    assert f.is_deleted() is True


def test_is_deleted_false():
    f = P4File()
    f.head_action = "edit"
    assert f.is_deleted() is False


def test_is_marked_for_delete():
    f = P4File()
    f.action = "delete"
    assert f.is_marked_for_delete() is True
    f.action = "edit"
    assert f.is_marked_for_delete() is False


def test_is_moved_deleted_via_action():
    f = P4File()
    f.action = "move/delete"
    assert f.is_moved_deleted() is True


def test_is_moved_deleted_via_head_action():
    f = P4File()
    f.head_action = "move/delete"
    assert f.is_moved_deleted() is True


def test_is_moved_deleted_false():
    f = P4File()
    assert f.is_moved_deleted() is False


def test_is_moved_added():
    f = P4File()
    f.action = "move/add"
    assert f.is_moved_added() is True
    f.action = "edit"
    assert f.is_moved_added() is False


def test_is_up_to_date_true():
    f = P4File()
    f.have_revision = "5"
    f.head_revision = "5"
    assert f.is_up_to_date() is True


def test_is_up_to_date_false():
    f = P4File()
    f.have_revision = "4"
    f.head_revision = "5"
    assert f.is_up_to_date() is False


def test_is_under_client_root_true():
    f = P4File()
    f._raw_data = "some normal output"
    assert f.is_under_client_root() is True


def test_is_under_client_root_false():
    f = P4File()
    f._raw_data = "/some/path is not under client's root"
    assert f.is_under_client_root() is False


def test_is_under_client_root_none_raw_data():
    f = P4File()
    f._raw_data = None
    assert f.is_under_client_root() is True


# ---------------------------------------------------------------------------
# needs_syncing
# ---------------------------------------------------------------------------

def test_needs_syncing_deleted_returns_false():
    f = P4File()
    f.head_action = "delete"
    assert f.needs_syncing() is False


def test_needs_syncing_open_for_add_returns_false():
    f = P4File()
    f.action = "add"
    f.head_revision = "1"
    assert f.needs_syncing() is False


def test_needs_syncing_no_head_revision_returns_false():
    f = P4File()
    f._head_revision = None
    assert f.needs_syncing() is False


def test_needs_syncing_no_have_revision_returns_true():
    f = P4File()
    f._have_revision = None
    f.head_revision = "5"
    assert f.needs_syncing() is True


def test_needs_syncing_behind_returns_true():
    f = P4File()
    f.have_revision = "3"
    f.head_revision = "5"
    assert f.needs_syncing() is True


def test_needs_syncing_up_to_date_returns_false():
    f = P4File()
    f.have_revision = "5"
    f.head_revision = "5"
    assert f.needs_syncing() is False


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

def test_get_status_open_for_delete():
    f = P4File()
    f.action = "delete"
    assert f.get_status() == Status.OPEN_FOR_DELETE


def test_get_status_deleted():
    f = P4File()
    f.head_action = "delete"
    assert f.get_status() == Status.DELETED


def test_get_status_moved_deleted():
    f = P4File()
    f.head_action = "move/delete"
    assert f.get_status() == Status.MOVED_DELETED


def test_get_status_need_sync():
    f = P4File()
    f.have_revision = "3"
    f.head_revision = "5"
    assert f.get_status() == Status.NEED_SYNC


def test_get_status_depot_only():
    # Note: in get_status(), needs_syncing() is checked before is_depot_only().
    # When have_revision is None and head_revision is set, needs_syncing() returns
    # True, so get_status() returns NEED_SYNC rather than DEPOT_ONLY.
    # is_depot_only() is still useful as a direct predicate (tested above).
    f = P4File()
    f._have_revision = None
    f.head_revision = "5"
    assert f.get_status() == Status.NEED_SYNC


def test_get_status_open_for_add():
    f = P4File()
    f.action = "add"
    assert f.get_status() == Status.OPEN_FOR_ADD


def test_get_status_open_for_edit():
    f = P4File()
    f.action = "edit"
    f.have_revision = "2"
    f.head_revision = "2"
    assert f.get_status() == Status.OPEN_FOR_EDIT


def test_get_status_untracked():
    f = P4File()
    f._raw_data = "- no such file(s)"
    assert f.get_status() == Status.UNTRACKED


def test_get_status_moved():
    f = P4File()
    f.action = "move/add"
    assert f.get_status() == Status.MOVED


def test_get_status_up_to_date():
    f = P4File()
    f.have_revision = "5"
    f.head_revision = "5"
    assert f.get_status() == Status.UP_TO_DATE


def test_get_status_unknown():
    f = P4File()
    # Neither have == head, nor any action/raw_data set — falls through to UNKNOWN
    f.have_revision = "3"
    f.head_revision = "2"  # have > head: unusual, returns UNKNOWN
    assert f.get_status() == Status.UNKNOWN


def test_get_status_override_takes_priority():
    f = P4File()
    f.action = "edit"
    f._status_override = Status.UNKNOWN
    assert f.get_status() == Status.UNKNOWN


# ---------------------------------------------------------------------------
# __eq__
# ---------------------------------------------------------------------------

def test_eq_identical_files():
    f1 = P4File("/local/file.txt", "//depot/file.txt")
    f2 = P4File("/local/file.txt", "//depot/file.txt")
    assert f1 == f2


def test_eq_different_files():
    f1 = P4File("/local/a.txt")
    f2 = P4File("/local/b.txt")
    assert f1 != f2


def test_eq_non_p4file():
    f = P4File("/local/file.txt")
    assert f.__eq__("not a P4File") is NotImplemented

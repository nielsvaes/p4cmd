import datetime


class Status:
    OPEN_FOR_DELETE = "OPEN_FOR_DELETE"
    NEED_SYNC = "NEED_SYNC"
    DEPOT_ONLY = "DEPOT_ONLY"
    OPEN_FOR_ADD = "OPEN_FOR_ADD"
    OPEN_FOR_EDIT = "OPEN_FOR_EDIT"
    UNTRACKED = "UNTRACKED"
    MOVED = "MOVED"
    UP_TO_DATE = "UP_TO_DATE"
    UNKNOWN = "UNKNOWN"
    DELETED = "DELETED"
    MOVED_DELETED = "MOVED_DELETED"


class P4File:
    def __init__(self, local_file_path=None, depot_file_path=None):
        self._local_file_path = local_file_path
        self._depot_file_path = depot_file_path
        self._last_submitted_by = None
        self._have_revision = None
        self._head_revision = None
        self._checked_out_by = None
        self._last_submit_time = None
        self._action = None
        self._raw_data = None
        self._head_action = None
        self._file_size = None
        self._status_override = None

    def update_self(self, p4client):
        search_file = self._depot_file_path or self._local_file_path
        copy_of_self = p4client.files_to_p4files([search_file])[0]
        self.__dict__.update(copy_of_self.__dict__)

    def update_last_submitted_by(self, p4client):
        info_dict = p4client.run_cmd("changes", [self._depot_file_path])[0]
        self.last_submitted_by = info_dict.get("user", "UNKNOWN")

    # --- Status predicates ---

    def is_valid(self):
        return self._local_file_path is not None or self._depot_file_path is not None

    def is_open_for_add(self):
        return self._action == "add"

    def is_open_for_edit(self):
        return self._action == "edit"

    def is_untracked(self):
        return bool(self._raw_data and "- no such file(s)" in self._raw_data)

    def is_local_only(self):
        return self.is_untracked()

    def is_checked_out(self):
        return self._action is not None

    def is_depot_only(self):
        return self._have_revision is None and self._head_revision is not None

    def is_deleted(self):
        return self._head_action == "delete"

    def is_marked_for_delete(self):
        return self._action == "delete"

    def is_moved_deleted(self):
        return self._action == "move/delete" or self._head_action == "move/delete"

    def is_moved_added(self):
        return self._action == "move/add"

    def is_up_to_date(self):
        return self._have_revision == self._head_revision

    def is_under_client_root(self):
        return not (self._raw_data and "is not under client's root" in self._raw_data)

    def needs_syncing(self):
        if self.is_deleted() or self.is_moved_deleted():
            return False
        if self.is_open_for_add() or self.is_open_for_edit():
            return False
        if self._head_revision is None:
            return False
        if self._have_revision is None:
            return True
        return self._have_revision < self._head_revision

    def get_status(self):
        if self._status_override is not None:
            return self._status_override
        if self.is_marked_for_delete():
            return Status.OPEN_FOR_DELETE
        if self.is_deleted():
            return Status.DELETED
        if self.is_moved_deleted():
            return Status.MOVED_DELETED
        if self.needs_syncing():
            return Status.NEED_SYNC
        if self.is_depot_only():
            return Status.DEPOT_ONLY
        if self.is_open_for_add():
            return Status.OPEN_FOR_ADD
        if self.is_open_for_edit():
            return Status.OPEN_FOR_EDIT
        if self.is_local_only():
            return Status.UNTRACKED
        if self.is_moved_added():
            return Status.MOVED
        if self._have_revision == self._head_revision:
            return Status.UP_TO_DATE
        return Status.UNKNOWN

    # --- Properties ---

    @property
    def local_file_path(self):
        return self._local_file_path

    @local_file_path.setter
    def local_file_path(self, value):
        self._local_file_path = value

    @property
    def depot_file_path(self):
        return self._depot_file_path

    @depot_file_path.setter
    def depot_file_path(self, value):
        self._depot_file_path = value

    @property
    def action(self):
        return self._action

    @action.setter
    def action(self, value):
        self._action = value

    @property
    def head_action(self):
        return self._head_action

    @head_action.setter
    def head_action(self, value):
        self._head_action = value

    @property
    def raw_data(self):
        return self._raw_data

    @raw_data.setter
    def raw_data(self, value):
        self._raw_data = value

    @property
    def have_revision(self):
        return self._have_revision

    @have_revision.setter
    def have_revision(self, value):
        try:
            self._have_revision = int(value)
        except (TypeError, ValueError):
            self._have_revision = None

    @property
    def head_revision(self):
        return self._head_revision

    @head_revision.setter
    def head_revision(self, value):
        try:
            self._head_revision = int(value)
        except (TypeError, ValueError):
            self._head_revision = None

    @property
    def last_submit_time(self):
        return self._last_submit_time

    @last_submit_time.setter
    def last_submit_time(self, value):
        try:
            value = datetime.datetime.fromtimestamp(float(value)).strftime('%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError):
            pass
        self._last_submit_time = value

    @property
    def checked_out_by(self):
        return self._checked_out_by

    @checked_out_by.setter
    def checked_out_by(self, value):
        self._checked_out_by = value

    @property
    def last_submitted_by(self):
        return self._last_submitted_by

    @last_submitted_by.setter
    def last_submitted_by(self, value):
        self._last_submitted_by = value

    @property
    def file_size(self):
        return self._file_size

    @file_size.setter
    def file_size(self, value):
        self._file_size = value

    def get_file_size(self, in_megabyte=True):
        """Returns file size in MB (default) or bytes"""
        try:
            size = int(self._file_size)
            return round(size / 1048576, 2) if in_megabyte else size
        except (TypeError, ValueError):
            return None

    # --- Legacy get_*/set_* API (kept for backwards compatibility) ---

    def get_local_file_path(self):
        return self.local_file_path

    def set_local_file_path(self, value):
        self.local_file_path = value

    def get_depot_file_path(self):
        return self.depot_file_path

    def set_depot_file_path(self, value):
        self.depot_file_path = value

    def get_action(self):
        return self.action

    def set_action(self, value):
        self.action = value

    def get_head_action(self):
        return self.head_action

    def set_head_action(self, value):
        self.head_action = value

    def get_raw_data(self):
        return self.raw_data

    def set_raw_data(self, value):
        self.raw_data = value

    def get_have_revision(self):
        return self.have_revision

    def set_have_revision(self, value):
        self.have_revision = value

    def get_head_revision(self):
        return self.head_revision

    def set_head_revision(self, value):
        self.head_revision = value

    def get_last_submit_time(self):
        return self.last_submit_time

    def set_last_submit_time(self, value):
        self.last_submit_time = value

    def get_checked_out_by(self):
        return self.checked_out_by

    def set_checked_out_by(self, value):
        self.checked_out_by = value

    def get_last_submitted_by(self):
        return self.last_submitted_by

    def set_last_submitted_by(self, value):
        self.last_submitted_by = value

    def set_file_size(self, value):
        self.file_size = value

    def set_status(self, value):
        self._status_override = value

    def __eq__(self, other):
        if not isinstance(other, P4File):
            return NotImplemented
        return self.__dict__ == other.__dict__

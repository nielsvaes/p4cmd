import datetime

class Status:
    OPEN_FOR_DELETE = "OPEN_FOR_DELETE"
    NEED_SYNC = "NEED_SYNC"
    DEPOT_ONLY = "DEPOT_ONLY"
    OPEN_FOR_ADD = "OPEN_FOR_ADD"
    OPEN_FOR_EDIT = "OPEN_FOR_EDIT"
    UNTRACKED = "UNTRACKED"
    MOVED = "MOVED"
    UP_TO_DATE  = "UP_TO_DATE"
    UNKNOWN = "UNKNOWN"


class P4File(object):
    def __init__(self, local_file_path=None, depot_file_path=None):
        super(P4File, self).__init__()
        self.__local_file_path = local_file_path
        self.__depot_file_path = depot_file_path

        self.__last_submitted_by = None
        self.__have_revision = None
        self.__head_revision = None
        self.__checked_out_by = None
        self.__last_submit_time = None
        self.__action = None
        self.__raw_data = None
        self.__head_action = None

    def update_self(self, p4client):
        if self.__depot_file_path is not None:
            search_file = self.__depot_file_path
        else:
            search_file = self.__local_file_path

        copy_of_self = p4client.files_to_p4files([search_file])[0]
        self.__dict__.update(copy_of_self.__dict__)

    def update_last_submitted_by(self, p4client):
        info_dict = p4client.run_cmd2("changes", [self.__depot_file_path])[0]
        self.set_last_submitted_by(info_dict.get("user", "UNKNOWN"))

    def is_valid(self):
        if self.__local_file_path is not None or self.__depot_file_path is not None:
            return True
        return False

    def is_open_for_add(self):
        if self.__action == "add":
            return True
        return False

    def is_open_for_edit(self):
        if self.__action == "edit":
            return True
        return False

    def is_untracked(self):
        if "- no such file(s)" in self.__raw_data:
            return True
        return False

    def is_local_only(self):
        return self.is_untracked()

    def is_checked_out(self):
        if self.__action is not None:
            return True
        return False

    def is_depot_only(self):
        if self.__have_revision is None and self.__head_revision is not None:
            return True
        return False

    def is_deleted(self):
        if self.__head_action == "delete":
            return True
        return False

    def is_marked_for_delete(self):
        if self.__action == "delete":
            return True
        return False

    def is_moved_deleted(self):
        if self.__action == "move/delete" or self.__head_action == "move/delete":
            return True
        return False

    def is_moved_added(self):
        if self.__action == "move/add":
            return True
        return False

    def is_up_to_date(self):
        if self.__have_revision == self.__head_revision:
            return True
        return False

    def is_under_client_root(self):
        if "is not under client's root" in self.__raw_data:
            return False
        return True

    def needs_syncing(self):
        if not self.is_deleted() and not self.is_moved_deleted():
            if not self.is_open_for_add() and not self.is_open_for_edit():
                if self.__head_revision is None:
                    return False
                if self.__have_revision is None and self.__head_revision is not None:
                    return True
                if self.__have_revision < self.__head_revision:
                    return True
                return False

    def get_status(self):
        if self.is_marked_for_delete():
            return Status.OPEN_FOR_DELETE
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
        if self.__have_revision == self.__head_revision:
            return Status.UP_TO_DATE

    def set_status(self, value):
        self.__status = value

    def get_head_action(self):
        return self.__head_action

    def set_head_action(self, value):
        self.__head_action = value

    def get_raw_data(self):
        return self.__raw_data

    def set_raw_data(self, value):
        self.__raw_data = value

    def get_action(self):
        return self.__action

    def set_action(self, value):
        self.__action = value

    def get_depot_file_path(self):
        return self.__depot_file_path

    def set_depot_file_path(self, value):
        self.__depot_file_path = value

    def get_local_file_path(self):
        return self.__local_file_path

    def set_local_file_path(self, value):
        self.__local_file_path = value

    def get_last_submit_time(self):
        return self.__last_submit_time

    def set_last_submit_time(self, value):
        try:
            value = datetime.datetime.fromtimestamp(float(value)).strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
        self.__last_submit_time = value

    def get_checked_out_by(self):
        return self.__checked_out_by

    def set_checked_out_by(self, value):
        self.__checked_out_by = value

    def get_head_revision(self):
        return self.__head_revision

    def set_head_revision(self, value):
        try:
            value = int(value)
        except:
            value = None
        self.__head_revision = value

    def get_have_revision(self):
        return self.__have_revision

    def set_have_revision(self, value):
        try:
            value = int(value)
        except:
            value = None
        self.__have_revision = value

    def get_last_submitted_by(self):
        return self.__last_submitted_by

    def set_last_submitted_by(self, value):
        self.__last_submitted_by = value
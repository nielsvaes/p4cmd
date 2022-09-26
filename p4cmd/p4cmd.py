import os
import marshal
import sys
import subprocess
import socket

import logging

from . import p4errors
from .p4file import P4File, Status

MAX_CMD_LEN = 8190
MAX_ARG_LEN = 8000  # max length of args string when combined, close to max, but leaving some extra margin


class P4Client(object):
    def __init__(self, perforce_root, user=None, client=None, server=None, silent=True):
        """
        Make a new P4Client

        :param perforce_root: *string* root of your Perforce workspace. This would also be where your .p4config file is
        :param user: *string* P4USER, if None will tried to be found automatically
        :param client: *string* P4CLIENT, if None will tried to be found automatically
        :param silent: *bool* if True, suppresses error messages to cut down on terminal spam
        """
        self.perforce_root = perforce_root

        self.user = user
        self.client = client
        self.server = server

        if not self.__p4config_exists():
            if not silent:
                logging.warning("No .p4config file found in %s!" % self.perforce_root)

        if user is None:
            self.user = self.get_p4_setting("P4USER")
            if self.user is None:
                raise p4errors.WorkSpaceError("Could not find P4USER")
        if client is None:
            self.client = self.find_p4_client()
            if self.client is None:
                raise p4errors.WorkSpaceError("Could not find P4CLIENT")
        if server is None:
            self.server = self.get_p4_setting("P4PORT")
            if self.server is None:
                raise p4errors.WorkSpaceError("Could not find P4PORT")

        self.silent = silent

    @classmethod
    def from_env(cls, *args, **kwargs):
        """
        In case the P4ROOT environment string exists, calling this function will return a P4Client with its root set
        to P4ROOT

        :param user: *string* P4USER, if None will tried to be found automatically
        :param client: *string* P4CLIENT, if None will tried to be found automatically
        :return: P4Client
        """
        root_folder = os.environ.get("P4ROOT", "")
        return cls(root_folder, *args, **kwargs)

    def set_perforce_root(self, root):
        """
        Set the root of the perforce commands. This is important so it can use the proper .p4config file for the cmds
        """
        self.perforce_root = root

    def run_cmd2(self, cmd, args=[], use_global_options=True, online_check=True):
        """
        Reads the output stream of the command and returns it as a marshaled dict.

        :param cmd: *string* p4 command like "change", "reopen", "move"
        :param args: *list* of string arguments like ["-c", "27277", "//depot/folder/file.atom"]
        :param use_global_options: *bool*
        :param online_check: *bool* if set to True, will first check if the remote server is reachable before executing the command.
        :return: *list* of dictionaries with either the marshaled returns of the command or dictionaries with the
        raw output of the command
        """
        if online_check:
            if not self.host_online():
                logging.warning("Can't connect to %s on port %s" % (self.__server_address(), self.__port_number()))
                #raise p4errors.ServerOffline("Can't connect to %s on port %s" % (self.__server_address(), self.__port_number()))

        if self.perforce_root is not None:
            os.chdir(self.perforce_root)

        # build arg strings within the max size
        clamped_arg_list = split_list_into_strings_of_length(args, max_length=MAX_ARG_LEN)

        dict_list = []
        for clamped_arg in clamped_arg_list:
            if use_global_options:
                global_options = ["-u", self.user, "-c", self.client]
                command = "p4 -G %s %s %s" % (" ".join(global_options), cmd, clamped_arg)
            else:
                command = "p4 %s %s" % (cmd, clamped_arg)

            if len(command) > MAX_CMD_LEN:
                # This shouldn't happen, but just in case the command prefix end up really long
                logging.warning("Command length: {} exceeds MAX_CMD_LEN {} on command: {}".format(len(command),
                                                                                                  MAX_CMD_LEN,
                                                                                                  command))

            pipe = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
            output = pipe.stdout

            try:
                while True:
                    value_dict = marshal.load(output)
                    dict_list.append(value_dict)
            except EOFError:
                pass
            except ValueError as error:
                output_dict = {
                    "command": command,
                    "code": "error",
                    "error": str(error),
                    "raw_output": subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)
                }
                dict_list.append(output_dict)

        return dict_list

    def get_p4_setting(self, setting):
        """
        Gets a Perforce setting

        :param setting: *string*
        :return: setting value. In case a bad marshal object is returned and the function can't find the settings,
        the entire info dictionary from Perforce is returned
        """
        try:
            # skipping the online check for setting commands
            info_dict = self.run_cmd2("set", [setting], use_global_options=False, online_check=False)[0]
        except:
            raise p4errors.WorkSpaceError("Unable to find setting %s" % setting)

        raw_output = self.__get_dict_value(info_dict, "raw_output", None)

        if raw_output is not None:
            if raw_output == b"":
                return None
            try:
                raw_output = raw_output.split("=")[1].split(" ")[0].rstrip()
            except:
                raw_output = raw_output.decode("utf-8").split("=")[1].split(" ")[0].rstrip()

            if raw_output == "none":
                return None
            return raw_output

    def find_p4_client(self):
        """
        Uses the current P4CLIENT if set, or otherwise gets the first available workspace
        """
        client = self.get_p4_setting("P4CLIENT")
        if client is None:
            return self.get_all_workspaces()[0]
        return client

    def find_p4_port(self):
        """
        Returns the Perforce server this client connects to

        :return: *string*
        """
        return self.get_p4_setting("P4PORT")

    def set_workspace(self, workspace):
        """
        Chooses a workspace to be used in calls with this P4Client instance
        """
        workspaces = self.get_all_workspaces()
        if workspace in workspaces:
            self.client = workspace
        else:
            raise p4errors.WorkSpaceError("Tried to set a workspace/client({}) that did not exist".format(workspace))

    def files_to_p4files(self, file_list, allow_invalid_files=False):
        """
        Turns a list of files into P4File objects. If the Perforce server can't be reached, returns a list of P4Files
        that have their local path set and their status set to UNKNOWN

        :param file_list: *list* of file paths
        :param allow_invalid_files: *bool* if set to False, this function will skip any files that are deleted or
        marked for delete
        :return: *list* P4Files
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list

        if self.host_online():
            fstat_output = self.run_cmd2("fstat", file_list)
            p4files = self.__fstat_to_p4_files(fstat_output, allow_invalid_files=allow_invalid_files)
            return p4files
        else:
            p4files = []
            for file_path in file_list:
                perforce_file = P4File()
                perforce_file.set_local_file_path(file_path)
                perforce_file.set_status(Status.UNKNOWN)
                perforce_file.set_raw_data("HOST OFFLINE")
                p4files.append(perforce_file)
            return p4files

    def folder_to_p4files(self, folder, include_subfolders=True, allow_invalid_files=False):
        """
        Returns all the files in a folder as a list of P4File objects. Uses the files_to_p4files function if the host
        is offline

        :param folder: *string*
        :param include_subfolders: *bool*
        :param allow_invalid_files:  *bool* if set to False, this function will skip any files that are deleted or
        marked for delte
        :return: *list* P4Files
        """

        if self.host_online():
            if include_subfolders:
                folder = folder + "..." if folder.endswith("/") or folder.endswith("\\") else folder + "/..."
            else:
                folder = folder + "*" if folder.endswith("/") or folder.endswith("\\") else folder + "/*"

            fstat_output = self.run_cmd2("fstat", [folder])
            p4files = self.__fstat_to_p4_files(fstat_output, allow_invalid_files=allow_invalid_files)
            return p4files

        else:
            if include_subfolders:
                all_files = []
                for root, dirs, files in os.walk(folder):
                    for file_name in files:
                        complete_file_path = os.path.join(root, file_name)
                        if not complete_file_path in files:
                            all_files.append(complete_file_path)
            else:
                all_files = [os.path.join(folder, file) for file in os.listdir(folder) if os.path.isfile(os.path.join(folder, file))]

            return self.files_to_p4files(all_files)

    def make_new_changelist(self, description):
        """
        Makes a new numbered changelist

        :param description: *string* description of the changelist
        :return: *string* changelist number
        """
        if not self.host_online():
            logging.warning("Can't connect to %s on port %s" % (self.__server_address(), self.__port_number()))
            #raise p4errors.ServerOffline("Can't connect to %s on port %s" % (self.__server_address(), self.__port_number()))
            return

        output = subprocess.check_output('p4 --field "Description=%s" --field "Files=" change -o | p4 change -i' % description,
                                         stderr=subprocess.STDOUT,
                                         shell=True).decode()
        changelist_number = output.split(" ")[1]
        return int(changelist_number)

    def changelist_exists(self, changelist):
        """
        Returns true if the changelist number exists

        :param changelist: *str* or *int* changelist number or description
        :return: *bool*
        """
        if type(changelist) == int:
            if changelist in self.get_pending_changelists():
                return True
        else:
            changelist = str(changelist)
            changelists = self.get_pending_changelists(description_filter=changelist, perfect_match_only=True, case_sensitive=True)
            if len(changelists):
                return True
            return False

    def move_files_to_changelist(self, file_list, changelist="default"):
        """
        Moves the files in file_list to a changelist. Makes a new changelist if the given one doesn't exist.

        :param file_list: *list* of file paths
        :param changelist: *string* or *int* changelist description or changelist number
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        changelist = self.__ensure_changelist(changelist)
        info_dicts = self.run_cmd2("reopen", ["-c", changelist] + file_list)

        for info_dict in info_dicts:
            if self.__get_dict_value(info_dict, "code") == "error" and not self.silent:
                print(self.__get_dict_value(info_dict, "data"))

        return info_dicts

    def rename_file(self, old_file_path, new_file_path, changelist="default"):
        """
        P4 move-renames a file

        :param old_file_path: *string*
        :param new_file_path: *string*
        :param changelist:  *string* or *int* changelist number or description. Will be made if it doesn't exist.
        :return: *bool*
        """
        changelist = self.__ensure_changelist(changelist)

        info_dict = self.run_cmd2("move", ["-c", str(changelist), old_file_path, new_file_path])[0]
        if self.__get_dict_value(info_dict, "code") != "error":
            return True
        return False

    def copy_file(self, original_file_path, copied_file_path, changelist="default"):
        """
        P4 copy-renames a file

        :param original_file_path: *string*
        :param copied_file_path: *string*
        :param changelist:  *string* or *int* changelist number or description. Will be made if it doesn't exist.
        :return: *bool*
        """
        changelist = self.__ensure_changelist(changelist)

        info_dict = self.run_cmd2("copy", ["-c", str(changelist), original_file_path, copied_file_path])[0]
        if self.__get_dict_value(info_dict, "code") != "error":
            return True
        return False

    def revert_files(self, file_list, unchanged_only=False):
        """
        Reverts files in file_list

        :param file_list: *list* files
        :param unchanged_only: *bool*
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent:
            self.__validate_file_list(file_list)
        if unchanged_only:
            info_dicts = self.run_cmd2("revert", ["-a"], file_list)
        else:
            info_dicts = self.run_cmd2("revert", file_list)

        return info_dicts

    def revert_folders(self, folder_list):
        """
        Recursively reverts complete folders

        :param folder_list: *list* folder paths
        :return: *list* of info dicts
        """
        folder_list = convert_to_list(folder_list) if not isinstance(folder_list, list) else folder_list
        if not self.silent: self.__validate_file_list(folder_list)

        cleaned_folder_list = []
        for folder in folder_list:
            folder = folder.replace("\\", "/")
            folder = folder.rstrip("/")
            folder += "/..."
            cleaned_folder_list.append(folder)

        info_dicts = self.run_cmd2("revert", [] + cleaned_folder_list)
        return info_dicts

    def revert_changelist(self, unchanged_only=False, changelist="default"):
        """
        Reverts all files in a given changelist
        :param changelist: string or int value
        :param unchanged_only: *bool*
        """
        files = self.get_files_in_changelist(changelist)
        self.revert_files(files, unchanged_only=unchanged_only)

    def sync_folders(self, folder_list):
        """
        Recursively syncs complete folders

        :param folder_list: *list* folder paths
        :return: *list* of info dicts
        """
        folder_list = convert_to_list(folder_list) if not isinstance(folder_list, list) else folder_list
        if not self.silent: self.__validate_file_list(folder_list)

        cleaned_folder_list = []
        for folder in folder_list:
            folder = folder.replace("\\", "/")
            folder = folder.rstrip("/")
            folder += "/..."
            cleaned_folder_list.append(folder)

        info_dicts = self.run_cmd2("sync", [] + cleaned_folder_list)
        return info_dicts

    def sync_files(self, file_list, revision=-1, verify=True, force=False):
        """
        Syncs files

        :param file_list: *list*
        :param verify: *bool* if true, checks that file synced files exist on disk. Throws a warning if they don't
        This could happen when a synced file is deleted locally
        :param revision: *int* if -1, get latest, else get revision number
        :param force: *bool* force sync
        :return: *list* of info dicts
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if revision != -1:
            verify = False
            file_list = [f"{path}#{revision}" for path in file_list]

        initial_arg_list = ["-f"] if force else []
        if not self.silent: self.__validate_file_list(file_list)

        info_dicts = self.run_cmd2("sync", initial_arg_list + file_list)

        if verify:
            local_file_paths = self.get_local_paths(file_list)
            for local_file_path in local_file_paths:
                if not os.path.isfile(local_file_path):
                    logging.warning(f"File didn't exist after syncing, try force syncing it instead: {local_file_path}")

        return info_dicts

    def delete_files(self, file_list, changelist="default"):
        """
        Marks files for delete

        :param file_list: *list*
        :param changelist: *string* or *int* changelist number
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent: self.__validate_file_list(file_list)
        info_dicts = self.run_cmd2("delete", ["-c", changelist] + file_list)
        return info_dicts

    def delete_changelist(self, changelist="default", perfect_match_only=False, case_sensitive=False):
        """
        Deletes a changelist via cl num or description
        :param changelist:
        :return:
        """
        cl_num = self.get_pending_changelists(changelist, perfect_match_only, case_sensitive)
        for cl in cl_num:
            info_dicts = self.run_cmd2('change', ['-d', cl])
            # TODO: Break down info dicts and look for errors

    def get_shelved_files(self):
        """
        Returns a list that holds other lists where index 0 is the depot path of the shelved file and index 1
        is the number of the changelist this file is in

        :return:
        """
        files_and_cl = []
        changelists = self.get_pending_changelists()
        info_dicts = self.run_cmd2("describe", ["-S", " ".join("%s" % cl for cl in changelists)])
        for info_dict in info_dicts:
            for key in info_dict.keys():
                if b"depotFile" in key:
                    depot_file = self.__get_dict_value(info_dict, key)
                    changelist = int(self.__get_dict_value(info_dict, "change"))
                    files_and_cl.append([depot_file, changelist])

        return files_and_cl

    def add_or_edit_folders(self, folders, include_subfolders=True, changelist="default"):
        """
        Marks a folder for add or edit

        :param folders: *list* or *string*
        :param include_subfolders: *bool*
        :param changelist: *string* or *int* changelist number or description. Will be made if it doesn't exist.*string* or *int* changelist number
        """
        folders = convert_to_list(folders) if not isinstance(folders, list) else folders

        all_files = []
        for folder in folders:
            if include_subfolders:
                for root, dirs, files in os.walk(folder):
                    for file_name in files:
                        complete_file_path = os.path.join(root, file_name)
                        if not complete_file_path in files:
                            all_files.append(complete_file_path)
            else:
                all_files.extend([os.path.join(folder, file) for file in os.listdir(folder) if os.path.isfile(os.path.join(folder, file))])

        return self.add_or_edit_files(all_files, changelist=changelist)

    def add_or_edit_files(self, file_list, changelist="default"):
        """
        Marks the files in file_list for add if they are new, or edit if they are already versioned

        :param file_list: *list* (ideally)
        :param changelist: *string* or *int* changelist number or description. Will be made if it doesn't exist.*string* or *int* changelist number
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent: self.__validate_file_list(file_list)

        files_for_add = []
        files_for_checkout = []
        all_info_dicts = []

        p4files = self.files_to_p4files(file_list, allow_invalid_files=True)
        for p4file in p4files:
            if p4file.is_checked_out():
                continue
            if p4file.is_local_only():
                files_for_add.append(p4file.get_local_file_path())
            elif p4file.get_depot_file_path() is not None:
                files_for_checkout.append(p4file.get_depot_file_path())

        if len(files_for_add):
            info_dicts = self.add_files(file_list, changelist=changelist)
            all_info_dicts.extend(info_dicts)

        if len(files_for_checkout):
            info_dicts = self.edit_files(file_list, changelist=changelist)
            all_info_dicts.extend(info_dicts)

        return all_info_dicts

    def get_changelist_for_file(self, depot_path):
        """
        Returns the number of the changelist the file is in, or -1 if the file isn't in any changelist

        :param depot_path: *string* depot_path of the file
        :return: *int* number of changelist
        """
        info_dicts = self.run_cmd2("opened", ["-a", "-u", self.user])
        for info_dict in info_dicts:
            if depot_path == self.__get_dict_value(info_dict, "depotFile"):
                return int(self.__get_dict_value(info_dict, "change"))
        return -1

    def edit_files(self, file_list, changelist="default"):
        """
        Marks the files in file_list for edit

        :param file_list: *list*
        :param changelist: *string* or *int* changelist number or description. Will be made if it doesn't exist.
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent: self.__validate_file_list(file_list)

        changelist = self.__ensure_changelist(changelist)

        info_dicts = self.run_cmd2("edit", ["-c", changelist] + file_list)
        for info_dict in info_dicts:
            if self.__get_dict_value(info_dict, "code") == "error" and not self.silent:
                print(self.__get_dict_value(info_dict, "data"))
        return info_dicts

    def add_files(self, file_list, changelist="default"):
        """
        Marks the files in file_list for add
        :param file_list: *list*
        :param changelist:  *string* or *int* changelist number or description. Will be made if it doesn't exist.
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent: self.__validate_file_list(file_list)

        changelist = self.__ensure_changelist(changelist)

        info_dicts = self.run_cmd2("add", ["-c", changelist] + file_list)
        return info_dicts

    def get_files_in_changelist(self, changelist="default"):
        """
        Returns the depot paths of all the files in the changelist

        :param changelist: *string* or *int* changelist number
        :return: *list* of depot paths
        """
        depot_paths = []

        if type(changelist) == str:
            try:
                changelist = self.get_pending_changelists(changelist, perfect_match_only=True, case_sensitive=True)[0]
            except IndexError as err:
                return depot_paths

        info_dicts = self.run_cmd2("describe", ["-O", changelist])
        for info_dict in info_dicts:
            for key, value in info_dict.items():
                if "depotFile" in key.decode():
                    depot_paths.append(value.decode())

        return depot_paths

    def get_pending_changelists(self, description_filter="", perfect_match_only=False, case_sensitive=False, descriptions=False):
        """
        Returns all the pending changelists, filtered on the changelist description

        :param description_filter: *string* to filter changelist descriptions
        :param perfect_match_only: *bool* if True, will only return CLs with the exact matching filter
        :param case_sensitive: *bool*
        :param descriptions: *bool* if set to True, will return the changelist description instead of the changelist number
        :return: *list* with changelist numbers as ints
        """
        info_dicts = self.run_cmd2("changes", ["-l", "-s", "pending", "-u", self.user, "-c", self.client])
        changelists = []

        for info_dict in info_dicts:
            description_filter = description_filter.rstrip("\n")
            cl_description = self.__get_dict_value(info_dict, "desc").rstrip("\n")

            if not case_sensitive:
                description_filter = description_filter.lower()
                cl_description = cl_description.lower()

            # no filter means just add all the changelists
            if description_filter == "":
                changelists.append([self.__get_dict_value(info_dict, "change"), cl_description])
            # else, apply filters
            else:
                if perfect_match_only:
                    if description_filter == cl_description:
                        changelists.append([self.__get_dict_value(info_dict, "change"), cl_description])
                else:
                    if description_filter in cl_description:
                        changelists.append([self.__get_dict_value(info_dict, "change"), cl_description])

        if descriptions:
            return [pair[1] for pair in changelists]
        else:
            return [int(pair[0]) for pair in changelists]

    def get_or_make_changelist(self, changelist_description, case_sensitive=False):
        """
        Returns a changelist based on the description. Makes one if it doesn't exist

        :param changelist_description: *string*
        :param case_sensitive: *bool*
        :return: *int* changelist number
        """
        if type(changelist_description) != str:
            return "default"

        if changelist_description == "default":
            return "default"

        changelists = self.get_pending_changelists(
            description_filter=changelist_description,
            perfect_match_only=True,
            case_sensitive=case_sensitive,
        )

        if len(changelists):
            return changelists[0]
        else:
            return self.make_new_changelist(description=changelist_description)

    def get_all_workspaces(self):
        """
        Returns a list of all workspaces that belong to this user
        """
        info_dicts = self.run_cmd2("clients", ["-u", self.user])
        workspaces = []

        for info_dict in info_dicts:
            workspace = self.__get_dict_value(info_dict, "client")
            workspaces.append(workspace)

        return workspaces

    def get_depot_paths(self, paths):
        """
        Returns the depot path of the given files or folders, based on the client

        :param paths: *list* of file paths
        :return: *list* of depot paths
        """
        updated_paths = []
        for path in paths:
            path = path.replace("\\", "/")
            path = path.rstrip("/")
            if os.path.isdir(path):
                path += "/..."
            updated_paths.append(path)

        info_dicts = self.run_cmd2("where", updated_paths)
        depot_paths = [self.__get_dict_value(info, "depotFile").rstrip("/...") for info in info_dicts]
        return depot_paths

    def get_local_paths(self, paths):
        """
        Returns the local path of the given files or folders, based on the client

        :param paths: *list* of file paths
        :return: *list* of depot paths
        """

        # strip out revision specifier from paths
        no_rev_paths = []
        for path in paths:
            path_without_ext, path_ext = os.path.splitext(path)
            if "#" in path_ext:
                path_ext = path_ext.split("#")[0]
            no_rev_paths.append("{}{}".format(path_without_ext, path_ext))

        info_dicts = self.run_cmd2("where", no_rev_paths)
        local_paths = [self.__get_dict_value(info, "path") for info in info_dicts]
        return local_paths

    def get_history(self, paths):
        """
        Returns changes for the given paths

        :param paths: *list* of file paths
        :return: *list* of change info
        """
        info_dicts = []
        for path in paths:
            info_dicts.extend(self.run_cmd2("changes", ["-l", path]))

        # decode from bytes
        if sys.version_info.major > 2:
            info_dicts = decode_dictionaries(info_dicts)

        return info_dicts

    def host_online(self):
        """
        Checks if the host for this client is online

        :return: *bool*
        """
        port = self.__port_number()
        host = self.__server_address()

        try:
            sock = socket.create_connection((host, port), timeout=2)
            return True
        except:
            return False

    def __server_address(self):
        """
        Returns the server address this client is connecting to, based on P4PORT

        :return: *string* server address
        """
        server = self.server.split(":")[-2]
        return server

    def __port_number(self):
        """
        Returns the port this client is connecting to, based on P4PORT

        :return: *string* port number
        """
        port = self.server.split(":")[-1]
        return port

    def __ensure_changelist(self, changelist):
        """
        Ensures the given changelist exists. Either returns the changelist you've provided or it'll make a new one

        :param changelist: *string* with cl description or *int* cl number
        :return:
        """
        if type(changelist) == str:
            try:
                changelist = int(changelist)
                return changelist
            except:
                pass
            changelist = self.get_or_make_changelist(changelist)

        elif type(changelist == bytes):
            return int(changelist)
        elif type(changelist == float):
            return int(changelist)
        elif type(changelist) == int:
            return changelist

        return changelist

    def __get_dict_value(self, dictionary, key, default_value=None):
        """
        Python 3 treats the strings in the info dicts as bytes-type strings, Python 2 doesn't. This functions checks the
        Python version and changes the keys and values accordingly

        :param dictionary: *dict* dictionary from where to get the info
        :param key: *string* key you want the value of
        :param default_value: default value to return in case the key doesn't exist
        :return:
        """
        if sys.version_info.major == 2:
            return dictionary.get(key, default_value)
        else:
            try:
                return dictionary.get(key.encode(), default_value).decode()
            except:
                return dictionary.get(key, default_value)

    def __fstat_to_p4_files(self, fstat_output_list, allow_invalid_files=False):
        """
        Turns the output of the fstat command into a list of P4File objects

        :param fstat_output_list: *list* of info dictionaries generated by the fstat command
        :param allow_invalid_files: *bool* if set to False, this function will skip any files that are deleted or
        marked for delete
        :return:
        """
        p4files = []
        for file_dict in fstat_output_list:
            p4file = P4File()
            p4file.set_depot_file_path(self.__get_dict_value(file_dict, "depotFile"))
            p4file.set_local_file_path(self.__get_dict_value(file_dict, "clientFile"))
            p4file.set_have_revision(self.__get_dict_value(file_dict, "haveRev"))
            p4file.set_head_revision(self.__get_dict_value(file_dict, "headRev"))
            p4file.set_last_submit_time(self.__get_dict_value(file_dict, "headTime"))
            p4file.set_action(self.__get_dict_value(file_dict, "action"))
            p4file.set_head_action(self.__get_dict_value(file_dict, "headAction"))
            p4file.set_raw_data(str(file_dict))

            opened_by = []
            for key, value in file_dict.items():
                other_open = "otherOpen" if sys.version_info.major == 2 else "otherOpen".encode()
                if other_open in key and key != other_open:
                    value = self.__get_dict_value(file_dict, key)
                    opened_by.append(value)

            p4file.set_checked_out_by(opened_by)

            if allow_invalid_files:
                p4files.append(p4file)
            else:
                if p4file.is_valid():
                    if not p4file.is_deleted() and not p4file.is_moved_deleted():
                        p4files.append(p4file)

        return p4files

    def __p4config_exists(self):
        """
        Travels up the chain of parent folders trying to find a .p4config file.
        https://stackoverflow.com/questions/37427683/python-search-for-a-file-in-current-directory-and-all-its-parents

        :return: *bool*
        """
        starting_dir = self.perforce_root
        last_dir = ""
        current_dir = starting_dir

        while last_dir != current_dir:
            for item in os.listdir(current_dir):
                if item == ".p4config":
                    logging.info(".p4config found in %s" % current_dir)
                    self.perforce_root = current_dir
                    return True
            last_dir = current_dir
            current_dir = os.path.abspath(current_dir + os.path.sep + os.pardir)
        return False

    def __validate_file_list(self, file_list):
        """
        Validation function to ensure correct files are being synced to correct workspaces & clients etc.
        Is an extendable function
        :param file_list: List of files to iterate
        :return:
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list

        # Easy utility to check that the file is underneath the correct perforce root
        # Quicker than waiting for the result of a p4 fstat
        for f in file_list:
            if not f.lower().startswith(self.perforce_root.lower()):
                raise Exception(f'{f} is not under perforce root: {self.perforce_root}')


def split_list_into_strings_of_length(input_list, max_length=100):
    """
    From incoming list of strings, build joined together strings that are clamped to a max size

    :param input_list:
    :param max_length: str clamp length
    """
    full_list_str = " ".join([str(arg) for arg in input_list])

    # if str is already below max length, just return it wrapped in a list
    if not len(full_list_str) > max_length:
        return [full_list_str]

    # Keep appending on the last string until we hit the max length
    # then add a new entry to the list and keep appending
    clamped_str_list = [""]
    for arg in input_list:
        current_str = clamped_str_list[-1]
        new_str = "{}{} ".format(current_str, arg)  # the space is deliberately placed, since the first item has no len

        # if new string is too long, just append the arg as a new item and skip to next arg
        if len(new_str) >= max_length:
            clamped_str_list.append("{} ".format(arg))  #
            continue

        # set latest to updated string
        clamped_str_list[-1] = new_str

    return clamped_str_list


def decode_dictionaries(info_dicts):
    """
    Decode list of dictionary keys and values into unicode from bytes
    """
    decoded_dicts = []
    for info_dict in info_dicts:
        decoded_dict = {k.decode(): v.decode() for k, v in info_dict.items()}
        decoded_dicts.append(decoded_dict)
    return decoded_dicts

def convert_to_list(value):
    if isinstance(value, tuple):
        converted = [v for v in value]
    else:
        converted = [value]
    return converted


class HostOnline(object):
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
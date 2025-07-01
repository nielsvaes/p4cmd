import os
import marshal
import sys
import subprocess
import socket
from pprint import pformat

import logging

from . import p4errors
from .p4file import P4File, Status
from .utils import split_list_into_strings_of_length, convert_to_list, decode_dictionaries, validate_not_empty

MAX_CMD_LEN = 8190
MAX_ARG_LEN = 8000  # max length of args string when combined, close to max, but leaving some extra margin


class P4Client(object):
    def __init__(self, perforce_root, user=None, client=None, server=None, silent=True, max_parallel_connections=4):
        """
        Make a new P4Client

        :param perforce_root: *string* root of your Perforce workspace. This would also be where your .p4config file is
        :param user: *string* P4USER, if None will be tried to be found automatically
        :param client: *string* P4CLIENT, if None will be tried to be found automatically
        :param silent: *bool* if True, suppresses error messages to cut down on terminal spam
        :param max_parallel_connections: *int* max number of connections to use while syncing/submitting. This requires
        the server to have net.parallel.max and net parallel.threads to be > 1
        """
        self.perforce_root = perforce_root
        self.silent = silent

        self.max_parallel_connections = max_parallel_connections
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
        
        self.depot_root = self.get_depot_paths([self.perforce_root])[0]

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

    def set_max_parallel_connections(self, value):
        """
        Set the number of maximum parallel connections to use for sync/submit. Default class value is 4

        :param value: *int*
        :return:
        """
        self.max_parallel_connections = value

    def run_cmd(self, cmd, args=[], file_list=[], use_global_options=True, online_check=True):
        """
        Reads the output stream of the command and returns it as a marshaled dict.

        :param cmd: *string* p4 command like "change", "reopen", "move"
        :param args: *list* of string arguments like ["-c", "27277"]
        :param file_list: *list* of string arguments like ["//depot/folder/file.atom", "D:/Games/Whatever.fbx]
        :param use_global_options: *bool*
        :param online_check: *bool* if set to True, will first check if the remote server is reachable before executing the command.
        :return: *list* of dictionaries with either the marshaled returns of the command or dictionaries with the
        raw output of the command
        """
        if online_check:
            if not self.host_online():
                logging.warning("Can't connect to %s on port %s" % (self.__server_address(), self.__port_number()))

        if self.perforce_root is not None:
            os.chdir(self.perforce_root)

        file_list = [f'"{f}"' for f in file_list]

        # build arg and file strings within the max size
        clamped_arg_list = split_list_into_strings_of_length(args, max_length=MAX_ARG_LEN)
        clamped_file_list = split_list_into_strings_of_length(file_list, max_length=MAX_ARG_LEN)

        dict_list = []
        for clamped_arg in clamped_arg_list:
            for clamped_files in clamped_file_list:
                if use_global_options:
                    command = f"p4 -G -u {self.user} -c {self.client} {cmd} {clamped_arg} {clamped_files}"
                else:
                    command = f"p4 {cmd} {clamped_arg} {clamped_files}"

                if len(command) > MAX_CMD_LEN:
                    # This shouldn't happen, but just in case the command prefix end up really long
                    logging.warning(f"Command length: {format(len(command))} exceeds MAX_CMD_LEN {MAX_CMD_LEN} on command: {MAX_CMD_LEN}")

                with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True) as pipe:
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
                    pipe.kill()

        return dict_list

    def get_ticket_expiration(self):
        """
        Get the time in seconds when the current authentication ticket will expire

        :return: *int* seconds until authentication ticket expires or *None*
        """
        if not self.host_online():
            return None
        result = self.run_cmd("login", args=["-s"])
        info_dict = result[0]
        expiration_seconds = self.__get_dict_value(info_dict, "TicketExpiration", None)
        if expiration_seconds is not None:
            return int(expiration_seconds)
        return None

    def get_p4_setting(self, setting):
        """
        Gets a Perforce setting

        :param setting: *string*
        :return: setting value. In case a bad marshal object is returned and the function can't find the settings,
        the entire info dictionary from Perforce is returned
        """
        try:
            # skipping the online check for setting commands
            info_dict = self.run_cmd("set", [setting], use_global_options=False, online_check=False)[0]
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

    @validate_not_empty
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
            fstat_output = self.run_cmd("fstat", file_list=file_list)
            p4files = self.fstat_to_p4_files(fstat_output, allow_invalid_files=allow_invalid_files)
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

    @validate_not_empty
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

            fstat_output = self.run_cmd("fstat", file_list=[folder])
            p4files = self.fstat_to_p4_files(fstat_output, allow_invalid_files=allow_invalid_files)
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
    
    @validate_not_empty
    def move_files_to_changelist(self, file_list, changelist="default"):
        """
        Moves the files in file_list to a changelist. Makes a new changelist if the given one doesn't exist.

        :param file_list: *list* of file paths
        :param changelist: *string* or *int* changelist description or changelist number
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        changelist = self.__ensure_changelist(changelist)
        info_dicts = self.run_cmd("reopen", args=["-c", changelist], file_list=file_list)

        for info_dict in info_dicts:
            if self.__get_dict_value(info_dict, "code") == "error" and not self.silent:
                logging.error(self.__get_dict_value(info_dict, "data"))

        return info_dicts

    def combine_changelists(self, source_changelists, target_changelist):
        """
        Moves all the files from the source_changelists to the target_changelist

        :param source_changelists: *list* source changelists that will be emptied
        :param target_changelist: *string* or *int* changelist that will hold all the files
        empty after moving the files
        :return: *list* of info dictionaries
        """
        target_changelist = self.__ensure_changelist(target_changelist)
        files_to_move = []
        for source_cl in source_changelists:
            source_cl = self.__ensure_changelist(source_cl)
            files_to_move.extend(self.get_files_in_changelist(source_cl))

        result = self.move_files_to_changelist(files_to_move, target_changelist)
        return result


    def rename_file(self, old_file_path, new_file_path, changelist="default"):
        """
        P4 move-renames a file

        :param old_file_path: *string*
        :param new_file_path: *string*
        :param changelist:  *string* or *int* changelist number or description. Will be made if it doesn't exist.
        :return: *bool*
        """
        changelist = self.__ensure_changelist(changelist)

        info_dict = self.run_cmd("move", args=["-c", str(changelist)], file_list=[old_file_path, new_file_path])[0]
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

        info_dict = self.run_cmd("copy", args=["-c", str(changelist)], file_list=[original_file_path, copied_file_path])[0]
        if self.__get_dict_value(info_dict, "code") != "error":
            return True
        return False

    @validate_not_empty
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
            info_dicts = self.run_cmd("revert", ["-a"], file_list=file_list)
        else:
            info_dicts = self.run_cmd("revert", file_list=file_list)

        return info_dicts


    @validate_not_empty
    def revert_folders(self, folder_list, unchanged_only=False):
        """
        Recursively reverts complete folders

        :param folder_list: *list* folder paths
        :param unchanged_only: *bool*
        :return: *list* of info dicts
        """
        folder_list = convert_to_list(folder_list) if not isinstance(folder_list, list) else folder_list
        if not self.silent:
            self.__validate_file_list(folder_list)

        cleaned_folder_list = []
        for folder in folder_list:
            folder = folder.replace("\\", "/")
            folder = folder.rstrip("/")
            folder += "/..."
            cleaned_folder_list.append(folder)

        if unchanged_only:
            info_dicts = self.run_cmd("revert", ["-a"], file_list=cleaned_folder_list)
        else:
            info_dicts = self.run_cmd("revert", args=[], file_list=cleaned_folder_list)
        return info_dicts

    def revert_changelist(self, unchanged_only=False, changelist="default"):
        """
        Reverts all files in a given changelist
        :param changelist: string or int value
        :param unchanged_only: *bool*
        """
        changelist = self.__ensure_changelist(changelist)
        if unchanged_only:
            return self.run_cmd("revert", args=["-a", "-c", changelist])
        else:
            return self.run_cmd("revert", args=["-c", changelist, "//..."])

    def submit_changelist(self, changelist, revert_unchanged_files=True):
        """
        Submits a changelist

        :param changelist: string or int value.
        :param revert_unchanged_files: *bool* does what it says on the box
        :return:
        """
        changelist = self.__ensure_changelist(changelist)

        if revert_unchanged_files:
            self.revert_changelist(unchanged_only=True, changelist=changelist)

        info_dicts = self.run_cmd("submit", args=["-c", changelist, "--parallel", f"threads={self.max_parallel_connections}"])
        return info_dicts

    @validate_not_empty
    def sync_folders(self, folder_list):
        """
        Recursively syncs complete folders

        :param folder_list: *list* folder paths
        :return: *list* of info dicts
        """
        folder_list = convert_to_list(folder_list) if not isinstance(folder_list, list) else folder_list
        if not self.silent:
            self.__validate_file_list(folder_list)

        cleaned_folder_list = []
        for folder in folder_list:
            folder = folder.replace("\\", "/")
            folder = folder.rstrip("/")
            folder += "/..."
            cleaned_folder_list.append(folder)

        info_dicts = self.run_cmd("sync", args=["--parallel", f"threads={self.max_parallel_connections}"], file_list=cleaned_folder_list)
        return info_dicts

    @validate_not_empty
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

        initial_arg_list = ["-f", "--parallel", f"threads={self.max_parallel_connections}"] if force else ["--parallel", f"threads={self.max_parallel_connections}"]
        if not self.silent:
            self.__validate_file_list(file_list)

        info_dicts = self.run_cmd("sync", args=initial_arg_list, file_list=file_list)

        if verify:
            local_file_paths = self.get_local_paths(file_list)
            for local_file_path in local_file_paths:
                if not os.path.isfile(local_file_path):
                    logging.warning(f"File didn't exist after syncing, try force syncing it instead: {local_file_path}")

        return info_dicts

    @validate_not_empty
    def reconcile_offline_files(self, file_list, changelist="default"):
        """
        Adds, opens for edit or delete any files that were changed outside Perforce

        :param file_list: *list* of local files
        :param changelist: string or int value
        :return: *list* of info dicts
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list

        changelist = self.__ensure_changelist(changelist)

        info_dicts = self.run_cmd("reconcile", args=["-c", changelist], file_list=file_list)
        return info_dicts

    @validate_not_empty
    def reconcile_offline_folders(self, folder_list, changelist="default"):
        """
        Adds, opens for edit or delete any files in the rootfolder + subfolders that were changed outside Perforce

        :param folder_list: *list* folders
        :param changelist: string or int value
        :return: *list* of info dicts
        """
        folder_list = convert_to_list(folder_list) if not isinstance(folder_list, list) else folder_list
        if not self.silent:
            self.__validate_file_list(folder_list)

        cleaned_folder_list = []
        for folder in folder_list:
            folder = folder.replace("\\", "/")
            folder = folder.rstrip("/")
            folder += "/..."
            cleaned_folder_list.append(folder)

        changelist = self.__ensure_changelist(changelist)

        info_dicts = self.run_cmd("reconcile", args=["-c", changelist], file_list=cleaned_folder_list)
        return info_dicts

    @validate_not_empty
    def delete_files(self, file_list, changelist="default"):
        """
        Marks files for delete

        :param file_list: *list*
        :param changelist: *string* or *int* changelist number
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent:
            self.__validate_file_list(file_list)

        changelist = self.__ensure_changelist(changelist)

        info_dicts = self.run_cmd("delete", args=["-c", changelist], file_list=file_list)
        return info_dicts

    def delete_changelist(self, changelist="default", perfect_match_only=False, case_sensitive=False):
        """
        Deletes a changelist via changelist number or description
        :param changelist: *string* or *int* change list number
        :param perfect_match_only: bool* only delete if there's a perfect match of the changelist description
        :param case_sensitive: *bool*
        """
        info_dicts = []
        cl_num = self.get_pending_changelists(changelist, perfect_match_only, case_sensitive)
        for cl in cl_num:
            info_dicts.append(self.run_cmd('change', args=['-d', cl]))
            # TODO: Break down info dicts and look for errors
        return info_dicts

    def get_shelved_files(self):
        """
        Returns a list that holds other lists where index 0 is the depot path of the shelved file and index 1
        is the number of the changelist this file is in

        :return:
        """
        files_and_cl = []
        changelists = self.get_pending_changelists()
        info_dicts = self.run_cmd("describe", args=["-S", " ".join("%s" % cl for cl in changelists)])
        for info_dict in info_dicts:
            for key in info_dict.keys():
                if b"depotFile" in key:
                    depot_file = self.__get_dict_value(info_dict, key)
                    changelist = int(self.__get_dict_value(info_dict, "change"))
                    files_and_cl.append([depot_file, changelist])

        return files_and_cl

    @validate_not_empty
    def shelve_files(self, changelist, file_list=None, revert_after_shelve=False, force=False):
        """
        Shelves files in a changelist. If no files are specified, shelves all files in the changelist.
    
        :param changelist: *string* or *int* changelist number or description
        :param file_list: *list* or *None* list of files to shelve. If None, shelves all files in the changelist
        :param revert_after_shelve: *bool* if True, reverts the files after shelving them
        :param force: *bool* if True, forces the shelving operation even if files are already shelved
        :return: *list* of info dictionaries
        """
        changelist = self.__ensure_changelist(changelist)
        
        # if no files specified, get all files in the changelist
        if file_list is None:
            file_list = self.get_files_in_changelist(changelist)
        else:
            file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
            if not self.silent:
                self.__validate_file_list(file_list)
        
        # if there are no files to shelve, return empty list
        if not file_list:
            if not self.silent:
                logging.warning(f"No files to shelve in changelist {changelist}")
            return []
        
        # iuild args list based on options
        args = ["-c", str(changelist)]
        if force:
            args.append("-f")
        
        # run the shelve command
        info_dicts = self.run_cmd("shelve", args=args, file_list=file_list)
        
        for info_dict in info_dicts:
            if self.__get_dict_value(info_dict, "code") == "error" and not self.silent:
                logging.error(self.__get_dict_value(info_dict, "data"))
        
        # revert files if requested
        if revert_after_shelve and file_list:
            revert_info_dicts = self.revert_files(file_list)
            # add revert info to the return data
            info_dicts.extend(revert_info_dicts)
        
        return info_dicts

    def unshelve_files(self, changelist, file_list=None, target_changelist="default", force=False, delete_shelved_files=False):
        """
        Unshelves files from a shelved changelist. If no files are specified, unshelves all files.
    
        :param changelist: *string* or *int* source changelist number containing shelved files
        :param file_list: *list* or *None* list of files to unshelve. If None, unshelves all files
        :param target_changelist: *string* or *int* target changelist to unshelve files into
        :param force: *bool* if True, forces the unshelve operation even if files are already opened
        :param delete_shelved_files: *bool* if True, deletes the shelved files after unshelving them
        :return: *list* of info dictionaries
        """
        source_changelist = self.__ensure_changelist(changelist)
        target_changelist = self.__ensure_changelist(target_changelist)
        
        # build the arguments list
        args = []
        
        # add force flag if requested
        if force:
            args.append("-f")
        
        # add source changelist (required)
        args.extend(["-s", str(source_changelist)])
        
        # add target changelist if specified and not default
        if target_changelist != "default":
            args.extend(["-c", str(target_changelist)])
        
        # prepare file list if provided
        if file_list is not None:
            file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
            if not self.silent:
                self.__validate_file_list(file_list)
        else:
            file_list = []
        
        # run the unshelve command
        info_dicts = self.run_cmd("unshelve", args=args, file_list=file_list)
        
        # check for errors in the unshelve operation
        has_error = False
        for info_dict in info_dicts:
            if self.__get_dict_value(info_dict, "code") == "error" and not self.silent:
                logging.error(self.__get_dict_value(info_dict, "data"))
                has_error = True
        
        # delete shelved files if requested and unshelve was successful
        if delete_shelved_files and not has_error:
            # build the arguments for the shelve -d command
            delete_args = ["-d", "-c", str(source_changelist)]
            
            # if file_list provided, use it for the delete operation as well
            delete_info_dicts = self.run_cmd("shelve", args=delete_args, file_list=file_list)
            
            # check for errors in the delete operation
            for info_dict in delete_info_dicts:
                if self.__get_dict_value(info_dict, "code") == "error" and not self.silent:
                    logging.error(self.__get_dict_value(info_dict, "data"))
            
            # add the delete info to the return data
            info_dicts.extend(delete_info_dicts)
        
        return info_dicts

    @validate_not_empty
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


    @validate_not_empty
    def add_or_edit_files(self, file_list, changelist="default"):
        """
        Marks the files in file_list for add if they are new, or edit if they are already versioned

        :param file_list: *list* (ideally)
        :param changelist: *string* or *int* changelist number or description. Will be made if it doesn't exist.*string* or *int* changelist number
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent:
            self.__validate_file_list(file_list)

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
        info_dicts = self.run_cmd("opened", args=["-a", "-u", self.user])
        for info_dict in info_dicts:
            if depot_path == self.__get_dict_value(info_dict, "depotFile"):
                return int(self.__get_dict_value(info_dict, "change"))
        return -1

    @validate_not_empty
    def edit_files(self, file_list, changelist="default"):
        """
        Marks the files in file_list for edit

        :param file_list: *list*
        :param changelist: *string* or *int* changelist number or description. Will be made if it doesn't exist.
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent:
            self.__validate_file_list(file_list)

        changelist = self.__ensure_changelist(changelist)

        info_dicts = self.run_cmd("edit", args=["-c", changelist], file_list=file_list)
        for info_dict in info_dicts:
            if self.__get_dict_value(info_dict, "code") == "error" and not self.silent:
                logging.error(self.__get_dict_value(info_dict, "data"))
        return info_dicts

    @validate_not_empty
    def add_files(self, file_list, changelist="default"):
        """
        Marks the files in file_list for add
        :param file_list: *list*
        :param changelist:  *string* or *int* changelist number or description. Will be made if it doesn't exist.
        :return: *list* of info dictionaries
        """
        file_list = convert_to_list(file_list) if not isinstance(file_list, list) else file_list
        if not self.silent:
            self.__validate_file_list(file_list)

        changelist = self.__ensure_changelist(changelist)

        info_dicts = self.run_cmd("add", args=["-c", changelist], file_list=file_list)
        return info_dicts

    def get_files_in_changelist(self, changelist="default"):
        """
        Returns the depot paths of all the files in the changelist

        :param changelist: *string* or *int* changelist number
        :return: *list* of depot paths
        """
        changelist = self.__ensure_changelist(changelist)
        depot_paths = []

        info_dicts = self.run_cmd("opened", args=["-c", changelist])
        for info_dict in info_dicts:
            for key, value in info_dict.items():
                if "depotFile" in key.decode():
                    depot_paths.append(value.decode())

        return depot_paths

    def get_all_files_in_all_changelists(self):
        """
        Does what it says on the box

        :return: *list*
        """
        depot_paths = []

        info_dicts = self.run_cmd("opened")
        for info_dict in info_dicts:
            for key, value in info_dict.items():
                if "depotFile" in key.decode():
                    depot_paths.append(value.decode())

        return depot_paths

    def get_pending_changelists(self, description_filter="", perfect_match_only=False, case_sensitive=False, descriptions=False):
        """
        Returns all the pending change lists, filtered on the changelist description

        :param description_filter: *string* to filter changelist descriptions
        :param perfect_match_only: *bool* if True, will only return CLs with the exact matching filter
        :param case_sensitive: *bool*
        :param descriptions: *bool* if set to True, will return the changelist description instead of the changelist number
        :return: *list* with changelist numbers as ints
        """
        info_dicts = self.run_cmd("changes", args=["-l", "-s", "pending", "-u", self.user, "-c", self.client])
        changelists = []

        for info_dict in info_dicts:
            description_filter = description_filter.rstrip("\n")
            try:
                cl_description = self.__get_dict_value(info_dict, "desc").rstrip("\n")
            except AttributeError as err:
                raise p4errors.P4cmdError(err)

            if not cl_description:
                logging.warning(f"The CL description is empty in this return object!\n{pformat(info_dict)}")

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
            return_list = [pair[1] for pair in changelists]
            return_list.append("default")
        else:
            return_list = [int(pair[0]) for pair in changelists]
            return_list.append("default")
        return return_list

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

        if len(changelists) > 1: # > 1 because "default" is always appended
            return changelists[0]
        else:
            return self.make_new_changelist(description=changelist_description)

    def get_all_workspaces(self):
        """
        Returns a list of all workspaces that belong to this user
        """
        info_dicts = self.run_cmd("clients", args=["-u", self.user])
        workspaces = []

        for info_dict in info_dicts:
            workspace = self.__get_dict_value(info_dict, "client")
            workspaces.append(workspace)

        return workspaces

    @validate_not_empty
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

        info_dicts = self.run_cmd("where", updated_paths)
        depot_paths = [self.__get_dict_value(info, "depotFile").rstrip("/...") for info in info_dicts]
        return depot_paths


    @validate_not_empty
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

        info_dicts = self.run_cmd("where", file_list=no_rev_paths)
        local_paths = [self.__get_dict_value(info, "path") for info in info_dicts]
        return local_paths

    @validate_not_empty
    def get_history(self, paths):
        """
        Returns changes for the given paths

        :param paths: *list* of file paths
        :return: *list* of change info
        """
        info_dicts = []
        for path in paths:
            info_dicts.extend(self.run_cmd("changes", args=["-l", path]))

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
            sock.close()
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

    def fstat_to_p4_files(self, fstat_output_list, allow_invalid_files=False):
        """
        Turns the output of the fstat command into a list of P4File objects

        :param fstat_output_list: *list* of info dictionaries generated by the fstat command
        :param allow_invalid_files: *bool* if set to False, this function will skip any files that are deleted or
        marked for delete
        :return:
        """
        p4files = []
        p4_client = self.find_p4_client()
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
                action_owner = "actionOwner" if sys.version_info == 2 else "actionOwner".encode()
                if action_owner in key:
                    value = self.__get_dict_value(file_dict, key)
                    value = value.decode() + "@" + p4_client
                    opened_by.append(value.encode())

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
            if os.path.exists(current_dir):
                if ".p4config" in os.listdir(current_dir):
                    logging.info(".p4config found in %s" % current_dir)
                    self.perforce_root = current_dir
                    return True

            last_dir = current_dir
            current_dir = os.path.dirname(last_dir)
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
            if not f.lower().startswith(self.perforce_root.lower()) and not f.lower().startswith(self.depot_root.lower()):
                raise Exception(f'{f} is not under perforce root: {self.perforce_root}, {self.depot_root}')


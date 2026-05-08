### P4CMD 🌴

[![Tests](https://github.com/nielsvaes/p4cmd/actions/workflows/tests.yml/badge.svg)](https://github.com/nielsvaes/p4cmd/actions/workflows/tests.yml)
[![Publish](https://github.com/nielsvaes/p4cmd/actions/workflows/python-publish.yml/badge.svg)](https://github.com/nielsvaes/p4cmd/actions/workflows/python-publish.yml)

A Python Perforce package that doesn't bring in any other packages to work.
Relies on the `p4` CLI installed on the system.

```bash
pip install p4cmd
```

## Getting started

### Creating a client

Pass the root path of your Perforce workspace, or use the `P4ROOT` environment variable:

```python
from p4cmd import p4cmd

# Direct path
p4 = p4cmd.P4Client("~/p4/MyGame")

# Or with explicit credentials
p4 = p4cmd.P4Client("~/p4/MyGame", user="my.user", client="my-workspace", server="ssl:perforce:1666")
```

```python
import os
from p4cmd import p4cmd

os.environ["P4ROOT"] = "~/p4/MyGame"
p4 = p4cmd.P4Client.from_env()
```

If the path you pass doesn't contain a `.p4config` file, P4Client will walk up the directory tree until it finds one and use that as `perforce_root`.

## P4Client API

### Connection & settings

| Method | Description |
|---|---|
| `host_online(timeout=2.0)` | Check if the Perforce server is reachable |
| `get_ticket_expiration()` | Seconds until the authentication ticket expires |
| `get_p4_setting(setting)` | Read a Perforce setting (e.g. `"P4CLIENT"`) |
| `find_p4_client()` | Return the current workspace name |
| `find_p4_port()` | Return the server address |
| `set_workspace(workspace)` | Switch the active workspace |
| `set_perforce_root(root)` | Change the workspace root directory |
| `set_max_parallel_connections(value)` | Set max parallel connections for sync/submit (default 4) |
| `get_all_workspaces()` | List all workspaces for the current user |

### File operations

| Method | Description |
|---|---|
| `add_or_edit_files(file_list, changelist="default")` | Add new files or check out existing ones — auto-detects which |
| `add_or_edit_folders(folders, include_subfolders=True, changelist="default")` | Same as above, for entire folders |
| `add_files(file_list, changelist="default")` | Mark files for add |
| `edit_files(file_list, changelist="default")` | Mark files for edit |
| `delete_files(file_list, changelist="default")` | Mark files for delete |
| `rename_file(old_path, new_path, changelist="default")` | P4 move/rename a file |
| `copy_file(original_path, copied_path, changelist="default")` | P4 copy a file |
| `revert_files(file_list, unchanged_only=False)` | Revert files |
| `revert_folders(folder_list, unchanged_only=False)` | Revert all files in folders |
| `sync_files(file_list, revision=-1, verify=True, force=False)` | Sync files to a specific revision |
| `sync_folders(folder_list)` | Sync entire folders |
| `reconcile_offline_files(file_list, add=True, edit=True, delete=True, changelist="default")` | Reconcile offline changes |
| `reconcile_offline_folders(folder_list, add=True, edit=True, delete=True, changelist="default")` | Reconcile offline changes in folders |

### Changelists

| Method | Description |
|---|---|
| `make_new_changelist(description)` | Create a new numbered changelist |
| `get_or_make_changelist(description, case_sensitive=False)` | Find a CL by description, or create it |
| `changelist_exists(changelist)` | Check if a CL exists (by number or description) |
| `update_changelist_description(changelist, new_description)` | Update a CL's description |
| `delete_changelist(changelist, ...)` | Delete a CL (with options to obliterate, delete shelved files) |
| `get_pending_changelists(description_filter="", ...)` | List pending CLs, optionally filtered by description |
| `get_files_in_changelist(changelist="default")` | List depot paths in a CL |
| `get_all_files_in_all_changelists()` | List depot paths across all pending CLs |
| `get_changelist_for_file(depot_path)` | Find which CL contains a file |
| `move_files_to_changelist(file_list, changelist="default")` | Move files between changelists |
| `combine_changelists(source_changelists, target_changelist)` | Merge multiple CLs into one |
| `revert_changelist(unchanged_only=False, changelist="default")` | Revert all files in a CL |
| `submit_changelist(changelist, revert_unchanged_files=True)` | Submit a CL |

### Shelving

| Method | Description |
|---|---|
| `shelve_files(changelist, file_list=None, revert_after_shelve=False, force=False)` | Shelve files |
| `unshelve_files(changelist, file_list=None, target_changelist="default", force=False, delete_shelved_files=False)` | Unshelve files |
| `get_shelved_files()` | List all shelved files and their CLs |
| `delete_shelf(changelist)` | Delete shelved files without deleting the CL |

### Path conversion & history

| Method | Description |
|---|---|
| `get_depot_paths(paths)` | Convert local paths to depot paths |
| `get_local_paths(paths)` | Convert depot paths to local paths |
| `get_history(paths)` | Get change history for files |

### P4File conversion

| Method | Description |
|---|---|
| `files_to_p4files(file_list, allow_invalid_files=False)` | Convert file paths to `P4File` objects with full status info |
| `folder_to_p4files(folder, include_subfolders=True, allow_invalid_files=False, specific_file_filter="")` | Same, for all files in a folder |

## P4File

`P4File` represents a single file and its Perforce status. You get these from `files_to_p4files` or `folder_to_p4files`. All attributes are available as both properties and legacy `get_`/`set_` methods.

### Properties

| Property | Type | Description |
|---|---|---|
| `local_file_path` | `str` | Local filesystem path |
| `depot_file_path` | `str` | Depot path (`//depot/...`) |
| `action` | `str` | Current open action (`add`, `edit`, `delete`, `move/add`, `move/delete`) |
| `head_action` | `str` | Head revision action |
| `have_revision` | `int` | Local revision number |
| `head_revision` | `int` | Latest depot revision number |
| `last_submit_time` | `str` | Formatted timestamp of last submission |
| `last_submitted_by` | `str` | User who last submitted |
| `checked_out_by` | `list` | Users who have the file checked out |
| `file_size` | `str` | Raw file size from depot |
| `raw_data` | `str` | Raw fstat data |

### Status predicates

| Method | Description |
|---|---|
| `get_status()` | Returns a `Status` constant (see below) |
| `is_open_for_add()` | File is marked for add |
| `is_open_for_edit()` | File is marked for edit |
| `is_marked_for_delete()` | File is marked for delete |
| `is_checked_out()` | File has any open action |
| `is_untracked()` / `is_local_only()` | File exists locally but not in depot |
| `is_depot_only()` | File exists in depot but was never synced |
| `is_deleted()` | Head revision is a delete |
| `is_moved_deleted()` | File was moved away |
| `is_moved_added()` | File was moved here |
| `is_up_to_date()` | Local and head revisions match |
| `is_under_client_root()` | File is within the workspace mapping |
| `is_valid()` | Has at least one path set |
| `needs_syncing()` | Behind head revision and needs sync |
| `get_file_size(in_megabyte=True)` | File size in MB or bytes |

### Status constants

```python
from p4cmd.p4file import Status

Status.OPEN_FOR_ADD
Status.OPEN_FOR_EDIT
Status.OPEN_FOR_DELETE
Status.NEED_SYNC
Status.DEPOT_ONLY
Status.UP_TO_DATE
Status.UNTRACKED
Status.MOVED
Status.DELETED
Status.MOVED_DELETED
Status.UNKNOWN
```

### Other methods

| Method | Description |
|---|---|
| `update_self(p4client)` | Refresh all attributes from the server |
| `update_last_submitted_by(p4client)` | Refresh just the `last_submitted_by` field |

## Usage examples

### Check out or add files

You can mix local and depot paths. If you pass a changelist description that doesn't exist, it will be created automatically.

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

files = ["~/p4/MyGame/Raw/Characters/info_file.json",
         "//MyGame/Main/Templates/morefiles.json"]

p4.add_or_edit_files(files, changelist="My new changelist")
```

### Inspect files in bulk

```python
p4 = p4cmd.P4Client("~/p4/MyGame")
p4files = p4.folder_to_p4files("~/p4/MyGame/Animations")

files_to_sync = []
for pf in p4files:
    if pf.checked_out_by:
        print(f"depot: {pf.depot_file_path}")
        print(f"local: {pf.local_file_path}")
        print(f"status: {pf.get_status()}")
        print(f"checked out by: {pf.checked_out_by}")
    if pf.needs_syncing():
        files_to_sync.append(pf.local_file_path)

p4.sync_files(files_to_sync)
```

### Changelists

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

# List all pending changelists
all_cls = p4.get_pending_changelists()
# [35272, 33160, 32756, 30872, 27277, 'default']

# Filter by description
houdini_cls = p4.get_pending_changelists(description_filter="houdini")
# [35272, 33160, 'default']

# Exact match
exact = p4.get_pending_changelists(
    description_filter="[houdini tools]",
    perfect_match_only=True,
    case_sensitive=True,
)
# [33160, 'default']

# Get or create a changelist
cl = p4.get_or_make_changelist("My tools CL")

# List files in a changelist (by number or description)
files = p4.get_files_in_changelist(33160)
files = p4.get_files_in_changelist("[houdini tools]")
```

### Submit

```python
p4 = p4cmd.P4Client("~/p4/MyGame")
p4.submit_changelist("Character files", revert_unchanged_files=False)
```

### Sync with parallel connections

```python
p4 = p4cmd.P4Client("~/p4/MyGame")
p4.set_max_parallel_connections(2)
p4.sync_folders(["//Content/Basketball/Players/"])
```

### Revert files

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

# Revert specific files
p4.revert_files(["~/p4/MyGame/Raw/Characters/info_file.json"])

# Revert only unchanged files (keep actual edits)
p4.revert_files(["~/p4/MyGame/Raw/Characters/info_file.json"], unchanged_only=True)

# Revert everything in a folder
p4.revert_folders(["~/p4/MyGame/Raw/Characters"])

# Revert all files in a changelist
p4.revert_changelist(changelist=12345)
p4.revert_changelist(changelist=12345, unchanged_only=True)
```

### Rename and copy files

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

# Rename / move a file
p4.rename_file(
    "//MyGame/Main/Characters/old_name.fbx",
    "//MyGame/Main/Characters/new_name.fbx",
    changelist="Rename characters",
)

# Copy a file (branching)
p4.copy_file(
    "//MyGame/Main/Templates/base_config.json",
    "//MyGame/Main/Templates/new_config.json",
    changelist="Copy config template",
)
```

### Delete files

```python
p4 = p4cmd.P4Client("~/p4/MyGame")
p4.delete_files(
    ["~/p4/MyGame/Raw/Characters/unused_file.json"],
    changelist="Clean up unused files",
)
```

### Move files between changelists

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

# Move files from default to a named changelist
p4.move_files_to_changelist(
    ["//MyGame/Main/Characters/hero.fbx"],
    changelist="Character updates",
)

# Merge multiple changelists into one
p4.combine_changelists(
    source_changelists=[33160, 33161],
    target_changelist=33162,
)
```

### Manage changelist descriptions

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

# Update a changelist description (supports multi-line)
p4.update_changelist_description(
    12345,
    "Updated character models\nReviewed by: artist@studio",
)

# Check if a changelist exists
if p4.changelist_exists("My tools CL"):
    print("CL exists")
```

### Convert between depot and local paths

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

# Local paths -> depot paths
depot_paths = p4.get_depot_paths(["~/p4/MyGame/Raw/Characters"])
# ['//MyGame/Main/Raw/Characters']

# Depot paths -> local paths
local_paths = p4.get_local_paths(["//MyGame/Main/Raw/Characters"])
# ['~/p4/MyGame/Raw/Characters']
```

### File history

```python
p4 = p4cmd.P4Client("~/p4/MyGame")
history = p4.get_history(["//MyGame/Main/Characters/hero.fbx"])
for entry in history:
    print(entry)
```

### Shelving

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

# Shelve and optionally revert
p4.shelve_files(changelist=12345, revert_after_shelve=True)

# Unshelve into a different changelist
p4.unshelve_files(12345, target_changelist=67890)

# List all your shelved files
shelved = p4.get_shelved_files()
for depot_path, cl_number in shelved:
    print(f"{depot_path} in CL {cl_number}")

# Delete shelved files without deleting the changelist
p4.delete_shelf(12345)
```

### Reconcile offline work

```python
p4 = p4cmd.P4Client("~/p4/MyGame")
p4.reconcile_offline_folders(
    ["~/p4/MyGame/Raw/Characters"],
    add=True, edit=True, delete=False,
    changelist="Offline reconcile",
)
```

### Check server connection

```python
p4 = p4cmd.P4Client("~/p4/MyGame")

if p4.host_online():
    expiry = p4.get_ticket_expiration()
    if expiry is not None:
        print(f"Ticket expires in {expiry} seconds")
else:
    print("Server unreachable")
```

### Find which changelist a file is in

```python
p4 = p4cmd.P4Client("~/p4/MyGame")
cl = p4.get_changelist_for_file("//MyGame/Main/Characters/hero.fbx")
if cl != -1:
    print(f"File is in CL {cl}")
```

### Filter P4Files by status

```python
from p4cmd.p4file import Status

p4 = p4cmd.P4Client("~/p4/MyGame")
p4files = p4.folder_to_p4files("~/p4/MyGame/Raw/Characters")

# Group files by status
for pf in p4files:
    status = pf.get_status()
    if status == Status.NEED_SYNC:
        print(f"Needs sync: {pf.local_file_path}")
    elif status == Status.DEPOT_ONLY:
        print(f"Never synced: {pf.depot_file_path}")
    elif status == Status.OPEN_FOR_EDIT:
        print(f"Being edited: {pf.local_file_path}")

# Get file sizes
large_files = [
    pf for pf in p4files
    if pf.get_file_size(in_megabyte=True) and pf.get_file_size(in_megabyte=True) > 100
]
print(f"{len(large_files)} files over 100 MB")
```

## Development setup

### Running tests

```bash
pip install pytest
pytest tests/ -v
```

### Integration tests

Integration tests communicate with a real Perforce server. Copy `tests/.env.example`
to `tests/.env` and fill in your details, then run:

```bash
pytest tests/test_integration.py -v
```

### Pre-commit hook

A pre-commit hook that runs the unit test suite before every commit is included.
To install it:

```bash
cp scripts/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The CI pipeline also runs all tests before publishing to PyPI, so a release
will never be created from a failing build.

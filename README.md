### P4CMD 🌴

A Python Perforce package that doesn't bring in any other packages to work. 
Relies on p4cli installed on the system.

## p4cmd

The `p4cmd` module holds the P4Client class that allows you to interact with the P4 server.

To instantiate a new client, you either pass it the root path of you Perforce workspace or if the "P4ROOT" system variable is set, you can use the `from_env` class function

```python
from p4cmd import p4cmd

client = p4cmd.P4Client("~/nisse/projects/raw")

```

```python
from p4cmd import p4cmd
import os

# settings system variable
os.environ["P4ROOT"] = "~/nisse/projects/raw"

# now we can use from_env
client = p4cmd.P4Client.from_env()
```

Most of the functions are pretty self explanatory and have docstrings about how they work. 

There are 2 functions called `file_to_p4files` and `folder_to_p4files` that use the `P4File` class in `p4file`. 

## p4file

This module holds the `P4File` class that allows you to quickly and easily get information about any file on disk or in the depot. 

## Usage

Some use case examples to help you on your way.

Checking out files or adding new files. You can mix/match local and depot paths. Add a changelist number or description to put the files in that CL. If you add a description of a changelist that doesn't exist, it will be created. 
```python
from p4cmd import p4cmd
root = "~/p4/MyGame"

files = [r"~/p4/MyGame/Raw/Characters/info_file.json",
         "//MyGame/Main/Templates/morefiles.json"]

p4 = p4cmd.P4Client(root)
p4.add_or_edit_files(files, changelist="My new changelist")

```

Seperate `edit_files` and `add_files` methods also exist if you need to use them for some reason. 

Perforce operations can be quite slow, so if you need to check a bunch of files at once you can use do something like this:

```python
from p4cmd import p4cmd
root = "~/p4/MyGame"

folder = r"~/p4/MyGame/Animations"

p4 = p4cmd.P4Client(root)
p4files = p4.folder_to_p4files(folder)

files_to_sync = []
for p4file in p4files:
    if p4file.get_checked_out_by() is not None: # somebody else other than you checked out the file
        print("depot path:", p4file.get_depot_file_path())
        print("local path:", p4file.get_local_file_path())
        print("status:", p4file.get_status())
        print("Checked out by:", p4file.get_checked_out_by())
    if p4file.needs_syncing():
        files_to_sync.append(p4file.get_local_file_path())

p4.sync_files([files_to_sync])

```

```text
depot path: //MyGame/Main/MyGame/run.fbx
local path: ~/p4/MyGame/MyGame/run.fbx
status: UP_TO_DATE
Checked out by: barack.obama@barack.obama-US-BOBAMA-MyGame
depot path: //MyGame/Main/MyGame/dance.json
local path: ~/p4/MyGame/MyGame/dance.json
status: NEED_SYNC

```

`folder_to_p4files` returns a list of type p4file. A p4file has a bunch of functions to get information about the file and its status. This will get information back about all the files in one go, instead of you having to make a server call for every file on its own. 

Getting all your pending changelists:

```python

from p4cmd import p4cmd
root = "~/p4/MyGame"

p4 = p4cmd.P4Client(root)
all_changelists = p4.get_pending_changelists()

```
`[35272, 33160, 32756, 30872, 27277]`

Getting changelists with shelved files:
```python
from p4cmd import p4cmd
root = "~/p4/MyGame"

p4 = p4cmd.P4Client(root)
shelved_changelists = [pair[1] for pair in p4.get_shelved_files()]

```
`[30872, 30872, 27277]`


Searching in changelist descriptions:
```python
from p4cmd import p4cmd
root = "~/p4/MyGame"

p4 = p4cmd.P4Client(root)
houdini_cls = p4.get_pending_changelists(description_filter="houdini")

```
`[35272, 33160]`


Finding an exact changelist:
```python
from p4cmd import p4cmd
root = "~/p4/MyGame"

p4 = p4cmd.P4Client(root)
houdini_anim_cl = p4.get_pending_changelists(description_filter="[houdini tools]", perfect_match_only=True, case_sensitive=True)
```
`[33160]`

Listing all the files in a changelist by changelist number:

```python
from p4cmd import p4cmd
root = "~/p4/MyGame"

p4 = p4cmd.P4Client(root)
files = p4.get_files_in_changelist(33160)

```
```text
//MyGame/Animations/a_pose.fbx
//MyGame/Animations/t_pose.fbx
```

List all the files in a changelist by changelist description:

```python
from p4cmd import p4cmd
root = "~/p4/MyGame"

p4 = p4cmd.P4Client(root)
files = p4.get_files_in_changelist("[houdini tools]")
```
```text
//MyGame/Animations/a_pose.fbx
//MyGame/Animations/t_pose.fbx
```


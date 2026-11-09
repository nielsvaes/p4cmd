import subprocess

import pytest
from unittest.mock import MagicMock, patch

from p4cmd.p4cmd import P4Client


def make_fstat_dict(**kwargs):
    """Build a bytes-keyed dict like P4's marshaled fstat output."""
    return {k.encode(): v.encode() for k, v in kwargs.items()}


def fake_p4_popen(mock_popen, output=b"", returncode=0):
    """Make a patched subprocess.Popen act like p4 writing ``output`` (bytes) to its stdout, which
    _run_command gives it as a file, and exiting with ``returncode``. A list of outputs gives one per
    call. What each call got as stdin (subprocess.DEVNULL, or the bytes in its stdin file) is collected
    in ``mock_popen.stdin_received``."""
    outputs = list(output) if isinstance(output, list) else None
    mock_popen.stdin_received = []

    def popen(*args, **kwargs):
        stdin = kwargs.get("stdin")
        mock_popen.stdin_received.append(stdin if stdin is subprocess.DEVNULL else stdin.read())
        kwargs["stdout"].write(outputs.pop(0) if outputs is not None else output)
        process = MagicMock()
        process.__enter__.return_value = process
        process.__exit__.return_value = False
        process.wait.return_value = returncode
        process.returncode = returncode
        return process

    mock_popen.side_effect = popen
    return mock_popen


@pytest.fixture
def p4client(tmp_path):
    """
    A P4Client with all server calls mocked out.
    Passing explicit user/client/server skips the `p4 set` auto-detection calls.
    Only get_depot_paths (called for depot_root) still hits run_cmd — mocked here.
    """
    (tmp_path / ".p4config").write_text("P4PORT=ssl:perforce.example.com:1666\n")
    where_result = [
        {b"depotFile": b"//depot/project/...", b"path": b"/fake/project/...", b"unmap": b""}
    ]
    with patch.object(P4Client, "host_online", return_value=True):
        with patch.object(P4Client, "run_cmd", return_value=where_result):
            client = P4Client(
                str(tmp_path),
                user="testuser",
                client="testclient",
                server="ssl:perforce.example.com:1666",
            )
    client.depot_root = "//depot/project"
    return client

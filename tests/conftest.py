import pytest
from unittest.mock import patch

from p4cmd.p4cmd import P4Client


def make_fstat_dict(**kwargs):
    """Build a bytes-keyed dict like P4's marshaled fstat output."""
    return {k.encode(): v.encode() for k, v in kwargs.items()}


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

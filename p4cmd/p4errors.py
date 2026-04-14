"""Error types for p4cmd."""


class P4cmdError(Exception):
    """Base exception for all p4cmd errors."""
    pass


class WorkSpaceError(P4cmdError):
    """Raised when the workspace configuration is invalid or missing.

    Examples: P4CLIENT/P4USER/P4PORT not found, perforce_root not set,
    workspace name doesn't exist.
    """
    pass


class P4CommandError(P4cmdError):
    """Raised when a P4 command returns one or more error dicts.

    Attributes:
        cmd: The P4 command that failed (e.g. "sync", "edit").
        messages: List of error message strings from the error dicts.
    """
    def __init__(self, cmd, messages):
        self.cmd = cmd
        self.messages = messages
        joined = "; ".join(str(m).strip() for m in messages)
        super().__init__(f"p4 {cmd}: {joined}")


class ServerOffline(P4cmdError):
    """Raised when the Perforce server is unreachable.

    Methods that require a server connection raise this instead of
    silently returning None. Callers can catch this to implement
    offline fallback behavior.
    """
    pass

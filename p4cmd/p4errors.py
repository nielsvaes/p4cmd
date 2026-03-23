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


class ServerOffline(P4cmdError):
    """Raised when the Perforce server is unreachable.

    Methods that require a server connection raise this instead of
    silently returning None. Callers can catch this to implement
    offline fallback behavior.
    """
    pass

""" Error types """
class P4cmdError(Exception):
    """ Generic P4cmdError """
    pass

class WorkSpaceError(P4cmdError):
    """ Error with the workspace """
    pass

class ChangeListError(P4cmdError):
    """ Error with the changelist """
    pass

class ServerOffline(P4cmdError):
    pass
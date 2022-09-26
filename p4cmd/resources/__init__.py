import os

class P4StatusIcon(object):
    path_cache = {}

    @classmethod
    def get_path(cls, status):
        """
        Get the path to one of the icons, using a P4File.Status constant as identifier.
        This will also cache the info when a match is found so feel free to hammer it.

        :param cls:
        :param status: a P4File.Status constant.
        :return: Path to the Icon resource. None if file does not exist or the status is undefined.
        """
        path = cls.path_cache.get(status, None)
        if path:
            return path

        this_dir = os.path.dirname(os.path.realpath(__file__))
        if status:
            filename = "perforce_" + status + ".png"
            full_path = os.path.join(this_dir, filename)
            if os.path.exists(full_path):
                cls.path_cache[status] = full_path
                return full_path
            else:
                return None
        else:
            return None

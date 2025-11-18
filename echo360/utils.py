import pathlib


def naive_versiontuple(v):
    """
    This only works for version tuple with the same number of parts.
    Expects naive_versiontuple('xx.yy.zz') < naive_versiontuple('aa.bb.cc').
    """
    return tuple(map(int, (v.split("."))))


# PERSISTENT_SESSION_FOLDER = "_browser_persistent_session"


PERSISTENT_SESSION_FOLDER = pathlib.Path.cwd().absolute()/"_echo360dl_store"
PERSISTENT_SESSION_FILE = PERSISTENT_SESSION_FOLDER/"store.bin"
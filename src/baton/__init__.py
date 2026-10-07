import os

__version__ = "0.5.0"


def env(name, default=None):
    """Read BATON_<name>, falling back to the pre-rename HANDOFF_<name>."""
    return os.environ.get("BATON_" + name, os.environ.get("HANDOFF_" + name, default))

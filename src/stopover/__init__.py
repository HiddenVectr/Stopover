import os

__version__ = "0.16.0"


def env(name, default=None):
    """Read STOPOVER_<name>, falling back to the names from before each rename: BATON_<name>, then HANDOFF_<name>."""
    for prefix in ("STOPOVER_", "BATON_", "HANDOFF_"):
        if prefix + name in os.environ:
            return os.environ[prefix + name]
    return default

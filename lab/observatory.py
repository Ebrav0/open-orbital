"""Import the observatory as the physics authority. Lab does not copy SCHEMA."""
import sys

from lab.paths import OBSERVATORY, OPENMP

_CACHE = None


def modules():
    global _CACHE
    if _CACHE is None:
        for path in (OBSERVATORY, OPENMP):
            if path.is_dir() and str(path) not in sys.path:
                sys.path.insert(0, str(path))
        import physics
        import server
        _CACHE = (server, physics)
    return _CACHE


def server():
    return modules()[0]


def physics():
    return modules()[1]

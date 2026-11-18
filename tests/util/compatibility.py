"""Compatibility markers of the Windows memory audit tests (from win_razor).

``OS_COMPAT`` and ``compatibility_test`` only attach markers (``compatibility``,
``compatible`` / ``incompatible``); nothing deselects on them, as in win_razor.
Select with ``-m`` to act on them, e.g. ``-m "not incompatible"``.
"""
import platform

import psutil
import pytest

from tests.util.util import is_win

LINUX = "linux"
MAC = "darwin"
WINDOWS = "win32"
ALL_OS = (LINUX, MAC, WINDOWS)


def OS_COMPAT(*args):
    """Mark a test as compatible with the given platforms (decorator)."""
    os_list = [LINUX, MAC, WINDOWS] if list(args)[0] == ALL_OS else list(args)
    return pytest.mark.compatibility(*os_list)


def compatibility_test(func):
    """``compatible`` marker if ``func()`` is true on this host, else ``incompatible``."""
    return pytest.mark.compatible if func() else pytest.mark.incompatible


def is_x64():
    return platform.machine().endswith("64")


def is_win10():
    """Windows 10 RTM (10.0.10240) or later."""
    if not is_win():
        return False
    version = tuple(int(part) for part in platform.win32_ver()[1].split(".")[:3])
    return version >= (10, 0, 10240)


def is_64bit_win10():
    return is_win10() and is_x64()


def is_memory_audit_compatible():
    """64-bit Windows 10 or later, or any Windows older than 10."""
    return is_64bit_win10() or not is_win10()


def has_8gb_ram_or_more():
    # 8 GB allocated reports a little less (about 8191.4 MB) after hardware reservations
    return psutil.virtual_memory().total / pow(1024, 2) > 8190

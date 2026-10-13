"""File system helpers for evidence trees: long paths and complete timestamps.

Both matter on Windows. Collected evidence is deeply nested, so paths often
pass the 260 character limit of the classic Win32 API. Parsers also report a
file's own created, modified and accessed times, so a working copy must carry
all three or the parser output describes the copy instead of the evidence.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"

_LONG_PREFIX = "\\\\?\\"
_UNC_PREFIX = "\\\\?\\UNC\\"
# Windows FILETIME counts 100 ns intervals from 1601-01-01; Unix time starts 1970-01-01.
_FILETIME_UNIX_EPOCH = 116_444_736_000_000_000


def long_path(path: Path | str) -> str:
    """Absolute path string that Windows accepts beyond 260 characters."""
    text = os.path.abspath(str(path))
    if not IS_WINDOWS or text.startswith(_LONG_PREFIX):
        return text
    if text.startswith("\\\\"):
        return _UNC_PREFIX + text[2:]
    return _LONG_PREFIX + text


def plain_path(text: str) -> str:
    """Inverse of long_path, for showing paths to people and passing them to tools."""
    if text.startswith(_UNC_PREFIX):
        return "\\\\" + text[len(_UNC_PREFIX) :]
    if text.startswith(_LONG_PREFIX):
        return text[len(_LONG_PREFIX) :]
    return text


def remove_tree(path: Path | str) -> None:
    """Delete a folder tree, including read-only files a tool may have left in it."""

    def clear_read_only_and_retry(function, failed_path, _error):
        os.chmod(failed_path, stat.S_IWRITE)
        function(failed_path)

    target = long_path(path)
    if not os.path.lexists(target):
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=clear_read_only_and_retry)
    else:
        shutil.rmtree(target, onerror=clear_read_only_and_retry)


def copy_timestamps(source: os.stat_result, destination: str) -> None:
    """Give destination the created, modified and accessed times recorded in source."""
    if IS_WINDOWS:
        created = getattr(source, "st_birthtime_ns", source.st_ctime_ns)
        _set_windows_times(destination, created, source.st_atime_ns, source.st_mtime_ns)
    else:
        os.utime(destination, ns=(source.st_atime_ns, source.st_mtime_ns))


def _set_windows_times(path: str, created_ns: int, accessed_ns: int, modified_ns: int) -> None:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.SetFileTime.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 3
    kernel32.SetFileTime.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    file_write_attributes = 0x0100
    share_all = 0x1 | 0x2 | 0x4
    open_existing = 3
    backup_semantics = 0x0200_0000
    handle = kernel32.CreateFileW(
        long_path(path), file_write_attributes, share_all, None, open_existing, backup_semantics, None
    )
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error(), f"Cannot open {plain_path(path)} to set its timestamps")
    try:
        times = [_filetime(value) for value in (created_ns, accessed_ns, modified_ns)]
        if not kernel32.SetFileTime(handle, *(ctypes.byref(value) for value in times)):
            raise ctypes.WinError(ctypes.get_last_error(), f"Cannot set timestamps on {plain_path(path)}")
    finally:
        kernel32.CloseHandle(handle)


def _filetime(unix_ns: int):
    from ctypes import wintypes

    value = unix_ns // 100 + _FILETIME_UNIX_EPOCH
    return wintypes.FILETIME(value & 0xFFFF_FFFF, value >> 32)

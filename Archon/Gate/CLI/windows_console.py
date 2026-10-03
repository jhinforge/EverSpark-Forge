"""Keep classic Windows console selection from pausing service output."""
import ctypes
import sys
from ctypes import wintypes


def disable_quick_edit(kernel32=None) -> bool:
    if sys.platform != "win32":
        return False
    try:
        if kernel32 is None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
            kernel32.GetStdHandle.restype = wintypes.HANDLE
            kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetConsoleMode.restype = wintypes.BOOL
            kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.SetConsoleMode.restype = wintypes.BOOL
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False  # redirected input or a non-console host
        return bool(kernel32.SetConsoleMode(handle, (mode.value | 0x0080) & ~0x0040))
    except (OSError, AttributeError):
        return False

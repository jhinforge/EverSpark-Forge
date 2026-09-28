"""Per-user Windows Credential Manager storage for Archon provider secrets."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


_NOT_FOUND = 1168
_GENERIC = 1
_LOCAL_MACHINE = 2  # Persists across logon sessions for this Windows user.


class CredentialError(RuntimeError):
    pass


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FileTime), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    def __init__(self, target: str = "EverSpark Forge/Vast API Key") -> None:
        if sys.platform != "win32":
            raise CredentialError("Local credential storage requires Windows")
        self.target = target
        self.api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                       wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    def get(self) -> str | None:
        result = ctypes.POINTER(_Credential)()
        if not self.api.CredReadW(self.target, _GENERIC, 0, ctypes.byref(result)):
            if ctypes.get_last_error() == _NOT_FOUND:
                return None
            raise CredentialError("Cannot read the Windows credential")
        try:
            data = ctypes.string_at(result.contents.CredentialBlob,
                                    result.contents.CredentialBlobSize)
            return data.decode("utf-8")
        finally:
            self.api.CredFree(result)

    def set(self, secret: str) -> None:
        data = secret.encode("utf-8")
        blob = ctypes.create_string_buffer(data)
        credential = _Credential()
        credential.Type = _GENERIC
        credential.TargetName = self.target
        credential.CredentialBlobSize = len(data)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = _LOCAL_MACHINE
        credential.UserName = "EverSpark"
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialError("Cannot save the Windows credential")

    def delete(self) -> None:
        if not self.api.CredDeleteW(self.target, _GENERIC, 0):
            if ctypes.get_last_error() != _NOT_FOUND:
                raise CredentialError("Cannot delete the Windows credential")

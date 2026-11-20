import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Any


class SessionStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p))


def _session_path() -> Path:
    session_file = os.environ.get("ARCADE_SESSION_FILE", "").strip()
    if session_file:
        return Path(session_file).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "Arcade" / "save-clicker-session.bin"


def _protect(data: bytes, encrypt: bool) -> bytes:
    if os.name != "nt":
        raise SessionStoreError("Remembered login is only supported on Windows.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_buffer = ctypes.create_string_buffer(data, len(data))
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(input_buffer, ctypes.c_void_p),
    )
    output_blob = _DataBlob()
    description = wintypes.LPWSTR()
    flags = 0x1

    if encrypt:
        transform = crypt32.CryptProtectData
        transform.argtypes = (
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        )
        transform.restype = wintypes.BOOL
        succeeded = transform(
            ctypes.byref(input_blob),
            "Arcade Save Clicker session",
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )
    else:
        transform = crypt32.CryptUnprotectData
        transform.argtypes = (
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        )
        transform.restype = wintypes.BOOL
        succeeded = transform(
            ctypes.byref(input_blob),
            ctypes.byref(description),
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )

    if not succeeded:
        error = ctypes.WinError(ctypes.get_last_error())
        raise SessionStoreError(f"Windows could not {'encrypt' if encrypt else 'decrypt'} the saved login.") from error

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        if output_blob.pbData:
            kernel32.LocalFree(output_blob.pbData)
        if description:
            kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))


def save_session(session: dict[str, str]) -> None:
    if any(not isinstance(session.get(key), str) or not session[key] for key in ("server_url", "token", "username")):
        raise SessionStoreError("The session is missing required login details.")
    try:
        encrypted = _protect(
            json.dumps(session, separators=(",", ":"), allow_nan=False).encode("utf-8"),
            encrypt=True,
        )
        path = _session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=".save-clicker-",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(encrypted)
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    except OSError as error:
        raise SessionStoreError(f"Could not save the remembered login: {error}") from error


def load_session() -> dict[str, str] | None:
    path = _session_path()
    try:
        encrypted = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SessionStoreError(f"Could not read the remembered login: {error}") from error

    try:
        session: Any = json.loads(_protect(encrypted, encrypt=False).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, SessionStoreError) as error:
        raise SessionStoreError("The remembered login is damaged or unavailable.") from error
    if not isinstance(session, dict) or any(
        not isinstance(session.get(key), str) or not session[key]
        for key in ("server_url", "token", "username")
    ):
        raise SessionStoreError("The remembered login has an invalid format.")
    return session


def clear_session() -> None:
    try:
        _session_path().unlink(missing_ok=True)
    except OSError as error:
        raise SessionStoreError(f"Could not remove the remembered login: {error}") from error

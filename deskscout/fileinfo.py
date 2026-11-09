"""读取 exe 的版本资源（产品名/公司/版本），用于补全绿色软件信息."""

from __future__ import annotations

import ctypes
import os

_version = ctypes.WinDLL("version", use_last_error=True)
_version.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
_version.GetFileVersionInfoSizeW.restype = ctypes.c_uint32
_version.GetFileVersionInfoW.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_void_p,
]
_version.GetFileVersionInfoW.restype = ctypes.c_bool
_version.VerQueryValueW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_uint32),
]
_version.VerQueryValueW.restype = ctypes.c_bool


def _query(buffer, subblock: str) -> str:
    pointer = ctypes.c_void_p()
    length = ctypes.c_uint32()
    if not _version.VerQueryValueW(
        buffer, subblock, ctypes.byref(pointer), ctypes.byref(length)
    ):
        return ""
    if not pointer.value or not length.value:
        return ""
    try:
        return ctypes.wstring_at(pointer.value, length.value).split("\x00", 1)[0].strip()
    except (OSError, ValueError):
        return ""


def read_version_info(path: str) -> dict:
    """返回 {product, description, company, version}；失败返回空字典."""
    if not path or not os.path.isfile(path):
        return {}
    try:
        size = _version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return {}
        buffer = ctypes.create_string_buffer(size)
        if not _version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return {}
    except (OSError, ctypes.ArgumentError):
        return {}

    lang, codepage = 0x0409, 0x04B0
    pointer = ctypes.c_void_p()
    length = ctypes.c_uint32()
    if _version.VerQueryValueW(
        buffer, r"\VarFileInfo\Translation", ctypes.byref(pointer), ctypes.byref(length)
    ) and pointer.value and length.value >= 4:
        values = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint16))
        lang, codepage = values[0], values[1]

    prefix = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\"
    return {
        "product": _query(buffer, prefix + "ProductName"),
        "description": _query(buffer, prefix + "FileDescription"),
        "company": _query(buffer, prefix + "CompanyName"),
        "version": _query(buffer, prefix + "ProductVersion")
        or _query(buffer, prefix + "FileVersion"),
    }

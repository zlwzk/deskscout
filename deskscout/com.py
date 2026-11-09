"""极简 COM 封装：读写 Windows 快捷方式（.lnk）.

不依赖 pywin32 / comtypes，直接用 ctypes 调 IShellLinkW 与 IPersistFile，
避免额外的第三方依赖，单文件打包体积也更小。
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

ole32 = ctypes.OleDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
shell32.SHGetPathFromIDListW.restype = wintypes.BOOL


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> GUID:
    value = GUID()
    if ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value)) != 0:
        raise OSError(f"非法 GUID: {text}")
    return value


CLSID_SHELL_LINK = _guid("{00021401-0000-0000-C000-000000000046}")
IID_ISHELL_LINK_W = _guid("{000214F9-0000-0000-C000-000000000046}")
IID_IPERSIST_FILE = _guid("{0000010B-0000-0000-C000-000000000046}")

CLSCTX_INPROC_SERVER = 1

ole32.CoCreateInstance.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [
    ctypes.POINTER(GUID),
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.POINTER(GUID),
    ctypes.POINTER(ctypes.c_void_p),
]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
ole32.CoUninitialize.restype = None
ole32.CoUninitialize.argtypes = []
ole32.CoTaskMemFree.restype = None
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

_thread_state = threading.local()


def com_init() -> None:
    """在当前线程初始化 COM（幂等）."""
    if getattr(_thread_state, "ready", False):
        return
    try:
        ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    except OSError:
        pass
    _thread_state.ready = True


def _vtable_call(interface: ctypes.c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(
        interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    )[0]
    raw = vtable[index]
    address = raw if isinstance(raw, int) else raw.value
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(address)


def _create_shell_link() -> ctypes.c_void_p:
    com_init()
    pointer = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_SHELL_LINK),
        None,
        CLSCTX_INPROC_SERVER,
        ctypes.byref(IID_ISHELL_LINK_W),
        ctypes.byref(pointer),
    )
    if hr != 0 or not pointer.value:
        raise OSError(f"无法创建 IShellLink（HRESULT=0x{hr & 0xFFFFFFFF:08X}）")
    return pointer


def _release(interface: ctypes.c_void_p) -> None:
    if interface and interface.value:
        try:
            _vtable_call(interface, 2, ctypes.c_long)(interface)
        except OSError:
            pass


def _query_interface(interface: ctypes.c_void_p, iid: GUID) -> ctypes.c_void_p:
    out = ctypes.c_void_p()
    hr = _vtable_call(
        interface, 0, ctypes.c_long, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
    )(interface, ctypes.byref(iid), ctypes.byref(out))
    if hr != 0 or not out.value:
        raise OSError(f"QueryInterface 失败（HRESULT=0x{hr & 0xFFFFFFFF:08X}）")
    return out


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------


def read_shortcut(path: str) -> dict | None:
    """解析 .lnk，返回 target/args/icon/description/is_shell_item."""
    if not path or not os.path.isfile(path):
        return None
    link = None
    persist = None
    try:
        link = _create_shell_link()
        persist = _query_interface(link, IID_IPERSIST_FILE)
        hr = _vtable_call(
            persist, 5, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_uint32
        )(persist, path, 0)  # STGM_READ
        if hr != 0:
            return None

        buffer = ctypes.create_unicode_buffer(1024)
        hr = _vtable_call(
            link, 3, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_uint32,
        )(link, buffer, 1024, None, 0)
        target = buffer.value if hr == 0 else ""

        args_buf = ctypes.create_unicode_buffer(1024)
        _vtable_call(
            link, 10, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int
        )(link, args_buf, 1024)
        arguments = args_buf.value

        icon_buf = ctypes.create_unicode_buffer(1024)
        icon_index = ctypes.c_int(0)
        _vtable_call(
            link, 16, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        )(link, icon_buf, 1024, ctypes.byref(icon_index))
        icon = icon_buf.value

        desc_buf = ctypes.create_unicode_buffer(1024)
        _vtable_call(
            link, 6, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int
        )(link, desc_buf, 1024)
        description = desc_buf.value

        pidl = ctypes.c_void_p()
        hr_idl = _vtable_call(
            link, 4, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p)
        )(link, ctypes.byref(pidl))
        # 普通文件快捷方式也会返回“文件系统 PIDL”，只有解析不出路径的才是
        # 商店应用/控制面板这类 shell 命名空间项目。
        is_shell_item = False
        if pidl.value:
            path_buf = ctypes.create_unicode_buffer(1024)
            is_fs = bool(shell32.SHGetPathFromIDListW(pidl, path_buf))
            is_shell_item = not is_fs
            ole32.CoTaskMemFree(pidl)

        return {
            "target": target,
            "args": arguments,
            "icon": icon,
            "description": description,
            "is_shell_item": is_shell_item,
        }
    except (OSError, ctypes.ArgumentError):
        return None
    finally:
        _release(persist)
        _release(link)


# --------------------------------------------------------------------------
# 创建
# --------------------------------------------------------------------------


def create_shortcut(
    link_path: str,
    target: str,
    arguments: str = "",
    working_dir: str = "",
    icon: str = "",
    description: str = "",
    show_cmd: int = 1,
) -> bool:
    """创建 .lnk。target 可以是 exe/文档，或用 explorer.exe + shell: 参数."""
    if not link_path or not target:
        return False
    folder = os.path.dirname(link_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    if os.path.exists(link_path):
        return False

    link = None
    persist = None
    try:
        link = _create_shell_link()
        _vtable_call(link, 20, ctypes.c_long, ctypes.c_wchar_p)(link, target)
        if arguments:
            _vtable_call(link, 11, ctypes.c_long, ctypes.c_wchar_p)(link, arguments)
        work = working_dir or os.path.dirname(target)
        if work and os.path.isdir(work):
            _vtable_call(link, 9, ctypes.c_long, ctypes.c_wchar_p)(link, work)
        if description:
            _vtable_call(link, 7, ctypes.c_long, ctypes.c_wchar_p)(link, description[:255])
        if icon:
            _vtable_call(
                link, 17, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int
            )(link, icon, 0)
        _vtable_call(
            link, 15, ctypes.c_long, ctypes.c_int
        )(link, int(show_cmd) or 1)

        persist = _query_interface(link, IID_IPERSIST_FILE)
        hr = _vtable_call(
            persist, 6, ctypes.c_long, ctypes.c_wchar_p, wintypes.BOOL
        )(persist, link_path, wintypes.BOOL(True))
        return hr == 0
    except (OSError, ctypes.ArgumentError):
        return False
    finally:
        _release(persist)
        _release(link)


def create_url_shortcut(path: str, url: str) -> bool:
    """写 .url 网络快捷方式（纯文本 INI，不需要 COM）."""
    if not path or not url:
        return False
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        content = (
            "[InternetShortcut]\r\n"
            f"URL={url}\r\n"
            "IconIndex=0\r\n"
            "\r\n"
        )
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return True
    except OSError:
        return False


def read_url_shortcut(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if line.lower().startswith("url="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""

"""桌面扫描: 已有图标、容量评估、失效与重复检测."""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes

from . import com
from .filters import normalize_name, normalize_path
from .models import DesktopItem

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def desktop_dirs() -> list[tuple[str, bool]]:
    """返回 [(目录, 是否公共桌面)]."""
    result: list[tuple[str, bool]] = []
    try:
        user_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    except (KeyError, RuntimeError):
        user_desktop = ""
    if user_desktop and os.path.isdir(user_desktop):
        result.append((user_desktop, False))
    public = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop")
    if os.path.isdir(public):
        result.append((public, True))
    return result


_SKIP_NAMES = {"desktop.ini", "thumbs.db"}


def scan_desktop() -> list[DesktopItem]:
    """枚举桌面上的可见图标（含 .lnk/.url/文件/文件夹）."""
    items: list[DesktopItem] = []
    seen: dict[str, str] = {}
    for folder, is_public in desktop_dirs():
        try:
            entries = os.scandir(folder)
        except OSError:
            continue
        with entries:
            for entry in entries:
                name = entry.name
                if name.casefold() in _SKIP_NAMES or name.startswith("."):
                    continue
                if entry.is_dir():
                    kind = "folder"
                    target = entry.path
                else:
                    ext = os.path.splitext(name)[1].casefold()
                    if ext == ".lnk":
                        kind = "lnk"
                    elif ext == ".url":
                        kind = "url"
                    else:
                        kind = "file"
                    target = ""

                item = DesktopItem(
                    path=entry.path,
                    name=os.path.splitext(name)[0] if kind in {"lnk", "url"} else name,
                    kind=kind,
                    is_public=is_public,
                )
                if kind == "lnk":
                    info = com.read_shortcut(entry.path)
                    if info:
                        item.target = info.get("target", "")
                        item.args = info.get("args", "")
                        item.icon = info.get("icon", "")
                        item.is_shell_item = bool(info.get("is_shell_item"))
                        item.broken = bool(
                            item.target and not item.is_shell_item and not _target_exists(item.target)
                        )
                    else:
                        item.broken = True
                elif kind == "url":
                    item.target = com.read_url_shortcut(entry.path)
                    item.broken = not item.target
                elif kind == "file":
                    item.target = entry.path

                fingerprint = normalize_name(item.name)
                if fingerprint and fingerprint in seen:
                    item.duplicate_of = seen[fingerprint]
                elif fingerprint:
                    seen[fingerprint] = item.path
                items.append(item)
    return items


def _target_exists(target: str) -> bool:
    if not target:
        return False
    if target.startswith("shell:"):
        return True
    expanded = os.path.expandvars(target.strip('"'))
    if os.path.exists(expanded):
        return True
    # 目标可能是 exe 路径但被移走；再按文件名在 PATH 里找一次不算数，直接判失效
    return False


# --------------------------------------------------------------------------
# 容量
# --------------------------------------------------------------------------

_SPI_GETWORKAREA = 0x0030


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _icon_cell_size() -> tuple[int, int]:
    """读取桌面图标间距（twips），换算成像素；默认 75×75."""
    width = height = 75
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics"
        ) as key:
            for value_name, setter in (("IconSpacing", "w"), ("IconVerticalSpacing", "h")):
                try:
                    raw, _ = winreg.QueryValueEx(key, value_name)
                    pixels = max(48, int(abs(int(str(raw).strip())) / 15))
                    if setter == "w":
                        width = pixels
                    else:
                        height = pixels
                except (OSError, ValueError):
                    continue
    except OSError:
        pass
    return width, height


def _dpi_scale() -> float:
    try:
        return round(user32.GetDpiForSystem() / 96.0, 2)
    except (AttributeError, OSError):
        return 1.0


def desktop_capacity() -> dict:
    """估算桌面图标网格容量、已占用与剩余空位."""
    rect = RECT()
    user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    work_w = max(1, rect.right - rect.left)
    work_h = max(1, rect.bottom - rect.top)

    cell_w, cell_h = _icon_cell_size()
    columns = max(1, work_w // cell_w)
    rows = max(1, work_h // cell_h)
    total = columns * rows

    used = 0
    for folder, _ in desktop_dirs():
        try:
            with os.scandir(folder) as entries:
                used += sum(
                    1
                    for e in entries
                    if e.name.casefold() not in _SKIP_NAMES and not e.name.startswith(".")
                )
        except OSError:
            continue

    free = max(0, total - used)
    disk = {}
    try:
        import shutil

        base = desktop_dirs()[0][0] if desktop_dirs() else os.path.expanduser("~")
        usage = shutil.disk_usage(base)
        disk = {"total": usage.total, "free": usage.free}
    except OSError:
        pass

    return {
        "work_area": (work_w, work_h),
        "cell": (cell_w, cell_h),
        "columns": columns,
        "rows": rows,
        "total": total,
        "used": used,
        "free": free,
        "disk_free": disk.get("free", 0),
        "disk_total": disk.get("total", 0),
        "dpi_scale": _dpi_scale(),
    }

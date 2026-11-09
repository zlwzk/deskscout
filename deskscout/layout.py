"""桌面布局守护：把图标位置存成快照，被新装软件挤乱后一键还原.

Windows 自己把桌面图标坐标存在
``HKCU\\Software\\Microsoft\\Windows\\Shell\\Bags\\<bag>\\Desktop``
的 ``ItemPos<宽>x<高>`` 二进制值里，这里直接整段复制/写回，不解析私有结构，
所以不会“大概恢复”，而是把当时那份数据原样放回去。
写回后需要资源管理器重新读取，因此提供“重启资源管理器”选项。
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import winreg

from . import config

_SHELL_BAGS = r"Software\Microsoft\Windows\Shell\Bags"
_STATE_FILE = "desktop_layout.json"


def _iter_bags():
    """遍历 Bags 下所有带 Desktop 子键的 bag，返回 (bag 名, Desktop 键路径)."""
    try:
        bags = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SHELL_BAGS)
    except OSError:
        return
    index = 0
    try:
        while True:
            try:
                bag = winreg.EnumKey(bags, index)
            except OSError:
                break
            index += 1
            path = f"{_SHELL_BAGS}\\{bag}\\Desktop"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path):
                    yield bag, path
            except OSError:
                continue
    finally:
        bags.Close()


def _read_values(path: str) -> dict:
    """只取与图标位置有关的二进制值：Win10 的 ItemPos*、Win11 的 IconLayouts/Sort."""
    values: dict[str, list[int]] = {}
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        return values
    index = 0
    try:
        while True:
            try:
                name, data, kind = winreg.EnumValue(key, index)
            except OSError:
                break
            index += 1
            if kind != winreg.REG_BINARY or not isinstance(data, bytes):
                continue
            lowered = name.casefold()
            if not (lowered.startswith("itempos") or lowered == "iconlayouts"):
                continue
            values[name] = list(data)
    finally:
        key.Close()
    return values


def capture(desktop_items=None) -> dict:
    """抓一份快照：bag 结构 + 每个 ItemPos 的原始字节 + 当时的图标名单."""
    bags = {}
    for bag, path in _iter_bags():
        values = _read_values(path)
        if values:
            bags[bag] = {"path": path, "values": values}
    snapshot = {
        "captured_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "screen": _screen_size(),
        "bags": bags,
        "items": [item.name for item in (desktop_items or [])],
        "item_count": len(desktop_items or []),
    }
    config.save_json(_STATE_FILE, snapshot)
    return snapshot


def load_snapshot() -> dict:
    data = config.load_json(_STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def _screen_size() -> list[int]:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return [user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)]
    except (AttributeError, OSError):
        return [0, 0]


def restore(snapshot: dict) -> dict:
    """把快照里的 ItemPos 原样写回；返回每个 bag 的写入结果."""
    result = {"bags": 0, "values": 0, "errors": []}
    bags = (snapshot or {}).get("bags") or {}
    for bag, payload in bags.items():
        path = payload.get("path") or f"{_SHELL_BAGS}\\{bag}\\Desktop"
        values = payload.get("values") or {}
        if not values:
            continue
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
                for name, raw in values.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_BINARY, bytes(raw))
                    result["values"] += 1
            result["bags"] += 1
        except OSError as exc:
            result["errors"].append(f"{bag}: {exc}")
    _notify_shell()
    return result


def compare(snapshot: dict | None = None) -> dict:
    """对比当前注册表与快照：新增/消失的图标，以及位置数据是否变化."""
    snapshot = snapshot if snapshot is not None else load_snapshot()
    saved = {}
    for bag, payload in ((snapshot or {}).get("bags") or {}).items():
        for name, raw in (payload.get("values") or {}).items():
            saved[f"{bag}|{name}"] = list(raw)
    current = {}
    for bag, path in _iter_bags():
        for name, raw in _read_values(path).items():
            current[f"{bag}|{name}"] = raw
    added = [key for key in current if key not in saved]
    removed = [key for key in saved if key not in current]
    changed = [key for key in current if key in saved and current[key] != saved[key]]

    saved_items = [str(name) for name in (snapshot or {}).get("items", [])]
    try:
        from .desktop import scan_desktop

        current_items = [item.name for item in scan_desktop()]
    except (OSError, ValueError):
        current_items = []
    new_icons = [name for name in current_items if name not in saved_items]
    gone_icons = [name for name in saved_items if name not in current_items]
    return {
        "captured_at": (snapshot or {}).get("captured_at", ""),
        "saved_count": len(saved),
        "current_count": len(current),
        "added": len(added),
        "removed": len(removed),
        "changed": len(changed),
        "items_before": (snapshot or {}).get("item_count", 0),
        "items_now": len(current_items),
        "new_icons": new_icons,
        "gone_icons": gone_icons,
        "drift": bool(added or removed or changed or new_icons or gone_icons),
    }


def _notify_shell() -> None:
    try:
        import ctypes

        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except (AttributeError, OSError):
        pass


def restart_explorer() -> bool:
    """重启资源管理器让布局立即生效（桌面会闪一下，不影响已开窗口）."""
    try:
        subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True, timeout=10)
        subprocess.Popen(["explorer.exe"], close_fds=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False

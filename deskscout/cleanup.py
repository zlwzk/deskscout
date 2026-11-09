"""卸载残留清理：找出“注册表还在、目录没了”和“目录还在、注册表没了”的条目.

原则：
- 只报告，不自动删；
- 删除前先导出注册表备份（%APPDATA%\\DeskScout\\backup\\*.reg）；
- 目录删除走回收站（可还原），并且拒绝删除盘符根目录、系统目录与系统组件目录；
- 默认只勾选“安全项”（空目录 / 注册表指向不存在的路径）。
"""

from __future__ import annotations

import ctypes
import datetime as dt
import os
import subprocess
import winreg

from . import config
from .health import dir_size

_HIVE_MAP = {
    "HKEY_LOCAL_MACHINE": "HKLM",
    "HKEY_CURRENT_USER": "HKCU",
    "HKEY_CLASSES_ROOT": "HKCR",
    "HKEY_USERS": "HKU",
}

# 这些目录名属于系统/运行库，永远不当残留
_SYSTEM_DIR_NAMES = {
    "windowsapps", "modifiablewindowsapps", "common files", "windows defender",
    "windows mail", "windows media player",
    "windows nt", "windows photo viewer", "windows portable devices", "windows sidebar",
    "internet explorer", "microsoft", "microsoft office", "microsoft.net", "msbuild",
    "reference assemblies", "dotnet", "uninstall information", "modifiable", "temp",
}


def _roots() -> list[str]:
    roots = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(env)
        if not value:
            continue
        candidate = os.path.join(value, "Programs") if env == "LOCALAPPDATA" else value
        if os.path.isdir(candidate):
            roots.append(candidate)
    return roots


def _allowed_roots() -> list[str]:
    allowed = [os.path.normcase(root) for root in _roots()]
    return allowed


def _is_safe_dir(path: str) -> bool:
    """只有位于已知安装根目录、且层级足够的目录才允许处理."""
    normalized = os.path.normcase(os.path.abspath(path))
    for root in _allowed_roots():
        if normalized == root or not normalized.startswith(root + os.sep):
            continue
        relative = normalized[len(root) + 1:]
        if os.sep in relative:
            return False
        if relative.casefold() in _SYSTEM_DIR_NAMES:
            return False
        return True
    return False


def _reg_path(entry_key: str) -> tuple[str, str] | None:
    if not entry_key.startswith("reg:"):
        return None
    raw = entry_key[4:]
    hive, _, rest = raw.partition("\\")
    if hive not in _HIVE_MAP:
        return None
    return _HIVE_MAP[hive], rest


def registry_residuals(entries) -> list[dict]:
    """注册表在、安装目录/启动目标都不见了."""
    items = []
    for entry in entries:
        if entry.source != "registry":
            continue
        location = entry.install_location
        target = entry.target
        has_dir = bool(location) and os.path.isdir(location)
        has_target = bool(target) and os.path.exists(target)
        if has_dir or has_target:
            continue
        key = _reg_path(entry.key)
        if not key:
            continue
        display = location or target or ""
        items.append({
            "id": f"reg:{entry.key}",
            "kind": "registry",
            "name": entry.name,
            "detail": f"安装位置已不存在：{display}" if display else "安装位置与启动目标都已不存在",
            "path": entry.key,
            "size": 0,
            "safe": True,
            "hive": key[0],
            "subkey": key[1],
        })
    return items


def orphan_dirs(entries, min_age_days: int = 30) -> list[dict]:
    """安装根目录下、没有任何已安装条目引用、且很久没动过的顶层目录."""
    referenced = set()
    for entry in entries:
        for value in (entry.install_location, entry.target):
            if value:
                referenced.add(os.path.normcase(os.path.abspath(value.split(",")[0].strip())))
    items = []
    cutoff = dt.datetime.now().timestamp() - min_age_days * 86400
    for root in _roots():
        try:
            entries_iter = list(os.scandir(root))
        except OSError:
            continue
        for item in entries_iter:
            if not item.is_dir(follow_symlinks=False):
                continue
            name = item.name
            if name.casefold() in _SYSTEM_DIR_NAMES or name.startswith((".", "$")):
                continue
            path = os.path.normcase(os.path.abspath(item.path))
            if not _is_safe_dir(item.path):
                continue
            hit = any(ref == path or ref.startswith(path + os.sep) or path.startswith(ref + os.sep)
                      for ref in referenced)
            if hit:
                continue
            try:
                stamp = item.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            if stamp > cutoff:
                continue
            size = dir_size(item.path, budget=1.2)
            empty = size == 0
            items.append({
                "id": f"dir:{path}",
                "kind": "dir",
                "name": name,
                "detail": f"{item.path}" + ("（空目录）" if empty else ""),
                "path": item.path,
                "size": size,
                "safe": empty,
            })
    return items


def scan(entries, min_age_days: int = 30) -> list[dict]:
    items = registry_residuals(entries) + orphan_dirs(entries, min_age_days)
    items.sort(key=lambda item: (not item["safe"], item["kind"], item["name"].casefold()))
    cfg = config.load()
    cfg.setdefault("cleanup", {})["last_scan"] = int(dt.datetime.now().timestamp())
    config.save(cfg)
    return items


def _backup_path() -> str:
    folder = os.path.join(config.app_dir(), "backup")
    os.makedirs(folder, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(folder, f"cleanup-{stamp}.reg")


def backup_registry(items: list[dict]) -> str:
    """把待删除的注册表项导出成一个 .reg 备份文件."""
    keys = [f"{item['hive']}\\{item['subkey']}" for item in items if item["kind"] == "registry"]
    if not keys:
        return ""
    path = _backup_path()
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Windows Registry Editor Version 5.00\n\n")
        for key in keys:
            subprocess.run(["reg", "export", key, path, "/y"],
                           capture_output=True, timeout=20, check=False)
        return path if os.path.exists(path) else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def delete_registry(items: list[dict]) -> tuple[int, list[str]]:
    done = 0
    errors = []
    for item in items:
        if item["kind"] != "registry":
            continue
        key = f"{item['hive']}\\{item['subkey']}"
        try:
            result = subprocess.run(["reg", "delete", key, "/f"],
                                    capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"{item['name']}: {exc}")
            continue
        if result.returncode == 0:
            done += 1
        else:
            message = (result.stderr or b"").decode("utf-8", "ignore").strip()
            errors.append(f"{item['name']}: {message or 'reg delete 失败'}")
    return done, errors


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def _recycle(paths: list[str]) -> tuple[int, list[str]]:
    done = 0
    errors: list[str] = []
    for path in paths:
        if not _is_safe_dir(path) or not os.path.isdir(path):
            errors.append(f"{path}: 不在允许清理的安装目录内")
            continue
        source = path + "\0"
        struct = _SHFILEOPSTRUCTW(
            hwnd=None, wFunc=3,  # FO_DELETE
            pFrom=source, pTo=None,
            fFlags=0x40 | 0x10 | 0x4,  # ALLOWUNDO | NOCONFIRMATION | SILENT
            fAnyOperationsAborted=0, hNameMappings=None, lpszProgressTitle=None,
        )
        try:
            code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(struct))
        except (AttributeError, OSError) as exc:
            errors.append(f"{os.path.basename(path)}: {exc}")
            continue
        if code == 0 and not struct.fAnyOperationsAborted:
            done += 1
        else:
            errors.append(f"{os.path.basename(path)}: 回收站操作失败（代码 {code}）")
    return done, errors


def execute(items: list[dict]) -> dict:
    """按选中项执行清理：先备份注册表，再删除；目录走回收站."""
    reg_items = [item for item in items if item["kind"] == "registry"]
    dir_items = [item for item in items if item["kind"] == "dir"]
    backup = backup_registry(reg_items) if reg_items else ""
    reg_done, reg_errors = delete_registry(reg_items) if reg_items else (0, [])
    dir_done, dir_errors = _recycle([item["path"] for item in dir_items]) if dir_items else (0, [])
    return {
        "registry_removed": reg_done,
        "dirs_removed": dir_done,
        "backup": backup,
        "errors": reg_errors + dir_errors,
    }


def uninstall_command(entry) -> str:
    """把注册表里的 UninstallString 直接交给 shell，交给系统卸载程序处理."""
    return (entry.uninstall_string or "").strip()

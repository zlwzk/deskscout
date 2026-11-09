"""配置读写：%APPDATA%\\DeskScout\\config.json."""

from __future__ import annotations

import copy
import json
import os

APP_DIR_NAME = "DeskScout"

DEFAULTS: dict = {
    "scan": {
        "registry": True,
        "startmenu": True,
        "store": True,
        "steam": True,
        "folder": False,
        "custom_folder": "",
    },
    "filter": {
        "include_system": False,
        "hide_targetless": True,
    },
    "shortcuts": {
        "mode": "desktop",          # desktop | folder
        "folder_name": "新建快捷方式",
        "confirm_before_create": True,
    },
    "ui": {
        "geometry": "1180x780",
        "auto_scan_on_start": True,
        "last_view": "apps",
        "autostart": False,
    },
    "update": {
        "auto_check": True,
        "last_check": 0,
        "skipped_version": "",
    },
}


def app_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(app_dir(), "config.json")


def _deep_merge(base: dict, patch: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load() -> dict:
    try:
        with open(config_path(), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            return _deep_merge(DEFAULTS, stored)
    except (OSError, ValueError):
        pass
    return copy.deepcopy(DEFAULTS)


def save(config: dict) -> bool:
    try:
        with open(config_path(), "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def get(config: dict, dotted: str, default=None):
    node = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "DeskScout"


def is_autostart() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
            return bool(value)
    except OSError:
        return False


def set_autostart(enable: bool, exe_path: str) -> bool:
    """写入/删除 HKCU Run 自启动项."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE)
                except OSError:
                    pass
        return True
    except OSError:
        return False

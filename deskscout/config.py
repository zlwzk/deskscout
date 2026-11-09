"""配置读写：%APPDATA%\\DeskScout\\config.json."""

from __future__ import annotations

import copy
import json
import os
import shutil

APP_DIR_NAME = "DeskScout"
SCHEMA_VERSION = 3

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
        "confirm_before_create": False,
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
        "last_seen_version": "",
        "inbox": [],                # [{version,title,date,notes}] 应用内公告
        "remote_enabled": True,
        "remote_url": "https://raw.githubusercontent.com/zlwzk/deskscout/main/announcements.json",
    },
    # ---- 1.2.0 起：收藏 / 屏蔽 / 便携库 / 自启 / 桌面快照 ----
    "library": {
        "favorites": [],            # [{name,key,publisher,source_url,version,target,install,note,added,last_seen}]
        "blocklist": [],            # [{key,name,reason,added}]
    },
    "portable": {
        "roots": [],                # 绿色软件目录
        "export_path": "",
        "last_export": "",
    },
    "autostart": {
        "disabled": [],             # [{kind,key,name,command,backup}]
    },
    "desktop": {
        "snapshot": None,           # {captured_at,items:[{name}],raw:{value: [ints]}}
        "snapshot_at": "",
    },
    "cleanup": {
        "last_scan": 0,
    },
    "health": {
        "cache": {},                # {"path|mtime": size}
        "last_report": {},
    },
    "appearance": {
        "icon_style": "native",     # native | rounded | mono
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
            merged = _deep_merge(DEFAULTS, stored)
            old_schema = int(stored.get("schema_version") or 0)
            # 1.1.0 起“创建前二次确认”默认关闭：老配置里遗留的 True 只做一次性迁移，
            # 之后用户在设置页的勾选仍然有效。
            if not old_schema:
                merged.setdefault("shortcuts", {})["confirm_before_create"] = False
            # 版本升级只补默认值，不覆盖用户数据（收藏/屏蔽/自启备份/快照都原样保留）
            if old_schema < SCHEMA_VERSION:
                merged["schema_version"] = SCHEMA_VERSION
                save(merged)
            return merged
    except (OSError, ValueError):
        pass
    fresh = copy.deepcopy(DEFAULTS)
    fresh["schema_version"] = SCHEMA_VERSION
    return fresh


def save(config: dict) -> bool:
    """原子写入并保留上一份 .bak，避免异常退出把收藏/屏蔽等数据写坏."""
    try:
        config["schema_version"] = SCHEMA_VERSION
        path = config_path()
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
        if os.path.exists(path):
            try:
                shutil.copy2(path, path + ".bak")
            except OSError:
                pass
        os.replace(temp, path)
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


def state_path(name: str) -> str:
    return os.path.join(app_dir(), name)


def load_json(name: str, default):
    """读取状态文件（last_scan.json、快照等）；文件损坏时返回默认值."""
    try:
        with open(state_path(name), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return copy.deepcopy(default)


def save_json(name: str, data) -> bool:
    try:
        path = state_path(name)
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temp, path)
        return True
    except OSError:
        return False


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

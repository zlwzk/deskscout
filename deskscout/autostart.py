"""开机自启管理：注册表 Run / 启动文件夹 / 计划任务 / 服务的四路枚举与开关.

禁用不是“删掉”，而是把原始信息备份进 config.json 的 ``autostart.disabled``，
随时可以还原；启动文件夹里的文件则移到 ``%APPDATA%\\DeskScout\\autostart_backup``。
计划任务用 schtasks 禁用，服务改 Start 值（需要管理员，失败会如实回报）。
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import os
import shutil
import subprocess
import winreg

from . import config

_RUN_KEYS = [
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM32", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
]
_HIVES = {
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKLM32": winreg.HKEY_LOCAL_MACHINE,
}
_MS_HINTS = ("microsoft", "windows", "edgeupdate", "onedrive", "securityhealth")


def _startup_folders() -> list[tuple[str, str]]:
    result = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("ProgramData")
    if appdata:
        result.append(("用户启动", os.path.join(
            appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")))
    if programdata:
        result.append(("公共启动", os.path.join(
            programdata, r"Microsoft\Windows\Start Menu\Programs\Startup")))
    return [(label, path) for label, path in result if os.path.isdir(path)]


def _risk(command: str, name: str, age_days: int | None) -> str:
    text = (command or "").strip().strip('"').casefold()
    if not text:
        return "空命令"
    if any(hint in text for hint in ("\\temp\\", "/temp/", "\\tmp\\")):
        return "临时目录"
    if text.endswith((".vbs", ".cmd", ".bat")):
        return "脚本启动"
    if age_days is not None and age_days <= 14:
        return "近期新增"
    return ""


def _exe_of(command: str) -> str:
    text = (command or "").strip()
    if text.startswith('"'):
        return text[1:].split('"', 1)[0]
    if text.lower().endswith(".exe"):
        return text
    for token in text.split():
        if token.casefold().endswith(".exe"):
            return token.strip('"')
    return ""


def run_items() -> list[dict]:
    items = []
    for label, path in _RUN_KEYS:
        try:
            key = winreg.OpenKey(_HIVES[label], path)
        except OSError:
            continue
        try:
            age_days = None
            try:
                stamp = winreg.QueryInfoKey(key)[2] / 10_000_000 - 11644473600
                age_days = max(0, int((dt.datetime.now().timestamp() - stamp) / 86400))
            except (OSError, ValueError):
                pass
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                command = str(value)
                items.append({
                    "kind": "run",
                    "id": f"run:{label}\\{name}",
                    "name": name,
                    "command": command,
                    "location": f"{label}\\{path}",
                    "enabled": True,
                    "risk": _risk(command, name, age_days),
                    "age_days": age_days,
                })
        finally:
            key.Close()
    return items


def startup_items() -> list[dict]:
    items = []
    for label, folder in _startup_folders():
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            if entry.name.casefold() == "desktop.ini":
                continue
            if entry.name.casefold().endswith(".lnk"):
                command = _shortcut_target(entry.path)
            else:
                command = entry.path
            items.append({
                "kind": "startup",
                "id": f"startup:{entry.path}",
                "name": os.path.splitext(entry.name)[0],
                "command": command or entry.path,
                "location": f"{label}：{folder}",
                "path": entry.path,
                "enabled": True,
                "risk": _risk(command or entry.path, entry.name, None),
                "age_days": None,
            })
    return items


def _shortcut_target(path: str) -> str:
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort),
                        ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

        class _IShellLinkW(ctypes.Structure):
            pass

        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        clsid = _GUID(0x00021401, 0, 0, (ctypes.c_ubyte * 8)(0xC0, 0, 0, 0, 0, 0, 0, 0x46))
        # 用 PowerShell 兜底太慢，这里直接读 .lnk 二进制里的目标路径片段
        del clsid
        with open(path, "rb") as handle:
            data = handle.read()
        for segment in data.split(b"\x00"):
            if len(segment) > 4 and segment[:2] == b"C:":
                return segment.decode("utf-16-le", "ignore")
        return ""
    except (OSError, AttributeError, ValueError):
        return ""


def task_items() -> list[dict]:
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/fo", "csv", "/v"],
            capture_output=True, timeout=25, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    text = (result.stdout or b"").decode("utf-8", "ignore")
    if not text.strip():
        return []
    items = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            name = (row.get("TaskName") or "").strip()
            if not name or name.casefold().startswith("\\microsoft"):
                continue
            state = (row.get("Scheduled Task State") or row.get("Status") or "").strip()
            command = (row.get("Task To Run") or "").strip()
            schedule = (row.get("Schedule Type") or "").strip()
            if "boot" not in schedule.casefold() and "logon" not in schedule.casefold():
                # 只关心开机/登录触发的项，每小时跑一次的更新器不算自启
                if schedule.casefold() not in {"", "one time", "at startup", "at logon"}:
                    continue
            lowered = name.casefold()
            if any(hint in lowered for hint in ("\\mozilla\\", "\\google\\", "\\adobe\\")):
                pass
            items.append({
                "kind": "task",
                "id": f"task:{name}",
                "name": name.lstrip("\\").split("\\")[-1],
                "command": command,
                "location": f"计划任务：{name}",
                "enabled": state.casefold() != "disabled",
                "risk": _risk(command, name, None),
                "age_days": None,
            })
    except (csv.Error, ValueError):
        return []
    return items


def service_items() -> list[dict]:
    try:
        result = subprocess.run(["sc", "query", "type=", "service", "state=", "all"],
                                capture_output=True, timeout=25, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for raw in (result.stdout or b"").decode("utf-8", "ignore").splitlines():
        line = raw.strip()
        if line.startswith("SERVICE_NAME:"):
            names.append(line.split(":", 1)[1].strip())
    items = []
    for name in names:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 rf"SYSTEM\CurrentControlSet\Services\{name}")
        except OSError:
            continue
        try:
            start, _ = winreg.QueryValueEx(key, "Start")
            service_type, _ = winreg.QueryValueEx(key, "Type")
            try:
                display, _ = winreg.QueryValueEx(key, "DisplayName")
            except OSError:
                display = name
            try:
                image, _ = winreg.QueryValueEx(key, "ImagePath")
            except OSError:
                image = ""
        except OSError:
            key.Close()
            continue
        key.Close()
        if int(service_type) & 0x0F in (1, 2):  # 内核/文件系统驱动，不列
            continue
        if int(start) != 2:                      # 只列自动启动
            continue
        if name.casefold().startswith(_MS_HINTS):
            continue
        windir = (os.environ.get("WINDIR") or "").casefold()
        image_text = str(image).casefold()
        if windir and windir in image_text:      # 系统自带服务（svchost/system32 等）不列
            continue
        if image_text.startswith(("%systemroot%", "%windir%", "\\systemroot")):
            continue
        items.append({
            "kind": "service",
            "id": f"service:{name}",
            "name": display,
            "command": str(image),
            "location": f"服务：{name}",
            "service_name": name,
            "enabled": True,
            "risk": _risk(str(image), name, None),
            "age_days": None,
        })
    return items


def list_all() -> list[dict]:
    items = []
    for collector in (run_items, startup_items, task_items, service_items):
        try:
            items.extend(collector())
        except OSError:
            continue
    disabled = {record.get("id") for record in
                (config.load().get("autostart", {}) or {}).get("disabled", [])}
    for item in items:
        if item["id"] in disabled:
            item["enabled"] = False
    items.sort(key=lambda item: (not item["enabled"], item["kind"], item["name"].casefold()))
    return items


def _remember(cfg: dict, item: dict, backup: dict) -> None:
    records = cfg.setdefault("autostart", {}).setdefault("disabled", [])
    records = [record for record in records if record.get("id") != item["id"]]
    records.append({"id": item["id"], "kind": item["kind"], "name": item["name"],
                    "command": item["command"], "backup": backup,
                    "added": dt.datetime.now().strftime("%Y-%m-%d %H:%M")})
    cfg["autostart"]["disabled"] = records


def _forget(cfg: dict, item_id: str) -> dict | None:
    records = cfg.setdefault("autostart", {}).setdefault("disabled", [])
    target = next((record for record in records if record.get("id") == item_id), None)
    cfg["autostart"]["disabled"] = [record for record in records if record.get("id") != item_id]
    return target


def disable(item: dict) -> tuple[bool, str]:
    cfg = config.load()
    kind = item.get("kind")
    try:
        if kind == "run":
            label, _, rest = item["location"].partition("\\")
            with winreg.OpenKey(_HIVES[label], rest, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, item["name"])
            _remember(cfg, item, {"location": item["location"], "name": item["name"]})
        elif kind == "startup":
            backup_dir = os.path.join(config.app_dir(), "autostart_backup")
            os.makedirs(backup_dir, exist_ok=True)
            target = os.path.join(backup_dir, os.path.basename(item["path"]))
            shutil.move(item["path"], target)
            _remember(cfg, item, {"backup_file": target})
        elif kind == "task":
            result = subprocess.run(["schtasks", "/change", "/tn", item["name"], "/disable"],
                                    capture_output=True, timeout=20, check=False)
            if result.returncode != 0:
                return False, (result.stderr or b"").decode("utf-8", "ignore").strip() or "禁用计划任务失败"
            _remember(cfg, item, {})
        elif kind == "service":
            result = subprocess.run(["sc", "config", item["service_name"], "start=", "demand"],
                                    capture_output=True, timeout=20, check=False)
            if result.returncode != 0:
                return False, (result.stderr or b"").decode("utf-8", "ignore").strip() or "修改服务启动类型失败（可能需要管理员权限）"
            _remember(cfg, item, {})
        else:
            return False, "不支持的类型"
    except (OSError, KeyError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    config.save(cfg)
    return True, ""


def enable(item: dict) -> tuple[bool, str]:
    cfg = config.load()
    record = _forget(cfg, item["id"])
    kind = item.get("kind")
    try:
        if kind == "run":
            backup = (record or {}).get("backup") or {"location": item["location"], "name": item["name"]}
            label, _, rest = backup["location"].partition("\\")
            with winreg.OpenKey(_HIVES[label], rest, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, backup["name"], 0, winreg.REG_SZ, item["command"])
        elif kind == "startup":
            backup = (record or {}).get("backup") or {}
            source = backup.get("backup_file")
            if not source or not os.path.exists(source):
                return False, "备份文件已不存在，请手动恢复"
            shutil.move(source, item.get("path") or os.path.join(
                _startup_folders()[0][1], os.path.basename(source)))
        elif kind == "task":
            result = subprocess.run(["schtasks", "/change", "/tn", item["name"], "/enable"],
                                    capture_output=True, timeout=20, check=False)
            if result.returncode != 0:
                return False, "启用计划任务失败"
        elif kind == "service":
            result = subprocess.run(["sc", "config", item["service_name"], "start=", "auto"],
                                    capture_output=True, timeout=20, check=False)
            if result.returncode != 0:
                return False, "修改服务启动类型失败（可能需要管理员权限）"
        else:
            return False, "不支持的类型"
    except (OSError, KeyError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    config.save(cfg)
    return True, ""


def summary(items: list[dict]) -> dict:
    enabled = [item for item in items if item["enabled"]]
    risky = [item for item in enabled if item["risk"]]
    by_kind: dict[str, int] = {}
    for item in enabled:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    return {"total": len(items), "enabled": len(enabled), "risky": len(risky), "by_kind": by_kind}

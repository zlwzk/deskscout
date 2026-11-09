"""各种扫描来源.

每个 scan_* 只负责“取数据 + 单条判断”，跨来源的去重与最终策略在 engine.py。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import winreg
from typing import Callable

from . import com, fileinfo
from .filters import (
    clean_display_name,
    is_bad_launch_target,
    is_launchable_target,
    is_non_app_entry,
    is_web_target,
    is_system_component,
    normalize_name,
    normalize_path,
    split_icon_path,
)
from .models import AppEntry

Progress = Callable[[str, int], None] | None

_UNINSTALL_ROOTS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)

_SKIP_EXE_RE = re.compile(
    r"(unins|uninstall|setup|install(er)?|update|upgrade|crash|report|helper|"
    r"remove|repair|mainten|vcredist|dxsetup|dotnet|elevat|service|daemon|"
    r"telemetry|diagnos|benchmark)",
    re.IGNORECASE,
)


def _safe_string(key, name: str) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _safe_int(key, name: str) -> int:
    try:
        value, _ = winreg.QueryValueEx(key, name)
        return int(value)
    except (OSError, ValueError, TypeError):
        return 0


def _launch_candidates(folder: str) -> list[str]:
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    candidates = []
    for entry in entries:
        if not entry.is_file():
            continue
        if not entry.name.casefold().endswith(".exe"):
            continue
        if _SKIP_EXE_RE.search(entry.name):
            continue
        candidates.append(entry.path)
    return candidates[:200]


def _guess_target_from_folder(folder: str, display_name: str) -> str:
    """在安装目录里挑一个最像主程序的 exe（只在找不到 DisplayIcon 时兜底）."""
    if not folder or not os.path.isdir(folder):
        return ""
    candidates = _launch_candidates(folder)
    if not candidates:
        return ""
    tokens = {t for t in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", display_name.casefold()) if len(t) >= 3}
    best, best_score = "", 0
    for path in candidates:
        stem = normalize_name(os.path.splitext(os.path.basename(path))[0])
        score = 0
        if stem and stem == normalize_name(display_name):
            score += 5
        for token in tokens:
            if token in stem:
                score += 2
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size > 400 * 1024:
            score += 1
        if score > best_score:
            best, best_score = path, score
    return best if best_score >= 2 else ""


# --------------------------------------------------------------------------
# 注册表
# --------------------------------------------------------------------------


def scan_registry(progress: Progress = None) -> list[AppEntry]:
    entries: list[AppEntry] = []
    total = 0
    for root, path in _UNINSTALL_ROOTS:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    subkey = winreg.OpenKey(key, subkey_name)
                except OSError:
                    continue
                with subkey:
                    total += 1
                    entry = _entry_from_uninstall_key(subkey, subkey_name, root, path)
                    if entry is not None:
                        entries.append(entry)
        if progress:
            progress(f"注册表：已读取 {total} 条卸载项", 20)
    return entries


def _entry_from_uninstall_key(key, subkey_name: str, root, root_path: str) -> AppEntry | None:
    display_name_raw = _safe_string(key, "DisplayName")
    if not display_name_raw:
        return None
    display_name = clean_display_name(display_name_raw)
    non_app, _ = is_non_app_entry(display_name)
    if non_app:
        return None

    publisher = _safe_string(key, "Publisher")
    version = _safe_string(key, "DisplayVersion")
    install_location = _safe_string(key, "InstallLocation")
    uninstall_string = _safe_string(key, "QuietUninstallString") or _safe_string(key, "UninstallString")
    display_icon_raw = _safe_string(key, "DisplayIcon")
    icon_path, icon_index = split_icon_path(display_icon_raw)
    release_type = _safe_string(key, "ReleaseType")
    parent_key = _safe_string(key, "ParentKeyName")
    system_component = _safe_int(key, "SystemComponent")
    estimated_kb = _safe_int(key, "EstimatedSize")

    system, reason = is_system_component(
        name=display_name,
        publisher=publisher,
        install_location=install_location,
        uninstall_string=uninstall_string,
        icon_path=icon_path,
        release_type=release_type,
        parent_key=parent_key,
        system_component=system_component,
    )
    if system:
        return AppEntry(
            key=f"reg:{root_path}\\{subkey_name}",
            name=display_name,
            version=version,
            publisher=publisher,
            source="registry",
            category="system",
            confidence="high",
            install_location=install_location,
            uninstall_string=uninstall_string,
            icon_path=icon_path,
            size_bytes=estimated_kb * 1024,
            note=reason,
        )

    target = ""
    if (
        icon_path
        and os.path.isfile(icon_path)
        and is_launchable_target(icon_path)
        and not is_bad_launch_target(icon_path)
    ):
        target = icon_path
    if not target:
        target = _guess_target_from_folder(install_location, display_name)
    confidence = "high" if target else "low"

    invalid = False
    note = ""
    if not target:
        note = "未找到可启动的主程序"
        if install_location and not os.path.isdir(os.path.expandvars(install_location)):
            invalid = True
            note = "安装目录已不存在（疑似卸载残留）"
        elif uninstall_string and not uninstall_string.casefold().startswith("msiexec"):
            uninstall_exe, _ = split_icon_path(uninstall_string)
            if uninstall_exe and not os.path.exists(os.path.expandvars(uninstall_exe)):
                invalid = True
                note = "卸载程序已缺失（疑似卸载残留）"

    category = "user"
    if "steamapps" in (install_location or "").casefold() and "common" in (install_location or "").casefold():
        category = "game"

    return AppEntry(
        key=f"reg:{root_path}\\{subkey_name}",
        name=display_name,
        version=version,
        publisher=publisher,
        source="registry",
        category=category,
        confidence=confidence,
        install_location=install_location,
        uninstall_string=uninstall_string,
        icon_path=icon_path,
        target=target,
        working_dir=os.path.dirname(target) if target else "",
        size_bytes=estimated_kb * 1024,
        invalid=invalid,
        note=note,
    )


# --------------------------------------------------------------------------
# 开始菜单
# --------------------------------------------------------------------------

_START_MENU_ROOTS = (
    (os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"), False),
    (os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs"), True),
)

_SYSTEM_MENU_HINTS = (
    "administrative tools",
    "windows 管理工具",
    "windows 系统工具",
    "system tools",
    "accessibility",
    "轻松使用",
    "附件",
    "accessories",
    "startup",
    "启动",
    "windows powershell",
    "命令提示符",
    "command prompt",
)


def scan_start_menu(progress: Progress = None) -> list[AppEntry]:
    entries: list[AppEntry] = []
    for root, is_public in _START_MENU_ROOTS:
        if not root or not os.path.isdir(root):
            continue
        for current, _dirs, files in os.walk(root):
            for filename in files:
                if not filename.casefold().endswith((".lnk", ".url")):
                    continue
                full = os.path.join(current, filename)
                entry = _entry_from_shortcut(full, root, is_public)
                if entry is not None:
                    entries.append(entry)
        if progress:
            progress(f"开始菜单：已读取 {len(entries)} 个快捷方式", 40)
    return entries


def _entry_from_shortcut(full_path: str, root: str, is_public: bool) -> AppEntry | None:
    # 程序组里的 .url 是“官网/文档链接”，不是软件
    if full_path.casefold().endswith(".url"):
        return None

    raw_name = os.path.splitext(os.path.basename(full_path))[0]
    name = clean_display_name(raw_name)
    non_app, _ = is_non_app_entry(name)
    if non_app:
        return None

    relative = os.path.relpath(full_path, root).casefold().replace(os.sep, "/")
    for hint in _SYSTEM_MENU_HINTS:
        if hint in relative:
            return None

    info = com.read_shortcut(full_path)
    if not info:
        return None
    target = info.get("target", "")
    args = info.get("args", "")
    icon = info.get("icon", "")
    is_shell = bool(info.get("is_shell_item"))

    if not target:
        return None
    if is_web_target(target):
        return None
    if not is_launchable_target(target):
        return None
    if is_bad_launch_target(target):
        return None
    if _is_system_target(target):
        return None

    system, reason = is_system_component(
        name=name,
        icon_path=target,
        install_location=os.path.dirname(target),
    )
    if system:
        return None

    exists = os.path.exists(os.path.expandvars(target))
    working_dir = os.path.dirname(os.path.expandvars(target)) if exists else ""

    return AppEntry(
        key=f"sm:{normalize_path(full_path)}",
        name=name,
        publisher="",
        source="startmenu",
        category="user",
        confidence="high" if exists else "low",
        icon_path=icon,
        target=os.path.expandvars(target),
        arguments=args,
        working_dir=working_dir,
        invalid=not exists,
        note="快捷方式目标已缺失" if not exists else "",
    )


def _is_system_target(target: str) -> bool:
    npath = normalize_path(target)
    if not npath:
        return False
    windir = normalize_path(os.environ.get("SystemRoot", r"C:\Windows"))
    for suffix in ("system32", "syswow64", "winsxs", "servicing", "systemapps", "installer", "kits"):
        try:
            if npath.startswith(os.path.join(windir, suffix).casefold().replace("/", "\\")):
                return True
        except (ValueError, TypeError):
            continue
    return False


# --------------------------------------------------------------------------
# Microsoft Store（AppX）
# --------------------------------------------------------------------------

_APPX_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$start = @()
try { foreach ($a in Get-StartApps) { $start += [pscustomobject]@{ n = $a.Name; id = $a.AppID } } } catch {}
$pkgs = @()
try {
  foreach ($p in Get-AppxPackage) {
    $pkgs += [pscustomobject]@{
      name = $p.Name; family = $p.PackageFamilyName; publisher = $p.Publisher
      nonremovable = [bool]$p.NonRemovable; sig = "$($p.SignatureKind)"
      version = "$($p.Version)"; loc = $p.InstallLocation; framework = [bool]$p.IsFramework
    }
  }
} catch {}
$payload = [pscustomobject]@{ start = $start; pkgs = $pkgs }
$json = $payload | ConvertTo-Json -Depth 4 -Compress
[IO.File]::WriteAllText('__OUT__', $json, [Text.UTF8Encoding]::new($false))
"""

_APPX_DENY = re.compile(
    r"^microsoft\.(windows|net|vclibs|ui|services|hevc|vp9|mpeg|webp|codec|store|"
    r"xbox|gaming|advertising|mixedreality|officehub|skypeapp|people|photos|"
    r"windowscommunicationsapps|zunemusic|zunevideo|bing|edge|getstarted|"
    r"cortana|yourphone|feedback|teams|wallet|barcode|lockapp|search|shell|"
    r"securehealthcare|passpoint|winget|desktopappinstaller|appinstaller|"
    r"oneconnect|paint|notepad|terminal|sticky|snipping|calculator|clock|"
    r"camera|soundrecorder|media|games|solitaire|storepurchaseapp|"
    r"client\.|immersivecontrolpanel|screensketch|quickassist|windowscommunications)",
    re.IGNORECASE,
)


def _powershell_path() -> str:
    """优先用系统自带的 Windows PowerShell；某些受限环境 PATH 里没有它."""
    candidates = [
        os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        ),
        os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "PowerShell",
            "7",
            "pwsh.exe",
        ),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("powershell.exe") or shutil.which("pwsh") or "powershell.exe"


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def scan_store(progress: Progress = None) -> list[AppEntry]:
    entries: list[AppEntry] = []
    handle = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix="deskscout_appx_", suffix=".json")
        os.close(fd)
        script = _APPX_SCRIPT.replace("__OUT__", temp_path.replace("'", "''"))
        creationflags = 0x08000000  # CREATE_NO_WINDOW
        completed = subprocess.run(
            [
                _powershell_path(),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=60,
            creationflags=creationflags,
        )
        with open(temp_path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, subprocess.SubprocessError):
        return entries
    finally:
        try:
            os.unlink(temp_path)
        except (OSError, UnboundLocalError):
            pass

    packages = {
        str(p.get("family", "")).casefold(): p
        for p in _as_list(payload.get("pkgs"))
        if isinstance(p, dict)
    }
    for app in _as_list(payload.get("start")):
        if not isinstance(app, dict):
            continue
        appid = str(app.get("id", "") or "")
        name = str(app.get("n", "") or "").strip()
        if not name or "!" not in appid:
            continue
        family = appid.split("!", 1)[0]
        package = packages.get(family.casefold(), {})
        if package.get("framework"):
            continue
        if _APPX_DENY.search(package.get("name", "") or family):
            continue
        signature = str(package.get("sig", "")).casefold()
        if signature in {"system", "none"} or package.get("nonremovable"):
            continue
        entries.append(
            AppEntry(
                key=f"appx:{appid.casefold()}",
                name=name,
                version=str(package.get("version", "") or ""),
                publisher="",
                source="store",
                category="store",
                confidence="high",
                install_location=str(package.get("loc", "") or ""),
                target=os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe"),
                arguments=f"shell:AppsFolder\\{appid}",
                working_dir=os.environ.get("SystemRoot", r"C:\Windows"),
            )
        )
    if progress:
        progress(f"Microsoft Store：已读取 {len(entries)} 个应用", 55)
    return entries


# --------------------------------------------------------------------------
# Steam
# --------------------------------------------------------------------------

_STEAM_KEYS = (
    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
)


def _steam_root() -> str:
    for root, path, value_name in _STEAM_KEYS:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                if value and os.path.isdir(value):
                    return os.path.normpath(value)
        except OSError:
            continue
    for probe in (
        os.path.expandvars(r"%ProgramFiles(x86)%\Steam"),
        os.path.expandvars(r"%ProgramFiles%\Steam"),
    ):
        if os.path.isdir(probe):
            return probe
    return ""


def _steam_libraries(root: str) -> list[str]:
    libraries = [root]
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        try:
            with open(vdf, "r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read()
            for match in re.finditer(r'"path"\s*"((?:[^"\\]|\\.)*)"', text):
                candidate = match.group(1).replace("\\\\", "\\")
                if os.path.isdir(candidate):
                    libraries.append(os.path.normpath(candidate))
        except OSError:
            pass
    seen: set[str] = set()
    unique = []
    for path in libraries:
        key = path.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def scan_steam(progress: Progress = None) -> list[AppEntry]:
    root = _steam_root()
    if not root:
        return []
    steam_exe = os.path.join(root, "steam.exe")
    if not os.path.isfile(steam_exe):
        return []
    entries: list[AppEntry] = []
    for library in _steam_libraries(root):
        steamapps = os.path.join(library, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        for filename in os.listdir(steamapps):
            if not (filename.startswith("appmanifest_") and filename.endswith(".acf")):
                continue
            path = os.path.join(steamapps, filename)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    text = handle.read()
            except OSError:
                continue
            name = _vdf_value(text, "name")
            appid = _vdf_value(text, "appid")
            installdir = _vdf_value(text, "installdir")
            state = _vdf_value(text, "StateFlags")
            if not name or not appid:
                continue
            if appid in {"228980"}:  # Steamworks Common Redistributables
                continue
            try:
                state_flag = int(state)
            except ValueError:
                state_flag = 4
            if state_flag & 4 == 0:
                continue
            icon = ""
            common = os.path.join(steamapps, "common", installdir)
            for candidate in _launch_candidates(common) if os.path.isdir(common) else []:
                icon = candidate
                break
            entries.append(
                AppEntry(
                    key=f"steam:{appid}",
                    name=clean_display_name(name),
                    publisher="Steam",
                    source="steam",
                    category="game",
                    confidence="high",
                    install_location=common,
                    icon_path=icon,
                    target=steam_exe,
                    arguments=f"-applaunch {appid}",
                    working_dir=root,
                )
            )
    if progress:
        progress(f"Steam：已读取 {len(entries)} 个已安装游戏", 70)
    return entries


def _vdf_value(text: str, key: str) -> str:
    match = re.search(rf'"{key}"\s*"((?:[^"\\]|\\.)*)"', text, re.IGNORECASE)
    return match.group(1) if match else ""


# --------------------------------------------------------------------------
# 自定义目录（绿色软件）
# --------------------------------------------------------------------------


def scan_folder(folder: str, progress: Progress = None) -> list[AppEntry]:
    if not folder or not os.path.isdir(folder):
        return []
    entries: list[AppEntry] = []
    skip_dirs = {"node_modules", "cache", "temp", "tmp", "logs", "docs", "doc", "help",
                 "locales", "plugins", "resources", "skins", "themes", "www", "data"}
    windir = normalize_path(os.environ.get("SystemRoot", r"C:\Windows"))
    count = 0
    for current, dirs, files in os.walk(folder):
        depth = os.path.relpath(current, folder).count(os.sep)
        if depth >= 2:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d.casefold() not in skip_dirs and not d.startswith(".")]
        for filename in files:
            if not filename.casefold().endswith(".exe"):
                continue
            if _SKIP_EXE_RE.search(filename):
                continue
            full = os.path.join(current, filename)
            if normalize_path(full).startswith(windir):
                continue
            count += 1
            if count > 400:
                break
            info = fileinfo.read_version_info(full)
            name = info.get("description") or info.get("product") or os.path.splitext(filename)[0]
            non_app, _ = is_non_app_entry(name)
            if non_app:
                continue
            entries.append(
                AppEntry(
                    key=f"dir:{normalize_path(full)}",
                    name=clean_display_name(name),
                    version=info.get("version", ""),
                    publisher=info.get("company", ""),
                    source="folder",
                    category="portable",
                    confidence="medium",
                    install_location=os.path.dirname(full),
                    icon_path=full,
                    target=full,
                    working_dir=os.path.dirname(full),
                )
            )
    if progress:
        progress(f"自定义目录：发现 {len(entries)} 个可执行程序", 78)
    return entries

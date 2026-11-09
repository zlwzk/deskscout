"""过滤、归一化与去重规则.

这里集中定义“什么算系统组件、什么算无效残留、什么算重复条目”，
扫描器只负责取数据，判断统一放在本模块，便于单独测试与调参。
"""

from __future__ import annotations

import os
import re
from typing import Iterable

from .models import AppEntry

# --------------------------------------------------------------------------
# 归一化
# --------------------------------------------------------------------------

_TRADEMARK_RE = re.compile(r"[®™©]")
_SCALE_SUFFIX_RE = re.compile(
    r"\s*\(\s*(user|machine|all users|当前用户|所有用户|仅当前用户)\s*\)\s*",
    re.IGNORECASE,
)
_SUFFIX_RE = re.compile(
    r"\s*[\(\[]\s*(x64|x86|64\s*-?\s*bit|32\s*-?\s*bit|64\s*[- ]?位|32\s*[- ]?位)\s*[\)\]]\s*$",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")
# 尾部版本号： "版本 1.2.3" / "Version 5.0" / "v1.2" / " (1.2.3)" / " 1.2.3"
_TRAILING_VERSION_RES = (
    re.compile(r"\s*(?:版本|version|ver\.?|v)\s*\d[\w.+\-]*\s*$", re.IGNORECASE),
    re.compile(r"\s*\(\s*\d[\d.]+\s*\)\s*$"),
    re.compile(r"\s+\d+\.\d[\w.+\-]*\s*$"),
)
# “Wallpaper Engine：壁纸引擎”这类中文别名后缀
_CN_ALIAS_RE = re.compile(r"\s*[：:]\s*[\u4e00-\u9fff][\u4e00-\u9fff\w·]*\s*$")

# 末尾的通用词，用于归并“XXX”与“XXX User Interface”
_GENERIC_SUFFIX_RE = re.compile(
    r"\s+(user interface|ui|launcher|client|tool|helper|updater|utility|"
    r"启动器|客户端|工具|辅助程序)\s*$",
    re.IGNORECASE,
)


def clean_display_name(name: str) -> str:
    """把“7-Zip 26.04 (x64)”“FlClash 版本 0.9.2”这类名字还原成干净的软件名."""
    if not name:
        return ""
    text = _TRADEMARK_RE.sub("", name)
    text = _SCALE_SUFFIX_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    for _ in range(4):
        changed = False
        for pattern in (_SUFFIX_RE, *_TRAILING_VERSION_RES):
            stripped = pattern.sub("", text).strip()
            if stripped and stripped != text:
                text, changed = stripped, True
                break
        if not changed:
            break
    if re.match(r"[A-Za-z0-9]", text):
        stripped = _CN_ALIAS_RE.sub("", text).strip()
        if stripped and stripped != text and len(stripped) >= 4:
            text = stripped
    # “XXX User Interface / Launcher / Tool” 这类后缀只保留主名称
    stripped = _GENERIC_SUFFIX_RE.sub("", text).strip()
    if stripped and len(stripped) >= 2:
        text = stripped
    return text.strip(" -_·") or name.strip().strip(" -_·")


def normalize_name(name: str) -> str:
    """用于比较的名称指纹：去版本号、位数后缀、商标符号与多余空格."""
    text = clean_display_name(name)
    text = _GENERIC_SUFFIX_RE.sub("", text).strip()
    return _SPACE_RE.sub(" ", text).strip().casefold()


def normalize_path(path: str) -> str:
    if not path:
        return ""
    text = path.strip().strip('"')
    text = os.path.expandvars(text)
    try:
        text = os.path.normpath(text)
    except (OSError, ValueError):
        pass
    return text.casefold()


def split_icon_path(value: str) -> tuple[str, str]:
    """把 DisplayIcon 拆成 (可执行/图标文件, 图标索引).

    DisplayIcon 常见形态: "C:\\App\\a.exe,0"、"C:\\App\\a.ico"、
    '"C:\\App\\a.exe",-1'。
    """
    if not value:
        return "", "0"
    text = value.strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        path = text[1:end] if end > 0 else text.strip('"')
        rest = text[end + 1 :] if end > 0 else ""
    else:
        path, rest = text, ""
        if "," in text:
            head, tail = text.rsplit(",", 1)
            if tail.strip().lstrip("-").isdigit():
                path, rest = head, tail
    index = rest.strip().lstrip(",").strip() or "0"
    if not index.lstrip("-").isdigit():
        index = "0"
    return path.strip().strip('"'), index


# --------------------------------------------------------------------------
# 系统组件识别
# --------------------------------------------------------------------------

_WINDIR = os.path.expandvars(r"%SystemRoot%")
_PROGRAMDATA = os.path.expandvars(r"%ProgramData%")

# 命中即视为系统组件/运行库/更新补丁： (正则, 原因)
SYSTEM_PATTERNS: list[tuple[str, str]] = [
    (r"^microsoft visual c\+\+", "VC++ 运行库"),
    (r"visual c\+\+.*(redistributable|runtime)", "VC++ 运行库"),
    (r"^microsoft \.net\b", ".NET 运行时"),
    (r"\.net\s*(framework|runtime|desktop runtime|targeting pack)", ".NET 运行时"),
    (r"\bwindows (software development kit|sdk)\b", "Windows SDK"),
    (r"\bwindows driver (kit|package)\b|\bwdk\b", "驱动开发包"),
    (r"\bwindows (assessment|performance toolkit|appcert|debugging tools)\b", "Windows 工具包"),
    (r"\bwindows performance (analyzer|recorder)\b|\bgpuview\b", "Windows 性能工具"),
    (r"\bwindows (feature|update|hotfix|service pack|update rollup)\b", "系统补丁"),
    (r"\bsecurity update\b|\bcumulative update\b|\bupdate for\b", "系统补丁"),
    (r"\bkb\d{6,}\b", "系统补丁"),
    (r"^microsoft edge\b", "Edge 浏览器（系统预装）"),
    (r"\bwebview2?\b", "WebView2 运行时"),
    (r"^directx\b", "DirectX"),
    (r"^visual studio (installer|locator|build tools)\b", "VS 安装器/生成工具"),
    (r"\bwindows desktop runtime\b", "Windows Desktop Runtime"),
    (r"\bwindows app (runtime|support)\b", "Windows App 运行时"),
    (r"^microsoft update\b|\bmicrosoft software update\b", "系统更新"),
    (r"^microsoft xbox (identity provider|gaming services|tcui)\b", "Xbox 系统组件"),
    (r"\b(xna|mdac|msxml|vbscript|cript)\b", "系统组件"),
    (r"^microsoft windows (desktop|driver|system)", "Windows 系统组件"),
    (r"^wsl$|^wsl settings$|^windows subsystem for linux", "Windows 子系统"),
    (r"games for windows", "系统预装游戏服务"),
    (r"\banticheat\b|反作弊", "游戏反作弊组件"),
    (r"\b系统补丁\b|\b更新程序\b|\b修复补丁\b", "系统补丁"),
]

_PUBLISHER_SYSTEM_HINTS = (
    "microsoft windows",
    "microsoft corporation",
    "microsoft®",
)

# 驱动包命名：厂商 - 类别 - 版本，例如 "Intel - System - 2023.1.0"
_DRIVER_NAME_RE = re.compile(
    r"^(intel|amd|nvidia|realtek|qualcomm|broadcom|microsoft|dell|hp|lenovo|asus|"
    r"synaptics|killer|rivet|oce|konica|canon|epson|brother|logitech|razer|corsair|"
    r"steelseries|mediatek|toshiba|samsung|western digital|sandisk|kingston|intel\(r\))"
    r"\s*-\s*(system|display|audio|media|net|network|bluetooth|chipset|input|usb|"
    r"storage|keyboard|mouse|printer|imaging|firmware|softwarecomponent)\s*-\s*",
    re.IGNORECASE,
)

_SYSTEM_FOLDER_HINTS = (
    normalize_path(os.path.join(_WINDIR, "system32")),
    normalize_path(os.path.join(_WINDIR, "syswow64")),
    normalize_path(os.path.join(_WINDIR, "winsxs")),
    normalize_path(os.path.join(_WINDIR, "systemapps")),
    normalize_path(os.path.join(_WINDIR, "servicing")),
    normalize_path(os.path.join(_WINDIR, "installer")),
    normalize_path(os.path.join(_WINDIR, "kits")),
    normalize_path(os.path.join(_PROGRAMDATA, "microsoft", "windows", "driverstore")),
    normalize_path(os.path.join(_PROGRAMDATA, "package cache")),
)


def is_system_component(
    *,
    name: str,
    publisher: str = "",
    install_location: str = "",
    uninstall_string: str = "",
    icon_path: str = "",
    release_type: str = "",
    parent_key: str = "",
    system_component: int = 0,
) -> tuple[bool, str]:
    """判断一条记录是否属于系统组件/运行库/补丁/驱动。返回 (是否系统, 原因)."""
    if system_component:
        return True, "标记为 SystemComponent"
    if parent_key:
        return True, "属于其他产品的补丁组件"
    if release_type and release_type.strip().casefold() in {
        "update",
        "hotfix",
        "security update",
        "servicepack",
        "update rollup",
        "driver",
    }:
        return True, f"更新/驱动类型（{release_type}）"

    low = (name or "").casefold()
    for pattern, reason in SYSTEM_PATTERNS:
        if re.search(pattern, low):
            return True, reason

    if _DRIVER_NAME_RE.match(name or ""):
        return True, "设备驱动包"

    # 安装/卸载路径落在系统目录
    for value in (install_location, uninstall_string, icon_path):
        npath = normalize_path(value)
        if not npath:
            continue
        for hint in _SYSTEM_FOLDER_HINTS:
            if hint and npath.startswith(hint):
                return True, "路径位于 Windows 系统目录"

    # 微软发行且明显是基础组件
    pub = (publisher or "").casefold()
    if pub in _PUBLISHER_SYSTEM_HINTS:
        if re.search(r"\b(runtime|redistributable|library|component|framework|sdk)\b", low):
            return True, "微软基础运行库"
    return False, ""


# 名称里带这些词的多为文档/网站/帮助，不是可启动软件
_EN_SKIP_RE = re.compile(
    r"\b(uninstall|read ?me|release ?notes|changelog|help|manual|documentation|docs|"
    r"faq|forum|website|support center|getting started|what'?s new|whats new|"
    r"license|licence|guide|tutorial|api reference|website)\b",
    re.IGNORECASE,
)
_CN_SKIP_RE = re.compile(
    r"(卸载|帮助|手册|说明文档|使用说明|文档|教程|官网|主页|论坛|常见问题|"
    r"更新日志|发行说明|新功能|许可|指南|参考手册|技术资料)"
)


def is_non_app_entry(name: str) -> tuple[bool, str]:
    if not name or not name.strip():
        return True, "名称为空"
    text = name.strip()
    if _EN_SKIP_RE.search(text) or _CN_SKIP_RE.search(text):
        return True, "文档/网站/帮助类条目"
    if re.fullmatch(r"[\W_]+", text):
        return True, "名称无有效字符"
    return False, ""


# 卸载器/安装器/更新器/崩溃上报器不是“主程序”
_BAD_TARGET_RE = re.compile(
    r"(unins|uninst|remove|setup|installer|update|upgrade|repair|crash|report|"
    r"helper|vcredist|dxsetup|oalinst|maintenan|activat|elevat|feedback|"
    r"diagnos|telemetry|launcher_uninstall)",
    re.IGNORECASE,
)
# 主程序之外的“边角”进程，评分时要降权
_HELPER_TARGET_RE = re.compile(
    r"(core|tray|service|daemon|helper|agent|worker|background|broker|updater|"
    r"crashpad|render|splash|toast)",
    re.IGNORECASE,
)

_LAUNCHABLE_EXTS = (".exe", ".com", ".bat", ".cmd", ".msi")
_ICON_EXTS = (".exe", ".ico", ".dll")


def is_bad_launch_target(path: str) -> bool:
    if not path:
        return True
    base = os.path.basename(path).casefold()
    return bool(_BAD_TARGET_RE.search(base))


def is_helper_target(path: str) -> bool:
    return bool(path) and bool(_HELPER_TARGET_RE.search(os.path.basename(path)))


def is_launchable_target(path: str) -> bool:
    """只有可执行文件算启动目标；.chm/.txt/.html/网址链接都不算软件."""
    if not path:
        return False
    lowered = path.strip().strip('"')
    if lowered.startswith(("http://", "https://", "shell:", "steam://")):
        return lowered.startswith("steam://")
    return lowered.casefold().endswith(_LAUNCHABLE_EXTS)


def is_web_target(path: str) -> bool:
    return bool(path) and path.strip().casefold().startswith(("http://", "https://"))


# --------------------------------------------------------------------------
# 去重合并
# --------------------------------------------------------------------------

_RANK_BY_SOURCE = {"registry": 3, "startmenu": 2, "store": 1, "steam": 2, "folder": 0}
_RANK_BY_CONFIDENCE = {"high": 3, "medium": 2, "low": 1}

_GENERIC_DIRS = {
    "program files",
    "program files (x86)",
    "windows",
    "users",
    "appdata",
    "local",
    "localappdata",
    "roaming",
    "programs",
    "common files",
    "desktop",
    "documents",
    "downloads",
}


def is_specific_install_dir(path: str) -> bool:
    """安装目录是否足够具体，可用于“同一个套件”的归并锚点."""
    if not path or not os.path.isdir(path):
        return False
    try:
        parts = [p for p in os.path.normpath(path).split(os.sep) if p]
    except (OSError, ValueError):
        return False
    if len(parts) < 3:
        return False
    return parts[-1].casefold() not in _GENERIC_DIRS


def _score(entry: AppEntry) -> tuple:
    return (
        1 if entry.launchable else 0,
        0 if is_helper_target(entry.target) else 1,
        _RANK_BY_SOURCE.get(entry.source, 0),
        _RANK_BY_CONFIDENCE.get(entry.confidence, 0),
        1 if entry.version else 0,
        1 if entry.publisher else 0,
        -len(entry.name),
    )


def dedupe(entries: Iterable[AppEntry]) -> tuple[list[AppEntry], int]:
    """按名称指纹去重，保留“更能启动”的那条；完全相同的 key 直接跳过.

    不按 target 去重：不同应用可能共用同一个启动器（如 Anaconda 里的
    pythonw.exe 会同时承载 Navigator 与 Spyder），按路径合并会误吞软件。
    """
    by_name: dict[str, AppEntry] = {}
    seen_keys: set[str] = set()
    merged = 0

    for entry in entries:
        if entry.key and entry.key in seen_keys:
            merged += 1
            continue
        seen_keys.add(entry.key)
        fingerprint = normalize_name(entry.name)
        if not fingerprint:
            continue
        if fingerprint in by_name:
            keep_new = _score(entry) > _score(by_name[fingerprint])
            if keep_new:
                loser = by_name[fingerprint]
                _carry_over(entry, loser)
                by_name[fingerprint] = entry
            else:
                _carry_over(by_name[fingerprint], entry)
            merged += 1
            continue
        by_name[fingerprint] = entry

    return list(by_name.values()), merged


def _carry_over(winner: AppEntry, loser: AppEntry) -> None:
    """合并时把落选条目里更有用的字段补给胜出条目."""
    if not winner.version and loser.version:
        winner.version = loser.version
    if not winner.publisher and loser.publisher:
        winner.publisher = loser.publisher
    if not winner.icon_path and loser.icon_path:
        winner.icon_path = loser.icon_path
    if not winner.install_location and loser.install_location:
        winner.install_location = loser.install_location
    if not winner.uninstall_string and loser.uninstall_string:
        winner.uninstall_string = loser.uninstall_string
    if not winner.target and loser.target:
        winner.target = loser.target
        winner.arguments = loser.arguments
        winner.working_dir = loser.working_dir
    if winner.size_bytes == 0 and loser.size_bytes:
        winner.size_bytes = loser.size_bytes
    if loser.invalid and not winner.invalid:
        if "目标已缺失" in loser.note and "目标已缺失" not in winner.note:
            winner.note = (winner.note + "；" if winner.note else "") + loser.note

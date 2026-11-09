"""便携软件库：把绿色软件目录当“库”来管，导出 portable.json 换机重建.

目录结构约定：库里每个一级子目录就是一个软件，子目录里找体积最大的 exe 当入口。
导出时记录相对路径，导入时只要求用户重新指定“新机器上的库根目录”。
"""

from __future__ import annotations

import datetime as dt
import json
import os

from .filters import normalize_name, normalize_path
from .models import AppEntry

_RUNTIME_NAMES = {
    "python.exe", "pythonw.exe", "node.exe", "java.exe", "javaw.exe", "unins000.exe",
    "uninstall.exe", "setup.exe", "update.exe", "updater.exe", "helper.exe",
}


def _pick_exe(folder: str) -> str:
    """在软件目录里挑一个最像“主程序”的 exe：优先体积大、名字含目录名."""
    best = ""
    best_score = -1
    folder_name = os.path.basename(folder).casefold()
    try:
        candidates = [item for item in os.scandir(folder)
                      if item.is_file(follow_symlinks=False) and item.name.casefold().endswith(".exe")]
    except OSError:
        candidates = []
    if not candidates:
        # 再看下一层（有些包是 bin\xxx.exe）
        try:
            children = list(os.scandir(folder)) if os.path.isdir(folder) else []
        except OSError:
            children = []
        for item in children:
            if not item.is_dir(follow_symlinks=False):
                continue
            try:
                candidates.extend([sub for sub in os.scandir(item.path)
                                   if sub.is_file(follow_symlinks=False)
                                   and sub.name.casefold().endswith(".exe")])
            except OSError:
                continue
    for candidate in candidates:
        lowered = candidate.name.casefold()
        if lowered in _RUNTIME_NAMES:
            continue
        try:
            size = candidate.stat(follow_symlinks=False).st_size
        except OSError:
            size = 0
        score = size
        stem = lowered[:-4]
        if folder_name and (folder_name in stem or stem in folder_name):
            score += 5_000_000
        if score > best_score:
            best_score = score
            best = candidate.path
    return best


def scan_root(root: str) -> list[dict]:
    """扫描一个库根目录，返回 [{name, rel, exe, folder}]."""
    items: list[dict] = []
    if not root or not os.path.isdir(root):
        return items
    try:
        children = [item for item in os.scandir(root) if item.is_dir(follow_symlinks=False)]
    except OSError:
        return items
    for child in children:
        exe = _pick_exe(child.path)
        if not exe:
            continue
        items.append({
            "name": child.name,
            "rel": os.path.relpath(child.path, root),
            "exe_rel": os.path.relpath(exe, root),
            "folder": child.path,
            "exe": exe,
        })
    items.sort(key=lambda item: item["name"].casefold())
    return items


def scan_roots(roots: list[str]) -> dict:
    payload = {
        "version": 1,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "roots": [],
    }
    for root in roots:
        items = scan_root(root)
        payload["roots"].append({
            "label": os.path.basename(root.rstrip("\\/")) or root,
            "path": root,
            "items": items,
        })
    return payload


def entries_from(payload: dict, root_override: str = "") -> list[AppEntry]:
    """把库导出内容还原成可创建快捷方式的 AppEntry 列表."""
    result: list[AppEntry] = []
    for root in payload.get("roots", []):
        base = root_override or root.get("path", "")
        for item in root.get("items", []):
            target = os.path.join(base, item.get("exe_rel") or os.path.join(item.get("rel", ""), "app.exe"))
            if not os.path.exists(target):
                continue
            folder = os.path.dirname(target)
            result.append(AppEntry(
                key=f"dir:{normalize_path(folder)}",
                name=item.get("name") or os.path.basename(folder),
                source="folder",
                category="portable",
                target=target,
                install_location=folder,
                icon_path=target,
                shortcut_name="",
                note="便携软件库",
            ))
    return result


def export_to(path: str, roots: list[str]) -> dict:
    payload = scan_roots(roots)
    payload["export_path"] = path
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    payload["count"] = sum(len(root.get("items", [])) for root in payload["roots"])
    return payload


def load_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def summary(payload: dict) -> str:
    total = sum(len(root.get("items", [])) for root in payload.get("roots", []))
    parts = [f"{root.get('label') or root.get('path')}（{len(root.get('items', []))}）"
             for root in payload.get("roots", [])]
    return f"共 {total} 个便携软件：" + "、".join(parts)


def name_key(item: dict) -> str:
    return normalize_name(item.get("name", ""))

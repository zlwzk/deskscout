"""扫描编排：汇总各来源、过滤、去重、与桌面现状比对."""

from __future__ import annotations

import os
import time
from typing import Callable

from .filters import dedupe, normalize_name, normalize_path
from .models import AppEntry, DesktopItem, ScanOptions, ScanReport
from .scanners import scan_folder, scan_registry, scan_start_menu, scan_steam, scan_store

Progress = Callable[[str, int], None] | None


def scan_all(
    options: ScanOptions,
    desktop_items: list[DesktopItem] | None = None,
    progress: Progress = None,
) -> ScanReport:
    started = time.perf_counter()
    report = ScanReport()
    collected: list[AppEntry] = []
    stats: dict[str, int] = {}

    def note(message: str, percent: int) -> None:
        if progress:
            progress(message, percent)

    if options.registry:
        note("正在扫描注册表卸载项…", 5)
        items = scan_registry(progress)
        stats["registry"] = len(items)
        collected.extend(items)

    if options.startmenu:
        note("正在扫描开始菜单…", 35)
        items = scan_start_menu(progress)
        stats["startmenu"] = len(items)
        collected.extend(items)

    if options.store:
        note("正在读取 Microsoft Store 应用…", 50)
        items = scan_store(progress)
        stats["store"] = len(items)
        collected.extend(items)

    if options.steam:
        note("正在读取 Steam 游戏库…", 68)
        items = scan_steam(progress)
        stats["steam"] = len(items)
        collected.extend(items)

    if options.folder and options.custom_folder:
        note("正在扫描自定义目录…", 76)
        items = scan_folder(options.custom_folder, progress)
        stats["folder"] = len(items)
        collected.extend(items)

    report.raw_count = len(collected)

    # 1) 系统组件过滤
    if not options.include_system:
        collected = [e for e in collected if e.category != "system"]

    # 2) 无启动目标/残留过滤
    if options.hide_targetless:
        collected = [e for e in collected if e.launchable]

    report.filtered_count = len(collected)

    # 3) 去重
    collected, merged = dedupe(collected)
    # 3.1) 同一个安装目录下的子工具（如 Git CMD / AutoCAD 参照管理器）归并到主程序
    collected, location_merged = merge_by_location(collected)
    report.merged_count = merged + location_merged
    report.entries = collected

    # 4) 与桌面已有快捷方式比对
    if desktop_items is not None:
        attach_shortcuts(collected, desktop_items)

    collected.sort(key=lambda e: (normalize_name(e.name), e.source))
    report.source_stats = stats
    report.elapsed_ms = int((time.perf_counter() - started) * 1000)
    note(f"扫描完成：{len(collected)} 个应用", 100)
    return report


def merge_by_location(entries: list[AppEntry]) -> tuple[list[AppEntry], int]:
    """把开始菜单里属于同一安装目录的子工具并入主程序，避免一个软件出现好几条."""
    from .filters import is_helper_target, is_specific_install_dir

    anchors: list[tuple[str, AppEntry]] = []
    runtime_names = {"python.exe", "pythonw.exe", "node.exe", "java.exe", "javaw.exe",
                     "ruby.exe", "perl.exe", "wsl.exe", "cmd.exe", "powershell.exe"}
    for entry in entries:
        if entry.source not in {"registry", "steam", "folder", "startmenu"}:
            continue
        if entry.source == "startmenu" and os.path.basename(entry.target).casefold() in runtime_names:
            continue
        location = entry.install_location
        if not is_specific_install_dir(location) and entry.target:
            location = os.path.dirname(entry.target)
        if is_specific_install_dir(location):
            anchors.append((normalize_path(location), entry))
    anchors.sort(key=lambda pair: len(pair[0]), reverse=True)

    merged = 0
    kept: list[AppEntry] = []
    for entry in entries:
        dropped = False
        if entry.source == "startmenu" and entry.target:
            target = normalize_path(entry.target)
            for location, anchor in anchors:
                if anchor is entry:
                    continue
                if target == normalize_path(anchor.target) or target.startswith(location + "\\"):
                    # 主程序指向的是托盘/核心进程时，用开始菜单的真实入口覆盖
                    if is_helper_target(anchor.target) or not anchor.launchable:
                        anchor.target = entry.target
                        anchor.arguments = entry.arguments
                        anchor.working_dir = entry.working_dir
                        anchor.category = entry.category or anchor.category
                    anchor.note = (
                        anchor.note + "；" if anchor.note and "包含子工具" not in anchor.note else anchor.note
                    )
                    if "包含子工具" not in anchor.note:
                        anchor.note = (anchor.note + "；" if anchor.note else "") + "包含子工具"
                    dropped = True
                    merged += 1
                    break
        if not dropped:
            kept.append(entry)
    return kept, merged


def attach_shortcuts(entries: list[AppEntry], desktop_items: list[DesktopItem]) -> None:
    """把桌面已有快捷方式挂到对应应用上，避免重复创建."""
    by_target: dict[str, DesktopItem] = {}
    by_name: dict[str, DesktopItem] = {}
    for item in desktop_items:
        if item.kind not in {"lnk", "url"}:
            continue
        if item.target and not item.is_shell_item:
            key = normalize_path(item.target)
            if key:
                by_target.setdefault(key, item)
        fingerprint = normalize_name(item.name)
        if fingerprint:
            by_name.setdefault(fingerprint, item)

    for entry in entries:
        item = None
        if entry.target and "AppsFolder" not in entry.arguments:
            item = by_target.get(normalize_path(entry.target))
        if item is None:
            item = by_name.get(normalize_name(entry.name))
            if item is not None and entry.category == "store" and not item.is_shell_item:
                item = None
        if item is not None and not item.broken:
            entry.shortcut_name = item.name
        elif item is not None and item.broken:
            entry.note = (entry.note + "；" if entry.note else "") + "桌面快捷方式已失效"


def find_duplicate_targets(desktop_items: list[DesktopItem]) -> list[DesktopItem]:
    """桌面指向同一目标的多份快捷方式，只保留第一条的 duplicate_of."""
    seen: dict[str, str] = {}
    for item in desktop_items:
        if item.kind not in {"lnk", "url"} or not item.target or item.is_shell_item:
            continue
        key = normalize_path(item.target)
        if not key:
            continue
        if key in seen:
            item.duplicate_of = seen[key]
        else:
            seen[key] = item.path
    return desktop_items


def summarize(entries: list[AppEntry]) -> dict:
    total = len(entries)
    with_shortcut = sum(1 for e in entries if e.has_shortcut)
    launchable = sum(1 for e in entries if e.launchable and not e.has_shortcut)
    invalid = sum(1 for e in entries if e.invalid)
    by_category: dict[str, int] = {}
    for entry in entries:
        by_category[entry.category] = by_category.get(entry.category, 0) + 1
    return {
        "total": total,
        "with_shortcut": with_shortcut,
        "pending": launchable,
        "invalid": invalid,
        "by_category": by_category,
        "desktop_free": None,
    }

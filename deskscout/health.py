"""软件体检：体积、最近使用、套件集中度.

数据来源都只读本机：
- 体积：安装目录有界遍历（限制文件数与耗时），结果按目录 mtime 缓存到 size_cache.json；
- 使用：优先解析 UserAssist（资源管理器记录的“程序运行次数/最后一次运行”），
  退而使用目标 exe 的访问时间；两者都没有就标记为“未记录”。
"""

from __future__ import annotations

import codecs
import datetime as dt
import json
import os
import time
import winreg

from . import config
from .filters import normalize_name

_CACHE_FILE = "size_cache.json"
_USERASSIST_GUIDS = (
    "{CEBFF5CD-ACE2-4F4F-9178-9926F41749EA}",   # 直接运行的程序
    "{F4E57C4B-2036-45F0-A9AB-443BCFE33D9F}",   # 通过快捷方式启动的程序
)
_userassist_cache: tuple[float, dict] = (0.0, {})


# ---------------------------------------------------------------- 体积


def _size_cache() -> dict:
    data = config.load_json(_CACHE_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_size_cache(cache: dict) -> None:
    config.save_json(_CACHE_FILE, cache)


def dir_size(path: str, budget: float = 2.0, max_files: int = 6000, cache: dict | None = None) -> int:
    """有界统计目录体积；结果按 (路径, 目录 mtime) 缓存，重复扫描几乎零成本."""
    if not path or not os.path.isdir(path):
        return 0
    try:
        stamp = int(os.stat(path).st_mtime_ns)
    except OSError:
        return 0
    key = f"{os.path.normcase(path)}|{stamp}"
    if cache is not None and key in cache:
        try:
            return int(cache[key])
        except (TypeError, ValueError):
            pass

    started = time.perf_counter()
    total = 0
    count = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                for item in iterator:
                    count += 1
                    if count > max_files or time.perf_counter() - started > budget:
                        stack.clear()
                        break
                    try:
                        if item.is_dir(follow_symlinks=False):
                            stack.append(item.path)
                        elif item.is_file(follow_symlinks=False):
                            total += item.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    if cache is not None:
        cache[key] = total
    return total


def measure_sizes(entries, progress=None, budget: float = 1.6) -> dict:
    """给有安装目录的条目算体积；返回 {entry.key: bytes}."""
    cache = _size_cache()
    sizes: dict[str, int] = {}
    total = len(entries)
    for index, entry in enumerate(entries):
        folder = entry.install_location
        if not folder and entry.target:
            folder = os.path.dirname(entry.target)
        if folder and os.path.isdir(folder):
            size = dir_size(folder, budget=budget, cache=cache)
        else:
            size = 0
        entry.size_bytes = size
        sizes[entry.key] = size
        if progress and total:
            progress(f"正在统计体积：{entry.name}", int((index + 1) / total * 100))
    _save_size_cache(cache)
    return sizes


# ---------------------------------------------------------------- 最近使用


def _filetime_to_iso(raw: int) -> str:
    try:
        seconds = raw / 10_000_000 - 11644473600
        moment = dt.datetime.fromtimestamp(seconds)
    except (OSError, OverflowError, ValueError):
        return ""
    if not (2000 <= moment.year <= dt.datetime.now().year + 1):
        return ""
    return moment.strftime("%Y-%m-%d %H:%M")


def _decode_value_name(name: str) -> str:
    try:
        return codecs.decode(name, "rot13")
    except (UnicodeDecodeError, ValueError):
        return name


def userassist_map(refresh: bool = False) -> dict:
    """{小写路径: {'count': n, 'last': iso}}，解析失败就当没有."""
    global _userassist_cache
    if not refresh and _userassist_cache[0] > 0 and time.time() - _userassist_cache[0] < 300:
        return _userassist_cache[1]
    result: dict[str, dict] = {}
    for guid in _USERASSIST_GUIDS:
        path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist\{guid}\Count"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            continue
        try:
            index = 0
            while True:
                try:
                    name, data, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if not isinstance(data, bytes) or len(data) < 16:
                    continue
                decoded = _decode_value_name(name)
                if not decoded or decoded.startswith("UEME_"):
                    continue
                count = 0
                if len(data) >= 8:
                    count = int.from_bytes(data[4:8], "little")
                last = ""
                for offset in (60, 8):
                    if len(data) >= offset + 8:
                        last = _filetime_to_iso(int.from_bytes(data[offset:offset + 8], "little"))
                        if last:
                            break
                if not last and not count:
                    continue
                entry = {"count": count, "last": last}
                for candidate in (decoded, decoded.split("{", 1)[-1]):
                    clean = candidate.strip()
                    if clean.casefold().endswith((".exe", ".msi")):
                        result.setdefault(os.path.normcase(clean), entry)
        finally:
            key.Close()
    _userassist_cache = (time.time(), result)
    return result


def usage_for_entry(entry, table: dict | None = None) -> tuple[str, str]:
    """返回 (ISO 时间, 来源)。来源是 userassist / atime / ''."""
    table = userassist_map() if table is None else table
    candidates = [entry.target]
    if entry.install_location:
        candidates.append(entry.install_location)
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.casefold().endswith(".exe"):
            hit = table.get(os.path.normcase(candidate))
            if hit and hit.get("last"):
                return hit["last"], "userassist"
    if entry.target and os.path.exists(entry.target):
        try:
            stamp = os.stat(entry.target).st_atime
        except OSError:
            stamp = 0
        if stamp:
            moment = dt.datetime.fromtimestamp(stamp)
            if 2000 <= moment.year <= dt.datetime.now().year + 1:
                return moment.strftime("%Y-%m-%d %H:%M"), "atime"
    return "", ""


def decorate_usage(entries) -> None:
    table = userassist_map()
    for entry in entries:
        entry.last_used, entry.usage_source = usage_for_entry(entry, table)


def days_since(iso: str) -> int | None:
    if not iso:
        return None
    try:
        moment = dt.datetime.strptime(iso, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return max(0, (dt.datetime.now() - moment).days)


# ---------------------------------------------------------------- 报告


def _fmt_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def human_size(size: int) -> str:
    return _fmt_size(size)


def build_report(entries, desktop_items=None, capacity=None, stale_days: int = 180) -> dict:
    """生成体检报告结构，UI 与 CLI 共用."""
    decorate_usage(entries)
    by_source: dict[str, int] = {}
    by_category: dict[str, int] = {}
    publishers: dict[str, list] = {}
    total_size = 0
    biggest = []
    never_opened = []
    stale = []
    for entry in entries:
        by_source[entry.source] = by_source.get(entry.source, 0) + 1
        by_category[entry.category] = by_category.get(entry.category, 0) + 1
        total_size += entry.size_bytes
        label = (entry.publisher or "").strip() or "未知发布者"
        if label.startswith("http"):
            label = label.rstrip("/").split("/")[-2] if label.count("/") >= 4 else label
        publishers.setdefault(label, []).append(entry)
        if entry.size_bytes:
            biggest.append(entry)
        age = days_since(entry.last_used)
        if age is None:
            if not entry.has_shortcut:
                never_opened.append(entry)
        elif age >= stale_days:
            stale.append(entry)
    biggest.sort(key=lambda e: e.size_bytes, reverse=True)
    suites = sorted(((name, items) for name, items in publishers.items() if len(items) >= 3),
                    key=lambda pair: len(pair[1]), reverse=True)

    desktop_report = {}
    if desktop_items:
        broken = [item for item in desktop_items if item.broken]
        duplicate = [item for item in desktop_items if item.duplicate_of]
        desktop_report = {
            "total": len(desktop_items),
            "broken": len(broken),
            "duplicate": len(duplicate),
        }
    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(entries),
        "total_size": total_size,
        "total_size_text": _fmt_size(total_size),
        "by_source": by_source,
        "by_category": by_category,
        "biggest": [(e.name, _fmt_size(e.size_bytes), e.size_bytes) for e in biggest[:10]],
        "never_opened": [(e.name, e.source_label) for e in never_opened[:12]],
        "never_opened_count": len(never_opened),
        "stale": [(e.name, days_since(e.last_used)) for e in stale[:12]],
        "stale_count": len(stale),
        "suites": [(name, [(e.name, e.version) for e in items]) for name, items in suites[:6]],
        "suite_count": len(suites),
        "desktop": desktop_report,
        "capacity": capacity or {},
    }


def report_text(report: dict) -> str:
    """纯文本版，供 CLI 与复制到剪贴板."""
    lines = [f"DeskScout 软件体检 · {report.get('generated_at', '')}", ""]
    lines.append(f"共 {report.get('total', 0)} 个应用，占用约 {report.get('total_size_text', '0 B')}")
    source_text = "、".join(f"{k} {v}" for k, v in report.get("by_source", {}).items())
    if source_text:
        lines.append(f"来源分布：{source_text}")
    desktop = report.get("desktop") or {}
    if desktop:
        lines.append(f"桌面图标 {desktop.get('total', 0)} 个，失效 {desktop.get('broken', 0)} 个，"
                     f"重复 {desktop.get('duplicate', 0)} 个")
    if report.get("biggest"):
        lines.append("")
        lines.append("体积前十：")
        for name, size_text, _size in report["biggest"]:
            lines.append(f"  {name} · {size_text}")
    if report.get("suites"):
        lines.append("")
        lines.append("同一发布者的套件：")
        for name, items in report["suites"]:
            lines.append(f"  {name} · {len(items)} 个（{'、'.join(i[0] for i in items[:6])}）")
    if report.get("never_opened_count"):
        lines.append("")
        names = "、".join(item[0] for item in report.get("never_opened", []))
        lines.append(f"几乎没有使用痕迹：{report['never_opened_count']} 个（{names}）")
    if report.get("stale_count"):
        lines.append(f"半年以上没打开：{report['stale_count']} 个")
    return "\n".join(lines)

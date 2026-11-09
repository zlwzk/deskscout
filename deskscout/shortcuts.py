"""快捷方式创建：命名清洗、重名避让、批量创建、结果统计."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Iterable

from . import com
from .filters import clean_display_name
from .models import AppEntry

INVALID_CHARS = '\\/:*?"<>|'
RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass
class CreateResult:
    created: list[str]
    skipped: list[str]
    failed: list[tuple[str, str]]

    @property
    def created_count(self) -> int:
        return len(self.created)


def sanitize_name(name: str, max_length: int = 60) -> str:
    text = clean_display_name(name or "未命名")
    for char in INVALID_CHARS:
        text = text.replace(char, " ")
    text = re.sub(r"[\x00-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if len(text) > max_length:
        text = text[:max_length].rstrip(" .")
    if text.casefold() in RESERVED_NAMES:
        text = f"{text} 应用"
    return text or "未命名应用"


def target_folder(base_dir: str, mode: str, folder_name: str) -> str:
    if mode == "folder":
        cleaned = sanitize_name(folder_name or "新建快捷方式", 40)
        return os.path.join(base_dir, cleaned)
    return base_dir


def _existing_names(folder: str) -> set[str]:
    try:
        return {os.path.splitext(entry.name)[0].casefold() for entry in os.scandir(folder)}
    except OSError:
        return set()


def unique_path(folder: str, name: str, taken: set[str]) -> str:
    stem = sanitize_name(name)
    candidate = stem
    index = 2
    while candidate.casefold() in taken or os.path.exists(os.path.join(folder, candidate + ".lnk")):
        candidate = f"{stem} ({index})"
        index += 1
        if index > 200:
            break
    taken.add(candidate.casefold())
    return os.path.join(folder, candidate + ".lnk")


def create_for_entries(
    entries: Iterable[AppEntry],
    folder: str,
    reserved_names: set[str] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> CreateResult:
    """批量创建快捷方式。folder 不存在会自动创建."""
    result = CreateResult([], [], [])
    os.makedirs(folder, exist_ok=True)
    taken = _existing_names(folder)
    if reserved_names:
        taken |= {name.casefold() for name in reserved_names}

    items = list(entries)
    total = len(items)
    for index, entry in enumerate(items, start=1):
        if progress:
            progress(index, total, entry.name)
        if not entry.target:
            result.skipped.append(f"{entry.name}（缺少启动目标）")
            continue
        link_path = unique_path(folder, entry.name, taken)
        if entry.target.casefold().startswith(("http://", "https://")):
            ok = com.create_url_shortcut(link_path[:-4] + ".url", entry.target)
            final = link_path[:-4] + ".url"
        else:
            icon = entry.icon_path or entry.target
            ok = com.create_shortcut(
                link_path=link_path,
                target=entry.target,
                arguments=entry.arguments,
                working_dir=entry.working_dir,
                icon=icon if os.path.exists(icon) else "",
                description=f"由 DeskScout 创建 · {clean_display_name(entry.name)}",
            )
            final = link_path
        if ok and os.path.exists(final):
            result.created.append(os.path.basename(final))
        else:
            result.failed.append((entry.name, "创建失败（可能没有写入权限）"))
    return result


def desktop_base_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop")


def plan_preview(entries: Iterable[AppEntry], folder: str, limit: int = 8) -> list[str]:
    """预演命名与重名避让，用于确认弹窗展示."""
    taken = _existing_names(folder)
    names: list[str] = []
    for entry in entries:
        path = unique_path(folder, entry.name, taken)
        names.append(os.path.basename(path))
        if len(names) >= limit:
            break
    return names

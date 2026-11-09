"""扫描历史：保存上一次结果，供 CLI --diff 与界面“本次变化”使用."""

from __future__ import annotations

import datetime as dt
import os

from . import config
from .filters import normalize_name

_FILE = "last_scan.json"


def _key(entry) -> str:
    return (entry.target or f"name:{normalize_name(entry.name)}").casefold()


def save(entries) -> dict:
    payload = {
        "ts": int(dt.datetime.now().timestamp()),
        "when": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "apps": [
            {
                "key": _key(entry),
                "name": entry.name,
                "version": entry.version,
                "source": entry.source,
                "target": entry.target,
                "install": entry.install_location,
            }
            for entry in entries
        ],
    }
    config.save_json(_FILE, payload)
    return payload


def load() -> dict:
    data = config.load_json(_FILE, {})
    return data if isinstance(data, dict) else {}


def diff(entries, previous: dict | None = None) -> dict:
    """与上次扫描对比：新增 / 消失 / 版本变化."""
    previous = previous if previous is not None else load()
    old = {item.get("key"): item for item in (previous or {}).get("apps", []) if item.get("key")}
    current = {_key(entry): entry for entry in entries}
    added = [entry.name for key, entry in current.items() if key not in old]
    removed = [item.get("name", "") for key, item in old.items() if key not in current]
    changed = []
    for key, entry in current.items():
        old_item = old.get(key)
        if not old_item:
            continue
        if (old_item.get("version") or "") != (entry.version or ""):
            changed.append({
                "name": entry.name,
                "from": old_item.get("version") or "",
                "to": entry.version or "",
            })
    return {
        "previous_at": (previous or {}).get("when", ""),
        "added": sorted(added, key=str.casefold),
        "removed": sorted(removed, key=str.casefold),
        "changed": changed,
        "first_run": not bool(old),
    }


def diff_text(result: dict) -> str:
    if result.get("first_run"):
        return "没有上一次扫描记录，本次已作为基线保存。"
    lines = [f"对比上一次扫描（{result.get('previous_at') or '未知时间'}）："]
    added = result.get("added") or []
    removed = result.get("removed") or []
    changed = result.get("changed") or []
    lines.append(f"新增 {len(added)} 个" + ("：" + "、".join(added[:20]) if added else ""))
    lines.append(f"消失 {len(removed)} 个" + ("：" + "、".join(removed[:20]) if removed else ""))
    if changed:
        detail = "、".join(f"{item['name']} {item['from']}→{item['to']}" for item in changed[:15])
        lines.append(f"版本变化 {len(changed)} 个：{detail}")
    return "\n".join(lines)


def age_text(payload: dict) -> str:
    stamp = int(payload.get("ts") or 0)
    if not stamp:
        return ""
    seconds = max(0, int(dt.datetime.now().timestamp()) - stamp)
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


def exists() -> bool:
    return os.path.exists(config.state_path(_FILE))

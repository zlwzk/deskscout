"""收藏夹与屏蔽名单（都保存在 config.json，随版本升级保留）.

收藏：即使软件被卸载，条目也留在收藏页，附带当时的发布者/项目地址/版本，
     方便日后重新下载；取消收藏后不再展示。
屏蔽：命中后扫描结果里不再出现，可随时解除。
"""

from __future__ import annotations

import datetime as dt

from .filters import normalize_name


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _lib(config: dict) -> dict:
    node = config.setdefault("library", {})
    node.setdefault("favorites", [])
    node.setdefault("blocklist", [])
    return node


def entry_key(entry) -> str:
    """稳定标识：优先目标路径，其次名称指纹."""
    target = (entry.target or "").strip()
    if target:
        return target.casefold()
    return f"name:{normalize_name(entry.name)}"


# ---------------------------------------------------------------- 收藏


def is_favorite(config: dict, entry) -> bool:
    key = entry_key(entry)
    return any(item.get("key") == key for item in _lib(config)["favorites"])


def add_favorite(config: dict, entry) -> bool:
    lib = _lib(config)
    key = entry_key(entry)
    if any(item.get("key") == key for item in lib["favorites"]):
        return False
    lib["favorites"].insert(0, {
        "key": key,
        "name": entry.name,
        "publisher": entry.publisher,
        "source_url": entry.source_url,
        "homepage": entry.homepage,
        "version": entry.version,
        "target": entry.target,
        "install": entry.install_location,
        "note": entry.note,
        "added": _now(),
        "last_seen": _now(),
    })
    return True


def remove_favorite(config: dict, key: str) -> bool:
    lib = _lib(config)
    before = len(lib["favorites"])
    lib["favorites"] = [item for item in lib["favorites"] if item.get("key") != key]
    return len(lib["favorites"]) != before


def sync_favorites(config: dict, entries) -> dict:
    """扫描后更新收藏：仍在的刷新信息，不在的标成“已卸载”但保留."""
    lib = _lib(config)
    by_key = {entry_key(entry): entry for entry in entries}
    by_name = {normalize_name(entry.name): entry for entry in entries}
    present = 0
    for record in lib["favorites"]:
        entry = by_key.get(record.get("key") or "")
        if entry is None:
            entry = by_name.get(normalize_name(record.get("name", "")))
        if entry is None:
            record["installed"] = False
            continue
        present += 1
        record["installed"] = True
        record["key"] = entry_key(entry)
        record["name"] = entry.name
        record["version"] = entry.version or record.get("version", "")
        record["publisher"] = entry.publisher or record.get("publisher", "")
        record["source_url"] = entry.source_url or record.get("source_url", "")
        record["homepage"] = entry.homepage or record.get("homepage", "")
        record["target"] = entry.target or record.get("target", "")
        record["install"] = entry.install_location or record.get("install", "")
        record["last_seen"] = _now()
    return {"total": len(lib["favorites"]), "installed": present}


def favorites(config: dict) -> list:
    return _lib(config)["favorites"]


# ---------------------------------------------------------------- 屏蔽


def block_key(entry) -> str:
    return entry_key(entry)


def is_blocked(config: dict, entry) -> bool:
    lib = _lib(config)
    key = block_key(entry)
    fingerprint = normalize_name(entry.name)
    for item in lib["blocklist"]:
        if item.get("key") == key:
            return True
        if fingerprint and item.get("fingerprint") == fingerprint:
            return True
    return False


def add_block(config: dict, entry, reason: str = "") -> bool:
    lib = _lib(config)
    if is_blocked(config, entry):
        return False
    lib["blocklist"].insert(0, {
        "key": block_key(entry),
        "fingerprint": normalize_name(entry.name),
        "name": entry.name,
        "publisher": entry.publisher,
        "target": entry.target,
        "reason": reason,
        "added": _now(),
    })
    return True


def remove_block(config: dict, key: str) -> bool:
    lib = _lib(config)
    before = len(lib["blocklist"])
    lib["blocklist"] = [item for item in lib["blocklist"] if item.get("key") != key]
    return len(lib["blocklist"]) != before


def blocklist(config: dict) -> list:
    return _lib(config)["blocklist"]


def filter_blocked(config: dict, entries) -> tuple[list, int]:
    """返回 (保留条目, 被屏蔽数量)."""
    if not _lib(config)["blocklist"]:
        return entries, 0
    kept = [entry for entry in entries if not is_blocked(config, entry)]
    return kept, len(entries) - len(kept)

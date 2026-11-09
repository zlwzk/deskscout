"""给每个软件找到“官方下载入口”，把重装变成一次点击.

三类来源：
- Microsoft Store 应用 → 商店搜索页（本机 Store 客户端直接接管）；
- 有官网地址（注册表 URLInfoAbout / 版本资源）→ 官网；
- 识别出 GitHub 项目 → Releases 页面。
"""

from __future__ import annotations

import os
import urllib.parse

from .provenance import repo_from_text


def _store_links(entry) -> list[tuple[str, str]]:
    query = urllib.parse.quote(entry.name)
    return [
        ("Microsoft Store", f"ms-windows-store://search/?query={query}"),
        ("商店网页版", f"https://apps.microsoft.com/search?query={query}"),
    ]


def _homepage(entry) -> str:
    for candidate in (getattr(entry, "homepage", ""), getattr(entry, "source_url", "")):
        text = (candidate or "").strip()
        if text.startswith("http://") or text.startswith("https://"):
            return text
    return ""


def links_for(entry) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    if entry.source == "store":
        links.extend(_store_links(entry))
    repo = repo_from_text(getattr(entry, "source_url", "") or "")
    if repo:
        links.append(("GitHub 项目", repo))
        links.append(("GitHub Releases", repo.rstrip("/") + "/releases/latest"))
    page = _homepage(entry)
    if page and not repo:
        links.append(("官方网站", page))
    if not links and entry.name:
        query = urllib.parse.quote(f"{entry.name} 官网 下载")
        links.append(("搜索引擎", f"https://www.bing.com/search?q={query}"))
    return links


def primary_link(entry) -> tuple[str, str] | None:
    links = links_for(entry)
    return links[0] if links else None


def open_link(url: str) -> bool:
    if not url:
        return False
    try:
        os.startfile(url)  # noqa: S606 - 只打开用户明确点击的链接
        return True
    except OSError:
        return False


def reinstall_hint(entry) -> str:
    """给收藏页/详情页用的一句话说明."""
    if entry.source == "store":
        return "商店应用：可在 Microsoft Store 的“库”里直接重装"
    link = primary_link(entry)
    if link:
        return f"重装入口：{link[0]}"
    return "没有记录到官方入口，可右键搜索"

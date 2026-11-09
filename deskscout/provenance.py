"""识别“这个软件是不是从 GitHub 下载的”，并把发布者写成项目地址.

判定只用本机线索，不联网、不上传任何数据，也不做“同名仓库”猜测：
1. NTFS 备用数据流 ``Zone.Identifier`` 里的 ReferrerUrl / HostUrl
   —— 从浏览器下载的 exe 会带上完整来源页，最可靠；
2. exe 版本资源里的 Comments / URLInfoAbout / CompanyName / LegalCopyright；
3. 注册表里的 URLInfoAbout / URLUpdateInfo；
4. 安装目录里其它 exe 的同名线索（压缩包解压后主程序丢掉 ADS 时兜底）。

识别不到就保持空发布者，宁可留空也不写错项目地址。
"""

from __future__ import annotations

import os
import re

GITHUB_RE = re.compile(
    r"github\.com\s*/\s*([A-Za-z0-9][A-Za-z0-9-]{0,38})\s*/\s*([A-Za-z0-9._-]{1,100})",
    re.IGNORECASE,
)

# github.com 下的功能页，不是仓库
_RESERVED_PATHS = {
    "features", "topics", "collections", "events", "sponsors", "about", "pricing",
    "login", "join", "marketplace", "apps", "search", "orgs", "users", "site",
    "security", "readme", "explore", "trending", "settings", "notifications",
    "new", "organizations", "enterprise", "team", "customer-stories", "solutions",
    "resources", "open-source", "github", "dashboard", "issues", "pulls", "codespaces",
    "copilot", "account", "sessions", "contact", "site-policy", "changelog", "docs",
}

_cache: dict[str, str] = {}


def normalize_repo(owner: str, repo: str) -> str:
    owner = owner.strip()
    repo = repo.strip().strip("/")
    repo = re.split(r"[?#]", repo, 1)[0]
    for suffix in (".git", ".zip", ".exe", ".msi"):
        if repo.casefold().endswith(suffix):
            repo = repo[: -len(suffix)]
    repo = repo.rstrip(".,;:)]}\"'")
    if not owner or not repo:
        return ""
    if owner.casefold() in _RESERVED_PATHS:
        return ""
    if repo.casefold() in _RESERVED_PATHS:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", repo):
        return ""
    return f"https://github.com/{owner}/{repo}"


def repo_from_text(text: str) -> str:
    if not text:
        return ""
    match = GITHUB_RE.search(text)
    if not match:
        return ""
    return normalize_repo(match.group(1), match.group(2))


def _zone_identifier(path: str) -> str:
    """读 NTFS 的 Zone.Identifier，拿到下载来源."""
    if not path:
        return ""
    zone = path + ":Zone.Identifier"
    try:
        with open(zone, "r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return ""
    referrer = ""
    host = ""
    for line in text.splitlines():
        item = line.strip()
        if item.casefold().startswith("referrerurl="):
            referrer = item.split("=", 1)[1]
        elif item.casefold().startswith("hosturl="):
            host = item.split("=", 1)[1]
    # 优先来源页（能看到 owner/repo），其次下载直链
    return repo_from_text(referrer) or repo_from_text(host)


def _version_url(path: str) -> str:
    from . import fileinfo

    values = fileinfo.read_strings(
        path, ("Comments", "URLInfoAbout", "CompanyName", "LegalCopyright", "ProductName")
    )
    for key in ("Comments", "URLInfoAbout", "CompanyName", "LegalCopyright", "ProductName"):
        url = repo_from_text(values.get(key, ""))
        if url:
            return url
    return ""


def url_for_file(path: str) -> str:
    """给一个 exe/安装文件返回 GitHub 仓库地址（可能为空）."""
    if not path or not os.path.isfile(path):
        return ""
    key = path.casefold()
    if key in _cache:
        return _cache[key]
    url = _zone_identifier(path) or _version_url(path)
    _cache[key] = url
    return url


def url_for_entry(entry) -> str:
    """按 目标 exe -> 图标文件 -> 安装目录内的 exe 的顺序探测."""
    candidates = []
    for value in (getattr(entry, "target", ""), getattr(entry, "icon_path", "")):
        if value:
            candidates.append(value.split(",", 1)[0].strip().strip('"'))
    for candidate in candidates:
        url = url_for_file(candidate)
        if url:
            return url

    install = getattr(entry, "install_location", "") or ""
    if install and os.path.isdir(install):
        try:
            entries = [e for e in os.scandir(install) if e.is_file() and e.name.casefold().endswith(".exe")]
        except OSError:
            entries = []
        entries.sort(key=lambda e: os.path.getsize(e.path) if os.path.exists(e.path) else 0, reverse=True)
        for item in entries[:8]:
            url = url_for_file(item.path)
            if url:
                return url
    return ""


def _apply(entry, url: str, existing: str) -> None:
    entry.source_url = url
    if existing.casefold() == url.casefold():
        return
    entry.publisher = url
    if existing:
        entry.note = (entry.note + "；" if entry.note else "") + f"原发布者：{existing}"
    else:
        entry.note = (entry.note + "；" if entry.note else "") + "发布者取自 GitHub 项目地址"


def enrich_publishers(entries) -> int:
    """给发布者为空的条目补 GitHub 项目地址；返回改动条数."""
    changed = 0
    for entry in entries:
        existing = (entry.publisher or "").strip()
        url = repo_from_text(existing)
        if not url and entry.category != "system":
            url = url_for_entry(entry)
        if url:
            _apply(entry, url, existing)
            changed += 1
    return changed

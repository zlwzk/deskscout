"""自动更新：查询 GitHub Release、下载新版、退出后替换自身."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from . import EXE_NAME, RELEASES_API, __version__

USER_AGENT = f"DeskScout/{__version__} (+https://github.com/zlwzk/deskscout)"
LAST_ERROR = ""


def parse_version(text: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", (text or "").lstrip("vV"))
    return tuple(int(n) for n in numbers[:4]) if numbers else (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _request(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def check_latest(timeout: float = 8.0) -> tuple[dict | None, str]:
    """返回 (版本信息, 错误信息)。网络不可用时 info 为 None."""
    global LAST_ERROR
    try:
        payload = json.loads(_request(RELEASES_API, timeout).decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError) as exc:
        LAST_ERROR = str(exc)
        return None, LAST_ERROR

    tag = str(payload.get("tag_name", "") or "")
    assets = payload.get("assets") or []
    asset_url, asset_name, asset_size = "", "", 0
    for asset in assets:
        name = str(asset.get("name", ""))
        if name.casefold() == EXE_NAME.casefold() or name.casefold().endswith(".exe"):
            asset_url = str(asset.get("browser_download_url", ""))
            asset_name = name
            asset_size = int(asset.get("size", 0) or 0)
            break
    info = {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "notes": str(payload.get("body", "") or ""),
        "html_url": str(payload.get("html_url", "")),
        "published_at": str(payload.get("published_at", "")),
        "asset_url": asset_url,
        "asset_name": asset_name or EXE_NAME,
        "asset_size": asset_size,
    }
    LAST_ERROR = ""
    return info, ""


def download_asset(info: dict, timeout: float = 120.0, progress=None) -> str | None:
    """下载 release 里的 exe 到临时目录，返回本地路径."""
    url = info.get("asset_url") or ""
    if not url:
        return None
    folder = os.path.join(tempfile.gettempdir(), "DeskScout_update")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, info.get("asset_name") or EXE_NAME)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response, open(target, "wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            read = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                read += len(chunk)
                if progress and total:
                    progress(min(99, int(read * 100 / total)))
        if progress:
            progress(100)
        expected = int(info.get("asset_size") or 0)
        if expected and os.path.getsize(target) != expected:
            return None
        return target
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


_BAT_TEMPLATE = """@echo off
chcp 65001 >nul
setlocal
set "TARGET={target}"
set "NEW={new}"
for /L %%i in (1,1,40) do (
  tasklist /FI "IMAGENAME eq {image}" 2>nul | find /I "{image}" >nul
  if errorlevel 1 goto replace
  timeout /t 1 /nobreak >nul
)
:replace
copy /Y "%NEW%" "%TARGET%" >nul
if errorlevel 1 goto fail
start "" "%TARGET%"
goto done
:fail
start "" "%TARGET%"
:done
del "%~f0"
"""


def launch_self_replace(new_exe: str) -> bool:
    """写一个延迟替换脚本并启动；仅打包后的 exe 可用."""
    if not getattr(sys, "frozen", False):
        return False
    if not new_exe or not os.path.exists(new_exe):
        return False
    target = os.path.abspath(sys.executable)
    image = os.path.basename(target)
    script_path = os.path.join(tempfile.gettempdir(), "deskscout_update.bat")
    content = _BAT_TEMPLATE.format(
        target=target.replace("%", "%%"),
        new=new_exe.replace("%", "%%"),
        image=image.replace("%", "%%"),
    )
    try:
        with open(script_path, "w", encoding="utf-8", newline="\r\n") as handle:
            handle.write(content)
        subprocess.Popen(
            ["cmd.exe", "/c", script_path],
            creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            close_fds=True,
        )
        return True
    except OSError:
        return False

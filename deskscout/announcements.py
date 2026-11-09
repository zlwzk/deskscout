"""应用内更新公告：正文随程序内置，离线也能看；同时可拉取远端 announcements.json.

config["update"]["inbox"] 保存用户收到过的公告，形成应用内“收件箱”；
config["update"]["last_seen_version"] 用来判断是否需要在升级后弹一次窗。
远端只做“兜底/追加”：程序内已有的版本永远以本地正文为准，不发新版也能推一条通知。
"""

from __future__ import annotations

import json
import urllib.request

ANNOUNCEMENTS: dict[str, str] = {
    "1.0.0": """DeskScout v1.0.0 · 桌面应用管家 首个正式版

新增
· 五路扫描：注册表三根、开始菜单、Microsoft Store、Steam、自定义目录
· 自动排除系统组件与运行库，保留 Microsoft Store 下载的应用
· 桌面容量检测：按屏幕分辨率算出可用格子，创建前先看还剩几格
· 一键补齐桌面快捷方式，已有快捷方式自动跳过
· 三种视图：已安装软件 / 桌面现状 / 设置
· 命令行模式：--scan / --json / --csv / --version
· 自动更新：读取 GitHub Release，下载后延迟替换并自动重启
· 开机自启、单实例互斥

修复
· 卸载器、更新器、帮助文档不会被误当成软件
· 同名不同软件不会按路径合并，只按名称指纹去重""",
    "1.1.0": """DeskScout v1.1.0 · 图标与扫描精度升级

修复
· 图标改为走 Windows Shell 的原生图像接口，软件显示自己的图标，不再出现白纸/文件图标
· Microsoft Store 应用（含没有开始菜单入口的）现在也能取到原始图标
· 商店应用清单补齐：包清单里有、开始菜单里没有的应用也会被扫到
· 主程序定位增强：DisplayIcon 不是 exe 时，继续查图标目录、卸载器目录与安装子目录

新增
· 更新公告收件箱：每次发版的说明随程序内置在软件里，随时能翻，离线也能看
· 升级后第一次启动弹一次更新说明，看过即记住版本号，之后不再重复弹出
· GitHub 来源识别：从下载来源、版本资源、注册表链接里认出开源项目，发布者自动写成项目地址
· 创建快捷方式去掉二次确认弹窗，直接按当前设置创建（可在设置里重新开启确认）
· 版本号分档：小更新只改修，功能新增升第二位，不兼容改动才动第一位

优化
· 扫描结果里新增「GitHub 项目」统计，发布者一栏直接可点开项目主页
· 快捷方式图标统一缓存成 ICO，桌面不会再出现通用文件图标
· 商店应用过滤更狠：shell 扩展、分享宿主、后台服务不再混进列表""",
    "1.2.0": """DeskScout v1.2.0 · 体检、守护与库管理

新增
· 软件体检卡片：装了多少、占多大、多久没打开、谁是同一家的套件，一张卡片看完
· 桌面布局守护：记录一次“理想桌面”，被新装软件挤乱后一键把图标位置原样还原
· 卸载残留清理：比对“注册表有、目录没了”和“目录还在、注册表没了”，默认只勾安全项，删注册表前自动导出 .reg 备份
· 便携软件库：绿色软件目录纳入库管理，导出 portable.json（相对路径），新机器一键重建全部快捷方式
· 开机自启四路管理：注册表 Run、启动文件夹、计划任务、服务一次列全，标明“近期新增/临时目录/脚本启动”，可禁用也可还原
· 图标统一风格：原图 / 圆角底 / 单色蒙版三选一，桌面看起来像一套系统
· 收藏夹：收藏的软件即使被卸载也保留名称、版本、官网与项目地址，方便重新下载；取消收藏即移出
· 屏蔽名单：不想看到的软件一键屏蔽，扫描结果里不再出现，随时可解除
· 应用下载入口：商店应用给商店搜索页，开源项目给 Releases，其余给官网，重装只差一次点击
· 桌面热力图：按最近使用时间给桌面图标标色，一眼看出哪些是长期没动过的僵尸快捷方式
· 公告云端化：程序内公告优先，远端 announcements.json 兜底，不发新版也能推通知
· CLI 增强：--scan --json 新增 --diff，对比上次扫描输出新增/消失的软件

优化
· 扫描阶段就应用屏蔽名单，被屏蔽的软件不再计入统计，也不再拖慢界面渲染
· 收藏、屏蔽、自启禁用记录、桌面快照全部落在 %APPDATA%\\DeskScout，配置改为原子写入并保留 config.json.bak
· 体积统计有缓存（按目录 mtime），第一次体检略慢，之后几乎零成本
· 公告只在版本变化时弹一次，关掉后进“公告收件箱”随时回看""",
}


def notes_for(version: str) -> str:
    return ANNOUNCEMENTS.get(version, "")


def title_for(version: str) -> str:
    return f"DeskScout v{version} 更新公告"


def _version_key(version: str):
    parts = []
    for piece in str(version).split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def latest_version() -> str:
    return max(ANNOUNCEMENTS, key=_version_key)


def fetch_remote(url: str, timeout: int = 8) -> list[dict]:
    """读取远端 announcements.json：支持数组或 {"announcements": [...]}。"""
    if not url:
        return []
    request = urllib.request.Request(url, headers={"User-Agent": "DeskScout"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        raw = response.read().decode("utf-8", "ignore")
    data = json.loads(raw)
    items = data.get("announcements", []) if isinstance(data, dict) else data
    result = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        version = str(item.get("version", "")).strip()
        if not version:
            continue
        notes = item.get("notes") or item.get("body") or ""
        result.append({
            "version": version,
            "title": item.get("title") or title_for(version),
            "date": item.get("date", ""),
            "notes": notes,
            "remote": True,
        })
    return result


def merge_inbox(config: dict, remote_items: list[dict]) -> list[str]:
    """把远端公告并入收件箱；返回本次新增的版本号列表（按新→旧）.

    内置正文先入档：收件箱既收远端推送，也当历史公告的离线存档。
    """
    update = config.setdefault("update", {})
    inbox = update.get("inbox") or []
    known = {str(item.get("version", "")) for item in inbox}
    for version in ANNOUNCEMENTS:
        if version in known:
            continue
        inbox.append({
            "version": version,
            "title": title_for(version),
            "date": "",
            "notes": ANNOUNCEMENTS[version],
            "remote": False,
        })
        known.add(version)
    added = []
    for item in remote_items:
        version = item.get("version", "")
        body = notes_for(version)
        if version in known:
            continue
        if not body:
            body = (item.get("notes") or "").strip()
        if not body:
            continue
        inbox.append({
            "version": version,
            "title": item.get("title") or title_for(version),
            "date": item.get("date", ""),
            "notes": body,
            "remote": bool(item.get("remote")),
        })
        known.add(version)
        added.append(version)
    update["inbox"] = sorted(inbox, key=lambda item: _version_key(str(item.get("version", ""))),
                             reverse=True)
    return added


MIRROR_TEMPLATE = "https://cdn.jsdelivr.net/gh/{repo}@{branch}/announcements.json"


def mirror_url(url: str) -> str:
    """把 raw.githubusercontent.com 地址换成 jsDelivr 镜像（国内更容易通）."""
    lowered = url.casefold()
    if "raw.githubusercontent.com" not in lowered:
        return ""
    try:
        tail = url.split("raw.githubusercontent.com/", 1)[1]
        parts = tail.split("/")
        owner, repo, branch = parts[0], parts[1], parts[2]
        path = "/".join(parts[3:])
    except (IndexError, ValueError):
        return ""
    if path.split("/")[-1] != "announcements.json":
        return ""
    return MIRROR_TEMPLATE.format(repo=f"{owner}/{repo}", branch=branch)


def sync(config: dict, timeout: int = 10) -> dict:
    """按设置拉一次远端公告；失败不抛异常，返回状态给界面显示."""
    update = config.setdefault("update", {})
    if not update.get("remote_enabled", True):
        return {"ok": False, "reason": "已在设置里关闭云端公告", "added": []}
    url = (update.get("remote_url") or "").strip()
    if not url:
        return {"ok": False, "reason": "没有配置远端地址", "added": []}
    candidates = [url]
    backup = mirror_url(url)
    if backup:
        candidates.append(backup)
    last_error = ""
    for candidate in candidates:
        try:
            items = fetch_remote(candidate, timeout=timeout)
        except (OSError, ValueError, TimeoutError) as exc:
            last_error = f"{candidate} → {exc}"
            continue
        if not items:
            last_error = f"{candidate} → 内容为空"
            continue
        added = merge_inbox(config, items)
        return {"ok": True, "reason": f"远端公告 {len(items)} 条", "added": added,
                "source": candidate}
    return {"ok": False, "reason": f"拉取失败：{last_error}", "added": []}


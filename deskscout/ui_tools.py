"""1.2.0 的各类工具对话框：体检、收藏、屏蔽、便携库、开机自启、桌面布局、残留清理.

这里只做界面，业务逻辑全部来自 health / library / portable / autostart / layout / cleanup，
主窗口（ui.DeskScoutApp）负责提供 cfg、entries、save_config() 与状态栏文案。
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import (announcements, autostart, cleanup, config, desktop, downloads, health,
               icons, layout, library, portable, shortcuts)
from .filters import normalize_name

CARD = "#ffffff"
SUBTLE = "#f6f8fc"
BORDER = "#e4e9f2"
TEXT = "#101828"
MUTED = "#667085"
ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
WARN = "#b54708"
DANGER = "#b42318"
OK = "#067647"
FONT = "Microsoft YaHei UI"
ROW_HEIGHT = 28


def _dialog(app, title: str, subtitle: str = "", size: str = "820x560"):
    win = tk.Toplevel(app)
    win.title(title)
    win.configure(bg=CARD)
    win.geometry(size)
    win.minsize(640, 420)
    win.transient(app)
    head = tk.Frame(win, bg=CARD)
    head.pack(fill="x", padx=16, pady=(14, 4))
    tk.Label(head, text=title, font=(FONT, 13, "bold"), bg=CARD, fg=TEXT).pack(anchor="w")
    if subtitle:
        tk.Label(head, text=subtitle, font=(FONT, 9), bg=CARD, fg=MUTED,
                 wraplength=760, justify="left").pack(anchor="w", pady=(3, 0))
    body = tk.Frame(win, bg=CARD)
    body.pack(fill="both", expand=True, padx=16, pady=8)
    footer = tk.Frame(win, bg=CARD)
    footer.pack(fill="x", padx=16, pady=(4, 14))
    return win, body, footer


def _tree(parent, columns: list[tuple[str, str, int]], height: int = 12):
    wrap = tk.Frame(parent, bg=CARD)
    wrap.pack(fill="both", expand=True)
    tree = ttk.Treeview(wrap, columns=[item[0] for item in columns], show="headings",
                        style="List.Treeview", selectmode="extended", height=height)
    for key, label, width in columns:
        tree.heading(key, text=label)
        tree.column(key, width=width, anchor="w", stretch=key in (columns[0][0], columns[-1][0]))
    scroll = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview,
                           style="List.Vertical.TScrollbar")
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    tree.tag_configure("odd", background=SUBTLE)
    tree.tag_configure("muted", foreground=MUTED)
    tree.tag_configure("warn", foreground=WARN)
    tree.tag_configure("danger", foreground=DANGER)
    tree.tag_configure("ok", foreground=OK)
    return tree


def _run_bg(app, work, done, interval: int = 150) -> None:
    """后台跑耗时任务，回到主线程再更新界面."""
    box: queue.Queue = queue.Queue()

    def runner() -> None:
        try:
            box.put(("ok", work()))
        except Exception as exc:  # 单个工具失败不该拖垮窗口
            box.put(("err", exc))

    threading.Thread(target=runner, daemon=True).start()

    def poll() -> None:
        try:
            status, payload = box.get_nowait()
        except queue.Empty:
            app.after(interval, poll)
            return
        done(status, payload)

    app.after(interval, poll)


# ------------------------------------------------------------------ 软件体检


def show_health(app) -> None:
    win, body, footer = _dialog(
        app, "软件体检报告",
        "按安装目录体积、最近打开时间与发布者套件统计；体积按目录 mtime 缓存，重复体检很快。",
        "840x620",
    )
    progress = tk.Label(body, text="正在统计体积…", font=(FONT, 9), bg=CARD, fg=MUTED)
    progress.pack(anchor="w")
    text = tk.Text(body, wrap="word", font=(FONT, 10), bg=SUBTLE, fg=TEXT, relief="flat",
                   padx=14, pady=12)
    text.pack(fill="both", expand=True, pady=(8, 0))
    text.insert("1.0", "正在读取使用记录与目录体积，请稍候…")
    text.configure(state="disabled")

    report_holder: dict = {}

    def work():
        health.measure_sizes(app.entries, budget=0.9)
        return health.build_report(app.entries, app.desktop_items, app.capacity)

    def done(status, payload):
        if status == "err":
            progress.configure(text=f"体检失败：{payload}", fg=DANGER)
            return
        report_holder["data"] = payload
        progress.configure(text=f"报告生成时间 {payload.get('generated_at', '')}", fg=MUTED)
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", health.report_text(payload))
        text.configure(state="disabled")
        app._set_status("体检完成")

    buttons = footer
    ttk.Button(buttons, text="重新统计", style="Ghost.TButton",
               command=lambda: (progress.configure(text="正在统计体积…", fg=MUTED),
                                _run_bg(app, work, done))).pack(side="left")
    ttk.Button(buttons, text="复制报告", style="Ghost.TButton",
               command=lambda: _copy(app, health.report_text(report_holder.get("data", {})))).pack(side="left", padx=8)
    ttk.Button(buttons, text="保存为 TXT", style="Ghost.TButton",
               command=lambda: _save_text(app, report_holder.get("data", {}))).pack(side="left")
    ttk.Button(buttons, text="关闭", style="Accent.TButton",
               command=win.destroy).pack(side="right")
    _run_bg(app, work, done)


def _copy(app, content: str) -> None:
    app.clipboard_clear()
    app.clipboard_append(content)
    app._set_status("已复制到剪贴板")


def _save_text(app, report: dict) -> None:
    if not report:
        return
    path = filedialog.asksaveasfilename(
        parent=app, title="保存体检报告", defaultextension=".txt",
        initialfile="DeskScout-体检报告.txt", filetypes=[("文本文件", "*.txt")],
    )
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(health.report_text(report))
        app._set_status(f"体检报告已保存：{path}")
    except OSError as exc:
        messagebox.showerror("保存失败", str(exc), parent=app)


# -------------------------------------------------------------------- 收藏夹


def show_favorites(app) -> None:
    win, body, footer = _dialog(
        app, "收藏夹",
        "收藏的软件即使被卸载也会保留名称、版本与下载入口；取消收藏后不再出现在这里。",
        "880x560",
    )
    tree = _tree(body, [("name", "名称", 210), ("version", "版本", 90),
                        ("state", "状态", 90), ("source", "下载入口", 300),
                        ("added", "收藏时间", 120)])
    records = library.favorites(app.cfg)

    def fill():
        tree.delete(*tree.get_children())
        for index, record in enumerate(library.favorites(app.cfg)):
            state = "已安装" if record.get("installed", True) else "已卸载"
            link = record.get("source_url") or record.get("homepage") or ""
            if not link:
                entry = _record_entry(record)
                first = downloads.primary_link(entry)
                link = first[1] if first else ""
            tree.insert("", "end", iid=str(index), tags=(("" if state == "已安装" else "warn"),),
                        values=(record.get("name", ""), record.get("version", ""), state,
                                link or "—", record.get("added", "")))

    fill()

    def selected_keys() -> list[str]:
        return [records[int(iid)]["key"] for iid in tree.selection() if iid.isdigit()
                and int(iid) < len(records)]

    def remove_selected():
        keys = selected_keys()
        if not keys:
            messagebox.showinfo("提示", "先在列表里选中要取消收藏的软件。", parent=win)
            return
        for key in keys:
            library.remove_favorite(app.cfg, key)
        app.save_config()
        fill()
        app._refresh_library_buttons()
        app._set_status(f"已取消收藏 {len(keys)} 个")

    def open_link():
        selection = tree.selection()
        if not selection:
            return
        record = records[int(selection[0])]
        entry = _record_entry(record)
        link = record.get("source_url") or record.get("homepage")
        if link:
            downloads.open_link(link)
            return
        first = downloads.primary_link(entry)
        if first:
            downloads.open_link(first[1])
        else:
            messagebox.showinfo("提示", "这条收藏没有记录下载入口。", parent=win)

    ttk.Button(footer, text="取消收藏", style="Ghost.TButton", command=remove_selected).pack(side="left")
    ttk.Button(footer, text="打开发布页 / 下载页", style="Ghost.TButton", command=open_link).pack(side="left", padx=8)
    ttk.Button(footer, text="关闭", style="Accent.TButton", command=win.destroy).pack(side="right")


def _record_entry(record: dict):
    from .models import AppEntry

    return AppEntry(
        key=record.get("key", ""), name=record.get("name", ""),
        version=record.get("version", ""), publisher=record.get("publisher", ""),
        source="store" if record.get("source") == "store" else "registry",
        source_url=record.get("source_url", ""), homepage=record.get("homepage", ""),
        target=record.get("target", ""),
    )


# ------------------------------------------------------------------ 屏蔽名单


def show_blocklist(app) -> None:
    win, body, footer = _dialog(
        app, "屏蔽名单",
        "屏蔽后，这些软件不会再出现在扫描结果里（随时可以解除）。",
        "820x520",
    )
    tree = _tree(body, [("name", "名称", 220), ("publisher", "发布者", 220),
                        ("reason", "备注", 180), ("added", "加入时间", 130)])
    records = library.blocklist(app.cfg)

    def fill():
        tree.delete(*tree.get_children())
        for index, record in enumerate(library.blocklist(app.cfg)):
            tree.insert("", "end", iid=str(index), tags=("muted",),
                        values=(record.get("name", ""), record.get("publisher", "") or "—",
                                record.get("reason", "") or "用户屏蔽", record.get("added", "")))

    fill()

    def unblock():
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("提示", "先选中要解除的软件。", parent=win)
            return
        for iid in selection:
            if iid.isdigit() and int(iid) < len(records):
                library.remove_block(app.cfg, records[int(iid)]["key"])
        app.save_config()
        fill()
        app._refresh_library_buttons()
        app.refresh_view()
        app._set_status("已解除屏蔽")

    def block_current():
        entries = app._selected_entries()
        if not entries:
            messagebox.showinfo("提示", "先在主界面选中要屏蔽的软件。", parent=win)
            return
        for entry in entries:
            library.add_block(app.cfg, entry, reason="从主界面屏蔽")
        app.save_config()
        fill()
        app._refresh_library_buttons()
        app.refresh_view()
        app._set_status(f"已屏蔽 {len(entries)} 个软件")

    ttk.Button(footer, text="解除屏蔽", style="Ghost.TButton", command=unblock).pack(side="left")
    ttk.Button(footer, text="屏蔽主界面选中项", style="Ghost.TButton", command=block_current).pack(side="left", padx=8)
    ttk.Button(footer, text="关闭", style="Accent.TButton", command=win.destroy).pack(side="right")


# ------------------------------------------------------------------- 便携库


def show_portable(app) -> None:
    win, body, footer = _dialog(
        app, "便携软件库",
        "把一个或多个绿色软件根目录纳入库管理；导出 portable.json（相对路径）后，"
        "换机器只需重新指定根目录即可一键重建全部快捷方式。",
        "860x560",
    )
    roots = app.cfg.setdefault("portable", {}).setdefault("roots", [])
    tree = _tree(body, [("path", "库根目录", 520), ("count", "识别到的软件", 120)])
    status = tk.Label(body, text="", font=(FONT, 9), bg=CARD, fg=MUTED)
    status.pack(anchor="w", pady=(6, 0))

    def fill():
        tree.delete(*tree.get_children())
        for index, root in enumerate(roots):
            items = portable.scan_root(root) if os.path.isdir(root) else []
            tree.insert("", "end", iid=str(index),
                        values=(root, f"{len(items)} 个" if os.path.isdir(root) else "目录不存在"))

    fill()

    def add_root():
        path = filedialog.askdirectory(parent=win, title="选择绿色软件根目录")
        if not path:
            return
        if path not in roots:
            roots.append(path)
        app.save_config()
        fill()

    def remove_root():
        for iid in tree.selection():
            if iid.isdigit() and int(iid) < len(roots):
                roots.pop(int(iid))
        app.save_config()
        fill()

    def export_json():
        path = filedialog.asksaveasfilename(
            parent=win, title="导出便携软件库", defaultextension=".json",
            initialfile="portable.json", filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            payload = portable.export_to(path, roots)
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=win)
            return
        app.cfg.setdefault("portable", {})["export_path"] = path
        app.cfg["portable"]["last_export"] = payload.get("generated_at", "")
        app.save_config()
        status.configure(text=f"已导出：{portable.summary(payload)}")

    def import_json():
        path = filedialog.askopenfilename(parent=win, title="选择 portable.json",
                                          filetypes=[("JSON", "*.json")])
        if not path:
            return
        payload = portable.load_file(path)
        if not payload.get("roots"):
            messagebox.showinfo("提示", "这个文件里没有可用的库记录。", parent=win)
            return
        base = filedialog.askdirectory(parent=win, title="新机器上对应的库根目录（可取消用原路径）")
        entries = portable.entries_from(payload, base)
        if not entries:
            messagebox.showinfo("提示", "没有找到可执行文件，请检查根目录是否选对。", parent=win)
            return
        folder = filedialog.askdirectory(parent=win, title="快捷方式放到哪个目录（取消=桌面）") \
            or shortcuts.desktop_base_dir()
        result = shortcuts.create_for_entries(entries, folder)
        status.configure(text=f"重建完成：成功 {result.created_count} 个，跳过 {len(result.skipped)} 个，"
                              f"失败 {len(result.failed)} 个")
        app._set_status(f"便携库重建：成功 {result.created_count} 个")

    ttk.Button(footer, text="添加目录", style="Ghost.TButton", command=add_root).pack(side="left")
    ttk.Button(footer, text="移除", style="Ghost.TButton", command=remove_root).pack(side="left", padx=8)
    ttk.Button(footer, text="扫描预览", style="Ghost.TButton", command=fill).pack(side="left")
    ttk.Button(footer, text="导出 portable.json", style="Accent.TButton", command=export_json).pack(side="left", padx=8)
    ttk.Button(footer, text="导入并重建快捷方式", style="Ghost.TButton", command=import_json).pack(side="left")
    ttk.Button(footer, text="关闭", style="Ghost.TButton", command=win.destroy).pack(side="right")


# ------------------------------------------------------------------ 开机自启

_KIND_LABEL = {"run": "注册表 Run", "startup": "启动文件夹", "task": "计划任务", "service": "服务"}


def show_autostart(app) -> None:
    win, body, footer = _dialog(
        app, "开机自启管理",
        "四路枚举：注册表 Run、启动文件夹、计划任务、服务。禁用会先备份，可随时还原；"
        "服务与部分计划任务需要管理员权限。",
        "980x600",
    )
    tree = _tree(body, [("kind", "类型", 100), ("name", "名称", 230),
                        ("state", "状态", 70), ("risk", "提示", 90), ("command", "命令", 420)])
    status = tk.Label(body, text="正在读取自启项…", font=(FONT, 9), bg=CARD, fg=MUTED)
    status.pack(anchor="w", pady=(6, 0))
    holder: dict = {"items": []}

    def render(items):
        holder["items"] = items
        tree.delete(*tree.get_children())
        for index, item in enumerate(items):
            tags = []
            if not item["enabled"]:
                tags.append("muted")
            if item["risk"]:
                tags.append("warn")
            tree.insert("", "end", iid=str(index), tags=tuple(tags),
                        values=(_KIND_LABEL.get(item["kind"], item["kind"]), item["name"],
                                "启用" if item["enabled"] else "已禁用", item["risk"] or "—",
                                item["command"] or "—"))
        summary = autostart.summary(items)
        status.configure(text=f"共 {summary['total']} 项，启用 {summary['enabled']} 项，"
                              f"其中 {summary['risky']} 项有风险提示")

    def load():
        _run_bg(app, autostart.list_all,
                lambda state, payload: render(payload) if state == "ok" else
                status.configure(text=f"读取失败：{payload}"))

    def selected() -> list[dict]:
        return [holder["items"][int(iid)] for iid in tree.selection()
                if iid.isdigit() and int(iid) < len(holder["items"])]

    def apply(enable: bool):
        items = selected()
        if not items:
            messagebox.showinfo("提示", "先选中要处理的条目。", parent=win)
            return
        if not enable and len(items) >= 1:
            if not messagebox.askyesno("确认禁用",
                                       f"将禁用 {len(items)} 项自启（已备份，可随时还原）。继续？",
                                       parent=win):
                return
        errors = []
        for item in items:
            ok, message = (autostart.enable if enable else autostart.disable)(item)
            if not ok:
                errors.append(f"{item['name']}：{message}")
        load()
        if errors:
            messagebox.showwarning("部分失败", "\n".join(errors[:6]), parent=win)
        app._set_status(("已启用" if enable else "已禁用") + f" {len(items) - len(errors)} 项自启")

    load()

    ttk.Button(footer, text="禁用选中", style="Ghost.TButton",
               command=lambda: apply(False)).pack(side="left")
    ttk.Button(footer, text="启用 / 还原选中", style="Ghost.TButton",
               command=lambda: apply(True)).pack(side="left", padx=8)
    ttk.Button(footer, text="刷新", style="Ghost.TButton",
               command=load).pack(side="left")
    ttk.Button(footer, text="关闭", style="Accent.TButton", command=win.destroy).pack(side="right")


# ---------------------------------------------------------------- 桌面布局


def show_layout(app) -> None:
    win, body, footer = _dialog(
        app, "桌面布局守护",
        "把当前图标位置存成快照；被新装软件挤乱后一键把坐标原样写回（读取的是 "
        "Shell\\Bags 里 Windows 自己存的那份数据）。",
        "760x520",
    )
    info = tk.Label(body, text="", font=(FONT, 9), bg=CARD, fg=MUTED, justify="left",
                    anchor="w", wraplength=700)
    info.pack(anchor="w")

    def refresh():
        snapshot = layout.load_snapshot()
        if not snapshot:
            info.configure(text="还没有快照。点“记录当前布局”保存一份理想桌面。")
            return
        compare = layout.compare(snapshot)
        info.configure(
            text=(f"快照时间：{snapshot.get('captured_at', '')}\n"
                  f"当时桌面图标：{snapshot.get('item_count', 0)} 个 · "
                  f"屏幕 {snapshot.get('screen', ['?', '?'])[0]}×{snapshot.get('screen', ['?', '?'])[1]}\n"
                  f"当前状态：新增位置 {compare['added']} 个、消失 {compare['removed']} 个、"
                  f"移动 {compare['changed']} 个"
                  + ("（与快照不一致）" if compare["drift"] else "（与快照一致）"))
        )

    refresh()

    def capture():
        try:
            snapshot = layout.capture(app.desktop_items)
            app.cfg.setdefault("desktop", {})["snapshot_at"] = snapshot["captured_at"]
            app.save_config()
        except OSError as exc:
            messagebox.showerror("记录失败", str(exc), parent=win)
            return
        refresh()
        app._set_status("桌面布局已记录")

    def restore():
        snapshot = layout.load_snapshot()
        if not snapshot:
            messagebox.showinfo("提示", "还没有可还原的快照。", parent=win)
            return
        if not messagebox.askyesno("确认还原", "把图标位置还原到快照时的状态？\n"
                                               "还原后建议点“重启资源管理器”让桌面立即刷新。",
                                   parent=win):
            return
        result = layout.restore(snapshot)
        message = f"已写回 {result['values']} 个位置值（{result['bags']} 组）。"
        if result["errors"]:
            message += "\n\n" + "\n".join(result["errors"][:4])
        messagebox.showinfo("还原完成", message, parent=win)
        refresh()

    def restart():
        if not messagebox.askyesno("重启资源管理器",
                                   "桌面会闪一下，已打开的窗口和程序不受影响。继续？", parent=win):
            return
        ok = layout.restart_explorer()
        app._set_status("资源管理器已重启" if ok else "重启资源管理器失败")

    ttk.Button(footer, text="记录当前布局", style="Accent.TButton", command=capture).pack(side="left")
    ttk.Button(footer, text="一键还原", style="Ghost.TButton", command=restore).pack(side="left", padx=8)
    ttk.Button(footer, text="对比", style="Ghost.TButton", command=refresh).pack(side="left")
    ttk.Button(footer, text="重启资源管理器", style="Ghost.TButton", command=restart).pack(side="left", padx=8)
    ttk.Button(footer, text="关闭", style="Ghost.TButton", command=win.destroy).pack(side="right")


# ---------------------------------------------------------------- 残留清理


def show_cleanup(app) -> None:
    win, body, footer = _dialog(
        app, "卸载残留清理",
        "比对“注册表有、目录没了”和“目录还在、注册表没了”。删除注册表前会自动导出 .reg 备份，"
        "目录删除走回收站；默认只勾选安全项。",
        "960x600",
    )
    tree = _tree(body, [("kind", "类型", 90), ("name", "名称", 220),
                        ("detail", "说明", 480), ("size", "体积", 90), ("safe", "安全", 70)])
    status = tk.Label(body, text="正在比对注册表与安装目录…", font=(FONT, 9), bg=CARD, fg=MUTED)
    status.pack(anchor="w", pady=(6, 0))
    holder: dict = {"items": []}

    def render(items):
        holder["items"] = items
        tree.delete(*tree.get_children())
        for index, item in enumerate(items):
            tags = ("ok" if item["safe"] else "warn",)
            tree.insert("", "end", iid=str(index), tags=tags,
                        values=("注册表" if item["kind"] == "registry" else "目录",
                                item["name"], item["detail"],
                                health.human_size(item["size"]) if item["size"] else "—",
                                "安全" if item["safe"] else "需确认"))
        status.configure(text=f"共发现 {len(items)} 项残留，其中安全项 "
                              f"{sum(1 for item in items if item['safe'])} 项")
        select_safe()

    def load():
        _run_bg(app, lambda: cleanup.scan(app.entries),
                lambda state, payload: render(payload) if state == "ok" else
                status.configure(text=f"扫描失败：{payload}"))

    def select_safe():
        tree.selection_remove(*tree.selection())
        for index, item in enumerate(holder["items"]):
            if item["safe"]:
                tree.selection_add(str(index))

    def run_cleanup():
        items = [holder["items"][int(iid)] for iid in tree.selection()
                 if iid.isdigit() and int(iid) < len(holder["items"])]
        if not items:
            messagebox.showinfo("提示", "先选中要清理的条目（可点“只选安全项”）。", parent=win)
            return
        if not messagebox.askyesno("确认清理",
                                   f"将清理 {len(items)} 项：注册表 {sum(1 for i in items if i['kind'] == 'registry')} 项、"
                                   f"目录 {sum(1 for i in items if i['kind'] == 'dir')} 项。\n"
                                   "注册表会先导出备份，目录会进回收站。继续？", parent=win):
            return
        result = cleanup.execute(items)
        message = (f"已删除注册表项 {result['registry_removed']} 个、目录 {result['dirs_removed']} 个。")
        if result["backup"]:
            message += f"\n备份：{result['backup']}"
        if result["errors"]:
            message += "\n\n" + "\n".join(result["errors"][:5])
        messagebox.showinfo("清理完成", message, parent=win)
        load()
        app._set_status("残留清理完成")

    load()

    ttk.Button(footer, text="只选安全项", style="Ghost.TButton", command=select_safe).pack(side="left")
    ttk.Button(footer, text="重新扫描", style="Ghost.TButton", command=load).pack(side="left", padx=8)
    ttk.Button(footer, text="清理选中", style="Accent.TButton", command=run_cleanup).pack(side="left")
    ttk.Button(footer, text="关闭", style="Ghost.TButton", command=win.destroy).pack(side="right")


# ------------------------------------------------------------------ 图标风格


def show_icon_style(app) -> None:
    win, body, footer = _dialog(
        app, "图标统一风格",
        "只影响 DeskScout 自己的列表、桌面快捷方式图标与新建快捷方式，不改动原软件文件。",
        "560x300",
    )
    style_var = tk.StringVar(value=icons.icon_style())
    descriptions = {
        "native": "原图：直接用软件自己的图标（默认）",
        "rounded": "圆角底：统一白底圆角卡片，风格割裂的软件也能排整齐",
        "mono": "单色蒙版：统一染成品牌蓝，像一套系统",
    }
    for value, text in descriptions.items():
        ttk.Radiobutton(body, text=text, value=value, variable=style_var,
                        style="Card.TRadiobutton").pack(anchor="w", pady=4)

    def apply_style():
        style = icons.set_icon_style(style_var.get())
        app.cfg.setdefault("appearance", {})["icon_style"] = style
        app.save_config()
        app.refresh_view()
        app._set_status(f"图标风格：{style}")
        win.destroy()

    ttk.Button(footer, text="应用", style="Accent.TButton", command=apply_style).pack(side="right")


# ------------------------------------------------------------------ 公告同步


def sync_announcements(app, silent: bool = False) -> None:
    cfg = app.cfg

    def work():
        return announcements.sync(cfg, timeout=8)

    def done(status, payload):
        if status == "err":
            if not silent:
                messagebox.showwarning("同步失败", str(payload), parent=app)
            return
        app.save_config()
        app._update_inbox_button()
        if payload.get("added"):
            app._set_status("收到新公告：" + "、".join(payload["added"]))
        elif not silent:
            app._set_status(payload.get("reason", "没有新公告"))

    _run_bg(app, work, done)


def refresh_library_counts(app) -> None:
    favorites = len(library.favorites(app.cfg))
    blocks = len(library.blocklist(app.cfg))
    app.fav_button.configure(text=f"收藏夹（{favorites}）")
    app.block_button.configure(text=f"屏蔽名单（{blocks}）")

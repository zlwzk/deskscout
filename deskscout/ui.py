"""DeskScout 图形界面（Tkinter / ttk）."""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from . import (
    APP_NAME_CN, HOMEPAGE, __version__, announcements, config, desktop, engine,
    icons, shortcuts, updater,
)
from .filters import clean_display_name, normalize_name
from .models import AppEntry, ScanOptions

BG = "#f3f5fa"
CARD = "#ffffff"
SUBTLE = "#f8fafc"
TEXT = "#1f2430"
MUTED = "#6b7280"
ACCENT = "#2f6feb"
ACCENT_DARK = "#2358c8"
BORDER = "#e2e6ef"
OK_GREEN = "#12805c"
WARN_ORANGE = "#b45309"
DANGER_RED = "#b42318"
FONT = "Microsoft YaHei UI"

SOURCE_CHOICES = ["全部来源", "注册表", "开始菜单", "Microsoft Store", "Steam 游戏", "自定义目录"]
CATEGORY_CHOICES = ["全部类型", "用户软件", "商店应用", "游戏", "绿色软件", "系统组件"]


class DeskScoutApp(tk.Tk):
    def __init__(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        super().__init__()

        self.cfg = config.load()
        self.entries: list[AppEntry] = []
        self.desktop_items = []
        self.capacity: dict = {}
        self.row_map: dict[str, AppEntry] = {}
        self.queue: queue.Queue = queue.Queue()
        self._icon_queue: queue.Queue = queue.Queue()
        self._icon_photos: dict[str, object] = {}
        self._icon_gen = 0
        self.scanning = False
        self.creating = False
        self.sort_column = "name"
        self.sort_reverse = False
        self.update_info: dict | None = None
        self._search_placeholder = True
        self._detail_entry: AppEntry | None = None
        self._ui_ready = False

        self.title(f"{APP_NAME_CN} DeskScout {__version__}")
        self.geometry(self.cfg["ui"].get("geometry", "1180x780"))
        self.minsize(1040, 700)
        self.configure(bg=BG)
        self._set_icon()
        self._build_styles()
        self._build_header()
        self._build_statusbar()
        self._build_tabs()
        self._build_banner()
        self._apply_settings_to_ui()
        self._ui_ready = True
        self.after(120, self.focus_set)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-f>", self._focus_search)
        self.bind("<F5>", lambda _event: self.start_scan())
        self.after(80, self._drain_queue)
        self.after(900, self._auto_update_check)
        self.after(1500, self._startup_announcement)
        if self.cfg["ui"].get("auto_scan_on_start", True):
            self.after(150, self.start_scan)
        else:
            self._set_status("就绪 · 点击「重新扫描」开始")
            self.refresh_desktop()

    # ------------------------------------------------------------------ 样式
    def _set_icon(self) -> None:
        try:
            icon = icons.load_app_icon(64)
            if icon is not None:
                self.iconphoto(True, icon)
        except tk.TkError:
            pass

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TkError:
            pass
        style.configure(".", background=BG, foreground=TEXT, font=(FONT, 10))
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=(FONT, 10))
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
        style.configure("Section.TLabelframe", background=CARD, bordercolor=BORDER, relief="solid")
        style.configure("Section.TLabelframe.Label", background=CARD, foreground=TEXT,
                        font=(FONT, 10, "bold"))
        style.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, font=(FONT, 10))
        style.map("Card.TCheckbutton", background=[("active", CARD)])
        style.configure("Card.TRadiobutton", background=CARD, foreground=TEXT, font=(FONT, 10))
        style.map("Card.TRadiobutton", background=[("active", CARD)])
        style.configure("App.TNotebook", background=BG, borderwidth=0, tabmargins=(8, 6, 8, 0))
        style.configure("App.TNotebook.Tab", background="#e8ecf5", foreground=TEXT,
                        padding=(18, 8), font=(FONT, 10))
        style.map("App.TNotebook.Tab",
                  background=[("selected", CARD), ("active", "#dde4f2")],
                  foreground=[("selected", ACCENT_DARK)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        font=(FONT, 10, "bold"), borderwidth=0, focusthickness=0, padding=(14, 7))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_DARK), ("disabled", "#a9c0ee")],
                  foreground=[("disabled", "#f0f4ff")])
        style.configure("Ghost.TButton", background=CARD, foreground=TEXT, borderwidth=1,
                        bordercolor=BORDER, padding=(12, 6), font=(FONT, 10))
        style.map("Ghost.TButton", background=[("active", "#eef2fb")])
        style.configure("List.Treeview", background=CARD, fieldbackground=CARD,
                        foreground=TEXT, rowheight=34, borderwidth=0, font=(FONT, 9))
        style.configure("List.Treeview.Heading", background="#eef1f8", foreground=TEXT,
                        font=(FONT, 9, "bold"), relief="flat", padding=(6, 6))
        style.map("List.Treeview", background=[("selected", "#dbe6ff")],
                  foreground=[("selected", TEXT)])
        style.map("List.Treeview.Heading", background=[("active", "#e4e9f6")])
        style.configure("List.Vertical.TScrollbar", background="#dfe4ee", troughcolor=CARD,
                        borderwidth=0, arrowsize=12)
        style.configure("Usage.Horizontal.TProgressbar", background=ACCENT, troughcolor="#e8ecf5",
                        borderwidth=0, thickness=8)
        style.configure("Search.TEntry", fieldbackground=SUBTLE, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, padding=(8, 6))
        style.configure("Filter.TCombobox", fieldbackground=SUBTLE, background=SUBTLE,
                        bordercolor=BORDER, arrowcolor=MUTED, padding=(6, 5))
        style.map("Filter.TCombobox", fieldbackground=[("readonly", SUBTLE)])

    # ------------------------------------------------------------------ 布局
    def _build_header(self) -> None:
        header = tk.Frame(self, bg=CARD, height=86)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=CARD)
        left.pack(side="left", padx=20, pady=14)
        tk.Label(left, text=APP_NAME_CN, font=(FONT, 18, "bold"), bg=CARD, fg=TEXT).pack(anchor="w")
        tk.Label(
            left,
            text=f"DeskScout {__version__} · 扫描已安装软件，安全补齐桌面快捷方式",
            font=(FONT, 9),
            bg=CARD,
            fg=MUTED,
        ).pack(anchor="w", pady=(4, 0))

        right = tk.Frame(header, bg=CARD)
        right.pack(side="right", padx=20, pady=16)
        self.status_pill = tk.Label(
            right, text="就绪", font=(FONT, 9), bg="#eef2fb", fg=ACCENT_DARK, padx=12, pady=6
        )
        self.status_pill.pack(side="left", padx=(0, 12))
        self.update_button = ttk.Button(right, text="检查更新", style="Ghost.TButton",
                                        command=lambda: self.check_update(manual=True))
        self.update_button.pack(side="left", padx=(0, 8))
        self.scan_button = ttk.Button(right, text="重新扫描 (F5)", style="Accent.TButton",
                                      command=self.start_scan)
        self.scan_button.pack(side="left")

    def _build_banner(self) -> None:
        self.banner = tk.Frame(self, bg="#eaf1ff")
        self.banner_label = tk.Label(self.banner, text="", font=(FONT, 9), bg="#eaf1ff", fg=ACCENT_DARK)
        self.banner_label.pack(side="left", padx=20, pady=7)
        self.banner_button = ttk.Button(self.banner, text="查看新版本", style="Ghost.TButton",
                                        command=self._open_update_dialog)
        self.banner_button.pack(side="right", padx=16, pady=5)
        self.banner_visible = False

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self, bg=CARD, height=36, highlightthickness=1, highlightbackground=BORDER)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status_text = tk.Label(bar, text="就绪", font=(FONT, 9), bg=CARD, fg=MUTED)
        self.status_text.pack(side="left", padx=16)
        self.progress = ttk.Progressbar(bar, style="Usage.Horizontal.TProgressbar",
                                        mode="determinate", length=150, maximum=100)
        self.capacity_label = tk.Label(bar, text="", font=(FONT, 9), bg=CARD, fg=MUTED)
        self.capacity_label.pack(side="right", padx=16)
        self.project_link = tk.Label(bar, text="GitHub 项目主页", font=(FONT, 9), bg=CARD,
                                     fg=ACCENT, cursor="hand2")
        self.project_link.pack(side="right", padx=(0, 14))
        self.project_link.bind("<Button-1>", lambda _event: webbrowser.open(HOMEPAGE))

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self, style="App.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(10, 6))
        self._build_apps_tab()
        self._build_desktop_tab()
        self._build_settings_tab()

    # ------------------------------------------------------------- 已安装软件
    def _build_apps_tab(self) -> None:
        tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=14)
        self.notebook.add(tab, text="  已安装软件  ")

        filters = tk.Frame(tab, bg=CARD)
        filters.pack(fill="x", pady=(0, 10))

        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filters, textvariable=self.search_var, width=30,
                                      style="Search.TEntry")
        self.search_entry.pack(side="left")
        self.search_entry.insert(0, "搜索名称 / 发布者 / 路径")
        self.search_entry.configure(foreground=MUTED)
        self.search_entry.bind("<FocusIn>", self._search_focus_in)
        self.search_entry.bind("<FocusOut>", self._search_focus_out)
        self.search_var.trace_add("write", lambda *_: self.refresh_view())

        self.source_var = tk.StringVar(value="全部来源")
        ttk.Combobox(filters, textvariable=self.source_var, values=SOURCE_CHOICES,
                     state="readonly", width=14, style="Filter.TCombobox").pack(side="left", padx=(8, 0))
        self.source_var.trace_add("write", lambda *_: self.refresh_view())

        self.category_var = tk.StringVar(value="全部类型")
        ttk.Combobox(filters, textvariable=self.category_var, values=CATEGORY_CHOICES,
                     state="readonly", width=11, style="Filter.TCombobox").pack(side="left", padx=(8, 0))
        self.category_var.trace_add("write", lambda *_: self.refresh_view())

        self.pending_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filters, text="只看未创建", variable=self.pending_var,
                        command=self.refresh_view, style="Card.TCheckbutton").pack(side="left", padx=(12, 0))

        self.count_label = tk.Label(filters, text="尚未扫描", font=(FONT, 9), bg=CARD, fg=MUTED)
        self.count_label.pack(side="right")

        wrap = tk.Frame(tab, bg=CARD)
        wrap.pack(fill="both", expand=True)

        columns = ("name", "version", "source", "category", "shortcut", "publisher", "target")
        self.tree = ttk.Treeview(wrap, columns=columns, show="tree headings",
                                 style="List.Treeview", selectmode="extended")
        headings = {
            "name": ("名称", 240, "w"),
            "version": ("版本", 108, "w"),
            "source": ("来源", 112, "w"),
            "category": ("类别", 78, "w"),
            "shortcut": ("桌面快捷方式", 106, "center"),
            "publisher": ("发布者", 140, "w"),
            "target": ("启动目标", 300, "w"),
        }
        for column, (label, width, anchor) in headings.items():
            self.tree.heading(column, text=label, command=lambda c=column: self.sort_by(c))
            self.tree.column(column, width=width, anchor=anchor, stretch=column in ("name", "target"))
        # 第 0 列只放真实图标（软件自己的 exe/商店图标）
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=34, minwidth=34, stretch=False, anchor="center")

        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview,
                                  style="List.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.tag_configure("odd", background=SUBTLE)
        self.tree.tag_configure("system", foreground="#9aa3b2")
        self.tree.tag_configure("invalid", foreground=DANGER_RED)
        self.tree.tag_configure("has", foreground=OK_GREEN)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _event: self.open_location())

        detail = tk.Frame(tab, bg=SUBTLE, height=92, highlightthickness=1,
                          highlightbackground=BORDER)
        detail.pack(fill="x", pady=(10, 0))
        detail.pack_propagate(False)
        self.detail_icon = tk.Label(detail, bg=SUBTLE)
        self.detail_icon.pack(side="left", padx=(14, 10))
        info = tk.Frame(detail, bg=SUBTLE)
        info.pack(side="left", fill="both", expand=True, pady=10)
        self.detail_name = tk.Label(info, text="选择一行查看详情", font=(FONT, 11, "bold"),
                                    bg=SUBTLE, fg=TEXT)
        self.detail_name.pack(anchor="w")
        self.detail_meta = tk.Label(info, text="", font=(FONT, 9), bg=SUBTLE, fg=MUTED)
        self.detail_meta.pack(anchor="w", pady=(2, 0))
        self.detail_target = tk.Label(info, text="", font=(FONT, 9), bg=SUBTLE, fg=MUTED,
                                      anchor="w", justify="left")
        self.detail_target.pack(anchor="w", fill="x")
        self.detail_note = tk.Label(info, text="", font=(FONT, 9), bg=SUBTLE, fg=WARN_ORANGE)
        self.detail_note.pack(anchor="w")

        detail_buttons = tk.Frame(detail, bg=SUBTLE)
        detail_buttons.pack(side="right", padx=12)
        ttk.Button(detail_buttons, text="打开文件位置", style="Ghost.TButton",
                   command=self.open_location).pack(pady=(0, 6))
        ttk.Button(detail_buttons, text="复制路径", style="Ghost.TButton",
                   command=self.copy_target).pack()

        actions = tk.Frame(tab, bg=CARD)
        actions.pack(fill="x", pady=(10, 0))
        self.summary_label = tk.Label(actions, text="", font=(FONT, 9), bg=CARD, fg=MUTED)
        self.summary_label.pack(side="left")

        self.create_button = ttk.Button(actions, text="为选中项创建快捷方式",
                                        style="Accent.TButton", command=self.create_selected)
        self.create_button.pack(side="right")
        ttk.Button(actions, text="全选", style="Ghost.TButton",
                   command=self.select_all).pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="反选", style="Ghost.TButton",
                   command=self.invert_selection).pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="导出清单", style="Ghost.TButton",
                   command=self.export_csv).pack(side="right", padx=(8, 0))

    # --------------------------------------------------------------- 桌面现状
    def _build_desktop_tab(self) -> None:
        tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=14)
        self.notebook.add(tab, text="  桌面现状  ")

        cards = tk.Frame(tab, bg=CARD)
        cards.pack(fill="x")
        self.cap_value_labels: dict[str, tk.Label] = {}
        definitions = (
            ("total", "图标总容量", "格"),
            ("used", "已占用", "项"),
            ("free", "剩余空位", "格"),
            ("disk", "桌面所在磁盘可用", ""),
        )
        for index, (key, title, unit) in enumerate(definitions):
            card = tk.Frame(cards, bg=SUBTLE, highlightthickness=1, highlightbackground=BORDER)
            card.pack(side="left", expand=True, fill="both",
                      padx=(0 if index == 0 else 10, 0))
            tk.Label(card, text=title, font=(FONT, 9), bg=SUBTLE, fg=MUTED).pack(anchor="w", padx=14, pady=(10, 0))
            value_row = tk.Frame(card, bg=SUBTLE)
            value_row.pack(anchor="w", padx=14, pady=(2, 12))
            value = tk.Label(value_row, text="—", font=(FONT, 17, "bold"), bg=SUBTLE, fg=TEXT)
            value.pack(side="left")
            tk.Label(value_row, text=unit, font=(FONT, 9), bg=SUBTLE, fg=MUTED).pack(side="left", padx=(4, 0))
            self.cap_value_labels[key] = value

        usage = tk.Frame(tab, bg=CARD)
        usage.pack(fill="x", pady=(14, 4))
        self.usage_label = tk.Label(usage, text="", font=(FONT, 9), bg=CARD, fg=MUTED)
        self.usage_label.pack(side="left")
        self.usage_bar = ttk.Progressbar(usage, style="Usage.Horizontal.TProgressbar",
                                         maximum=100, value=0, length=260)
        self.usage_bar.pack(side="right")

        tools = tk.Frame(tab, bg=CARD)
        tools.pack(fill="x", pady=(6, 8))
        self.only_problem_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tools, text="只看失效 / 重复项", variable=self.only_problem_var,
                        command=self._render_desktop_items, style="Card.TCheckbutton").pack(side="left")
        ttk.Button(tools, text="打开桌面", style="Ghost.TButton",
                   command=lambda: os.startfile(shortcuts.desktop_base_dir())).pack(side="right", padx=(8, 0))
        ttk.Button(tools, text="刷新", style="Ghost.TButton",
                   command=self.refresh_desktop).pack(side="right")

        wrap = tk.Frame(tab, bg=CARD)
        wrap.pack(fill="both", expand=True)
        columns = ("name", "kind", "status", "target")
        self.desktop_tree = ttk.Treeview(wrap, columns=columns, show="headings",
                                         style="List.Treeview", selectmode="browse")
        for column, label, width, anchor in (
            ("name", "桌面名称", 260, "w"),
            ("kind", "类型", 90, "w"),
            ("status", "状态", 100, "w"),
            ("target", "指向目标", 480, "w"),
        ):
            self.desktop_tree.heading(column, text=label)
            self.desktop_tree.column(column, width=width, anchor=anchor,
                                     stretch=column in ("name", "target"))
        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=self.desktop_tree.yview,
                                  style="List.Vertical.TScrollbar")
        self.desktop_tree.configure(yscrollcommand=scrollbar.set)
        self.desktop_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.desktop_tree.tag_configure("odd", background=SUBTLE)
        self.desktop_tree.tag_configure("broken", foreground=DANGER_RED)
        self.desktop_tree.tag_configure("dup", foreground=WARN_ORANGE)

        note = tk.Label(
            tab,
            text="提示：桌面图标取自「当前用户桌面 + 公共桌面」。失效项表示快捷方式指向的程序已被移动或删除。",
            font=(FONT, 9), bg=CARD, fg=MUTED, anchor="w",
        )
        note.pack(fill="x", pady=(8, 0))

    # ------------------------------------------------------------------- 设置
    def _build_settings_tab(self) -> None:
        tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=14)
        self.notebook.add(tab, text="  设置  ")

        columns = tk.Frame(tab, bg=CARD)
        columns.pack(fill="both", expand=True)
        left = tk.Frame(columns, bg=CARD)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = tk.Frame(columns, bg=CARD)
        right.pack(side="left", fill="both", expand=True)

        scan_box = ttk.LabelFrame(left, text="扫描范围", style="Section.TLabelframe", padding=12)
        scan_box.pack(fill="x")
        self.var_registry = tk.BooleanVar()
        self.var_startmenu = tk.BooleanVar()
        self.var_store = tk.BooleanVar()
        self.var_steam = tk.BooleanVar()
        self.var_folder = tk.BooleanVar()
        for text, var, hint in (
            ("注册表卸载项（推荐）", self.var_registry, "最完整的软件清单，含版本与发布者"),
            ("开始菜单快捷方式", self.var_startmenu, "补齐没有写卸载项的绿色软件"),
            ("Microsoft Store 应用", self.var_store, "只保留用户安装的商店应用"),
            ("Steam 游戏库", self.var_steam, "读取所有 Steam 库目录"),
        ):
            row = tk.Frame(scan_box, bg=CARD)
            row.pack(fill="x", pady=2)
            ttk.Checkbutton(row, text=text, variable=var, style="Card.TCheckbutton",
                            command=self.save_settings).pack(anchor="w")
            tk.Label(row, text=hint, font=(FONT, 9), bg=CARD, fg=MUTED).pack(anchor="w", padx=(24, 0))

        folder_row = tk.Frame(scan_box, bg=CARD)
        folder_row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(folder_row, text="自定义目录", variable=self.var_folder,
                        style="Card.TCheckbutton", command=self.save_settings).pack(side="left")
        self.folder_var = tk.StringVar()
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var, style="Search.TEntry")
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(folder_row, text="浏览…", style="Ghost.TButton",
                   command=self.choose_folder).pack(side="left")

        filter_box = ttk.LabelFrame(left, text="过滤规则", style="Section.TLabelframe", padding=12)
        filter_box.pack(fill="x", pady=(10, 0))
        self.var_include_system = tk.BooleanVar()
        self.var_hide_targetless = tk.BooleanVar()
        ttk.Checkbutton(filter_box, text="显示系统组件 / 运行库 / 补丁",
                        variable=self.var_include_system, style="Card.TCheckbutton",
                        command=self.save_settings).pack(anchor="w", pady=2)
        ttk.Checkbutton(filter_box, text="隐藏没有启动目标的残留条目",
                        variable=self.var_hide_targetless, style="Card.TCheckbutton",
                        command=self.save_settings).pack(anchor="w", pady=2)
        tk.Label(filter_box, text="商店应用（包括没有开始菜单入口的）同样能取到原始图标；"
                                  "发布者一栏会自动识别 GitHub 项目地址（只读本机下载来源，不联网猜测）。",
                 font=(FONT, 9), bg=CARD, fg=MUTED, wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))
        tk.Label(filter_box, text="默认会排除 VC++ 运行库、.NET、驱动、KB 补丁、Windows 自带工具等系统组件；"
                                  "微软账号下自行安装的 Office、VS Code、商店应用仍会保留。",
                 font=(FONT, 9), bg=CARD, fg=MUTED, wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))

        tips_box = ttk.LabelFrame(left, text="使用提示", style="Section.TLabelframe", padding=12)
        tips_box.pack(fill="both", expand=True, pady=(10, 0))
        tips = tk.Label(
            tips_box,
            text=("1. 首次启动会自动扫描，也可以用 F5 重新扫描。\n"
                  "2. 在「已安装软件」页按来源 / 类别筛选，Ctrl 或 Shift 多选。\n"
                  "3. 点「为选中项创建快捷方式」，自动检查空位后直接创建，不再二次确认。\n"
                  "4. 桌面已有快捷方式的软件会自动跳过，不会重复创建。\n"
                  "5. 设置里的扫描范围与过滤规则会在下一次扫描生效。"),
            font=(FONT, 9), bg=CARD, fg=MUTED, justify="left", anchor="nw",
        )
        tips.pack(anchor="w", fill="both")

        shortcut_box = ttk.LabelFrame(right, text="快捷方式", style="Section.TLabelframe", padding=12)
        shortcut_box.pack(fill="x")
        self.shortcut_mode = tk.StringVar(value="desktop")
        ttk.Radiobutton(shortcut_box, text="直接放到桌面", value="desktop",
                        variable=self.shortcut_mode, style="Card.TRadiobutton",
                        command=self.save_settings).pack(anchor="w", pady=2)
        folder_line = tk.Frame(shortcut_box, bg=CARD)
        folder_line.pack(fill="x", pady=2)
        ttk.Radiobutton(folder_line, text="放到桌面文件夹：", value="folder",
                        variable=self.shortcut_mode, style="Card.TRadiobutton",
                        command=self.save_settings).pack(side="left")
        self.folder_name_var = tk.StringVar()
        ttk.Entry(folder_line, textvariable=self.folder_name_var, width=18,
                  style="Search.TEntry").pack(side="left", padx=6)
        self.folder_name_var.trace_add("write", lambda *_: self.save_settings())
        self.var_confirm_create = tk.BooleanVar()
        ttk.Checkbutton(shortcut_box, text="创建前再弹一次确认（默认关闭，选中即创建）",
                        variable=self.var_confirm_create, style="Card.TCheckbutton",
                        command=self.save_settings).pack(anchor="w", pady=(6, 0))
        tk.Label(shortcut_box, text="创建前仍会检查桌面剩余空位；空间不够时自动放入子文件夹，不再打断你。",
                 font=(FONT, 9), bg=CARD, fg=MUTED, wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))

        update_box = ttk.LabelFrame(right, text="更新与便捷设置", style="Section.TLabelframe", padding=12)
        update_box.pack(fill="x", pady=(10, 0))
        self.var_auto_update = tk.BooleanVar()
        ttk.Checkbutton(update_box, text="启动时自动检查新版本",
                        variable=self.var_auto_update, style="Card.TCheckbutton",
                        command=self.save_settings).pack(anchor="w", pady=2)
        self.var_auto_scan = tk.BooleanVar()
        ttk.Checkbutton(update_box, text="启动时自动扫描",
                        variable=self.var_auto_scan, style="Card.TCheckbutton",
                        command=self.save_settings).pack(anchor="w", pady=2)
        self.var_autostart = tk.BooleanVar()
        ttk.Checkbutton(update_box, text="开机自动启动 DeskScout",
                        variable=self.var_autostart, style="Card.TCheckbutton",
                        command=self.toggle_autostart).pack(anchor="w", pady=2)
        actions = tk.Frame(update_box, bg=CARD)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="检查更新", style="Ghost.TButton",
                   command=lambda: self.check_update(manual=True)).pack(side="left")
        self.inbox_button = ttk.Button(actions, text="公告收件箱", style="Ghost.TButton",
                                       command=self._open_inbox)
        self.inbox_button.pack(side="left", padx=8)
        ttk.Button(actions, text="打开配置目录", style="Ghost.TButton",
                   command=lambda: os.startfile(config.app_dir())).pack(side="left")
        ttk.Button(actions, text="重置设置", style="Ghost.TButton",
                   command=self.reset_settings).pack(side="left", padx=8)

        about_box = ttk.LabelFrame(right, text="关于", style="Section.TLabelframe", padding=12)
        about_box.pack(fill="both", expand=True, pady=(10, 0))
        self.about_label = tk.Label(
            about_box,
            text=(f"DeskScout 桌面应用管家 v{__version__}\n"
                  "• 纯本地运行：扫描结果只留在本机，工具不联网上传任何清单\n"
                  "• 只读取安装信息与快捷方式，不修改已安装软件\n"
                  "• 创建快捷方式默认不再二次确认，可在上方设置里重新开启\n"
                  "• 图标取自 Windows Shell，商店应用同样显示原始图标\n"
                  f"• 项目主页：{HOMEPAGE}"),
            font=(FONT, 9), bg=CARD, fg=MUTED, justify="left", anchor="w",
        )
        self.about_label.pack(anchor="w", fill="x")

    # ------------------------------------------------------------ 配置 -> 界面
    def _apply_settings_to_ui(self) -> None:
        scan = self.cfg.get("scan", {})
        self.var_registry.set(bool(scan.get("registry", True)))
        self.var_startmenu.set(bool(scan.get("startmenu", True)))
        self.var_store.set(bool(scan.get("store", True)))
        self.var_steam.set(bool(scan.get("steam", True)))
        self.var_folder.set(bool(scan.get("folder", False)))
        self.folder_var.set(str(scan.get("custom_folder", "") or ""))

        filters = self.cfg.get("filter", {})
        self.var_include_system.set(bool(filters.get("include_system", False)))
        self.var_hide_targetless.set(bool(filters.get("hide_targetless", True)))

        short = self.cfg.get("shortcuts", {})
        self.shortcut_mode.set(str(short.get("mode", "desktop")))
        self.folder_name_var.set(str(short.get("folder_name", "新建快捷方式")))
        self.var_confirm_create.set(bool(short.get("confirm_before_create", False)))

        ui = self.cfg.get("ui", {})
        self.var_auto_scan.set(bool(ui.get("auto_scan_on_start", True)))
        self.var_autostart.set(config.is_autostart())

        update = self.cfg.get("update", {})
        self.var_auto_update.set(bool(update.get("auto_check", True)))

    def save_settings(self, *_args) -> None:
        if not self._ui_ready:
            return
        self.cfg["scan"] = {
            "registry": self.var_registry.get(),
            "startmenu": self.var_startmenu.get(),
            "store": self.var_store.get(),
            "steam": self.var_steam.get(),
            "folder": self.var_folder.get(),
            "custom_folder": self.folder_var.get().strip(),
        }
        self.cfg["filter"] = {
            "include_system": self.var_include_system.get(),
            "hide_targetless": self.var_hide_targetless.get(),
        }
        self.cfg["shortcuts"] = {
            "mode": self.shortcut_mode.get(),
            "folder_name": self.folder_name_var.get().strip() or "新建快捷方式",
            "confirm_before_create": self.var_confirm_create.get(),
        }
        self.cfg["ui"]["auto_scan_on_start"] = self.var_auto_scan.get()
        self.cfg["update"]["auto_check"] = self.var_auto_update.get()
        config.save(self.cfg)

    def reset_settings(self) -> None:
        if not messagebox.askyesno("重置设置", "确定恢复默认设置吗？已安装的快捷方式不会被删除。", parent=self):
            return
        self.cfg = config.DEFAULTS.copy()
        config.save(self.cfg)
        self._apply_settings_to_ui()
        self._set_status("设置已恢复默认")

    def choose_folder(self) -> None:
        path = filedialog.askdirectory(parent=self, title="选择要扫描的软件目录")
        if path:
            self.folder_var.set(path)
            self.var_folder.set(True)
            self.save_settings()

    def toggle_autostart(self) -> None:
        if not getattr(sys, "frozen", False):
            self.var_autostart.set(False)
            messagebox.showinfo("提示", "开机自启动仅在打包后的 DeskScout.exe 中生效。", parent=self)
            return
        enabled = self.var_autostart.get()
        ok = config.set_autostart(enabled, os.path.abspath(sys.executable))
        if not ok:
            self.var_autostart.set(not enabled)
            messagebox.showwarning("提示", "写入开机启动项失败，可能被安全软件拦截。", parent=self)
        else:
            self._set_status("已开启开机自启动" if enabled else "已关闭开机自启动")

    # ------------------------------------------------------------------ 扫描
    def build_options(self) -> ScanOptions:
        return ScanOptions(
            registry=self.var_registry.get(),
            startmenu=self.var_startmenu.get(),
            store=self.var_store.get(),
            steam=self.var_steam.get(),
            folder=self.var_folder.get(),
            custom_folder=self.folder_var.get().strip(),
            include_system=self.var_include_system.get(),
            hide_targetless=self.var_hide_targetless.get(),
        )

    def start_scan(self) -> None:
        if self.scanning or self.creating:
            return
        self.scanning = True
        self.scan_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.progress.pack(side="left", padx=(0, 12), before=self.capacity_label)
        self._set_pill("扫描中…", "#fff7e6", WARN_ORANGE)
        self._set_status("正在扫描已安装软件…")
        options = self.build_options()
        threading.Thread(target=self._scan_worker, args=(options,), daemon=True).start()

    def _scan_worker(self, options: ScanOptions) -> None:
        try:
            items = desktop.scan_desktop()
            engine.find_duplicate_targets(items)
            capacity = desktop.desktop_capacity()
            report = engine.scan_all(
                options, items,
                lambda message, percent: self.queue.put(("progress", message, percent)),
            )
            self.queue.put(("scan_done", report, items, capacity))
        except Exception as exc:  # 扫描失败不应让界面崩溃
            self.queue.put(("error", f"扫描失败：{exc}"))

    def _on_scan_done(self, report, items, capacity) -> None:
        self.scanning = False
        self.scan_button.configure(state="normal")
        self.progress.pack_forget()
        self.entries = report.entries
        self.desktop_items = items
        self.capacity = capacity
        self._set_pill("就绪", "#eef2fb", ACCENT_DARK)
        self._render_desktop_items()
        self._update_capacity()
        self.refresh_view()
        stats = " · ".join(f"{label} {count}" for label, count in (
            ("注册表", report.source_stats.get("registry", 0)),
            ("开始菜单", report.source_stats.get("startmenu", 0)),
            ("商店", report.source_stats.get("store", 0)),
            ("Steam", report.source_stats.get("steam", 0)),
        ) if count)
        self._set_status(
            f"扫描完成：{report.raw_count} 条原始记录 → {len(report.entries)} 个应用"
            f"（合并 {report.merged_count} 条，用时 {report.elapsed_ms} ms）"
        )
        if stats:
            self.count_label.configure(text=stats)

    # -------------------------------------------------------------- 列表渲染
    def _filtered_entries(self) -> list[AppEntry]:
        text = "" if self._search_placeholder else self.search_var.get().strip().casefold()
        source = self.source_var.get()
        category = self.category_var.get()
        only_pending = self.pending_var.get()
        rows = []
        for entry in self.entries:
            if text:
                haystack = f"{entry.name} {entry.publisher} {entry.target} {entry.source_label}".casefold()
                if text not in haystack:
                    continue
            if source != "全部来源" and entry.source_label != source:
                continue
            if category != "全部类型" and entry.category_label != category:
                continue
            if only_pending and entry.has_shortcut:
                continue
            rows.append(entry)
        return rows

    def refresh_view(self) -> None:
        rows = self._filtered_entries()
        rows.sort(key=self._sort_key, reverse=self.sort_reverse)
        self._render_rows(rows)
        total = len(self.entries)
        pending = sum(1 for e in self.entries if e.launchable and not e.has_shortcut)
        with_shortcut = sum(1 for e in self.entries if e.has_shortcut)
        self.summary_label.configure(
            text=f"共 {total} 个应用 · 已有桌面快捷方式 {with_shortcut} · 待创建 {pending}"
        )
        if total:
            self.count_label.configure(text=f"当前显示 {len(rows)} / {total}")

    def _render_rows(self, rows: list[AppEntry]) -> None:
        self.tree.delete(*self.tree.get_children())
        self.row_map.clear()
        for index, entry in enumerate(rows):
            tags = ["odd"] if index % 2 else []
            if entry.category == "system":
                tags.append("system")
            elif entry.has_shortcut:
                tags.append("has")
            elif entry.invalid or not entry.target:
                tags.append("invalid")
            shortcut_text = "✓ 已有" if entry.has_shortcut else ("无法创建" if not entry.target else "可创建")
            target_text = "Microsoft Store 应用" if entry.source == "store" else entry.target
            iid = f"row{index}"
            self.tree.insert(
                "", "end", iid=iid, tags=tuple(tags),
                values=(entry.name, entry.version, entry.source_label, entry.category_label,
                        shortcut_text, entry.publisher or "—", target_text or "—"),
            )
            self.row_map[iid] = entry
        self._refresh_row_icons(rows)

    def _refresh_row_icons(self, rows: list[AppEntry]) -> None:
        """图标在后台线程预取，主线程按批贴上去，避免列表卡住."""
        self._icon_gen += 1
        generation = self._icon_gen
        self._icon_queue = queue.Queue()
        self._icon_photos = {}

        def worker() -> None:
            for index, entry in enumerate(rows):
                try:
                    image = icons.entry_icon_pil(entry, 24)
                except (OSError, ValueError):
                    image = None
                self._icon_queue.put((generation, f"row{index}", image))

        threading.Thread(target=worker, daemon=True).start()
        self.after(60, self._drain_row_icons)

    def _drain_row_icons(self) -> None:
        applied = 0
        while applied < 16:
            try:
                generation, iid, image = self._icon_queue.get_nowait()
            except queue.Empty:
                break
            if generation != self._icon_gen:
                return
            applied += 1
            if image is None or iid not in self.row_map:
                continue
            try:
                photo = icons.tk_photo(image)
            except (RuntimeError, TypeError, ValueError):
                continue
            if photo is None:
                continue
            self._icon_photos[iid] = photo
            try:
                self.tree.item(iid, image=photo)
            except tk.TclError:
                continue
        if not self._icon_queue.empty():
            self.after(40, self._drain_row_icons)

    def _sort_key(self, entry: AppEntry):
        column = self.sort_column
        if column == "name":
            return normalize_name(entry.name)
        if column == "version":
            return updater.parse_version(entry.version)
        if column == "shortcut":
            return entry.has_shortcut
        if column == "source":
            return entry.source_label
        if column == "category":
            return entry.category_label
        if column == "publisher":
            return (entry.publisher or "").casefold()
        if column == "target":
            return (entry.target or "").casefold()
        return entry.name

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self.refresh_view()

    def select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def invert_selection(self) -> None:
        children = self.tree.get_children()
        selected = set(self.tree.selection())
        self.tree.selection_set([iid for iid in children if iid not in selected])

    def _on_select(self, _event=None) -> None:
        items = self.tree.selection()
        if not items:
            self._detail_entry = None
            self.detail_name.configure(text="选择一行查看详情")
            self.detail_meta.configure(text="")
            self.detail_target.configure(text="")
            self.detail_note.configure(text="")
            self.detail_icon.configure(image="")
            return
        entry = self.row_map.get(items[0])
        if entry is None:
            return
        self._detail_entry = entry
        photo = icons.get_entry_icon(entry, 48)
        if photo is not None:
            self.detail_icon.configure(image=photo)
            self.detail_icon.image = photo
        else:
            self.detail_icon.configure(image="")
        self.detail_name.configure(text=entry.name)
        meta_parts = [part for part in (
            f"版本 {entry.version}" if entry.version else "",
            entry.source_label,
            entry.category_label,
            entry.publisher,
        ) if part]
        self.detail_meta.configure(text=" · ".join(meta_parts))
        self.detail_target.configure(text=f"启动目标：{entry.target or '（无）'}")
        self.detail_note.configure(text=entry.note or "")

    def _selected_entries(self) -> list[AppEntry]:
        return [self.row_map[iid] for iid in self.tree.selection() if iid in self.row_map]

    def open_location(self) -> None:
        entry = self._detail_entry
        if entry is None:
            return
        target = entry.target
        if not target:
            messagebox.showinfo("提示", "该条目没有可用的启动目标。", parent=self)
            return
        if entry.source == "store":
            os.startfile("shell:AppsFolder")
            return
        if os.path.exists(target):
            os.system(f'explorer /select,"{target}"')
        else:
            folder = os.path.dirname(target)
            if folder and os.path.isdir(folder):
                os.startfile(folder)
            else:
                messagebox.showinfo("提示", "目标路径已不存在。", parent=self)

    def copy_target(self) -> None:
        entry = self._detail_entry
        if entry is None or not entry.target:
            return
        self.clipboard_clear()
        self.clipboard_append(entry.target)
        self._set_status("已复制启动路径")

    # ------------------------------------------------------------ 桌面现状
    def refresh_desktop(self) -> None:
        self.desktop_items = desktop.scan_desktop()
        engine.find_duplicate_targets(self.desktop_items)
        self.capacity = desktop.desktop_capacity()
        for entry in self.entries:
            entry.shortcut_name = ""
        if self.entries:
            engine.attach_shortcuts(self.entries, self.desktop_items)
        self._render_desktop_items()
        self._update_capacity()
        self.refresh_view()

    def _render_desktop_items(self) -> None:
        if not self.desktop_items:
            return
        self.desktop_tree.delete(*self.desktop_tree.get_children())
        only_problem = self.only_problem_var.get()
        shown = 0
        for index, item in enumerate(self.desktop_items):
            if only_problem and not (item.broken or item.duplicate_of):
                continue
            tags = ["odd"] if shown % 2 else []
            if item.broken:
                tags.append("broken")
            elif item.duplicate_of:
                tags.append("dup")
            kind_label = {"lnk": "快捷方式", "url": "网址", "folder": "文件夹", "file": "文件"}.get(item.kind, item.kind)
            self.desktop_tree.insert(
                "", "end", tags=tuple(tags),
                values=(item.name, kind_label, item.status_label, item.target or "——"),
            )
            shown += 1

    def _update_capacity(self) -> None:
        capacity = self.capacity or desktop.desktop_capacity()
        self.capacity = capacity
        total = capacity.get("total", 0)
        used = capacity.get("used", 0)
        free = capacity.get("free", 0)
        disk_free = capacity.get("disk_free", 0)
        self.cap_value_labels["total"].configure(text=str(total))
        self.cap_value_labels["used"].configure(text=str(used))
        self.cap_value_labels["free"].configure(text=str(free))
        self.cap_value_labels["disk"].configure(text=f"{disk_free / (1024 ** 3):.1f} GB" if disk_free else "—")
        ratio = (used / total * 100) if total else 0
        self.usage_bar.configure(value=min(100, ratio))
        self.usage_label.configure(
            text=f"桌面网格 {capacity.get('columns', 0)} × {capacity.get('rows', 0)} · "
                 f"已占用 {used} 项（{ratio:.0f}%）"
        )
        self.capacity_label.configure(
            text=f"桌面剩余 {free} 格 · 磁盘可用 {disk_free / (1024 ** 3):.1f} GB" if disk_free
            else f"桌面剩余 {free} 格"
        )

    # ------------------------------------------------------------ 创建快捷方式
    def create_selected(self) -> None:
        if self.scanning or self.creating:
            return
        entries = self._selected_entries()
        if not entries:
            messagebox.showinfo("提示", "请先在列表中选中要创建快捷方式的软件（可按住 Ctrl / Shift 多选）。", parent=self)
            return

        creatable = [e for e in entries if e.launchable]
        skipped = [e for e in entries if not e.launchable]
        already = [e for e in creatable if e.has_shortcut]
        todo = [e for e in creatable if not e.has_shortcut]
        note_lines = []
        if already:
            note_lines.append(f"其中 {len(already)} 个桌面已经有快捷方式，将跳过。")
        if skipped:
            note_lines.append(f"其中 {len(skipped)} 个缺少启动目标，将跳过。")
        if not todo:
            messagebox.showinfo("无需创建", "\n".join(note_lines) or "选中的软件都已有桌面快捷方式。", parent=self)
            return

        capacity = desktop.desktop_capacity()
        self.capacity = capacity
        free = capacity.get("free", 0)
        mode = self.shortcut_mode.get()
        folder = shortcuts.target_folder(shortcuts.desktop_base_dir(), mode,
                                         self.folder_name_var.get())
        fallback = False
        if mode == "desktop" and len(todo) > free:
            folder = shortcuts.target_folder(shortcuts.desktop_base_dir(), "folder",
                                             self.folder_name_var.get())
            fallback = True

        if config.get(self.cfg, "shortcuts.confirm_before_create", False):
            preview = shortcuts.plan_preview(todo, folder, 6)
            preview_text = "\n".join(f"· {name}" for name in preview)
            if len(todo) > len(preview):
                preview_text += f"\n… 其余 {len(todo) - len(preview)} 个"
            message = (
                f"将在以下位置创建 {len(todo)} 个快捷方式：\n{folder}\n\n"
                f"{preview_text}\n\n桌面剩余空位：{free}"
            )
            if note_lines:
                message = "\n".join(note_lines) + "\n\n" + message
            if not messagebox.askyesno("确认创建快捷方式", message, parent=self):
                return

        self._create_fallback = fallback
        self._create_notes = note_lines
        self.creating = True
        self.create_button.configure(state="disabled")
        self._set_pill("创建中…", "#fff7e6", WARN_ORANGE)
        self.progress.configure(value=0)
        self.progress.pack(side="left", padx=(0, 12), before=self.capacity_label)
        threading.Thread(target=self._create_worker, args=(todo, folder), daemon=True).start()

    def _create_worker(self, entries: list[AppEntry], folder: str) -> None:
        try:
            result = shortcuts.create_for_entries(
                entries, folder,
                progress=lambda done, total, name: self.queue.put(("create_progress", done, total, name)),
            )
            self.queue.put(("create_done", result, folder))
        except Exception as exc:
            self.queue.put(("error", f"创建快捷方式失败：{exc}"))

    def _on_create_done(self, result, folder) -> None:
        self.creating = False
        self.create_button.configure(state="normal")
        self.progress.pack_forget()
        self._set_pill("就绪", "#eef2fb", ACCENT_DARK)
        summary = f"已创建 {result.created_count} 个快捷方式"
        if result.skipped:
            summary += f"，跳过 {len(result.skipped)} 个"
        if result.failed:
            summary += f"，失败 {len(result.failed)} 个"
        self._set_status(f"{summary} → {folder}")
        self.refresh_desktop()

        if result.failed:
            lines = [summary, "", f"位置：{folder}", "", "失败明细："]
            lines.extend(f"· {name}：{reason}" for name, reason in result.failed[:8])
            messagebox.showwarning("部分快捷方式创建失败", "\n".join(lines), parent=self)
        elif getattr(self, "_create_fallback", False):
            messagebox.showinfo(
                "桌面空间不足，已改放文件夹",
                f"桌面只剩 {self.capacity.get('free', 0)} 个空位，本次创建的快捷方式已放入：\n{folder}",
                parent=self,
            )

    # ------------------------------------------------------------------ 导出
    def export_csv(self) -> None:
        rows = self._filtered_entries()
        if not rows:
            messagebox.showinfo("提示", "当前没有可导出的条目。", parent=self)
            return
        default_name = f"DeskScout-应用清单-{datetime.now():%Y%m%d}.csv"
        path = filedialog.asksaveasfilename(
            parent=self, title="导出应用清单", defaultextension=".csv",
            initialfile=default_name, initialdir=shortcuts.desktop_base_dir(),
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            import csv

            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["名称", "版本", "发布者", "来源", "类别", "桌面快捷方式", "启动目标", "备注"])
                for entry in rows:
                    writer.writerow([
                        entry.name, entry.version, entry.publisher, entry.source_label,
                        entry.category_label, entry.shortcut_name or "无",
                        entry.target, entry.note,
                    ])
            self._set_status(f"已导出 {len(rows)} 条记录：{path}")
            if messagebox.askyesno("导出完成", f"已导出 {len(rows)} 条记录。\n\n是否打开所在文件夹？", parent=self):
                os.startfile(os.path.dirname(path))
        except OSError as exc:
            messagebox.showwarning("导出失败", str(exc), parent=self)

    # --------------------------------------------------------------- 公告收件箱
    def _inbox(self) -> list:
        update = self.cfg.setdefault("update", {})
        inbox = update.get("inbox")
        if not isinstance(inbox, list):
            inbox = []
            update["inbox"] = inbox
        return inbox

    def _startup_announcement(self) -> None:
        """记一次收件箱；升级后首次启动弹一次更新说明，之后不再重复."""
        current = __version__
        inbox = self._inbox()
        known = {str(item.get("version")) for item in inbox if isinstance(item, dict)}
        if current not in known:
            inbox.insert(0, {
                "version": current,
                "title": announcements.title_for(current),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "notes": announcements.notes_for(current) or f"DeskScout 已更新到 v{current}。",
            })
            del inbox[20:]
            config.save(self.cfg)

        update = self.cfg.setdefault("update", {})
        self._update_inbox_button()

        seen = str(update.get("last_seen_version") or "")
        if not seen:
            # 首次安装不弹窗，只记住版本
            update["last_seen_version"] = current
            config.save(self.cfg)
            return
        if seen != current:
            update["last_seen_version"] = current
            config.save(self.cfg)
            self._show_announcement(current)

    def _update_inbox_button(self) -> None:
        button = getattr(self, "inbox_button", None)
        if button is None:
            return
        try:
            button.configure(text=f"公告收件箱（{len(self._inbox())}）")
        except tk.TkError:
            pass

    def _show_announcement(self, version: str) -> None:
        notes = announcements.notes_for(version) or f"DeskScout 已更新到 v{version}。"
        window = tk.Toplevel(self)
        window.title(announcements.title_for(version))
        window.configure(bg=CARD)
        window.geometry("640x500")
        window.minsize(520, 380)
        window.transient(self)
        window.attributes("-topmost", True)

        header = tk.Frame(window, bg=CARD)
        header.pack(fill="x", padx=20, pady=(18, 0))
        tk.Label(header, text=f"已更新到 DeskScout v{version}", font=(FONT, 15, "bold"),
                 bg=CARD, fg=TEXT).pack(anchor="w")
        tk.Label(header, text=f"{datetime.now():%Y-%m-%d} · 本次更新内容如下，之后可在「设置 → 公告收件箱」回看",
                 font=(FONT, 9), bg=CARD, fg=MUTED).pack(anchor="w", pady=(4, 0))

        body = tk.Text(window, wrap="word", font=(FONT, 9), bg=SUBTLE, fg=TEXT,
                       relief="flat", padx=12, pady=10)
        body.insert("1.0", notes)
        body.configure(state="disabled")
        body.pack(fill="both", expand=True, padx=20, pady=12)

        footer = tk.Frame(window, bg=CARD)
        footer.pack(fill="x", padx=20, pady=(0, 16))
        ttk.Button(footer, text="查看收件箱", style="Ghost.TButton",
                   command=lambda: (window.destroy(), self._open_inbox())).pack(side="left")
        ttk.Button(footer, text="知道了", style="Accent.TButton",
                   command=window.destroy).pack(side="right")

    def _open_inbox(self) -> None:
        inbox = self._inbox()
        window = tk.Toplevel(self)
        window.title("更新公告收件箱")
        window.configure(bg=CARD)
        window.geometry("720x480")
        window.transient(self)

        tk.Label(window, text="更新公告", font=(FONT, 13, "bold"), bg=CARD, fg=TEXT
                 ).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(window, text="每次发版的说明都会留在本机，离线也能查看。",
                 font=(FONT, 9), bg=CARD, fg=MUTED).pack(anchor="w", padx=18)

        content = tk.Frame(window, bg=CARD)
        content.pack(fill="both", expand=True, padx=18, pady=12)

        listing = tk.Listbox(content, width=24, font=(FONT, 9), bg=SUBTLE, fg=TEXT,
                             relief="flat", activestyle="none", exportselection=False,
                             highlightthickness=1, highlightbackground=BORDER)
        listing.pack(side="left", fill="y")
        body = tk.Text(content, wrap="word", font=(FONT, 9), bg=SUBTLE, fg=TEXT,
                       relief="flat", padx=12, pady=10)
        body.pack(side="left", fill="both", expand=True, padx=(12, 0))
        body.configure(state="disabled")

        records = [item for item in inbox if isinstance(item, dict)] or [
            {"version": __version__, "title": announcements.title_for(__version__),
             "date": datetime.now().strftime("%Y-%m-%d"),
             "notes": announcements.notes_for(__version__)}
        ]

        def show_selection(_event=None) -> None:
            index = listing.curselection()
            if not index:
                return
            record = records[index[0]]
            body.configure(state="normal")
            body.delete("1.0", "end")
            body.insert("1.0", f"v{record.get('version')} · {record.get('date', '')}\n\n"
                              f"{record.get('notes', '')}")
            body.configure(state="disabled")

        for record in records:
            listing.insert("end", f"v{record.get('version')}  {record.get('date', '')}")
        listing.bind("<<ListboxSelect>>", show_selection)
        if records:
            listing.selection_set(0)
            show_selection()

        ttk.Button(window, text="关闭", style="Ghost.TButton",
                   command=window.destroy).pack(anchor="e", padx=18, pady=(0, 14))

    # ------------------------------------------------------------------ 更新
    def _auto_update_check(self) -> None:
        if not self.var_auto_update.get():
            return
        self.check_update(manual=False)

    def check_update(self, manual: bool = False) -> None:
        self._set_status("正在检查更新…")
        threading.Thread(target=self._update_worker, args=(manual,), daemon=True).start()

    def _update_worker(self, manual: bool) -> None:
        info, error = updater.check_latest()
        self.queue.put(("update_info", info, error, manual))

    def _on_update_info(self, info, error, manual) -> None:
        self.update_info = info
        if info is None:
            self._set_status("检查更新失败：网络不可用")
            if manual:
                messagebox.showwarning("检查更新", f"无法访问 GitHub Releases。\n{error}", parent=self)
            return
        if not updater.is_newer(info.get("version", "")):
            self._set_status(f"已是最新版本 v{__version__}")
            self._hide_banner()
            if manual:
                messagebox.showinfo("检查更新", f"当前已是最新版本 v{__version__}。", parent=self)
            return
        version = info.get("version", "")
        note = "发现新版本" + (f"：v{version}" if version else "")
        self._set_status(note)
        self._show_banner(f"发现新版本 v{version}，当前 v{__version__}")
        if manual:
            self._open_update_dialog()

    def _show_banner(self, text: str) -> None:
        self.banner_label.configure(text=text)
        if not self.banner_visible:
            self.banner.pack(fill="x", after=self.winfo_children()[0])
            self.banner_visible = True

    def _hide_banner(self) -> None:
        if self.banner_visible:
            self.banner.pack_forget()
            self.banner_visible = False

    def _open_update_dialog(self) -> None:
        info = self.update_info
        if not info:
            return
        window = tk.Toplevel(self)
        window.title("发现新版本")
        window.configure(bg=CARD)
        window.geometry("560x430")
        window.transient(self)
        window.grab_set()

        tk.Label(window, text=f"DeskScout v{info.get('version', '')}", font=(FONT, 14, "bold"),
                 bg=CARD, fg=TEXT).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(window, text=f"当前版本 v{__version__} · 发布于 {info.get('published_at', '')[:10]}",
                 font=(FONT, 9), bg=CARD, fg=MUTED).pack(anchor="w", padx=18)

        notes = tk.Text(window, height=14, wrap="word", font=(FONT, 9), bg=SUBTLE, fg=TEXT,
                        relief="flat", padx=10, pady=8)
        notes.insert("1.0", info.get("notes") or "本次更新没有附带说明。")
        notes.configure(state="disabled")
        notes.pack(fill="both", expand=True, padx=18, pady=12)

        buttons = tk.Frame(window, bg=CARD)
        buttons.pack(fill="x", padx=18, pady=(0, 16))
        status = tk.Label(buttons, text="", font=(FONT, 9), bg=CARD, fg=MUTED)
        status.pack(side="left")

        def open_release() -> None:
            webbrowser.open(info.get("html_url") or HOMEPAGE)

        ttk.Button(buttons, text="打开发布页", style="Ghost.TButton",
                   command=open_release).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="稍后再说", style="Ghost.TButton",
                   command=window.destroy).pack(side="right", padx=(8, 0))
        download_button = ttk.Button(buttons, text="下载并安装", style="Accent.TButton")
        download_button.pack(side="right")

        def start_download() -> None:
            download_button.configure(state="disabled")
            status.configure(text="正在下载…")

            def worker() -> None:
                path = updater.download_asset(
                    info, progress=lambda pct: self.queue.put(("dl_progress", pct, status))
                )
                self.queue.put(("dl_done", path, status, download_button, window))

            threading.Thread(target=worker, daemon=True).start()

        download_button.configure(command=start_download)

    def _on_download_progress(self, percent: int, label) -> None:
        try:
            label.configure(text=f"正在下载… {percent}%")
        except tk.TkError:
            pass

    def _on_download_done(self, path, status_label, button, window) -> None:
        try:
            status_label.configure(text="下载完成" if path else "下载失败")
        except tk.TkError:
            pass
        if not path:
            button.configure(state="normal")
            messagebox.showwarning("更新失败", "安装包下载失败，请稍后重试或打开发布页手动下载。", parent=self)
            return
        if not getattr(sys, "frozen", False):
            messagebox.showinfo(
                "源码运行模式",
                f"安装包已下载到：\n{path}\n\n当前是源码运行模式，请手动替换或打开发布页下载。",
                parent=self,
            )
            webbrowser.open(self.update_info.get("html_url") or HOMEPAGE if self.update_info else HOMEPAGE)
            return
        if not messagebox.askyesno("安装更新", "将关闭 DeskScout 完成更新，随后自动重新打开。现在继续吗？", parent=self):
            button.configure(state="normal")
            return
        if updater.launch_self_replace(path):
            self.destroy()
        else:
            messagebox.showwarning("更新失败", "无法启动更新脚本，请手动替换安装包。", parent=self)

    # ------------------------------------------------------------------ 杂项
    def _search_focus_in(self, _event=None) -> None:
        if self._search_placeholder:
            self.search_entry.delete(0, "end")
            self.search_entry.configure(foreground=TEXT)
            self._search_placeholder = False

    def _search_focus_out(self, _event=None) -> None:
        if not self.search_entry.get().strip():
            self._search_placeholder = True
            self.search_entry.insert(0, "搜索名称 / 发布者 / 路径")
            self.search_entry.configure(foreground=MUTED)

    def _focus_search(self, _event=None) -> None:
        self.search_entry.focus_set()
        return "break"

    def _set_status(self, text: str) -> None:
        self.status_text.configure(text=text)

    def _set_pill(self, text: str, background: str, foreground: str) -> None:
        self.status_pill.configure(text=text, bg=background, fg=foreground)

    def _drain_queue(self) -> None:
        try:
            while True:
                message = self.queue.get_nowait()
                kind = message[0]
                if kind == "progress":
                    self.progress.configure(value=message[2])
                    self._set_status(message[1])
                elif kind == "scan_done":
                    self._on_scan_done(message[1], message[2], message[3])
                elif kind == "create_progress":
                    done, total = message[1], message[2]
                    if total:
                        self.progress.configure(value=int(done * 100 / total))
                    self._set_status(f"正在创建：{message[3]}（{done}/{total}）")
                elif kind == "create_done":
                    self._on_create_done(message[1], message[2])
                elif kind == "update_info":
                    self._on_update_info(message[1], message[2], message[3])
                elif kind == "dl_progress":
                    self._on_download_progress(message[1], message[2])
                elif kind == "dl_done":
                    self._on_download_done(message[1], message[2], message[3], message[4])
                elif kind == "error":
                    self.scanning = False
                    self.creating = False
                    self.scan_button.configure(state="normal")
                    self.create_button.configure(state="normal")
                    self.progress.pack_forget()
                    self._set_pill("就绪", "#eef2fb", ACCENT_DARK)
                    self._set_status(message[1])
                    messagebox.showwarning("出错了", message[1], parent=self)
        except queue.Empty:
            pass
        except tk.TkError:
            pass
        self.after(80, self._drain_queue)

    def _on_close(self) -> None:
        try:
            self.cfg["ui"]["geometry"] = self.geometry()
            config.save(self.cfg)
        finally:
            self.destroy()


def run(start_tab: int | None = None) -> None:
    app = DeskScoutApp()
    if start_tab:
        app.notebook.select(start_tab)
    app.mainloop()

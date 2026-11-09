"""数据结构定义."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SOURCE_LABELS = {
    "registry": "注册表",
    "startmenu": "开始菜单",
    "store": "Microsoft Store",
    "steam": "Steam 游戏",
    "folder": "自定义目录",
}

CATEGORY_LABELS = {
    "user": "用户软件",
    "store": "商店应用",
    "game": "游戏",
    "system": "系统组件",
    "portable": "绿色软件",
}


@dataclass
class AppEntry:
    """一条待管理的应用记录."""

    key: str
    name: str
    version: str = ""
    publisher: str = ""
    source: str = "registry"
    category: str = "user"
    confidence: str = "high"
    install_location: str = ""
    uninstall_string: str = ""
    icon_path: str = ""
    target: str = ""
    arguments: str = ""
    working_dir: str = ""
    source_url: str = ""
    size_bytes: int = 0
    shortcut_name: str = ""
    invalid: bool = False
    note: str = ""

    # ---- 派生字段（不参与序列化）----
    @property
    def launchable(self) -> bool:
        return bool(self.target) and not self.invalid

    @property
    def has_shortcut(self) -> bool:
        return bool(self.shortcut_name)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    def to_public_dict(self) -> dict:
        return asdict(self)


@dataclass
class DesktopItem:
    """桌面上的一个图标条目."""

    path: str
    name: str
    kind: str = "lnk"          # lnk / url / file / folder / appx
    target: str = ""
    args: str = ""
    icon: str = ""
    is_public: bool = False
    broken: bool = False
    is_shell_item: bool = False
    duplicate_of: str = ""

    @property
    def status_label(self) -> str:
        if self.is_shell_item:
            return "商店应用"
        if self.broken:
            return "目标缺失"
        return "正常"


@dataclass
class ScanOptions:
    registry: bool = True
    startmenu: bool = True
    store: bool = True
    steam: bool = True
    folder: bool = False
    custom_folder: str = ""
    include_system: bool = False
    hide_targetless: bool = True


@dataclass
class ScanReport:
    entries: list[AppEntry] = field(default_factory=list)
    raw_count: int = 0
    filtered_count: int = 0
    merged_count: int = 0
    github_count: int = 0
    elapsed_ms: int = 0
    source_stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

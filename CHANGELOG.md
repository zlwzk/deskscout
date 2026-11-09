# 更新日志

## v1.1.0 — 2026-11-09

图标与扫描精度升级（中更新：新增 3 个模块，扫描与交互均有变化，配置结构向后兼容）。

### 修复

- 图标不再退化成「文件图标」：改为调用 Windows Shell 的 `IShellItemImageFactory::GetImage`，
  对 exe、`.lnk`、商店应用（`shell:AppsFolder\<AUMID>`）都能取到软件自身图标；`ExtractIconExW` 只作兜底。
- Microsoft Store 应用取不到原始图标的问题解决：商店条目补齐 AUMID 与包清单信息，图标按 AUMID → 目标 exe → `icon_path` → 安装目录逐级回退。
- 商店清单补齐：包清单里有、开始菜单里没有入口的应用（NVIDIA Control Panel、Realtek Audio Console、RenamerX 等）也会出现在列表里。
- 主程序定位增强：`DisplayIcon` 指向图标文件或卸载器时，继续下钻安装目录与子目录，找到真正的主程序；`icon_path` 为空时用目标 exe 回填。
- 商店应用里混入 shell 扩展、分享宿主、后台服务（`BaiduNetdiskService`、`HonorFileShareExtend`、`ksystemsharehost`、`wpsappext*` 之类）的问题解决，列表从 33 条收敛到 22 条左右。

### 新增

- `provenance.py`：GitHub 来源识别。从 NTFS 下载来源（`Zone.Identifier` 的 ReferrerUrl / HostUrl）、exe 版本资源、注册表 `URLInfoAbout`、安装目录内其它 exe 的顺序取线索，命中后把发布者写成 `https://github.com/owner/repo`，原发布者降级进备注。只读本机线索，不联网猜。
- `announcements.py`：应用内更新公告。每次发版的正文内置在程序里，配合 `config.update.inbox` 形成收件箱，离线可看。
- 升级后首次启动弹一次更新公告，看过即写入 `last_seen_version`，之后不再重复弹出；首次安装只记录版本号、不打扰。
- 设置页新增「公告收件箱（N）」入口，左侧版本列表、右侧公告正文。
- 扫描结果新增「GitHub 项目」统计，发布者一栏可直接打开项目主页。

### 优化

- 创建快捷方式**取消二次确认**：`shortcuts.confirm_before_create` 默认改为关闭，桌面空位不足时静默回落到「新建快捷方式」子文件夹，完成后一次性说明；需要复核的用户可在设置里重新打开确认。
- 旧配置一次性迁移：`schema_version` 缺失时把 `confirm_before_create` 归位为关闭，之后设置页的勾选仍然生效。
- 快捷方式图标统一缓存成多尺寸 ICO（`%APPDATA%\DeskScout\icons\<sha1>.ico`），桌面不会再出现通用文件图标。
- `fileinfo.py` 改为单次打开 PE 资源读取多个字符串，图标与版本探测更快。

### 说明

- 版本号按小 / 中 / 大更新自动判断：1.1.0 属于「功能新增 + 交互变化」的中更新，2.0.0 留给不兼容改动。

## v1.0.0 — 2026-11-09

首个正式版本。

### 新增

- 五种扫描来源：注册表卸载项（HKLM / WOW6432Node / HKCU）、开始菜单、Microsoft Store、Steam 库、自定义目录。
- 系统组件过滤：自动排除 VC++ 运行库、.NET、驱动、KB 补丁、Windows SDK、Windows 自带工具，同时保留 Microsoft Store 里用户自行安装的应用。
- 名称清洗与去重：剥离版本号、位数、别名与通用后缀后按名称指纹去重，不再出现同一软件两条记录。
- 套件归并：同一安装目录下的子工具并入主程序，避免桌面被 Git CMD、配置工具之类的入口塞满。
- 桌面体检：统计当前用户桌面与公共桌面的快捷方式，标记失效与重复项，并按屏幕分辨率计算图标网格容量。
- 快捷方式创建：先检查桌面剩余空位，再弹确认框，只创建桌面缺失的那些；空位不足时可一键改为桌面子文件夹。
- 命令行模式：`--scan`、`--json`、`--csv`、`--folder`，方便批量核对与自动化。
- 应用内自动更新：启动时静默检查 GitHub Release，可下载并自动替换重启。
- 便捷设置：开机自启动、启动时自动扫描、扫描范围与过滤规则可视化配置。

### 修复（开发期）

- 修复把任意快捷方式误判为商店应用的问题：改用 `SHGetPathFromIDListW` 判断 PIDL 能否解析为文件路径。
- 修复 Anaconda 等共用启动器场景下的假重复：去重不再按目标路径合并。
- 修复卸载器被当作主程序、帮助文档与官网链接被当作软件的问题。
- 修复设置初始化阶段误写配置导致首次启动不自动扫描的问题。

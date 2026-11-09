# DeskScout v1.1.0 发布公告

> 图标该是软件自己的，公告该是你看得到的。

## 这一版修了什么

**图标终于不再是"白纸"**

- 旧版只对 `.ico` / `.png` 直接读取、`.exe` 走 `ExtractIconExW`，剩下的一律退化成首字母色块，桌面上就出现一排"文件图标"。
- 现在主力接口换成 Windows Shell 的 `SHCreateItemFromParsingName` + `IShellItemImageFactory::GetImage`：exe、快捷方式、商店应用都能拿到系统渲染出来的真实图标，32 位带 alpha 的位图也能正确转成 PNG/ICO。
- **Microsoft Store 应用也能取到原始图标了**。商店条目以前连图标路径都没填，现在补齐 AUMID，按 AUMID → 目标 exe → 图标文件 → 安装目录逐级回退，Claude、ChatGPT、TranslucentTB、RenamerX 这些都能显示官方图标。

**扫描更准**

- 商店应用从 33 条收敛到 22 条左右：`BaiduNetdiskService`、`HonorFileShareExtend`、`HRContextMenu`、`ksystemsharehost`、`wpsappext*` 这类 shell 扩展和后台服务被剔除。
- 同时补上了原本漏掉的：NVIDIA Control Panel、Realtek Audio Console、RenamerX、LED Keyboard Setting。
- 主程序定位增强：`DisplayIcon` 指向图标或卸载器时继续下钻安装目录与子目录，不再把卸载器当成软件。
- 全机扫描实测 121 条有效条目，无图标来源 0 条。

## 这一版加了什么

**发布者自动填成 GitHub 地址**

从 GitHub 下载的软件，发布者一栏直接显示 `https://github.com/owner/repo`，点开就是项目主页。线索按可靠性排序：NTFS 下载来源（`Zone.Identifier` 里的 ReferrerUrl）→ exe 版本资源 → 注册表 `URLInfoAbout` → 安装目录内其它 exe。**只读本机线索，不按软件名去 GitHub 搜索**——同名仓库猜错比留空更糟。

**更新公告进"收件箱"，升级只弹一次**

- 每次发版的说明随程序内置（`announcements.py`），不联网也能看。
- 升级后第一次启动弹一次公告窗口，看过即记住版本号，之后不再重复出现；首次安装只记录版本号，不打扰。
- 设置页新增「公告收件箱（N）」，左边版本列表、右边正文，历史公告随时翻。

**创建快捷方式不再二次确认**

- 去掉"确认创建"弹窗：点一下就直接建。
- 桌面空位不足时不再弹窗问，而是静默回落到桌面上的「新建快捷方式」子文件夹，完成后一次性告诉你放到了哪。
- 想复核的同学可以在设置里重新勾上「创建前再弹一次确认」，默认关闭。

## 版本号规则

| 档位 | 触发条件 |
| --- | --- |
| 小更新 `x.y.Z` | 只修 bug、改文案、调参数 |
| 中更新 `x.Y.z` | 新增功能、重构模块、交互变化（本版属于这一类） |
| 大更新 `X.y.z` | 不兼容改动、整体重做、配置结构破坏性变化 |

## 怎么用

1. 下载本页下方的 `DeskScout.exe`，双击即可，免安装。
2. 首次启动自动扫描（通常 5–15 秒，商店应用那段最慢）。
3. 在「已安装软件」页筛选、勾选，点「为选中项创建快捷方式」，直接完成。
4. 想换图标或加备注：右键条目看详情，图标与发布者都在里面。

系统要求：Windows 10 / 11（64 位）。程序不写系统目录、不改系统设置，
配置只放在 `%APPDATA%\DeskScout\config.json`，图标缓存放在 `%APPDATA%\DeskScout\icons\`。

## 已知限制

- 商店应用的枚举依赖 PowerShell 的 `Get-StartApps` 与 `Get-AppxPackageManifest`，企业策略禁用 PowerShell 时该来源会为空。
- Steam 只统计库中已安装（`appmanifest_*.acf` 存在）的游戏，未下载的不计入。
- 绿色软件需要手动指定目录扫描，程序不会全盘遍历（避免拖慢启动、误扫系统目录）。
- 桌面容量按图标网格估算，开启特殊布局（如分组）时数字可能有偏差。
- GitHub 发布者识别依赖本机线索：压缩包解压后丢失下载来源、或安装包没有写链接的，会保持原发布者或留空。

## 反馈

发现问题请到 [Issues](https://github.com/zlwzk/deskscout/issues) 反馈，附上软件名称与安装方式（安装包 / 商店 / 免安装），我会据此补规则。

---

**DeskScout v1.1.0 · MIT License · 纯本地运行，不上传任何数据**

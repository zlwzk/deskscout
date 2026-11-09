# DeskScout · 桌面应用管家

> 扫一遍本机，把该在桌面上的软件补齐。全程本地运行，不上传任何数据。

DeskScout 是一个 Windows 桌面小工具：它用多种方式把本机**真正安装的软件**找出来，
自动排除 Microsoft 系统组件、运行库、补丁和驱动，但**保留 Microsoft Store 里自行安装的应用**；
随后对照桌面已有的快捷方式，只把缺的那些，在你确认之后补到桌面。

![版本](https://img.shields.io/badge/version-1.0.0-2f6feb)
![平台](https://img.shields.io/badge/platform-Windows%2010%2F11-1f2430)
![依赖](https://img.shields.io/badge/dependencies-%E6%A0%87%E5%87%86%E5%BA%93%E5%8D%B3%E5%8F%AF-12805c)

---

## 为什么是它

| 常见做法 | 问题 |
| --- | --- |
| 只读注册表卸载项 | 绿色软件、商店应用全部漏掉 |
| 只扫开始菜单 | 会把「卸载」「帮助文档」「官网链接」当成软件 |
| 把所有 AppX 都扫进来 | 系统框架、驱动包、语言包混进来，列表全是噪音 |
| 一键批量建快捷方式 | 桌面上重复一堆，还把桌面塞满 |

DeskScout 的做法是**多源交叉 + 逐条判定 + 名称去重 + 目录归并**，并且**先算桌面还剩多少格**，
再问你要不要创建。

## 功能

- **五种扫描来源**：注册表卸载项（HKLM / WOW6432Node / HKCU）、开始菜单、Microsoft Store、Steam 库、自定义目录（绿色软件）。
- **不误扫**：过滤卸载器、更新器、崩溃上报、帮助文档、官网链接、运行库、驱动、KB 补丁、Windows 自带工具；名称里的版本号、位数、别名后缀会被清洗后再去重。
- **商店应用照扫**：`Get-StartApps` + `Get-AppxPackage` 双路校验，排除 framework / 系统签名 / 不可移除包，只留用户自己装的。
- **桌面体检**：统计当前用户桌面 + 公共桌面的图标数、失效快捷方式、重复项，并按屏幕分辨率算出手动排列的图标网格容量。
- **创建前先检查空位**：空位不够会直接告诉你，可一键改为放进桌面子文件夹。
- **必须你同意**：所有快捷方式都在确认弹窗之后才创建，弹窗里会列出将创建的名称与位置。
- **已有快捷方式自动排除**：桌面已经有的不再重复创建。
- **自动更新**：启动时静默检查 GitHub Release，有新版本可在应用内下载并自动替换重启。
- **零依赖**：只用 Python 标准库（图标处理用 Pillow），快捷方式读写通过 ctypes 直接调用 `IShellLinkW`，不需要 pywin32。
- **命令行模式**：`DeskScout.exe --scan` 可直接输出清单或导出 CSV。

## 使用

### 直接运行

1. 从 [Releases](https://github.com/zlwzk/deskscout/releases) 下载 `DeskScout.exe`。
2. 双击运行，首次会自动扫描（约 5–15 秒，取决于软件数量与磁盘速度）。
3. 在「已安装软件」页筛选、勾选，点「为选中项创建快捷方式」。
4. 确认弹窗会告诉你：将创建多少个、放在哪里、桌面还剩几格。

程序不写系统目录、不改注册表（只在开启「开机自启动」时写入当前用户的 Run 项），
配置文件位于 `%APPDATA%\DeskScout\config.json`。

### 从源码运行

```powershell
git clone https://github.com/zlwzk/deskscout.git
cd deskscout
python -m venv .venv
.\.venv\Scripts\pip install pillow
.\.venv\Scripts\python DeskScout.py
```

### 命令行

```powershell
DeskScout.exe --scan                 # 打印扫描结果
DeskScout.exe --scan --json          # 输出 JSON
DeskScout.exe --scan --csv out.csv   # 导出 CSV 清单
DeskScout.exe --scan --folder D:\Tools   # 额外扫描绿色软件目录
DeskScout.exe --version
```

## 扫描与过滤是怎么做的

```
注册表 Uninstall ─┐
开始菜单 .lnk     ─┤
Microsoft Store   ─┼─→ 归一化 → 系统组件判定 → 启动目标校验 → 名称清洗 → 去重 → 目录归并 → 桌面比对
Steam 库          ─┤
自定义目录        ─┘
```

几条关键规则：

1. **系统组件判定**：发布者/名称/安装位置命中 Microsoft Visual C++、.NET Framework、Windows SDK、Driver、Update for、KB 补丁、Runtime、Redistributable 等特征即排除；`SystemComponent=1`、`ParentKeyName` 存在、`ReleaseType` 为 Update/Hotfix 同样排除。
2. **商店应用例外**：来源为 AppX 的条目走独立规则，只排除 framework、`SignatureKind` 为 System/None、以及系统不可移除包。
3. **启动目标校验**：`DisplayIcon`、猜测目录里的 exe 都要过 `unins/setup/update/repair/crash/report/helper` 之类的黑名单，避免把卸载器当主程序。
4. **名称清洗**：循环剥离「版本 1.2」「v1.2」「(x64)」「(64-位)」「User」「启动器/客户端/Launcher」等后缀，再做指纹去重。
5. **套件归并**：同一安装目录下的多个入口（Git CMD、AutoCAD 参照管理器、WPS 配置工具）归并到主程序，不会在桌面铺一堆子工具。
6. **不按路径去重**：不同软件可能共用同一个启动器（例如 Anaconda 里的 `pythonw.exe` 同时承载 Navigator 与 Spyder），按路径合并会误吞软件，因此只按名称指纹去重。

## 隐私

- 扫描结果只存在内存与本地配置文件中，**不联网上传**。
- 应用只在「检查更新」时访问 GitHub Releases API，请求里不含任何本机软件信息。
- 导出的 CSV 只包含软件名称、版本、发布者、启动路径，不含用户名以外的系统信息；是否导出由你决定。
- 仓库与发布包中不含开发者个人信息、邮箱、机器名或桌面文件清单。

## 常见问题

**Q：为什么某个软件没扫到？**
A：先确认它是否在「设置 → 扫描范围」里勾选了对应来源；绿色软件请用「自定义目录」指定路径。若仍未出现，欢迎提 Issue 并附上该软件的安装方式（安装包 / 商店 / 免安装）。

**Q：为什么某些系统自带应用出现在列表里？**
A：默认已排除 Windows 自带工具与运行库；如果你在设置里打开了「显示系统组件」，它们会重新出现，便于排查。

**Q：桌面空位是怎么算的？**
A：按当前屏幕工作区与系统图标单元尺寸换算可容纳的图标格数，再减去桌面上已有的项目。不同 DPI 缩放下格子数量会不同。

**Q：创建错了怎么办？**
A：DeskScout 只新建快捷方式，不移动、不删除任何已有文件；直接删掉新建的 `.lnk` 即可。

## 开发

```
deskscout/
  models.py      数据模型
  filters.py     名称清洗、系统组件识别、去重
  com.py         IShellLinkW / IPersistFile（ctypes 手写）
  scanners.py    注册表、开始菜单、商店、Steam、目录扫描
  engine.py      编排、归并、桌面比对
  desktop.py     桌面枚举与容量计算
  shortcuts.py   命名避让与批量创建
  config.py      配置读写
  icons.py       图标提取与首字母色块
  updater.py     Release 检查与自替换
  ui.py          Tkinter 界面
  main.py        入口（GUI / CLI）
dev/             开发期自检脚本与资源生成脚本
```

打包：

```powershell
.\build.ps1
```

产物在 `dist\DeskScout.exe`。

## 许可

MIT License，详见 [LICENSE](LICENSE)。

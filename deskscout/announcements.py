"""应用内更新公告：每个版本发布时把说明内置到程序里，离线也能看.

config["update"]["inbox"] 保存用户收到过的公告，形成应用内“收件箱”；
config["update"]["last_seen_version"] 用来判断是否需要在升级后弹一次窗。
"""

from __future__ import annotations

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
}


def notes_for(version: str) -> str:
    return ANNOUNCEMENTS.get(version, "")


def title_for(version: str) -> str:
    return f"DeskScout v{version} 更新公告"


def latest_version() -> str:
    return max(ANNOUNCEMENTS, key=lambda v: tuple(int(p) for p in v.split(".") if p.isdigit()) or (0,))

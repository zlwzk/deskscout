"""命令行入口：支持 --scan 无界面扫描与 --version."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys

from . import APP_NAME, APP_NAME_CN, __version__, config, desktop, engine, health, history
from .models import ScanOptions


def _single_instance() -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "DeskScout.SingleInstance")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        return True
    except (AttributeError, OSError):
        return True


def cli_scan(options: ScanOptions, as_json: bool, csv_path: str,
             diff: bool = False, with_health: bool = False) -> int:
    cfg = config.load()
    items = desktop.scan_desktop()
    engine.find_duplicate_targets(items)
    report = engine.scan_all(options, items, lambda message, percent: None, config=cfg)
    capacity = desktop.desktop_capacity()
    changes = history.diff(report.entries)
    history.save(report.entries)

    report_data = None
    if with_health:
        health.measure_sizes(report.entries)
        report_data = health.build_report(report.entries, items, capacity)

    if as_json:
        payload = {
            "version": __version__,
            "raw_count": report.raw_count,
            "app_count": len(report.entries),
            "merged_count": report.merged_count,
            "blocked_count": report.blocked_count,
            "elapsed_ms": report.elapsed_ms,
            "source_stats": report.source_stats,
            "desktop": capacity,
            "changes": changes,
            "apps": [
                {
                    "name": entry.name,
                    "version": entry.version,
                    "publisher": entry.publisher,
                    "source": entry.source,
                    "category": entry.category,
                    "target": entry.target,
                    "install": entry.install_location,
                    "homepage": entry.homepage,
                    "size": entry.size_bytes,
                    "last_used": entry.last_used,
                    "shortcut": entry.shortcut_name,
                    "invalid": entry.invalid,
                }
                for entry in report.entries
            ],
        }
        if report_data:
            payload["health"] = report_data
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{APP_NAME_CN} {APP_NAME} v{__version__}")
        print(f"原始记录 {report.raw_count} 条 → 应用 {len(report.entries)} 个"
              f"（合并 {report.merged_count} 条"
              + (f"，屏蔽 {report.blocked_count} 条" if report.blocked_count else "")
              + f"，用时 {report.elapsed_ms} ms）")
        print(f"桌面容量 {capacity.get('columns')}×{capacity.get('rows')}，"
              f"已用 {capacity.get('used')}，剩余 {capacity.get('free')}")
        if diff:
            print(history.diff_text(changes))
        print(f"{'名称':<32}{'版本':<14}{'来源':<12}快捷方式")
        print("-" * 78)
        for entry in report.entries:
            name = entry.name if len(entry.name) <= 30 else entry.name[:29] + "…"
            print(f"{name:<32}{entry.version:<14}{entry.source_label:<12}"
                  f"{entry.shortcut_name or ('—' if entry.target else '无目标')}")
        if report_data:
            print()
            print(health.report_text(report_data))

    if csv_path:
        import csv

        with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["名称", "版本", "发布者", "来源", "类别", "体积", "最近使用",
                             "桌面快捷方式", "启动目标"])
            for entry in report.entries:
                writer.writerow([entry.name, entry.version, entry.publisher, entry.source_label,
                                 entry.category_label, entry.size_bytes, entry.last_used,
                                 entry.shortcut_name or "无", entry.target])
        print(f"清单已写入：{csv_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="DeskScout", description=f"{APP_NAME_CN} / {APP_NAME}")
    parser.add_argument("--version", action="store_true", help="显示版本号后退出")
    parser.add_argument("--scan", action="store_true", help="无界面扫描并打印结果")
    parser.add_argument("--json", action="store_true", help="配合 --scan，输出 JSON")
    parser.add_argument("--csv", default="", help="配合 --scan，导出 CSV 清单")
    parser.add_argument("--diff", action="store_true", help="配合 --scan，对比上次结果输出新增/消失软件")
    parser.add_argument("--health", action="store_true", help="配合 --scan，附带软件体检（体积/最近使用）")
    parser.add_argument("--no-store", action="store_true", help="跳过 Microsoft Store 扫描")
    parser.add_argument("--include-system", action="store_true", help="包含系统组件")
    parser.add_argument("--folder", default="", help="额外扫描指定目录（绿色软件）")
    parser.add_argument("--tab", type=int, default=None, help="启动时选中指定标签页（0/1/2）")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0

    if args.scan:
        options = ScanOptions(
            store=not args.no_store,
            include_system=args.include_system,
            folder=bool(args.folder),
            custom_folder=args.folder,
        )
        return cli_scan(options, args.json, args.csv, diff=args.diff, with_health=args.health)

    if not _single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(None, "DeskScout 已经在运行了。", APP_NAME_CN, 0x40)
        except (AttributeError, OSError):
            pass
        return 0

    from .ui import run

    run(args.tab)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""开发期自检：跑一遍完整扫描并打印结果，用来校准过滤规则."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskscout import desktop, engine
from deskscout.models import ScanOptions

def main():
    t0 = time.time()
    desk = desktop.scan_desktop()
    engine.find_duplicate_targets(desk)
    cap = desktop.desktop_capacity()
    report = engine.scan_all(ScanOptions(), desk, lambda m, p: None)
    print("elapsed %.2fs raw=%d filtered=%d merged=%d final=%d" % (
        time.time()-t0, report.raw_count, report.filtered_count, report.merged_count, len(report.entries)))
    print("stats", report.source_stats)
    print("capacity", cap)
    print("desktop", len(desk), "with shortcut", sum(1 for e in report.entries if e.has_shortcut),
          "pending", sum(1 for e in report.entries if e.launchable and not e.has_shortcut))
    print("-" * 100)
    for e in report.entries:
        flag = "✓" if e.has_shortcut else ("!" if e.invalid else " ")
        print(f"{flag} [{e.source:8}] {e.name[:42]:42} v{e.version[:12]:12} {e.category:8} {e.note[:24]:24} {e.target[:60]}")
    print("-" * 100)
    # 被判定为系统组件的，抽样看看是否误杀
    sys_entries = [e for e in report.entries if e.category == "system"]
    print("system kept (should be 0 when include_system=False):", len(sys_entries))

if __name__ == "__main__":
    main()

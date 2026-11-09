"""检查扫描结果里的重复名称与指纹，定位去重漏网."""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deskscout import desktop, engine
from deskscout.filters import normalize_name, clean_display_name
from deskscout.models import ScanOptions

desk = desktop.scan_desktop()
rep = engine.scan_all(ScanOptions(), desk)
groups = collections.defaultdict(list)
for e in rep.entries:
    groups[normalize_name(e.name)].append(e)
for key, items in groups.items():
    if len(items) > 1:
        print("DUP", repr(key), len(items))
        for i in items:
            print("   ", repr(i.name), i.source, i.target)
print("total", len(rep.entries))
print("---- names ----")
for e in rep.entries:
    if any(ord(c) > 127 for c in e.name) or "  " in e.name:
        print(repr(e.name))

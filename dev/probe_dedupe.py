"""定位去重失效的原因."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deskscout.filters import dedupe, normalize_name, _score
from deskscout.models import AppEntry
from deskscout import scanners

a = AppEntry(key="a", name="Spyder", source="startmenu", target=r"C:\ProgramData\anaconda3\pythonw.exe")
b = AppEntry(key="b", name="Spyder", source="startmenu", target=r"E:\ProgramData\anaconda3\pythonw.exe")
print("fp equal:", normalize_name(a.name) == normalize_name(b.name), repr(normalize_name(a.name)), repr(normalize_name(b.name)))
print("scores:", _score(a), _score(b))
print("dedupe:", [(e.name, e.key) for e in dedupe([a, b])[0]], dedupe([a, b])[1])

# 真实扫描里抓一遍开始菜单
items = scanners.scan_start_menu()
sp = [e for e in items if e.name == "Spyder"]
print("raw startmenu spyder:", [(e.key, e.target) for e in sp])
res, merged = dedupe(items)
sp2 = [e for e in res if e.name == "Spyder"]
print("after dedupe spyder:", [(e.key, e.target) for e in sp2], "merged", merged)

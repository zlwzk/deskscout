"""开发期自检：COM 快捷方式读写 + 桌面解析 + 容量计算."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskscout import com, desktop

tmp = tempfile.mkdtemp(prefix="dsm_")
lnk = os.path.join(tmp, "测试 快捷方式.lnk")
ok = com.create_shortcut(lnk, r"C:\Windows\System32\notepad.exe", working_dir=r"C:\Windows",
                         icon=r"C:\Windows\System32\notepad.exe", description="DeskScout 自检")
print("create:", ok, os.path.exists(lnk), os.path.getsize(lnk) if os.path.exists(lnk) else 0)
print("read:", com.read_shortcut(lnk))

url = os.path.join(tmp, "站点.url")
print("url create:", com.create_url_shortcut(url, "https://example.com"), com.read_url_shortcut(url))

items = desktop.scan_desktop()
print("desktop items:", len(items))
for it in items[:6]:
    print(" ", it.kind, it.name, "->", it.target or "(shell)", it.status_label)
cap = desktop.desktop_capacity()
print("capacity:", cap)
print("dups:", len([i for i in items if i.duplicate_of]), "broken:", len([i for i in items if i.broken]))
shutil.rmtree(tmp, ignore_errors=True)

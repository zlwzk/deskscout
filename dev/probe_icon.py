"""测试图标提取与快捷方式创建."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk
from deskscout import icons, shortcuts
from deskscout.models import AppEntry

root = tk.Tk()
root.withdraw()
exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
img = icons.get_icon(exe, "Chrome", 32)
print("icon chrome:", img, getattr(img, "width", lambda: -1)())
img2 = icons.get_icon("", "网易云音乐", 32)
print("letter tile:", img2)
img3 = icons.get_icon(r"C:\Windows\System32\notepad.exe", "Notepad", 48)
print("icon notepad:", img3)

tmp = tempfile.mkdtemp()
entries = [
    AppEntry(key="1", name="网易云音乐", target=exe, working_dir=os.path.dirname(exe), icon_path=exe),
    AppEntry(key="2", name="网易云音乐", target=exe, working_dir=os.path.dirname(exe), icon_path=exe),
    AppEntry(key="3", name='A/B:C*?"<>| 测试', target=exe),
    AppEntry(key="4", name="坏目标", target=""),
]
res = shortcuts.create_for_entries(entries, os.path.join(tmp, "新建快捷方式"))
print("created:", res.created)
print("skipped:", res.skipped, "failed:", res.failed)
print("files:", sorted(os.listdir(os.path.join(tmp, "新建快捷方式"))))
root.destroy()
shutil.rmtree(tmp, ignore_errors=True)

"""离屏验证创建流程：空间检查、同意确认、已存在跳过。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deskscout.config as cfgmod
import deskscout.desktop as deskmod
from deskscout import ui
from deskscout.models import AppEntry

base = cfgmod.DEFAULTS
patched = {**base, "ui": {**base["ui"], "auto_scan_on_start": False},
           "scan": {**base["scan"]}}
cfgmod.load = lambda: patched

app = ui.DeskScoutApp()
app.entries = [
    AppEntry(key="a", name="网易云音乐", target=r"C:\Windows\System32\notepad.exe", source="registry"),
    AppEntry(key="b", name="QT", target=r"C:\Windows\System32\calc.exe", source="registry"),
    AppEntry(key="c", name="已有项", target=r"C:\Windows\System32\mspaint.exe", source="registry",
             shortcut_name="已有项"),
]
app.refresh_view()

dialogs = []
real_yesno = ui.messagebox.askyesno
real_info = ui.messagebox.showinfo
ui.messagebox.askyesno = lambda title, message, **kw: (dialogs.append(("ask", title, message)), False)[1]
ui.messagebox.showinfo = lambda title, message, **kw: dialogs.append(("info", title, message))

# 1) 未选中
app.tree.selection_set(())
app.create_selected()
print("case1:", dialogs[-1][:2])

# 2) 选中三个（其中一个已有、一个无目标），桌面无空位
app.tree.selection_set(app.tree.get_children())
deskmod.desktop_capacity = lambda: {"work_area": (0, 0, 1920, 1040), "cell": (75, 75),
                                    "columns": 25, "rows": 13, "total": 325, "used": 325,
                                    "free": 0, "dpi_scale": 1.0,
                                    "disk_free": 12 * 1024 ** 3, "disk_total": 200 * 1024 ** 3}
dialogs.clear()
app.create_selected()
for kind, title, message in dialogs:
    print(f"case2 [{kind}] {title}\n{message}\n{'-' * 40}")

# 3) 空间充足，确认文案
deskmod.desktop_capacity = lambda: {"work_area": (0, 0, 1920, 1040), "cell": (75, 75),
                                    "columns": 25, "rows": 13, "total": 325, "used": 73,
                                    "free": 252, "dpi_scale": 1.0,
                                    "disk_free": 12 * 1024 ** 3, "disk_total": 200 * 1024 ** 3}
dialogs.clear()
app.create_selected()
for kind, title, message in dialogs:
    print(f"case3 [{kind}] {title}\n{message}\n{'-' * 40}")

ui.messagebox.askyesno = real_yesno
ui.messagebox.showinfo = real_info
print("status:", app.status_text.cget("text"))
app.destroy()

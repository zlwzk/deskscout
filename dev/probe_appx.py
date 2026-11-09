"""调试 AppX 扫描脚本的执行与输出."""
import os, sys, json, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deskscout.scanners import _APPX_SCRIPT, _powershell_path

fd, out = tempfile.mkstemp(suffix=".json")
os.close(fd)
script = _APPX_SCRIPT.replace("__OUT__", out.replace("'", "''"))
script_path = out + ".ps1"
with open(script_path, "w", encoding="utf-8") as f:
    f.write(script)
r = subprocess.run([_powershell_path(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", script_path], capture_output=True, text=True)
print("rc", r.returncode)
print("stdout", (r.stdout or "")[:800])
print("stderr", (r.stderr or "")[:1500])
print("out exists", os.path.exists(out), os.path.getsize(out))
if os.path.getsize(out):
    data = json.load(open(out, encoding="utf-8-sig"))
    print("keys", list(data)[:5], "start", len(data.get("start") or []), "pkgs", len(data.get("pkgs") or []))
    for a in (data.get("start") or [])[:6]:
        print("  ", a)

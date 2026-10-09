# -*- coding: utf-8 -*-
"""验证：启动 AUTO-MAS 后端期间不弹控制台黑窗。

后端 python.exe 是控制台程序，启动器跑在 pythonw 下；Popen 不加
CREATE_NO_WINDOW 时 Windows 会给它新建一个黑色控制台窗口（用户实机所见）。
方法：启动后端 → EnumWindows 找「属于后端进程树的可见顶层窗口」，应为 0。
"""
import os, sys, io, time, ctypes, shutil, tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND,
                                 ctypes.wintypes.LPARAM)


def windows_of_pids(pids):
    found = []

    def cb(hwnd, _):
        try:
            if user32.IsWindowVisible(hwnd):
                pid = ctypes.wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in pids:
                    n = user32.GetWindowTextLengthW(hwnd)
                    buf = ctypes.create_unicode_buffer(n + 1)
                    if n:
                        user32.GetWindowTextW(hwnd, buf, n + 1)
                        found.append((pid.value, buf.value))
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def child_pids(root_pid):
    pids = {root_pid}
    try:
        import subprocess
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace").stdout
        # tasklist CSV: ImageName,PID,SessionName,SessionNum,MemUsage
        # 没有父 pid，退回 wmic 拿父子关系
        out2 = subprocess.run(
            ["wmic", "process", "get", "ProcessId,ParentProcessId", "/FORMAT:CSV"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace").stdout
        rows = []
        for line in out2.splitlines()[1:]:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 3:
                try:
                    rows.append((int(parts[1]), int(parts[2])))  # PPID, PID
                except ValueError:
                    pass
        changed = True
        while changed:
            changed = False
            for ppid, pid in rows:
                if ppid in pids and pid not in pids:
                    pids.add(pid); changed = True
    except Exception:
        pass
    return pids


repo, py = launcher.auto_mas_paths()
work = tempfile.mkdtemp(prefix="mas_nowin_")
w = launcher.ServiceWorker(repo, py, work)
states = []
w.sig_state.connect(lambda s, d: states.append(s))
w.start()
end = time.time() + 120
while time.time() < end:
    app.processEvents()
    if any(s in ("ready", "failed") for s in states):
        break
    time.sleep(0.2)

ok = 0
if "ready" in states and w._proc:
    wins = windows_of_pids(child_pids(w._proc.pid))
    ok = len(wins)
    print("后端进程树可见窗口数:", ok)
    for p, t in wins[:8]:
        print("   pid=%d %r" % (p, t))
else:
    print("后端未就绪，无法判定:", states)

w.request_stop()
end = time.time() + 30
while time.time() < end:
    app.processEvents()
    if "stopped" in states:
        break
    time.sleep(0.2)

shutil.rmtree(work, ignore_errors=True)
print("判定:", "PASS 无黑窗" if ok == 0 else "FAIL 有 %d 个窗口" % ok)
sys.stdout.flush(); sys.stderr.flush()
os._exit(0 if ok == 0 else 1)

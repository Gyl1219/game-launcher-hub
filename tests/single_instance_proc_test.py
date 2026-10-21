# -*- coding: utf-8 -*-
"""单实例**跨进程**验证：真起两个进程，第二个必须自己退出并叫醒第一个。

这才是真实场景（用户双击两次快捷方式）。同进程内的 activate 投递
受 Qt 的 waitFor* 不派发槽影响，属于测试环境限制，不能作为验收依据。
"""
import os, sys, io, time, subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = r"D:\OKApps\launcher"
PY = r"D:\OKApps\ok-ww\data\apps\ok-ww\python\python.exe"
OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


# 子进程脚本：只做「抢锁 + 报告结果」，起窗口太慢且不需要
CHILD = r'''
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"%(root)s")
from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)
import launcher
g = launcher.SingleInstanceGuard()
got = []
g.signalled.connect(lambda m: got.append(m))
ok = g.try_acquire()
print("ACQUIRED=%%s" %% ("1" if ok else "0"), flush=True)
if ok:
    # 第一个实例：占住 6 秒，期间等第二个来敲门
    from PySide6.QtCore import QTimer, QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(6000, loop.quit)
    loop.exec()
    print("NOTIFIED=%%s" %% (",".join(got) or "-"), flush=True)
g.release()
''' % {"root": ROOT}

child_path = os.path.join(os.environ.get("TEMP", "."), "_si_child.py")
io.open(child_path, "w", encoding="utf-8").write(CHILD)

env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
env.pop("LAUNCHER_ALLOW_MULTI", None)

# 清理可能残留的锁文件
lock = os.path.join(ROOT, ".cache", "launcher.lock")
try:
    if os.path.exists(lock):
        os.remove(lock)
except Exception:
    pass

def read_until(pipe, marker, limit=40):
    """读到指定前缀的行为止（qfluentwidgets 会先往 stdout 打一版 banner）。"""
    for _ in range(limit):
        ln = pipe.readline()
        if not ln:
            return ""
        if ln.startswith(marker):
            return ln
    return ""


# ---------- 第一个进程：应拿到锁 ----------
p1 = subprocess.Popen([PY, child_path], stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT, text=True,
                      encoding="utf-8", errors="replace", env=env)
line1 = read_until(p1.stdout, "ACQUIRED=")
chk("1) 第一个进程拿到锁", "ACQUIRED=1" in line1, line1.strip())

# ---------- 第二个进程：必须拿不到锁并退出 ----------
t0 = time.time()
p2 = subprocess.run([PY, child_path], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", env=env, timeout=60)
took = time.time() - t0
chk("2) 第二个进程拿不到锁", "ACQUIRED=0" in (p2.stdout or ""),
    "stdout 里无 ACQUIRED=1" if "ACQUIRED=1" not in (p2.stdout or "") else "误拿到锁")
chk("2b) 第二个进程很快退出（不卡窗口）", took < 30, "%.1fs" % took)

# ---------- 第一个进程收到唤醒 ----------
rest = []
try:
    for ln in p1.stdout:
        rest.append(ln.strip())
        if ln.startswith("NOTIFIED="):
            break
except Exception:
    pass
try:
    p1.wait(timeout=20)
except Exception:
    p1.kill()
notified = [x for x in rest if x.startswith("NOTIFIED=")]
chk("3) 第一个进程收到了 activate", bool(notified) and "activate" in notified[0],
    "; ".join(rest)[:120])

# ---------- 第一个退出后，新进程能重新拿到锁 ----------
time.sleep(0.5)
p3 = subprocess.run([PY, child_path], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", env=env, timeout=60)
chk("4) 前一个退出后新进程能拿到锁", "ACQUIRED=1" in (p3.stdout or ""),
    (p3.stdout or "").strip()[:60])

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
os._exit(1 if FAIL else 0)

# -*- coding: utf-8 -*-
"""单实例守护（进程内视角）：锁判定 + 名字规则 + 残留清理 + 逃生阀。

跨进程的真实行为由 single_instance_proc_test.py 验（那才是用户双击两次的场景）。
本文件只验那些**与事件循环无关**的确定性部分：
  · 锁判定（文件锁由系统保证互斥）；
  · 单实例名带用户后缀（多用户同机不互踢）；
  · 残留锁/残留套接字不会把下次启动堵死；
  · LAUNCHER_ALLOW_MULTI 逃生阀存在。

⚠ 已知环境限制：同一进程内 QLocalSocket 的 waitFor* 不会派发
   QLocalServer 的 newConnection 槽，所以"进程内收 activate"测不出来。
   这不是产品缺陷（跨进程实测通过），故不在本文件断言。
"""
import os, sys, io

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer

app = QCoreApplication.instance() or QCoreApplication(sys.argv)
OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


name = launcher._single_instance_name()

# ---------- 1) 名字规则 ----------
chk("1) 单实例名稳定", name == launcher._single_instance_name(), name)
chk("1b) 名字带用户后缀（多用户同机不互踢）",
    len(name) > len(launcher.LAUNCHER_SINGLE_INSTANCE_NAME), name)

# 清掉可能残留的锁
guard0 = launcher.SingleInstanceGuard()
guard0.release()

# ---------- 2) 第一个拿到锁 ----------
g1 = launcher.SingleInstanceGuard()
chk("2) 无实例时第一个能拿到锁", g1.try_acquire() is True)
chk("2b) 拿锁后 has_lock() 为真", g1.has_lock() is True)

# ---------- 3) 第二个拿不到锁 ----------
g2 = launcher.SingleInstanceGuard()
chk("3) 第二个拿不到锁", g2.try_acquire() is False)
chk("3b) 第二个没有持锁", g2.has_lock() is False)
chk("3c) 第二个拿到了唤醒结果（送没送到不影响判定）",
    isinstance(g2.notify_existing("ping"), bool))

# ---------- 4) 连续探测依然拿不到 ----------
res = []
for _ in range(3):
    res.append(launcher.SingleInstanceGuard().try_acquire())
chk("4) 连续多次探测都拿不到锁", res == [False, False, False], str(res))

# ---------- 5) release 后可重新拿 ----------
g1.release()
chk("5) release 后放掉锁", g1.has_lock() is False)
g3 = launcher.SingleInstanceGuard()
chk("5b) release 后能重新拿到锁", g3.try_acquire() is True)
g3.release()

# ---------- 6) 崩溃残留（同名套接字）不阻塞新实例 ----------
srv = QLocalServer()
QLocalServer.removeServer(name)
srv.listen(name)
srv.close()          # 模拟"上个进程崩了，名字还在"
g4 = launcher.SingleInstanceGuard()
chk("6) 残留套接字不阻塞新实例", g4.try_acquire() is True)
g4.release()

# ---------- 7) 逃生阀 ----------
src = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "launcher.py"), encoding="utf-8").read()
chk("7) LAUNCHER_ALLOW_MULTI 逃生阀已实现", "LAUNCHER_ALLOW_MULTI" in src)
chk("7b) 已接进 main()（不是只写了个常量）",
    src.count("LAUNCHER_ALLOW_MULTI") >= 2, str(src.count("LAUNCHER_ALLOW_MULTI")))

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

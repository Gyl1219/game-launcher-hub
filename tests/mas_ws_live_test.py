# -*- coding: utf-8 -*-
"""实时通道端到端：对着**真后端**验 WebSocket 能连、能收真事件、能让位。

协议层的字节正确性由 mas_ws_test.py 钉死；这里验的是「装进车里能开」：
  1) 后端就绪后页面自动接上实时通道，握手 101 + accept 校验通过；
  2) 第二个连接进来时（上游只允许一条主连接）页面收到 4001 并**主动让位不重连**
     —— 这条很重要：不让位就会和官方界面互踢；
  3) 真事件帧能收到并解析（拿 /api/core/close 触发的 backend.shutdown.ready 当样本）。

用临时数据目录，不碰用户真实 auto-mas 数据。
"""
import os, sys, io, time, tempfile, shutil, subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtWidgets import QApplication

OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


def finish(code):
    print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
    for f in FAIL:
        print("   FAILED:", f)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


repo, py = launcher.auto_mas_paths()
if not (repo and py and os.path.isfile(py)):
    print("SKIP: 本机没有可用的 AUTO-MAS 后端（vendor/auto-mas + Python3.12 环境）")
    finish(0)

TMP = tempfile.mkdtemp(prefix="mas_ws_home_")
launcher.auto_mas_home = lambda: TMP
app = QApplication.instance() or QApplication(sys.argv)


def wait(cond, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.2)
    app.processEvents()
    return cond()


win = launcher.Launcher()
win.show()
page = win.mas_page
page._auto_started = True
win.switch_to(launcher.AUTO_MAS_MENU_KEY)
app.processEvents()

sub = None
try:
    # ---------- 1) 起后端 → 页面自动接实时通道 ----------
    page.start_backend()
    ok = wait(lambda: page._state in ("ready", "failed"), 180)
    chk("1) 后端 ready", ok and page._state == "ready",
        "%s %s" % (page._state, page._detail[:80]))
    if page._state != "ready":
        finish(1)
    chk("1b) 就绪后自动建了实时通道线程", page._events is not None)
    chk("1c) 握手成功（state=connected）",
        wait(lambda: page._ws_state == "connected", 30), page._ws_state)
    chk("1d) 实时页有连接状态提示",
        wait(lambda: "已连接" in page.live_note.text(), 5), page.live_note.text())

    # ---------- 2) 第二个连接 → 4001 让位 ----------
    got = []
    sub = launcher.MasEventClient(page._port)
    sub.sig_event.connect(lambda t, i, d: got.append((t, i, d)))
    sub_state = []
    sub.sig_state.connect(lambda s, d: sub_state.append(s))
    sub.start()
    chk("2) 第二个连接也握手成功",
        wait(lambda: "connected" in sub_state, 30), str(sub_state))
    chk("2b) 旧连接收到 4001 后主动让位（不重连）",
        wait(lambda: page._ws_state == "yielded", 30), page._ws_state)
    time.sleep(4)                     # 超过重连间隔，确认真的没再连上
    chk("2c) 让位后不再自动重连", page._ws_state == "yielded", page._ws_state)
    chk("2d) 界面明说「已被官方界面接管」",
        wait(lambda: "接管" in page.live_note.text(), 5), page.live_note.text())

    # ---------- 3) 真事件帧 ----------
    okc, _ = launcher.mas_api_request(page._base, "/api/core/close", {})
    chk("3) close 接口已调用", okc)
    got_shutdown = wait(lambda: any(e[0] == "backend.shutdown.ready" for e in got), 60)
    chk("3b) 收到 backend.shutdown.ready 真实事件帧", got_shutdown,
        "收到 %d 个事件：%s" % (len(got), [e[0] for e in got][:6]))
    if got_shutdown:
        ev = [e for e in got if e[0] == "backend.shutdown.ready"][0]
        chk("3c) 事件 id=Main（路由字段正确）", ev[1] == "Main", str(ev[:2]))

    # 后端真停掉之后，界面不能还挂着「已连接」（让位说明也要收回去）
    wait(lambda: page._state in ("stopped", "failed"), 30)
    chk("3d) 后端停止后不再谎报已连接",
        wait(lambda: "已连接" not in page.live_note.text(), 5),
        page.live_note.text())
finally:
    if sub is not None:
        try:
            sub.request_stop()
            sub.wait(3000)
        except Exception:
            pass
    try:
        page.shutdown()
        win.close()
        app.processEvents()
    except Exception:
        pass
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=20).stdout
    orph = [l for l in out.splitlines() if "auto-mas" in l.lower()]
    chk("4) 无 AUTO-MAS 孤儿进程", not orph, "残留 %d" % len(orph))
    shutil.rmtree(TMP, ignore_errors=True)

finish(1 if FAIL else 0)

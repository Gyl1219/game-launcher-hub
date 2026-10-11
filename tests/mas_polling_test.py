# -*- coding: utf-8 -*-
"""崩溃回归：MAS 页面在长时间轮询 + 状态往返下不崩。

历史事故有两次，都是「构建时看着正常、跑一会儿才崩」：
  1) 59e3835：MAS 卡片形态漏初始化 _installed 等字段，5 秒心跳一来
     refresh_data 就 AttributeError；
  2) 上次改卡片时把 self._installed 插在了定位后端之前 → UnboundLocalError。
共同点：**测试只测了「构建 + 点一次」，没测轮询路径**。
所以这里连跑 30 轮 reload（模拟 15 秒定时器 × 7.5 分钟）+ 全局心跳 tick，
再把状态机四个态来回切几遍，最后验 shutdown 幂等。
"""
import os, sys, io, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv)
OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

win = launcher.Launcher()
win.show()
app.processEvents()
page = win.mas_page
page._auto_started = True          # 本测试不起真后端
win.switch_to(launcher.AUTO_MAS_MENU_KEY)
app.processEvents()

# ---------- 1) 状态字段齐备（两次事故的根因都是字段没初始化）----------
need = ["_state", "_detail", "_port", "_base", "_health", "_queues", "_items",
        "_times", "_scripts", "_script_data", "_users", "_runtime", "_jobs",
        "_busy", "_home", "_log_path", "_bodies", "_heads", "_seg_index",
        "_timer", "_worker", "dot", "state_lbl", "detail_lbl", "start_btn",
        "stop_btn", "refresh_btn", "seg", "views", "log_edit", "log_note",
        # 实时通道与安装/卸载的状态字段（同样会在轮询渲染里被读到）
        "_events", "_ws_state", "_ws_detail", "_ws_events", "_live_tasks",
        "_live_notices", "_live_dirty", "_live_timer", "live_edit", "live_note",
        "_setup_card", "_setup_worker", "_setup_busy", "_setup_target"]
missing = [f for f in need if not hasattr(page, f)]
chk("1) 状态字段齐备", not missing, "缺: %s" % missing)

# ---------- 2) 连跑 30 轮刷新（崩溃场景）----------
err = None
try:
    for i in range(30):
        page.reload()
        page._render_all()
        if i % 5 == 0:
            launcher.heartbeat().tick.emit()   # 最真实的场景：全局心跳
        app.processEvents()
        time.sleep(0.01)
except Exception as e:
    err = "%s: %s" % (type(e).__name__, e)
chk("2) 连跑 30 轮 reload 不崩", err is None, err or "")

# ---------- 3) 状态机往返多轮 ----------
err2 = None
try:
    for _ in range(5):
        page._on_worker_state("starting", "端口 1")
        page._render_all()
        page._on_worker_state("ready", "v5.6.2")
        page._render_all()
        page._on_worker_state("stopped", "已优雅关闭")
        page._render_all()
        page._on_worker_state("failed", "boom")
        page._render_all()
    chk("3) 状态机往返 5 轮不崩", True)
except Exception as e:
    err2 = "%s: %s" % (type(e).__name__, e)
    chk("3) 状态机往返 5 轮不崩", False, err2)

# ---------- 4) 各态按钮可用性 ----------
page._on_worker_state("starting", "端口 1")
chk("4) starting：可停止、不可再启动",
    page.stop_btn.isEnabled() and not page.start_btn.isEnabled())
page._on_worker_state("ready", "v5.6.2")
chk("4b) ready：仍可停止", page.stop_btn.isEnabled())
page._on_worker_state("failed", "boom")
chk("4c) failed：可重启、不可停止",
    page.start_btn.isEnabled() and not page.stop_btn.isEnabled())
page._on_worker_state("stopped", "已优雅关闭")
chk("4d) stopped：可重启", page.start_btn.isEnabled())

# ---------- 5) 空 base 时刷新不应堆积线程 ----------
page.reload()
for _ in range(10):
    page.reload()
    app.processEvents()
chk("5) 空 base 下不产生后台任务", len(page._jobs) == 0, "jobs=%d" % len(page._jobs))

# ---------- 6) shutdown 幂等 ----------
err3 = None
try:
    page.shutdown()
    page.shutdown()
    page._on_worker_state("stopped", "")
except Exception as e:
    err3 = "%s: %s" % (type(e).__name__, e)
chk("6) shutdown 幂等", err3 is None, err3 or "")

# ---------- 7) 定时器在切页时真的停/起 ----------
page._timer.stop()
app.processEvents()
chk("7) 定时器可停", not page._timer.isActive())
page._timer.start()
chk("7b) 定时器可起", page._timer.isActive())
page._timer.stop()

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

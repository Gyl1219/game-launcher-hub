# -*- coding: utf-8 -*-
"""崩溃回归：MAS 卡在 5 秒轮询下不再 AttributeError。

事故：refresh_data 走到读 app_json 的分支，MAS 的 app_json 为空且
_installed 未初始化 → AttributeError: 'AppCard' object has no attribute '_installed'

本测试模拟多轮 heartbeat tick，确保不崩。
"""
import os, sys, io, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))


win = launcher.Launcher()
win.show()
app.processEvents()

card = win.cards.get("auto-mas")
chk("MAS 卡存在", card is not None)

if card:
    # 1) 状态字段齐备（事故根因）
    for f in ("_installed", "_host_ready", "_host_actual", "_install_dir",
              "data", "profile", "_mas", "_mas_state"):
        chk("字段 %s 已初始化" % f, hasattr(card, f))

    # 2) 连跑 30 轮 refresh_data（模拟 150 秒轮询）—— 这是崩溃场景
    err = None
    for i in range(30):
        try:
            card.refresh_data()
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            break
        app.processEvents()
    chk("2) 连跑 30 轮 refresh_data 不崩", err is None, err or "")

    # 3) snapshot 不崩（总览页每 5 秒读）
    err2 = None
    try:
        s = card.snapshot()
        chk("3) snapshot 返回 dict", isinstance(s, dict))
    except Exception as e:
        err2 = repr(e)
    chk("3b) snapshot 不崩", err2 is None, err2 or "")

    # 4) refresh_badge 不崩
    err3 = None
    try:
        card.refresh_badge()
    except Exception as e:
        err3 = repr(e)
    chk("4) refresh_badge 不崩", err3 is None, err3 or "")

    # 5) 全局心跳 tick 不崩（最真实场景）
    err4 = None
    try:
        for i in range(5):
            launcher.heartbeat().tick.emit()
            app.processEvents()
            time.sleep(0.05)
    except Exception as e:
        err4 = repr(e)
    chk("5) 心跳 tick 不崩", err4 is None, err4 or "")

    # 6) MAS 不被当成"未安装"去扫描游戏
    keys = [k for k, c in win.cards.items()
            if not (getattr(c, "_installed", False) or getattr(c, "_host_ready", False))]
    chk("6) MAS 不在待扫描列表", "auto-mas" not in keys, str(keys))

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

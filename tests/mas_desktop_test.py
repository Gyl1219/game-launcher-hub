# -*- coding: utf-8 -*-
"""验证「打开主界面」按钮与桌面版定位、端口显示。"""
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


# 1) 桌面版定位
exe = launcher.auto_mas_desktop_exe()
chk("1) 找到 AUTO-MAS 桌面版", bool(exe) and os.path.isfile(exe), exe or "未找到")

# 2) 卡片有「打开主界面」按钮
win = launcher.Launcher()
win.show()
app.processEvents()
card = win.cards.get("auto-mas")
chk("2) 卡片有 mas_open_btn", hasattr(card, "mas_open_btn"))
chk("2b) 按钮文案", card.mas_open_btn.text() == "打开主界面",
    card.mas_open_btn.text())
chk("2c) 找到桌面版时按钮可点", card.mas_open_btn.isEnabled())

# 3) ready 后详情带端口
card._mas_start()
end = time.time() + 120
while time.time() < end:
    app.processEvents()
    if getattr(card, "_mas_state", "") in ("ready", "failed"):
        break
    time.sleep(0.3)
detail = card.mas_detail.text()
port = getattr(card, "_mas_worker_port", 0)
chk("3) ready 详情含端口", "端口" in detail and str(port) in detail,
    "detail=%r port=%s" % (detail, port))

# 4) 停后端（不真开桌面版——offscreen 下弹窗会阻塞，直接验证等待逻辑存在）
card._mas_stop()
end = time.time() + 30
while time.time() < end:
    app.processEvents()
    if getattr(card, "_mas_state", "") == "stopped":
        break
    time.sleep(0.3)
chk("4) 停止成功", getattr(card, "_mas_state", "") == "stopped")

# 5) _mas_open_desktop / _mas_open_poll 方法存在
chk("5) 打开逻辑已接线", hasattr(card, "_mas_open_desktop")
    and hasattr(card, "_mas_open_poll"))

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush(); sys.stderr.flush()
os._exit(1 if FAIL else 0)

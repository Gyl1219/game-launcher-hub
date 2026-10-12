# -*- coding: utf-8 -*-
"""AUTO-MAS 入口分流单测：没装→下载安装，装了→进编排页。

用户明确的需求（本轮实现）：
  · launcher.exe 首发**不带** MAS（保持 ~112MB / GPL-3.0）；
  · 右上角始终显示 AUTO-MAS，不用的人不下载任何东西；
  · 需要用的人点一下 → 下载官方增量包并静默安装 → 自动进编排页；
  · 要用全功能（配账号/路径）→ 在编排页点「完整配置」开新窗口。

⚠ 前置：所有 QMessageBox 静态方法都必须先 mock。
   离屏环境下真弹模态框会**阻塞事件循环**（旧测试踩过），
   而安装成功/失败的回调里会弹 information/critical，漏 mock 就会卡死。

安全底线：本测试**绝不真的安装/卸载** AUTO-MAS
（本机已装真实副本），所有外部动作都换成记录桩。
"""
import os, sys, io

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

# ===== 先 mock 所有模态框，再创建窗口 =====
_answers = {"question": QMessageBox.No}


def _fake_question(*a, **k):
    return _answers.get("question", QMessageBox.No)


QMessageBox.question = staticmethod(_fake_question)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)

app = QApplication.instance() or QApplication(sys.argv)


class _FakeWorker(QObject):
    """假的 MasSetupWorker：记录接线、不真下载不真安装。

    必须提供与真 worker 相同的信号接口（progress/done/failed）+ start()/isRunning()，
    否则 Launcher 里的 connect / 重入守卫会 AttributeError。
    """

    progress = Signal(str)
    done = Signal(str)
    failed = Signal(str)
    made = []

    def __init__(self, *a, **k):
        super().__init__()
        _FakeWorker.made.append(1)

    def start(self):
        pass

    def isRunning(self):
        return False


OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


win = launcher.Launcher()
win.show()
app.processEvents()
ov = win.overview_page
KEY = launcher.AUTO_MAS_MENU_KEY

# ---------- 1) 右上角入口恒显示 ----------
chk("1) 右上角有 AUTO-MAS 入口", ov.mas_box.isVisibleTo(ov))
chk("1b) 按钮写着 AUTO-MAS", "AUTO-MAS" in ov.mas_btn.text(), ov.mas_btn.text())

# ---------- 2) 未装时：状态写「未安装」，点它走安装而不是切页 ----------
orig_info = launcher.auto_mas_installed_info
orig_worker = launcher.MasSetupWorker
launcher.auto_mas_installed_info = lambda: {}          # 模拟未装
try:
    ov.set_mas_installed(False)
    ov.set_mas_status("stopped")
    chk("2) 未装时状态写「未安装（点此下载）」",
        "未安装" in ov.mas_cap.text(), ov.mas_cap.text())

    # 选 No → 既不装也不切页
    _answers["question"] = QMessageBox.No
    launcher.MasSetupWorker = lambda *a, **k: _FakeWorker()
    _FakeWorker.made = []
    ov.mas_btn.click()
    app.processEvents()
    chk("2b) 未装时点按钮 → 弹安装确认（选否则不动）",
        win.stack.currentWidget() is ov and _FakeWorker.made == [],
        "页=%r 装=%d" % (type(win.stack.currentWidget()).__name__, len(_FakeWorker.made)))

    # 选 Yes → 启动安装
    _answers["question"] = QMessageBox.Yes
    calls = []
    launcher.MasSetupWorker = lambda target, *a, **k: (
        calls.append(target), _FakeWorker())[-1]
    ov.mas_btn.click()
    app.processEvents()
    chk("2c) 确认后确实启动了安装", len(calls) == 1, str(calls))
    chk("2d) 安装目标是 auto_mas_install_dir()",
        bool(calls) and calls[0] == launcher.auto_mas_install_dir(), str(calls))
    chk("2e) 安装中禁用按钮防连点",
        (not ov.mas_btn.isEnabled()) and "安装中" in ov.mas_btn.text(),
        "%s / %s" % (ov.mas_btn.isEnabled(), ov.mas_btn.text()))
finally:
    launcher.auto_mas_installed_info = orig_info
    launcher.MasSetupWorker = orig_worker

# ---------- 3) 装了之后：状态写「未启动」，点它直接进编排页 ----------
ov.set_mas_installed(True)
ov.set_mas_status("stopped")
chk("3) 已装时状态写「未启动」", "未启动" in ov.mas_cap.text(), ov.mas_cap.text())

# 上一步的安装是桩，没走完成回调 → 按钮还禁用着，先把它走完（真实流程就是这样）
win._on_mas_setup_done("v5.6.2")
app.processEvents()
win.switch_to("overview")
app.processEvents()
chk("3a) 装完后回到总览且按钮可点", ov.mas_btn.isEnabled(),
    "%s" % ov.mas_btn.isEnabled())

entry = []
launcher.MasSetupWorker = lambda *a, **k: (entry.append(1), _FakeWorker())[-1]
try:
    ov.mas_btn.click()
    app.processEvents()
    chk("3b) 已装时点按钮直接进编排页",
        win.stack.currentWidget() is win.mas_page,
        "页=%r" % type(win.stack.currentWidget()).__name__)
    chk("3c) 已装时不再触发安装", entry == [], str(entry))
finally:
    launcher.MasSetupWorker = orig_worker

# ---------- 4) 「完整配置」按钮 = 开新窗口做全功能 ----------
page = win.mas_page
chk("4) 编排页有「完整配置」按钮",
    hasattr(page, "open_desk_btn") and page.open_desk_btn.text() == "完整配置",
    getattr(getattr(page, "open_desk_btn", None), "text", lambda: None)())
exe = launcher.auto_mas_desktop_exe()
chk("4b) 探测到客户端时才可用",
    page.open_desk_btn.isEnabled() == bool(exe),
    "enabled=%s exe=%r" % (page.open_desk_btn.isEnabled(), exe))

opened = []
orig_run_exe = launcher.run_exe
launcher.run_exe = lambda parent, e, *a, **k: (opened.append(e), True)[-1]
try:
    page._open_desktop()
    if exe:
        chk("4c) 点「完整配置」打开官方客户端", opened == [exe], str(opened))
    else:
        chk("4c) 无客户端时不调用、只提示", opened == [], str(opened))
finally:
    launcher.run_exe = orig_run_exe

# ---------- 5) 安装完成回调：状态回正 + 自动进页 ----------
win.switch_to("overview")
app.processEvents()
win._on_mas_setup_done("v5.6.2")
app.processEvents()
chk("5) 装完按钮恢复可点", ov.mas_btn.isEnabled() and "AUTO-MAS" in ov.mas_btn.text(),
    "%s / %s" % (ov.mas_btn.isEnabled(), ov.mas_btn.text()))
chk("5b) 装完自动进入编排页", win.stack.currentWidget() is win.mas_page)

# ---------- 6) 安装失败回调：按钮恢复、不卡死 ----------
win._on_mas_setup_failed("网络错误")
app.processEvents()
chk("6) 安装失败后按钮恢复可点", ov.mas_btn.isEnabled())
chk("6b) 失败后状态回到 stopped", ov._mas_state == "stopped", ov._mas_state)
chk("6c) 本机真实安装未被测试触碰", bool(launcher.auto_mas_installed_info()))

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

# -*- coding: utf-8 -*-
"""托盘 + 关窗选择 契约测试（用户定稿：关窗弹选择框 + 「不再提醒」记住）。"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LAUNCHER_TELEMETRY_NOASK", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from PySide6.QtCore import Signal  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

fails = []


def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


_tmp = tempfile.mkdtemp(prefix="tray_test_")

# ---------- stubs：Launcher 构造里的网络 worker / MAS 页 / 托盘替身化 ----------
launcher.CatalogDownloadsWorker = type("W", (), {
    "__init__": lambda s, r, p=None: None, "start": lambda s: None})
launcher.GitHubStatsWorker = type("W", (), {
    "__init__": lambda s, p=None: None, "start": lambda s: None})
launcher.WishTotalsWorker = type("W", (), {
    "__init__": lambda s, r, p=None: None, "start": lambda s: None})
launcher.PosterWorker = type("W", (), {
    "__init__": lambda s, i, p=None: None, "start": lambda s: None})

real_tray_cls = launcher._TrayIcon


class _StubMasPage(QWidget):
    sig_status = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.shutdown_called = 0

    def shutdown(self):
        self.shutdown_called += 1


real_mas = launcher.MasPage
launcher.MasPage = _StubMasPage

real_cfg = launcher._load_cfg_safe
_cfg_state = {}


def _fake_cfg():
    return dict(_cfg_state)


launcher._load_cfg_safe = _fake_cfg
_saved = {}


def _fake_save(cfg):
    # 与真实行为一致：写回的键对后续 _load_cfg_safe 可见
    _cfg_state.clear()
    _cfg_state.update(cfg)
    _saved.update(cfg)
    return True


launcher._save_cfg_file = _fake_save


def make_launcher(cfg=None):
    _cfg_state.clear()
    _cfg_state.update(cfg or {})
    w = launcher.Launcher()
    w.show()
    app.processEvents()
    return w


def heartbeat_enabled():
    try:
        return bool(launcher.heartbeat()._enabled)
    except Exception:
        return None


# 假托盘：Launcher 场景不构造 QSystemTrayIcon（offscreen 下会崩，见文件尾说明）
class _FakeTray:
    def __init__(self, win):
        self.win = win
        self.tips = 0
        self.visible = False

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def show_minimized_tip(self):
        self.tips += 1

    def restore(self):
        self.win.restore_window()

    def quit_app(self):
        self.win._tray_force_exit = True
        self.win.close()
        try:
            launcher.QApplication.instance().quit()
        except Exception:
            pass


launcher._TrayIcon = _FakeTray


class _FakeLabel:
    def __init__(self, t=""):
        self._t = t

    def setText(self, t):
        self._t = t


class _FakeBtn:
    def setVisible(self, v):
        self.visible = v


# 关窗选择框替身：脚本化 (动作, 是否记住) 或取消
class _FakeCloseDlg:
    script = ("hide", True)
    rejected = False
    made = []

    def __init__(self, parent=None):
        _FakeCloseDlg.made.append(self)

    def exec(self):
        if _FakeCloseDlg.rejected:
            return launcher.QDialog.Rejected
        return launcher.QDialog.Accepted

    def result_pair(self):
        return _FakeCloseDlg.script


real_closedlg = launcher._CloseChoiceDialog
launcher._CloseChoiceDialog = _FakeCloseDlg   # 关窗流程不打桩会模态阻塞

print("--- 1) 未记住选择：关窗弹选择框（隐藏 + 不再提醒）---  【负向对照点】")
w = make_launcher({})
w.show()
app.processEvents()
_FakeCloseDlg.script = ("hide", True)
_FakeCloseDlg.rejected = False
_FakeCloseDlg.made = []
_qtplat = os.environ.pop("QT_QPA_PLATFORM", None)   # 摘守卫：本组专门测弹窗链路
w.close()
app.processEvents()
if _qtplat is not None:
    os.environ["QT_QPA_PLATFORM"] = _qtplat
chk("关窗弹出了选择框", len(_FakeCloseDlg.made) == 1)
chk("选择隐藏 → 窗口隐藏（任务继续）", w.isHidden(), w.isVisible())
chk("气泡提示给了", w._tray.tips == 1, w._tray.tips)
chk("「不再提醒」写入 config（tray_close_action=hide）",
    _saved.get("tray_close_action") == "hide", _saved)

print("\n--- 2) 记住选择后：关窗直接执行，不再弹 ---")
w.show()
app.processEvents()
_FakeCloseDlg.made = []
w.close()
app.processEvents()
chk("第二次关窗不再弹（直接隐藏）",
    len(_FakeCloseDlg.made) == 0 and w.isHidden(), len(_FakeCloseDlg.made))

print("\n--- 3) 选择退出 + 不再提醒 → 走完整清理 ---")
w2 = make_launcher({"tray_close_action": "exit"})
w2.show()
app.processEvents()
mas_before = getattr(w2.mas_page, "shutdown_called", 0)
w2.close()
app.processEvents()
chk("exit：不走托盘隐藏（_tray_minimized False）",
    not getattr(w2, "_tray_minimized", False))
chk("exit：心跳被停（清理照跑）", heartbeat_enabled() is False)
chk("exit：MAS 后端 shutdown 被调用",
    getattr(w2.mas_page, "shutdown_called", 0) > mas_before)

print("\n--- 4) 选择框点 X / Esc：取消关闭 ---")
_saved.clear()          # 只看本场景是否新写记忆键
w3 = make_launcher({})
w3.show()
app.processEvents()
_FakeCloseDlg.rejected = True
_FakeCloseDlg.made = []
_qtplat = os.environ.pop("QT_QPA_PLATFORM", None)
w3.close()
app.processEvents()
if _qtplat is not None:
    os.environ["QT_QPA_PLATFORM"] = _qtplat
chk("取消关闭：窗口仍然可见", w3.isVisible(), w3.isVisible())
chk("取消关闭：不写记忆键", "tray_close_action" not in _saved)
_FakeCloseDlg.rejected = False

print("\n--- 5) 已记住 hide：close 直接隐藏（不弹）---")
w4 = make_launcher({"tray_close_action": "hide"})
w4.show()
app.processEvents()
_FakeCloseDlg.made = []
w4.close()
app.processEvents()
chk("记住 hide：直接隐藏且不弹框",
    w4.isHidden() and len(_FakeCloseDlg.made) == 0)
w4.restore_window()
chk("隐藏态 restore_window 唤起", w4.isVisible())

print("\n--- 6) 托盘隐藏态退出：显式 quit（上一轮实机回归保留）---")
quit_calls = []


class _FakeApp:
    @staticmethod
    def instance():
        return _FakeApp

    @staticmethod
    def quit():
        quit_calls.append("quit")


real_qapp = launcher.QApplication
launcher.QApplication = _FakeApp
w6 = make_launcher({"tray_close_action": "hide"})
w6.hide()
w6._tray.quit_app()
chk("隐藏态托盘退出：置标记 + 显式 quit",
    w6._tray_force_exit is True and quit_calls == ["quit"],
    (w6._tray_force_exit, quit_calls))
launcher.QApplication = real_qapp

print("\n--- 7) 设置页不再有旧开关（tray_chk 已移除）---")
chk("SettingsPage 无 tray_chk 属性", not hasattr(launcher.SettingsPage(), "tray_chk"))

launcher._CloseChoiceDialog = real_closedlg

print("\n%d failed" % len(fails))
# 本测试构造多个 Launcher（含 QSystemTrayIcon 相关对象），Python 退出期析构
# 顺序不可控会以 0xC0000409 崩掉（产品单实例无此问题）。断言已全部跑完并
# 刷盘，os._exit 跳过退出期析构是 Qt 测试套件的标准 workaround。
sys.stdout.flush()
sys.stderr.flush()
import gc  # noqa: E402
gc.collect()
os._exit(1 if fails else 0)

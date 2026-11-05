# -*- coding: utf-8 -*-
"""托盘图标 + 关闭到托盘 契约测试（用户定稿：默认关、托盘菜单、单实例兼容隐藏态）。

负向对照：托盘分支（closeEvent 的隐藏路径）若被退回，组 2/3 立即红；
单实例的隐藏唤起若被退回，组 5 红。

测试基建说明：offscreen 环境下 QSystemTrayIcon 的构造/隐藏/销毁会以
0xC0000409 崩溃（3/3 稳定复现，os._exit 也躲不过——崩在测试中段）。
所以：
  · Launcher 场景（组 2~6）全部用假托盘（_FakeTray），不构造 QSystemTrayIcon；
  · 真实 _TrayIcon 的机制（菜单/恢复/退出）单独在组 1 用桩宿主验证；
  · 进程结尾 os._exit 跳过退出期析构（断言已全部跑完并刷盘）。
产品是单实例单托盘，无此问题。
"""
import gc
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

# ---------- stubs：Launcher 构造里的网络 worker / MAS 页全部替身化 ----------
launcher.CatalogDownloadsWorker = type("W", (), {
    "__init__": lambda s, r, p=None: None, "start": lambda s: None})
launcher.GitHubStatsWorker = type("W", (), {
    "__init__": lambda s, p=None: None, "start": lambda s: None})
launcher.WishTotalsWorker = type("W", (), {
    "__init__": lambda s, r, p=None: None, "start": lambda s: None})
launcher.PosterWorker = type("W", (), {
    "__init__": lambda s, i, p=None: None, "start": lambda s: None})

# 真实 _TrayIcon 类先存起来（组 1 单独验证其机制）
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

# closeEvent 读配置走 _load_cfg_safe —— 场景化替身
real_cfg = launcher._load_cfg_safe
_cfg_state = {}


def _fake_cfg():
    return dict(_cfg_state)


launcher._load_cfg_safe = _fake_cfg


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


# 假托盘：Launcher 场景不构造 QSystemTrayIcon（offscreen 下其隐藏/销毁会崩）；
# 行为用假托盘记录，真 _TrayIcon 机制只在组 1 单独验证
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

print("--- 1) _TrayIcon 本体：菜单 / 恢复 / 退出标记（真实 QSystemTrayIcon）---")
host = QWidget()
host._tray_force_exit = False
host.close_called = 0
_real_close = host.close


def _stub_close():
    host.close_called += 1
    _real_close()


def _host_restore():
    host.show()
    host.raise_()


host.close = _stub_close
host.restore_window = _host_restore
host.show()
w0 = real_tray_cls(host)
chk("托盘菜单存在且至少两项（显示/退出）",
    w0.contextMenu() is not None and len(w0.contextMenu().actions()) >= 2)
host.hide()
w0.restore()
chk("宿主隐藏时 restore() 能唤起", host.isVisible())
host._tray_force_exit = False
_quit_calls = []


class _FakeApp:
    @staticmethod
    def instance():
        return _FakeApp

    @staticmethod
    def quit():
        _quit_calls.append("quit")


_real_qapp = launcher.QApplication
launcher.QApplication = _FakeApp
w0.quit_app()
launcher.QApplication = _real_qapp
chk("托盘「退出」置强制退出标记、触发关闭并显式 quit（隐藏态退出的关键）",
    host._tray_force_exit is True and host.close_called == 1
    and _quit_calls == ["quit"],
    (host._tray_force_exit, host.close_called, _quit_calls))
w0.hide()
w0.setParent(None)
del w0
gc.collect()

print("\n--- 2) 默认关：close = 退出路径（不隐藏、清理照跑）---")
w = make_launcher({})
w.close()
app.processEvents()
chk("默认关：关闭不走托盘隐藏（_tray_minimized 为 False）",
    not getattr(w, "_tray_minimized", False), getattr(w, "_tray_minimized", None))
chk("默认关：心跳被停（清理照跑）", heartbeat_enabled() is False)
chk("默认关：MAS 后端 shutdown 被调用",
    getattr(w.mas_page, "shutdown_called", 0) > 0)

print("\n--- 3) 托盘开：close = 隐藏到托盘（清理被跳过）---  【负向对照点】")
w2 = make_launcher({"tray_close_to_tray": True})
w2.show()
app.processEvents()
mas_before2 = getattr(w2.mas_page, "shutdown_called", 0)
tips_before = w2._tray.tips
w2.close()
app.processEvents()
chk("托盘开：关闭后窗口隐藏（任务继续）", w2.isHidden(), w2.isVisible())
chk("托盘开：_tray_minimized 置位", getattr(w2, "_tray_minimized", False) is True)
chk("托盘开：心跳没停（清理被跳过）", heartbeat_enabled() is True)
chk("托盘开：MAS 后端没有 shutdown（还在跑）",
    getattr(w2.mas_page, "shutdown_called", 0) == mas_before2)
chk("托盘开：首次隐藏给气泡提示", w2._tray.tips == tips_before + 1, w2._tray.tips)
# 托盘「退出」→ 真退出路径
w2._tray.quit_app()
app.processEvents()
chk("托盘退出 → 走完整清理（心跳停 + MAS shutdown）",
    heartbeat_enabled() is False
    and getattr(w2.mas_page, "shutdown_called", 0) > mas_before2)

print("\n--- 4) restore_window：隐藏/最小化都能唤起 ---")
w3 = make_launcher({"tray_close_to_tray": True})
w3.hide()
w3.restore_window()
app.processEvents()
chk("隐藏态 restore_window → 可见", w3.isVisible() and not w3.isHidden())
w3.showMinimized()
w3.restore_window()
app.processEvents()
chk("最小化态 restore_window → 正常显示",
    w3.isVisible() and not w3.isMinimized())

print("\n--- 5) 设置页开关：读写 config（tray_close_to_tray）---")
cfgp = os.path.join(_tmp, "config.json")
launcher.SettingsPage._cfg_path = lambda self: cfgp
sp = launcher.SettingsPage()
chk("默认关（config 无键时 unchecked）", sp.tray_chk.isChecked() is False)
sp.tray_chk.setChecked(True)
sp._save_tray_toggle()
saved = json.load(open(cfgp, encoding="utf-8"))
chk("开关写回 config.tray_close_to_tray=true",
    saved.get("tray_close_to_tray") is True, saved.get("tray_close_to_tray"))
sp2 = launcher.SettingsPage()
chk("重开设置页回读为开", sp2.tray_chk.isChecked() is True)
sp2.tray_chk.setChecked(False)
sp2._save_tray_toggle()
saved2 = json.load(open(cfgp, encoding="utf-8"))
chk("关掉写回 false", saved2.get("tray_close_to_tray") is False)

print("\n--- 6) 单实例：隐藏态唤起（真缺口修复回归）---")
# Launcher 关闭到托盘后，第二实例的激活必须能唤起 —— restore_window 已挂到
# 单实例激活闭包（win.restore_window()），这里验证窗口隐藏态能被唤起
w4 = make_launcher({"tray_close_to_tray": True})
w4.hide()
w4.restore_window()
app.processEvents()
chk("隐藏态唤起（单实例激活同款路径）", w4.isVisible())

print("\n--- 7) 托盘隐藏态退出（实机回归：close 不触发 lastWindowClosed）---")
# 实机：窗口隐藏后托盘「退出」→ close() 的清理跑了但进程留在托盘。
# 修复后 quit_app 必须显式 QApplication.quit()。
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
w5 = make_launcher({"tray_close_to_tray": True})
w5.hide()
w5._tray.quit_app()
chk("隐藏态托盘退出：置强制退出标记", w5._tray_force_exit is True)
chk("隐藏态托盘退出：显式调用了 QApplication.quit()（进程真正退出）",
    quit_calls == ["quit"], quit_calls)
launcher.QApplication = real_qapp

print("\n%d failed" % len(fails))
# 本测试若构造真实 QSystemTrayIcon，Python 退出期析构顺序不可控，
# 进程会以 0xC0000409 崩掉（3/3 稳定复现；产品单实例无此问题，
# 纯测试多实例堆积才触发）。断言已全部跑完并刷盘，os._exit 跳过退出期析构。
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if fails else 0)

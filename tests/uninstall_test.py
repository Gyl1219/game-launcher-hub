# -*- coding: utf-8 -*-
"""卸载改进回归测试：直接删除档 + 相关快捷方式联动清理。

背景：原实现所有档位都「移入回收站」，GB 级卸载不释放空间；
且不清理桌面/开始菜单里指向安装目录的死链快捷方式。
"""
import os
import sys
import shutil
import tempfile
import unittest.mock as mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OK, FAIL = [], []


def chk(name, cond):
    (OK if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name)


qapp = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="uninst_t_")
BS = chr(92)   # 免疫 shell 转义，路径里的反斜杠统一用 chr(92) 拼


def norm(s):
    return str(s).replace(BS, "/").lower().rstrip("/")


# ---------- 1) 路径归一化 ----------
print("--- _norm_path_text ---")
chk("反斜杠归一成斜杠", launcher._norm_path_text("D:" + BS + "X" + BS + "Y") == "d:/x/y")
chk("尾部斜杠去掉", launcher._norm_path_text("D:/x/") == "d:/x")

# ---------- 2) 快捷方式扫描 ----------
print("--- _scan_related_shortcuts ---")
fake_desktop = os.path.join(TMP, "desktop")
fake_startmenu = os.path.join(TMP, "sm", "Microsoft", "Windows", "Start Menu", "Programs")
os.makedirs(fake_desktop)
os.makedirs(fake_startmenu)
inst_dir = os.path.join(TMP, "DZZZ-OD")
os.makedirs(inst_dir)


def make_lnk(path, target):
    """构造一个内容里带目标路径的假 .lnk（utf-16 段 + ansi 段都放一份）。"""
    t = target
    utf16 = t.encode("utf-16-le")
    open(path, "wb").write(utf16 + b"\x00\x00" * 8 + t.encode("latin-1", "ignore"))


make_lnk(os.path.join(fake_desktop, "绝区零一条龙.lnk"), inst_dir)
make_lnk(os.path.join(fake_startmenu, "zzz.lnk"), inst_dir)
make_lnk(os.path.join(fake_desktop, "无关.lnk"), "D:" + BS + "别的地方")

with mock.patch.object(launcher, "_desktop_dir", return_value=fake_desktop), \
     mock.patch.dict(os.environ, {"APPDATA": os.path.join(TMP, "sm"),
                                  "ProgramData": os.path.join(TMP, "no_pd")}):
    hits = launcher._scan_related_shortcuts(inst_dir)

names = sorted(os.path.basename(p) for p in hits)
chk("找到桌面 + 开始菜单里的 2 个相关快捷方式", names == ["zzz.lnk", "绝区零一条龙.lnk"])
chk("无关快捷方式不被误伤", all("无关" not in p for p in hits))
chk("安装目录不存在时返回空", launcher._scan_related_shortcuts(
    os.path.join(TMP, "nope")) == [])

# ---------- 3) 直接删除 ----------
print("--- _hard_delete ---")
victim = os.path.join(TMP, "victim", "sub")
os.makedirs(victim)
ro = os.path.join(victim, "ro.txt")
open(ro, "w").write("x")
os.chmod(ro, 0o444)   # 只读文件，rmtree 需要解只读
ok, msg = launcher._hard_delete(os.path.join(TMP, "victim"))
chk("连带只读文件一起删干净", ok and not os.path.exists(os.path.join(TMP, "victim")))

f = os.path.join(TMP, "afile.txt")
open(f, "w").close()
ok2, _ = launcher._hard_delete(f)
chk("单文件直接删除", ok2 and not os.path.exists(f))
chk("目标不存在 → 失败并说明", launcher._hard_delete(f)[0] is False)

# ---------- 4) 卸载流程端到端（假对话框注入点击） ----------
print("--- 卸载流程端到端 ---")


class _Btn:
    def __init__(self, tag):
        self.tag = tag


class FakeQMB:
    Warning = 4
    AcceptRole = 0
    DestructiveRole = 2
    RejectRole = 1

    chosen = None          # 由测试设置："soft" / "hard" / "cancel"
    clicks = []

    def __init__(self, parent=None):
        self._buttons = []

    def setWindowTitle(self, t):
        self.title = t

    def setText(self, t):
        self.text = t

    def setIcon(self, i):
        pass

    def addButton(self, text, role):
        b = _Btn(len(self._buttons))   # 0=soft 1=hard 2=cancel（按添加顺序）
        self._buttons.append(b)
        return b

    def setDefaultButton(self, b):
        pass

    def exec(self):
        pass

    def clickedButton(self):
        return self._buttons[{"soft": 0, "hard": 1, "cancel": 2}[FakeQMB.chosen]]

    @staticmethod
    def information(parent, title, text):
        FakeQMB.clicks.append(("info", title, text))

    @staticmethod
    def warning(parent, title, text):
        FakeQMB.clicks.append(("warn", title, text))


_real_qmb = launcher.QMessageBox
launcher.QMessageBox = FakeQMB
trash_calls = []


def fake_trash(p):
    trash_calls.append(p)
    return (True, "")


def make_card():
    exe = os.path.join(inst_dir, "App.exe")
    if not os.path.isfile(exe):
        open(exe, "w").close()
    a = {"key": "zzz", "display": "绝区零 一条龙", "generic": True, "exe": exe,
         "app_json": "", "working": "", "pythonw": "",
         "icon": "", "website": ""}
    c = launcher.AppCard(a)
    # 真实签名是 _is_process_running(force=False)（10-07 进程检测重构加的），
    # mock 必须一起接受该关键字，否则 uninstall_app 里 force=True 的调用会 TypeError。
    c._is_process_running = lambda force=False: False
    c.rebuild_body = lambda: None
    return c


try:
    # 重建安装目录与快捷方式（上面的 _hard_delete 测试删的是 victim，不影响这里）
    os.makedirs(inst_dir, exist_ok=True)
    make_lnk(os.path.join(fake_desktop, "绝区零一条龙.lnk"), inst_dir)

    # --- 直接删除档 ---
    card = make_card()
    FakeQMB.chosen = "hard"
    FakeQMB.clicks = []
    with mock.patch.object(launcher, "_desktop_dir", return_value=fake_desktop), \
         mock.patch.dict(os.environ, {"APPDATA": os.path.join(TMP, "sm"),
                                      "ProgramData": os.path.join(TMP, "no_pd")}), \
         mock.patch.object(launcher, "send_to_trash", side_effect=fake_trash):
        card.uninstall_app()
    chk("直接删除：安装目录真没了", not os.path.exists(inst_dir))
    chk("直接删除：相关快捷方式也清了",
        not os.path.exists(os.path.join(fake_desktop, "绝区零一条龙.lnk")))
    chk("直接删除：不经过回收站", trash_calls == [])
    chk("完成提示说明已释放空间",
        any(t == "info" and "空间已释放" in txt for t, _ti, txt in FakeQMB.clicks))

    # --- 移入回收站档 ---
    os.makedirs(inst_dir, exist_ok=True)
    open(os.path.join(inst_dir, "App.exe"), "w").close()
    make_lnk(os.path.join(fake_desktop, "绝区零一条龙.lnk"), inst_dir)
    trash_calls = []
    card2 = make_card()
    FakeQMB.chosen = "soft"
    FakeQMB.clicks = []
    with mock.patch.object(launcher, "_desktop_dir", return_value=fake_desktop), \
         mock.patch.dict(os.environ, {"APPDATA": os.path.join(TMP, "sm"),
                                      "ProgramData": os.path.join(TMP, "no_pd")}), \
         mock.patch.object(launcher, "send_to_trash", side_effect=fake_trash):
        card2.uninstall_app()
    chk("回收站档：安装目录 + 快捷方式都交给回收站", len(trash_calls) >= 2)
    chk("回收站档：目录本身未被直接删除", os.path.exists(inst_dir))
    chk("完成提示说明可还原",
        any(t == "info" and "还原" in txt for t, _ti, txt in FakeQMB.clicks))

    # --- 取消档 ---
    trash_calls = []
    card3 = make_card()
    FakeQMB.chosen = "cancel"
    FakeQMB.clicks = []
    with mock.patch.object(launcher, "_desktop_dir", return_value=fake_desktop), \
         mock.patch.dict(os.environ, {"APPDATA": os.path.join(TMP, "sm"),
                                      "ProgramData": os.path.join(TMP, "no_pd")}), \
         mock.patch.object(launcher, "send_to_trash", side_effect=fake_trash):
        card3.uninstall_app()
    chk("取消：什么都不清", trash_calls == [] and os.path.exists(inst_dir))
finally:
    launcher.QMessageBox = _real_qmb
    shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 46)
print("通过 %d / 失败 %d" % (len(OK), len(FAIL)))
if FAIL:
    for x in FAIL:
        print("   -", x)
print("=" * 46)

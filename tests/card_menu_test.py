# -*- coding: utf-8 -*-
"""卡片齿轮菜单（添加快捷方式 / 浏览安装位置 / 卸载）回归测试。"""
import os
import sys
import shutil
import tempfile
import unittest.mock as mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\OKApps\launcher")

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# offscreen 下模态弹窗永远阻塞，必须打桩（与 installer_test 同因）
_MSGBOX = []
launcher.QMessageBox.warning = staticmethod(
    lambda *a, **k: _MSGBOX.append(("warning", a[2] if len(a) > 2 else "")))
launcher.QMessageBox.information = staticmethod(
    lambda *a, **k: _MSGBOX.append(("info", a[2] if len(a) > 2 else "")))

# 已安装态卡片会 spawn git fetch 线程（沙盒网络挂住进程退出），禁掉
launcher.AppCard._generic_start_check = lambda self: None

OK, FAIL = [], []


def chk(name, cond):
    (OK if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name)


qapp = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="gearmenu_t_")

# 已安装的假程序（真实存在的 ASCII 路径 exe）
fake_exe = os.path.join(TMP, "DZZZ-OD", "OneDragon-RuntimeLauncher.exe")
os.makedirs(os.path.dirname(fake_exe), exist_ok=True)
open(fake_exe, "w").close()

BASE = {"key": "onedragon-zzz", "display": "绝区零 一条龙", "generic": True,
        "app_json": "", "working": "", "pythonw": "",
        "icon": "onedragon-zzz.png", "website": "https://one-dragon.com"}


def card(exe):
    a = dict(BASE)
    a["exe"] = exe
    return launcher.AppCard(a)


# =========================================================
# 1) 齿轮按钮存在
# =========================================================
print("--- 齿轮按钮 ---")
c = card(fake_exe)
gears = c.findChildren(launcher.TransparentToolButton)
chk("卡片上有齿轮按钮", len(gears) >= 1)
chk("齿轮 tooltip 是「更多操作」",
    any(g.toolTip() == "更多操作" for g in gears))


# =========================================================
# 2) 菜单构建：3 项 + 启停状态
# =========================================================
print("--- 菜单构建 ---")
menu = c._build_card_menu()
texts = [a.text() for a in menu.actions() if a.text()]
chk("菜单含「添加桌面快捷方式」", "添加桌面快捷方式" in texts)
chk("菜单含「浏览安装位置」", "浏览安装位置" in texts)
chk("菜单含「卸载」", "卸载" in texts)
chk("菜单**只有**这三项(不含截图里的其它项)",
    set(texts) == {"添加桌面快捷方式", "浏览安装位置", "卸载"})
amap = {a.text(): a for a in menu.actions() if a.text()}
chk("已安装态三项全部可用",
    all(amap[t].isEnabled() for t in amap))

c_uninst = card("D:/NOPE/None.exe")   # 必须持有引用：菜单 parent 是卡片，
menu2 = c_uninst._build_card_menu()   # 卡片被 GC 会连带删掉 C++ 侧菜单对象
amap2 = {a.text(): a for a in menu2.actions() if a.text()}
chk("未安装态三项全部禁用", all(not amap2[t].isEnabled() for t in amap2))


# =========================================================
# 3) .lnk 写入：纯 struct 快路径
# =========================================================
print("--- .lnk 写入 ---")
lnk = os.path.join(TMP, "测试.lnk")
ok = launcher._write_lnk(lnk, fake_exe, os.path.dirname(fake_exe))
chk("ASCII 目标写入成功", ok and os.path.isfile(lnk))
raw = open(lnk, "rb").read()
chk("lnk 二进制内含目标路径", b"OneDragon-RuntimeLauncher.exe" in raw)
chk("lnk 是合法 Shell Link(CLSID 头)",
    raw[4:20] == bytes.fromhex("0002140100000000c000000000000046"))
os.remove(lnk)


# =========================================================
# 4) 非 ASCII 目标 → 必须路由到 PowerShell 回退（mock，不真跑 PS）
# =========================================================
print("--- 非 ASCII 回退路由 ---")
called = {"ps": False, "struct": False}
with mock.patch.object(launcher, "_write_lnk_powershell",
                       side_effect=lambda *a, **k: called.__setitem__("ps", True) or True), \
     mock.patch.object(launcher, "_write_lnk_struct",
                       side_effect=lambda *a, **k: called.__setitem__("struct", True) or True):
    launcher._write_lnk(os.path.join(TMP, "x.lnk"), "D:/中文目录/游戏.exe", "D:/中文目录")
chk("中文路径走 PowerShell 回退", called["ps"] and not called["struct"])

called2 = {"ps": False, "struct": False}
with mock.patch.object(launcher, "_write_lnk_powershell",
                       side_effect=lambda *a, **k: called2.__setitem__("ps", True) or True), \
     mock.patch.object(launcher, "_write_lnk_struct",
                       side_effect=lambda *a, **k: called2.__setitem__("struct", True) or True):
    launcher._write_lnk(lnk, fake_exe, os.path.dirname(fake_exe))
chk("ASCII 路径走纯 struct 快路径", called2["struct"] and not called2["ps"])


# =========================================================
# 5) 添加快捷方式（端到端，桌面重定向到临时目录）
# =========================================================
print("--- 添加快捷方式 ---")
fake_desktop = os.path.join(TMP, "desktop")
os.makedirs(fake_desktop, exist_ok=True)
with mock.patch.object(launcher, "_desktop_dir", return_value=fake_desktop):
    c._create_desktop_shortcut()
made = os.path.join(fake_desktop, "绝区零 一条龙.lnk")
chk("lnk 落在桌面目录且用 display 命名", os.path.isfile(made))
chk("lnk 内容指向正确 exe",
    b"OneDragon-RuntimeLauncher.exe" in open(made, "rb").read())

# 未安装 → 弹提示且不写文件
with mock.patch.object(launcher, "_desktop_dir", return_value=fake_desktop):
    launcher.AppCard(dict(BASE, exe="D:/NOPE/x.exe"))._create_desktop_shortcut()
chk("未安装时不写 lnk 且弹提示",
    len(os.listdir(fake_desktop)) == 1 and
    any(t == "info" for t, _ in _MSGBOX))


# =========================================================
# 6) 浏览安装位置
# =========================================================
print("--- 浏览安装位置 ---")
OPENED = []
with mock.patch.object(launcher.QDesktopServices, "openUrl",
                       side_effect=lambda u: OPENED.append(u.toString())):
    c._open_install_dir()
chk("已安装 → 打开安装目录", OPENED and OPENED[0].startswith("file:///") and
    "DZZZ-OD" in OPENED[0])

OPENED.clear()
with mock.patch.object(launcher.QDesktopServices, "openUrl",
                       side_effect=lambda u: OPENED.append(u.toString())):
    card("D:/NOPE/None.exe")._open_install_dir()
chk("未安装 → 弹提示且不打开", not OPENED and
    any(t == "info" for t, _ in _MSGBOX))


# =========================================================
# 7) 真实桌面解析（本机应返回 D:\桌面）
# =========================================================
d = launcher._desktop_dir()
print("--- 桌面解析 ---")
print("   SHGetFolderPathW ->", d)
chk("能解析到真实桌面目录", bool(d) and os.path.isdir(d))

shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 46)
print("通过 %d / 失败 %d" % (len(OK), len(FAIL)))
if FAIL:
    for x in FAIL:
        print("   -", x)
print("=" * 46)

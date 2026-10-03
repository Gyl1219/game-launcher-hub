# -*- coding: utf-8 -*-
"""「打开官网/官方站点」按钮点击崩溃回归测试。

事故：点击 generic 卡的「打开官方站点」报
  TypeError: PySide6.QtCore.QUrl.__init__(bool)
根因：QPushButton.clicked 信号会带 checked(bool) 位置参数，
  `lambda url=site: ...` 的 url 被 bool 占位 → QUrl(True) 崩。
这个雷同时存在于 lite 卡未安装态（打开官网）和 generic 卡两处，一次修三处。

验证：真实 .click()（等价于用户点击，会带 bool），三张卡都不崩、
且 QDesktopServices.openUrl 收到的是 URL 字符串。
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from unittest.mock import patch  # noqa: E402

app = QApplication([])

fails = []


def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


OPENED = []  # 捕获 openUrl 实际收到的参数

with patch.object(launcher.QDesktopServices, "openUrl",
                  side_effect=lambda u: OPENED.append(u)):
    # ---------- 1) generic 卡（本次事故现场）----------
    g = launcher.AppCard({
        "key": "onedragon-zzz", "display": "ZZZ OneDragon", "generic": True,
        "exe": r"C:\nonexistent\OneDragon.exe",   # 未安装态：走「打开官网」按钮
        "app_json": "", "working": "", "pythonw": "", "icon": "",
        "website": "https://one-dragon.com/zzz/zh/home.html",
    })
    OPENED.clear()
    try:
        g.uninstall_btn  # 触发属性即可，不存在也没关系
    except AttributeError:
        pass
    # 未安装态的官网按钮：找 body 里最后一个 PushButton
    # （卡片布局里按钮是动态加的，直接遍历找）
    def find_buttons(widget):
        from PySide6.QtWidgets import QPushButton
        return widget.findChildren(launcher.PushButton)

    btns = [b for b in find_buttons(g) if b.text() == "打开官网"]
    chk("generic 未安装态有「打开官网」按钮", len(btns) == 1)
    try:
        btns[0].click()          # 真实点击路径：clicked 带 bool
        crashed = False
    except TypeError as e:
        crashed = True
        print("   点击异常:", e)
    chk("generic 未安装态点击不崩", not crashed)
    chk("openUrl 收到 QUrl 且 URL 正确",
        len(OPENED) == 1 and isinstance(OPENED[0], QUrl)
        and OPENED[0].toString() == "https://one-dragon.com/zzz/zh/home.html")

    # ---------- 2) generic 已安装态的「打开官方站点」按钮 ----------
    exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_fake_generic.exe")
    open(exe, "wb").write(b"MZ")
    g2 = launcher.AppCard({
        "key": "onedragon-zzz", "display": "ZZZ OneDragon", "generic": True,
        "exe": exe, "app_json": "", "working": "", "pythonw": "", "icon": "",
        "website": "https://one-dragon.com/zzz/zh/home.html",
    })
    OPENED.clear()
    btns2 = [b for b in find_buttons(g2) if "官方站点" in b.text()]
    chk("generic 已安装态有「打开官方站点」按钮", len(btns2) == 1)
    try:
        btns2[0].click()
        crashed = False
    except TypeError as e:
        crashed = True
        print("   点击异常:", e)
    chk("generic 已安装态点击不崩", not crashed)
    chk("已安装态 openUrl URL 正确",
        len(OPENED) == 1 and OPENED[0].toString().startswith("https://one-dragon.com"))

    # ---------- 3) lite 卡未安装态的「打开官网」（同一个雷）----------
    li = launcher.AppCard({
        "key": "whimbox", "display": "Whimbox", "lite": True,
        "exe": r"C:\nonexistent\whimbox_app.exe",
        "app_json": "", "working": "", "pythonw": "", "icon": "",
        "website": "https://github.com/nikkigallery/Whimbox",
    })
    OPENED.clear()
    btns3 = [b for b in find_buttons(li) if b.text() == "打开官网"]
    chk("lite 未安装态有「打开官网」按钮", len(btns3) == 1)
    try:
        btns3[0].click()
        crashed = False
    except TypeError as e:
        crashed = True
        print("   点击异常:", e)
    chk("lite 未安装态点击不崩", not crashed)
    chk("lite openUrl URL 正确",
        len(OPENED) == 1 and OPENED[0].toString() == "https://github.com/nikkigallery/Whimbox")

    # ---------- 4) 真实鼠标点击（QTest 模拟，最接近用户操作）----------
    OPENED.clear()
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(btns[0], Qt.LeftButton)
        crashed = False
    except TypeError as e:
        crashed = True
        print("   鼠标点击异常:", e)
    chk("真实鼠标点击不崩", not crashed)
    chk("鼠标点击仍收到正确 URL", len(OPENED) == 1)

try:
    os.remove(exe)
except Exception:
    pass

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

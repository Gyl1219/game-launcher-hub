# -*- coding: utf-8 -*-
"""AUTO-MAS 融合页：入口接线 + 分段视图 + 空态渲染 + 动作安全（不启后端）。

历史上这个文件名下测的是「MAS 独立卡片」；e4372d4 起 MAS 改成启动器原生页面
（侧栏菜单 + 常驻 stack 页），旧卡片形态的代码已整体移除，本测试随之改为验页面。

真后端的端到端在 mas_data_test.py；反复刷新的崩溃回归在 mas_polling_test.py。
"""
import os, sys, io

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


# 模态框必须 mock：离屏环境下真弹会阻塞事件循环（旧测试踩过这个坑）
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

win = launcher.Launcher()
win.show()
app.processEvents()
page = win.mas_page
KEY = launcher.AUTO_MAS_MENU_KEY

# 本测试不起真后端：把启动动作换成记录桩（自动启动的接线在下面单独断言，
# 这样既验了「进页面会自动拉起后端」，又不会真起进程拖慢测试）。
started = []
page.start_backend = lambda: started.append(True)
page._auto_started = False

# ---------- 1) 入口接线：菜单 → stack 页 ----------
chk("1) 侧栏出现 AUTO-MAS 菜单", KEY in win.sidebar._buttons)
chk("1b) 菜单文案正确",
    win.sidebar._buttons[KEY]._label.text() == "AUTO-MAS 任务编排"
    if KEY in win.sidebar._buttons else False)
chk("1c) 菜单图标文件存在",
    os.path.isfile(os.path.join(launcher.ASSETS_DIR, "auto-mas.png")),
    os.path.join(launcher.ASSETS_DIR, "auto-mas.png"))
chk("1d) 页面已入 stack 索引", KEY in win._page_index)
win.switch_to(KEY)
app.processEvents()
chk("1e) 点菜单真的切到该页",
    win.stack.currentIndex() == win._page_index[KEY],
    "current=%d" % win.stack.currentIndex())
chk("1f) 页面就是 MasPage 实例", win.stack.currentWidget() is page)
chk("1g) 首次进入页面自动拉起后端（WeGame 式常驻）",
    started == [True], "start_backend 调用 %d 次" % len(started))
chk("1h) 自动启动只做一次（切走再回来不重复拉起）",
    (lambda: (win.switch_to("overview"), win.switch_to(KEY),
              app.processEvents(), len(started) == 1)[-1])(),
    "start_backend 调用 %d 次" % len(started))

# ---------- 2) 四个分段视图 ----------
chk("2) 视图数 = 4", page.views.count() == 4, str(page._seg_index))
chk("2b) 分段键齐全",
    set(page._seg_index) == {"queue", "scripts", "log", "service"},
    str(list(page._seg_index)))
for key, idx in page._seg_index.items():
    page._on_seg(key)
    if page.views.currentIndex() != idx:
        chk("2c) 分段 %s 可切" % key, False, "idx=%d" % page.views.currentIndex())
chk("2c) 四个分段都能切", True)

# ---------- 3) 空态：界面必须有内容 ----------
chk("3) 未启动时状态 stopped", page._state == "stopped", page._state)
chk("3b) 队列视图有提示卡", page._bodies["queue"].count() > 1,
    "count=%d" % page._bodies["queue"].count())
chk("3c) 脚本视图有提示卡", page._bodies["scripts"].count() > 1,
    "count=%d" % page._bodies["scripts"].count())
chk("3d) 服务信息有内容", page._bodies["service"].count() > 1,
    "count=%d" % page._bodies["service"].count())
chk("3e) 日志页显示日志路径", "app.log" in page.log_note.text(),
    page.log_note.text()[:90])
chk("3f) 数据目录是 launcher 下的 auto-mas（不是 .cache）",
    "auto-mas" in page._home and ".cache" not in page._home, page._home)

# ---------- 4) 后端未运行时点动作：只提示不崩 ----------
err = None
try:
    page.run_queue("no-such-queue", False)
    page.run_queue("no-such-queue", True)
    page.stop_task("no-such-task")
    page.stop_task("")
    page.new_queue()
    page.delete_queue("no-such-queue")           # 确认框 mock 成 No → 不该发请求
    page.add_script("OkNte")
    page.pick_script_for_queue("no-such-queue")  # 没有脚本 → 只提示
    app.processEvents()
except Exception as e:
    err = "%s: %s" % (type(e).__name__, e)
chk("4) 后端未运行时动作不崩", err is None, err or "")

# ---------- 5) 防回归：旧卡片形态死代码必须已清除 ----------
card = win.cards[list(win.cards)[0]] if win.cards else None
chk("5) AppCard 不再有 _mas 成员", card is not None and not hasattr(card, "_mas"))
chk("5b) AppCard 不再有 _rebuild_mas_body",
    card is not None and not hasattr(card, "_rebuild_mas_body"))
chk("5c) config 里不再有 auto-mas 卡片条目",
    "auto-mas" not in [a.get("key") for a in launcher.APPS],
    str([a.get("key") for a in launcher.APPS]))
chk("5d) 菜单 key 常量未被改动", KEY == "auto-mas-menu", KEY)

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

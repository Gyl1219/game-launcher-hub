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

# ---------- 1) 入口接线：总览页右上角按钮 → stack 页 ----------
# 用户实机反馈：MAS 是「管助手本体」的编排插件，不该与游戏助手平级摆侧栏，
# 入口改到总览页右上角（与「扫描游戏」同排，带状态灯）。
chk("1) 侧栏不再有 AUTO-MAS 项", KEY not in win.sidebar._buttons,
    str(list(win.sidebar._buttons)))
chk("1b) 侧栏只列游戏助手 + 总览 + 设置",
    set(win.sidebar._buttons) == {"overview", "settings"} |
    {a.get("key") for a in launcher.LIVE_APPS},
    str(list(win.sidebar._buttons)))
ov = win.overview_page
chk("1c) 总览页有 MAS 入口按钮", hasattr(ov, "mas_btn"))
chk("1d) 按钮文案正确", ov.mas_btn.text() == "AUTO-MAS 任务编排", ov.mas_btn.text())
chk("1e) 入口带状态灯与定位说明",
    hasattr(ov, "mas_dot") and ov.mas_cap.text().startswith("编排插件"),
    ov.mas_cap.text())
chk("1f) 入口默认可见（mas_enabled 默认 true）", ov.mas_box.isVisibleTo(ov))
chk("1g) 卡片网格下方点明了层级",
    "不是又一个助手" in ov.grid_foot.text(), ov.grid_foot.text()[:60])
chk("1h) 页面已入 stack 索引", KEY in win._page_index)

# 点入口按钮 → 切到 MAS 页
ov.mas_btn.click()
app.processEvents()
chk("1i) 点入口真的切到该页",
    win.stack.currentIndex() == win._page_index[KEY],
    "current=%d" % win.stack.currentIndex())
chk("1j) 页面就是 MasPage 实例", win.stack.currentWidget() is page)
chk("1k) 进入编排页后侧栏无高亮（它没有对应导航项）",
    all(not b._selected for b in win.sidebar._buttons.values()),
    str({k: b._selected for k, b in win.sidebar._buttons.items()}))
chk("1l) 首次进入页面自动拉起后端（WeGame 式常驻）",
    started == [True], "start_backend 调用 %d 次" % len(started))

# 状态灯：由 MasPage.sig_status 推送，而不是自己轮询
page._set_state("ready", "v5.6.2")
chk("1m) 状态灯随后端状态更新",
    "运行中" in ov.mas_cap.text(), ov.mas_cap.text())
page._set_state("failed", "boom")
chk("1n) 失败态显示「不可用」", "不可用" in ov.mas_cap.text(), ov.mas_cap.text())
page._set_state("stopped", "已停止")
chk("1o) 停止态显示「未启动」", "未启动" in ov.mas_cap.text(), ov.mas_cap.text())
ov.set_mas_available(False)
app.processEvents()
chk("1p) mas_enabled=false 时入口整块隐藏", not ov.mas_box.isVisibleTo(ov))
ov.set_mas_available(True)
app.processEvents()
chk("1q) 重新启用后入口回来", ov.mas_box.isVisibleTo(ov))

# 切回总览：不崩，高亮回到总览
win.switch_to("overview")
app.processEvents()
chk("1r) 切回总览正常且侧栏高亮回到总览",
    win.stack.currentWidget() is ov and win.sidebar._buttons["overview"]._selected)
chk("1s) 再次进入不重复拉起后端",
    (win.switch_to(KEY), app.processEvents(), len(started) == 1)[-1],
    "start_backend 调用 %d 次" % len(started))

# ---------- 2) 五个分段视图（实时任务日志 + 队列/脚本/日志/服务信息）----------
chk("2) 视图数 = 5", page.views.count() == 5, str(page._seg_index))
chk("2b) 分段键齐全",
    set(page._seg_index) == {"live", "queue", "scripts", "log", "service"},
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

# ---------- 6) 优雅降级：缺 Python 3.12 时只有 MAS 页报不可用 ----------
# 这是交接文档的验收项之一：「缺少 Python3.12 时仅该功能报错，其余功能正常」。
orig_cands = launcher._auto_mas_python_candidates
launcher._auto_mas_python_candidates = lambda root=None: []
try:
    page2 = launcher.MasPage()          # 独立实例，不污染 win.mas_page 的状态
    page2.start_backend()
    app.processEvents()
    chk("6) 缺解释器 → failed 且提示说清原因",
        page2._state == "failed" and "Python 3.12" in page2._detail,
        "%s | %s" % (page2._state, page2._detail[:70]))
    chk("6b) 缺解释器时不留下后台线程/进程",
        page2._worker is None or page2._worker._proc is None)
    chk("6c) 该状态下界面仍可渲染", page2._bodies["service"].count() > 1)
finally:
    launcher._auto_mas_python_candidates = orig_cands
win.switch_to("overview")
app.processEvents()
chk("6d) 其它页面完全不受影响",
    win.stack.currentWidget() is win.overview_page)

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

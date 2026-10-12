# -*- coding: utf-8 -*-
"""AUTO-MAS 融合页：「完整配置」入口（开官方客户端新窗口）+ 数据目录选址/迁移。

历史上这个文件名下测的是卡片上的「打开主界面」按钮；页面化之后按钮搬到
MasPage 顶部服务条，本测试随之迁移，并补上 auto_mas_home() 的两条硬约束：
  1) 数据必须落在 launcher/auto-mas（.cache 是「随时可清」的目录，装账号配置会丢）；
  2) 旧版遗留在 .cache/auto-mas 的数据要能自动搬过来。

不真的启动 Electron 桌面端（沙盒跑不了 GUI，且会拉起第二个后端）。
"""
import os, sys, io, shutil, tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv)
OK, FAIL = [], []
TMPDIRS = []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

# ---------- 1) 桌面版定位 ----------
exe = launcher.auto_mas_desktop_exe()
chk("1) auto_mas_desktop_exe 返回路径或空串（不抛异常）",
    isinstance(exe, str), repr(exe))
if exe:
    chk("1b) 返回的路径真实存在", os.path.isfile(exe), exe)
else:
    print("      （本机没装 AUTO-MAS 桌面端，跳过路径存在性断言）")

# ---------- 2) 页面按钮接线 ----------
win = launcher.Launcher()
win.show()
app.processEvents()
page = win.mas_page
chk("2) 页面有「完整配置」按钮", hasattr(page, "open_desk_btn"))
chk("2b) 按钮文案", page.open_desk_btn.text() == "完整配置",
    page.open_desk_btn.text())
chk("2c) 按钮可用性与探测结果一致",
    page.open_desk_btn.isEnabled() == bool(exe),
    "enabled=%s exe=%r" % (page.open_desk_btn.isEnabled(), exe))
chk("2d) 探测结果缓存在实例上", hasattr(page, "_desk_exe"))

# 打开动作：把 run_exe 换成记录桩，避免真拉起第二个后端
calls = []
orig_run_exe = launcher.run_exe
launcher.run_exe = lambda parent, e, *a, **k: calls.append(e) or True
try:
    page._open_desktop()
    if exe:
        chk("2e) 有桌面版时调用 run_exe 打开它", calls == [exe], str(calls))
    else:
        chk("2e) 无桌面版时只提示不调用", calls == [], str(calls))
finally:
    launcher.run_exe = orig_run_exe

# ---------- 3) 数据目录选址 ----------
home = launcher.auto_mas_home()
chk("3) 默认数据目录在 launcher 下", os.path.normcase(home).startswith(
    os.path.normcase(os.path.abspath(launcher.LAUNCHER_DIR))), home)
chk("3b) 默认目录不含 .cache（用户数据不能放可清目录）",
    ".cache" not in home, home)
chk("3c) 页面用的就是同一目录",
    os.path.normcase(page._home) == os.path.normcase(home), page._home)

# ---------- 4) 旧数据目录迁移（.cache/auto-mas → auto-mas/）----------
tmp_new = tempfile.mkdtemp(prefix="mas_home_new_")
tmp_old = tempfile.mkdtemp(prefix="mas_home_old_")
TMPDIRS += [tmp_new, tmp_old]
os.makedirs(os.path.join(tmp_old, "config"), exist_ok=True)
with io.open(os.path.join(tmp_old, "config", "QueueConfig.json"), "w",
             encoding="utf-8") as f:
    f.write('{"instances": []}')
orig_legacy = launcher.AUTO_MAS_LEGACY_HOME
orig_cfg = launcher._load_cfg_safe
launcher.AUTO_MAS_LEGACY_HOME = tmp_old
launcher._load_cfg_safe = lambda: {"auto_mas_home": tmp_new}
try:
    got = launcher.auto_mas_home()
    chk("4) 配置里指定的目录生效",
        os.path.normcase(got) == os.path.normcase(os.path.abspath(tmp_new)), got)
    chk("4b) 旧数据已搬迁过来",
        os.path.isfile(os.path.join(tmp_new, "config", "QueueConfig.json")),
        os.path.join(tmp_new, "config", "QueueConfig.json"))
    # 已有 config/ 时不该再覆盖（幂等，避免每次启动都搬运）
    marker = os.path.join(tmp_new, "config", "KEEP.txt")
    with io.open(marker, "w", encoding="utf-8") as f:
        f.write("keep")
    launcher.auto_mas_home()
    chk("4c) 已有数据时不再重复搬运", os.path.isfile(marker))
finally:
    launcher.AUTO_MAS_LEGACY_HOME = orig_legacy
    launcher._load_cfg_safe = orig_cfg
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

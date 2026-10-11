# -*- coding: utf-8 -*-
"""AUTO-MAS 的「安装 / 卸载」链路单测（**绝不真的安装或卸载**）。

安全底线（写测试时踩不得）：
  · 本机已装 AUTO-MAS（D:\AUTO-MAS），任何测试都**不能**触发它的卸载程序；
  · 安装要下 116 MB 并真装，测试里也不能真跑；
  · 所以这里把「下载/解压/跑安装程序/跑卸载程序」全部换成记录桩，
    只验证**逻辑与接线**：取包地址对不对、注册表读得对不对、
    卡片按已装/未装切换、确认框被拒时不发动作、运行中禁止装/卸。

真机的安装/卸载留给用户手动点（本轮未做自动化，避免动到用户的真实安装）。
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


# ---------- 1) 取包：地址与文件名（联网查，但只查询不下载）----------
tag, url, name, _sz = launcher.auto_mas_latest_release()
chk("1) 能查到官方最新正式版 tag", bool(tag) and tag[0] in "vV", str(tag))
chk("1b) 资产名符合官方命名", name.startswith("AUTO-MAS-Setup-") and name.endswith("-x64.zip"),
    str(name))
chk("1c) 下载 URL 指向 GitHub 或 CNB 镜像",
    ("github.com" in url) or ("cnb.cool" in url), url[:90])
chk("1d) URL 里含查到的版本号", (tag.lstrip("vV") in url) or (tag in url), str(tag))

# ---------- 2) 注册表探测（只读）----------
info = launcher.auto_mas_installed_info()
chk("2) 探测不抛异常且返回 dict", isinstance(info, dict), str(info)[:80])
if info:
    chk("2b) 已装时能拿到卸载命令", bool(info.get("uninstall")), str(info.get("uninstall")))
    chk("2c) 卸载命令指向 unins000.exe",
        "unins000.exe" in (info.get("uninstall") or "").lower(),
        str(info.get("uninstall")))
    chk("2d) 有安装位置与版本",
        bool(info.get("location")) and bool(info.get("version")),
        "%s / %s" % (info.get("version"), info.get("location")))
else:
    print("      （本机未装 AUTO-MAS，跳过已装相关断言）")

# ---------- 3) 安装目录推导 ----------
d = launcher.auto_mas_install_dir()
chk("3) 安装目录为非空的绝对路径", bool(d) and os.path.isabs(d), d)
chk("3b) 目录名是 AUTO-MAS", os.path.basename(d.rstrip("\\/")) == "AUTO-MAS", d)
orig_cfg = launcher._load_cfg_safe
launcher._load_cfg_safe = lambda: {"auto_mas_install": "E:/tools/mas"}
try:
    chk("3c) config 的 auto_mas_install 可覆盖",
        launcher.auto_mas_install_dir().replace("\\", "/").lower() == "e:/tools/mas",
        launcher.auto_mas_install_dir())
finally:
    launcher._load_cfg_safe = orig_cfg

# ---------- 4) 安装状态卡：未装 / 已装 两种形态 ----------
uninstalled = launcher._MasSetupCard({}, "D:/X/AUTO-MAS")
chk("4) 未装时标题正确", "尚未安装" in uninstalled.findChildren(
    launcher.__dict__.get("StrongBodyLabel"))[0].text(),
    uninstalled.findChildren(launcher.__dict__["StrongBodyLabel"])[0].text())
chk("4b) 未装时主按钮是安装", uninstalled.main_btn.text() == "安装 AUTO-MAS",
    uninstalled.main_btn.text())
chk("4c) 未装时不显示卸载", not uninstalled.installed)
fired = []
uninstalled.sig_install.connect(lambda: fired.append("install"))
uninstalled.main_btn.click()
chk("4d) 点安装按钮触发 sig_install", fired == ["install"], str(fired))

installed = launcher._MasSetupCard({"version": "v5.6.2", "location": "D:\\AUTO-MAS\\",
                                    "uninstall": '"D:\\AUTO-MAS\\unins000.exe"'},
                                   "D:/X/AUTO-MAS")
chk("4e) 已装时标题正确",
    "已安装" in installed.findChildren(launcher.__dict__["StrongBodyLabel"])[0].text(),
    installed.findChildren(launcher.__dict__["StrongBodyLabel"])[0].text())
chk("4f) 已装时主按钮是卸载", installed.main_btn.text() == "卸载", installed.main_btn.text())
fired2 = []
installed.sig_uninstall.connect(lambda: fired2.append("uninstall"))
installed.main_btn.click()
chk("4g) 点卸载按钮触发 sig_uninstall", fired2 == ["uninstall"], str(fired2))
installed.set_busy(True, "正在卸载…")
chk("4h) 忙碌态禁用按钮并显示进度条",
    (not installed.main_btn.isEnabled()) and installed.bar.isVisibleTo(installed))
installed.set_busy(False)
chk("4i) 恢复后按钮可用", installed.main_btn.isEnabled())

# ---------- 5) 页面接线：确认框被拒时不能真装；运行中禁止装/卸 ----------
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)

win = launcher.Launcher()
win.show()
app.processEvents()
page = win.mas_page
page._auto_started = True
win.switch_to(launcher.AUTO_MAS_MENU_KEY)
app.processEvents()

chk("5) 组件分段已注册", "setup" in page._seg_index, str(list(page._seg_index)))
page._on_seg("setup")
chk("5b) 能切到组件分段", page.views.currentIndex() == page._seg_index["setup"])
chk("5c) 组件视图有卡片", page._bodies["setup"].count() > 1,
    "count=%d" % page._bodies["setup"].count())

# 确认框 = No → 不能启动任何线程
page.install_component()
app.processEvents()
chk("5d) 拒绝确认后不启动安装线程", page._setup_worker is None and not page._setup_busy)
page.uninstall_component()
app.processEvents()
chk("5e) 拒绝确认后不启动卸载线程", page._setup_worker is None and not page._setup_busy)

# 后端运行中 → 装/卸都必须被拦（会覆盖/删除程序文件）
page._set_state("ready", "运行中")
page.install_component()
app.processEvents()
chk("5f) 后端运行中禁止安装", page._setup_worker is None and not page._setup_busy)
page.uninstall_component()
app.processEvents()
chk("5g) 后端运行中禁止卸载", page._setup_worker is None and not page._setup_busy)

# ---------- 5h) 注册表卸载命令 → 可执行路径的解析 ----------
# 真实值形如 '"D:\AUTO-MAS\unins000.exe"'（带引号，可能还带参数）。
# 这段解析曾是 NameError（_strip_quotes 未定义）—— py_compile 查不出来，
# 只在用户真点"卸载"时才炸，所以必须有断言盯着。
for raw, want in (
    ('"D:\\AUTO-MAS\\unins000.exe"', "D:\\AUTO-MAS\\unins000.exe"),
    ("D:\\AUTO-MAS\\unins000.exe", "D:\\AUTO-MAS\\unins000.exe"),
    ('"C:\\Program Files\\a b\\u.exe" /S', "C:\\Program Files\\a b\\u.exe"),
    ("", ""),
):
    got = launcher._strip_quotes((raw.split(" /")[0].strip() or raw).strip('"'))
    chk("5h) 解析 %r" % raw, got == want, "得到 %r" % got)

# ---------- 6) 卸载动作只能走官方卸载程序，绝不自己删目录 ----------
# 把外部程序执行换成记录桩：确认「卸载」只会 Popen 官方卸载程序 + /S，
# 不会对本机真实安装做任何删除动作。
calls = []
orig_popen = launcher.subprocess.Popen


class _FakeProc:
    def __init__(self, args):
        calls.append(list(args))
        self.args = args

    def wait(self, *a, **k):
        return 0


launcher.subprocess.Popen = lambda args, *a, **k: _FakeProc(args)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    page._set_state("stopped", "")
    page.uninstall_component()
    app.processEvents()
    ok_call = bool(calls) and any(
        ("unins000.exe" in str(c[0]).lower()) for c in calls)
    chk("6) 卸载调用的是官方卸载程序", ok_call, str(calls))
    if calls:
        chk("6b) 带 NSIS 静默参数 /S", any("/S" in [str(x) for x in c] for c in calls),
            str(calls))
        chk("6c) 参数里没有 rmdir/del 之类自删动作",
            not any(any(str(x).lower() in ("rmdir", "del", "remove")
                        for x in c) for c in calls), str(calls))
    # 本机真实安装必须还在（没被测试删掉）
    chk("6d) 本机真实安装未被测试触碰", bool(launcher.auto_mas_installed_info()))
finally:
    launcher.subprocess.Popen = orig_popen

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

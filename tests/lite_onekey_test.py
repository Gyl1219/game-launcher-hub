import os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import launcher
from PySide6.QtWidgets import QApplication
from unittest.mock import patch, MagicMock
qapp = QApplication(sys.argv)

fails = []
def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

# ---------- 共用：搭一个 whimbox 卡片，并模拟"检查成功、选中 2.4.7" ----------
app = [a for a in launcher.APPS if a.get("key") == "whimbox"][0]
card = launcher.AppCard(app)
card._rebuild_lite_body()
card._on_lite_check_done({
    "tag": "2.4.7", "exe": "https://x/setup.exe",
    "whl": "https://x/whimbox-2.4.7-py3-none-any.whl",
    "body": "", "versions": [{"tag": "2.4.7", "exe": "https://x/setup.exe",
                              "whl": "https://x/whimbox-2.4.7-py3-none-any.whl"}],
})

EXE = card.app["exe"]                     # 实际配置路径（config.json 指向正版）
TARGET = os.path.dirname(EXE)            # D:/Program Files/whimbox_app

class _Sig:
    def __init__(self): self.slots = []
    def connect(self, fn): self.slots.append(fn)
    def emit(self, *a):
        for s in self.slots:
            s(*a)

# =====================================================================
# A. 确认弹窗：只弹 1 次 + 文案含"一条龙 / 锁定目录 / 不装系统盘"
# =====================================================================
with patch.object(launcher, "_exe_file_version", return_value="1.0.0"), \
     patch.object(launcher, "_lite_backend_version", return_value=""), \
     patch.object(card, "_lite_download", side_effect=lambda *a, **k: dl_calls.append(a)), \
     patch.object(launcher, "LiteInstallFrontendWorker") as FakeFE, \
     patch.object(launcher.QMessageBox, "question", side_effect=lambda *a, **k: (qargs.append(a) or launcher.QMessageBox.StandardButton.Yes)) as qmock:
    dl_calls, qargs = [], []
    card._on_lite_update()
    chk("确认弹窗只弹 1 次", qmock.call_count == 1)
    txt = qargs[0][2] if qargs else ""
    chk("弹窗文案含『一条龙』", "一条龙" in txt)
    chk("弹窗文案含安装目录(锁定)", TARGET in txt)
    chk("弹窗文案含『不会安装到系统盘』", "不会安装到系统盘" in txt)
    chk("前端下载被触发(stage=exe)", any(len(c) == 3 and c[2] == "exe" for c in dl_calls))

# =====================================================================
# B. _lite_run_installer 接线：worker 拿到锁定的 target + 走马灯进度可见
# =====================================================================
class FakeFEWorker:
    instances = []
    def __init__(self, setup, target, exe, fe_tag, old_ver, parent=None):
        self.args = (setup, target, exe, fe_tag, old_ver)
        self.finished_ok, self.failed = _Sig(), _Sig()
        self.started = False
        FakeFEWorker.instances.append(self)
    def start(self): self.started = True
    def isRunning(self): return False

with patch.object(launcher, "LiteInstallFrontendWorker", FakeFEWorker):
    FakeFEWorker.instances.clear()
    card._lite_run_installer(r"D:\cache\whimbox_app-setup-2.4.7.exe")
    w = FakeFEWorker.instances[-1]
    chk("前端安装 worker 已 start", w.started)
    chk("worker 锁定安装目录(target)", w.args[1] == TARGET)
    chk("进度条进入走马灯(0,0)", card.install_progress.minimum() == 0 and card.install_progress.maximum() == 0)
    chk("进度条已显示(not hidden)", not card.install_progress.isHidden())
    chk("finished_ok 接到 _lite_on_frontend_done",
        any(getattr(s, "__name__", "") == "_lite_on_frontend_done" for s in w.finished_ok.slots))
    chk("取消按钮已显示(not hidden)", not card.install_cancel_btn.isHidden())

# =====================================================================
# C. 真实 worker：命令是字符串 + /S /D=<目标> + 校验分支
# =====================================================================
class FakePopen:
    last = None
    def __init__(self, cmd, **kw):
        FakePopen.last = cmd
        self.returncode = 0
    def poll(self): return 0
    def kill(self): pass

def run_worker(fe_ver, old_ver, fe_tag, target):
    rec = {}
    w = launcher.LiteInstallFrontendWorker("D:/c/setup.exe", target, EXE, fe_tag, old_ver, parent=None)
    w.finished_ok.connect(lambda c: rec.setdefault("ok", c))
    w.failed.connect(lambda e: rec.setdefault("fail", e))
    with patch.object(launcher, "subprocess") as sp, \
         patch.object(launcher, "_exe_file_version", return_value=fe_ver):
        sp.Popen = FakePopen
        sp.run = lambda *a, **k: None
        sp.CREATE_NO_WINDOW = 0x08000000
        w.run()
    return FakePopen.last, rec

cmd, rec = run_worker("2.4.7", "2.1.1", "2.4.7", TARGET)
chk("安装命令是字符串", isinstance(cmd, str))
chk("命令含 /S", " /S " in cmd)
chk("命令含 /D=<目标目录>", ("/D=%s" % TARGET) in cmd)
chk("命令末段是 /D（NSIS 要求最后参数）", cmd.strip().endswith("/D=%s" % TARGET))
chk("命令未给 /D 路径加引号", "/D=\"%s\"" % TARGET not in cmd)
chk("校验通过→ok", rec.get("ok") == "ok")

cmd, rec = run_worker("2.1.1", "2.1.1", "2.4.7", TARGET)
chk("版本没变→unchanged", rec.get("ok") == "unchanged")

cmd, rec = run_worker("9.9.9", "2.1.1", "2.4.7", TARGET)
chk("变了但不等→tolerant", rec.get("ok") == "tolerant:9.9.9")

# =====================================================================
# D. _lite_on_frontend_done 各分支
# =====================================================================
with patch.object(launcher.QMessageBox, "information") as info, \
     patch.object(launcher.QMessageBox, "warning") as warn, \
     patch.object(card, "_lite_install_backend") as inst:
    # 无需后端
    card._lite_need_whl = False
    card._lite_on_frontend_done("ok")
    chk("ok+无须后端→information", info.called)
    chk("ok+无须后端→按钮恢复", card.update_btn.isEnabled())
    chk("ok+无须后端→不触发后端安装", not inst.called)

    # 需要后端：预下载已就绪 → 直接装
    info.reset_mock(); warn.reset_mock(); inst.reset_mock()
    card._lite_need_whl = True
    tf = tempfile.NamedTemporaryFile(suffix=".whl", delete=False); tf.close()
    card._lite_whl_ready = tf.name
    card._lite_on_frontend_done("ok")
    chk("ok+需后端→装后端(whl就绪)", inst.called and inst.call_args[0][0] == tf.name)
    os.remove(tf.name)

    # 装错位置
    info.reset_mock(); warn.reset_mock(); inst.reset_mock()
    card._lite_need_whl = False
    card._lite_on_frontend_done("wrong_location:C:\\bad\\whimbox_app.exe")
    chk("wrong_location→warning", warn.called)

    # 未更新成功
    warn.reset_mock()
    card._lite_need_whl = False
    card._lite_on_frontend_done("unchanged")
    chk("unchanged→warning", warn.called)

# =====================================================================
# E. whl 并行预下载：finished_ok 自动写 _lite_whl_ready
# =====================================================================
class FakeDL:
    instances = []
    def __init__(self, url, save, parent=None, key=""):
        self.save = save; self.finished_ok, self.failed = _Sig(), _Sig()
        self.key = key
        FakeDL.instances.append(self); self._ran = False
    def start(self):
        self._ran = True
        self.finished_ok.emit(self.save)   # 立即完成，写入缓存
with patch.object(launcher, "LiteDownloadWorker", FakeDL), \
     patch.object(launcher, "LAUNCHER_CACHE_DIR", tempfile.mkdtemp()):  # 密闭：不受真实缓存影响
    FakeDL.instances.clear()
    card._lite_whl_ready = ""
    card._lite_start_whl_prefetch("2.4.7", "https://x/whl")
    chk("预下载 worker 已启动", FakeDL.instances[-1]._ran)
    chk("预下载完成自动写 _lite_whl_ready", card._lite_whl_ready == FakeDL.instances[-1].save)

# =====================================================================
# F. 时长不可预测阶段：只给递增秒数心跳，不编造倒计时，且不按时长强杀
# =====================================================================
import re
card._lite_start_spin("测试中…")          # 不传 timeout = 时长不可预测（默认）
t1 = card.install_status.text()
chk("未知时长只显示已等秒数", "已等 0s" in t1)
chk("未知时长不编造倒计时", "倒计时" not in t1)
chk("启动立即显示(不等第一秒)", "已等" in t1)
card._lite_spin_start -= 5
card._lite_spin_tick()
t2 = card.install_status.text()
chk("秒数每秒递增(心跳)", "已等 5s" in t2 and t1 != t2)
card._lite_stop_spin()

# 只有显式给了已知上界，才显示倒计时（能力保留）
card._lite_start_spin("测试中…", timeout=600)
t3 = card.install_status.text()
m1 = re.search(r"倒计时 (\d+):(\d+)", t3)
rem1 = (int(m1.group(1)) * 60 + int(m1.group(2))) if m1 else -1
chk("给了上界才显示倒计时", m1 is not None)
# 同样有 ±1s 取整抖动（600 与 599 都可能）
chk("倒计时=所给上界(600s→10:00)", rem1 in (599, 600))
card._lite_spin_start -= 5
card._lite_spin_deadline -= 5
card._lite_spin_tick()
m2 = re.search(r"倒计时 (\d+):(\d+)", card.install_status.text())
rem2 = (int(m2.group(1)) * 60 + int(m2.group(2))) if m2 else -1
# 允许 ±1s：int() 向下取整在"刚好跨秒"时会差 1
chk("倒计时每秒递减", m2 is not None and abs(rem2 - (rem1 - 5)) <= 1)
# 超时后不倒计为负数
card._lite_spin_deadline = time.time() - 1
card._lite_spin_tick()
chk("超时显示『已超时』而非负数", "已超时" in card.install_status.text())
card._lite_stop_spin()

# 不再按猜测时长强杀（每次耗时不同，杀到一半会留下残缺安装）
w = launcher.LiteInstallFrontendWorker("D:/c/s.exe", TARGET, EXE, "2.4.7", "2.1.1",
                                       parent=None)
chk("安装器默认不自动杀(无猜测上界)", getattr(w, "_timeout", "MISSING") is None)

# =====================================================================
# G. 当前版本恰好在 release 列表里时也要标「（当前）」（2026-10-02 用户反馈）
# =====================================================================
with patch.object(launcher, "_exe_file_version", return_value="2.4.7"), \
     patch.object(launcher, "_lite_backend_version", return_value="2.4.8"):
    card2 = launcher.AppCard(app)
    card2._rebuild_lite_body()
    card2._on_lite_check_done({
        "tag": "3.1.0", "exe": "https://x/setup-3.1.0.exe",
        "whl": "https://x/whimbox-3.1.0-py3-none-any.whl",
        "body": "3.1.0 说明",
        "versions": [
            {"tag": "3.1.0", "exe": "https://x/setup-3.1.0.exe",
             "whl": "https://x/whimbox-3.1.0-py3-none-any.whl", "body": "3.1.0 说明"},
            {"tag": "2.4.8", "exe": "",
             "whl": "https://x/whimbox-2.4.8-py3-none-any.whl", "body": "2.4.8 说明"},
            {"tag": "2.4.7", "exe": "https://x/setup.exe",
             "whl": "https://x/whimbox-2.4.7-py3-none-any.whl", "body": "2.4.7 说明"},
        ],
    })
    chk("前端标（当前前端）", card2.ver_combo.findText("2.4.7（当前前端）") >= 0)
    chk("后端标（当前后端）", card2.ver_combo.findText("2.4.8（当前后端）") >= 0)
    chk("仓库最新标（最新）", card2.ver_combo.findText("3.1.0（最新）") >= 0)
    chk("不再有裸版本号项",
        all(card2.ver_combo.findText(t) == -1 for t in ("2.4.7", "2.4.8", "3.1.0")))
    chk("默认选中最新项", card2.ver_combo.currentText() == "3.1.0（最新）")
    chk("最新项说明正确", card2._lite_version_map.get("3.1.0（最新）") == "3.1.0 说明")
    chk("说明区显示最新说明", "3.1.0 说明" in card2.changelog_text.toPlainText())

    card2.ver_combo.setCurrentText("2.4.7（当前前端）")
    chk("选标注项解析回裸版本号 2.4.7", card2._lite_selected[0] == "2.4.7")
    chk("标注项保留该版官方更新说明",
        card2._lite_version_map.get("2.4.7（当前前端）") == "2.4.7 说明")
    chk("更新说明区显示该版说明", "2.4.7 说明" in card2.changelog_text.toPlainText())
    card2.ver_combo.setCurrentText("2.4.8（当前后端）")
    chk("选后端标注项解析回裸版本号 2.4.8", card2._lite_selected[0] == "2.4.8")

# =====================================================================
# H. 后端识别按 sys.path 真实优先级（用户目录 > 内嵌） + pip 假成功拦截
# =====================================================================
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "python-embedded", "Lib", "site-packages"))
open(os.path.join(tmp, "whimbox_app.exe"), "w").close()
open(os.path.join(tmp, "python-embedded", "python312.dll"), "w").close()
uss = os.path.join(tmp, "appdata", "Python", "Python312", "site-packages")
di = os.path.join(uss, "whimbox-2.4.7.dist-info")
os.makedirs(di)
fake_app = {"exe": os.path.join(tmp, "whimbox_app.exe")}
with patch.dict(os.environ, {"APPDATA": os.path.join(tmp, "appdata")}):
    chk("用户目录有 → 识别 2.4.7（App 实际 import 的就是它）",
        launcher._lite_backend_version(fake_app) == "2.4.7")
    os.rmdir(di)
    os.makedirs(os.path.join(tmp, "python-embedded", "Lib", "site-packages",
                             "whimbox-2.5.0.dist-info"))
    chk("用户目录无 → 回退读内嵌 site-packages",
        launcher._lite_backend_version(fake_app) == "2.5.0")

class FakePipProc:
    """非提权 pip：stdout 流式输出一行、退出码 0（谎报成功，实际没进内嵌目录）"""
    def __init__(self):
        self.stdout = iter(["Successfully installed whimbox-2.4.7\n"])
    def wait(self):
        return 0

class FakePsProc:
    """提权 powershell 包装进程：第一次 poll 未结束，随后退出"""
    def __init__(self):
        self._n = 0
    def poll(self):
        self._n += 1
        return None if self._n == 1 else 0

whl_tmp = os.path.join(tmp, "whimbox-2.4.7-py3-none-any.whl")   # 临时路径，避免碰真实缓存
open(whl_tmp, "w").close()
wk = launcher.LitePipWorker(
    os.path.join(tmp, "python-embedded", "python.exe"), whl_tmp, parent=None)
wk._poll_interval = 0
rec2, elev, progs = {}, [], []
wk.finished_ok.connect(lambda m: rec2.setdefault("ok", m))
wk.failed.connect(lambda m: rec2.setdefault("fail", m))
wk.progress_text.connect(lambda t: progs.append(t))
with patch.object(launcher, "_dir_writable", return_value=True), \
     patch.object(launcher.subprocess, "Popen", return_value=FakePipProc()), \
     patch.object(wk, "_run_elevated",
                  side_effect=lambda: (elev.append(1) or (True, "已提权重装"))):
    wk.run()
chk("pip 假成功(rc=0 但没进内嵌)→拦截并提权重装",
    len(elev) == 1 and rec2.get("ok") == "已提权重装")
chk("pip 输出实时进卡片(不等装完)", any("Successfully installed" in p for p in progs))
rec2.clear(); elev.clear(); progs.clear()
with patch.object(launcher, "_dir_writable", return_value=False), \
     patch.object(wk, "_run_elevated",
                  side_effect=lambda: (elev.append(1) or (True, "已提权重装"))):
    wk.run()
chk("目标目录不可写→直接 UAC 提权(不制造 C 盘残留)",
    len(elev) == 1 and rec2.get("ok") == "已提权重装")

# 黑窗被隐藏后，其重定向输出文件的尾巴能被搬进卡片
tail_rec = []
w2 = launcher.LitePipWorker("x", "y", parent=None)
w2.progress_text.connect(lambda t: tail_rec.append(t))
pf = os.path.join(tmp, "out.txt")
with open(pf, "w") as f:
    f.write("Installing collected packages: colorama\n43/100 [colorama]\n")
w2._emit_tail(pf)
chk("隐藏黑窗的输出尾巴实时搬进卡片", any("43/100 [colorama]" in t for t in tail_rec))

# =====================================================================
# I. pip 真实进度 → 卡片进度条从走马灯切成会涨的确定进度条
# =====================================================================
P = launcher.LitePipWorker._parse_percent
chk("解析 43/100 → 43%", P("43/100 [colorama]") == 43)
chk("解析 Installing 行里的 7/9", P("Installing collected packages: 7/9 [numpy]") == 77)
chk("解析终端百分比 45%", P("  Downloading pkg: 45% |####    | 1.2M/2.6M") == 45)
chk("解析不到返回 -1", P("Successfully installed whimbox-2.4.8") == -1)
card._lite_start_spin("安装中…")
chk("未拿到真进度前是走马灯(0,0)",
    card.install_progress.minimum() == 0 and card.install_progress.maximum() == 0)
card._on_lite_pip_percent(43)
chk("收到真进度→切成 0-100 确定进度",
    card.install_progress.minimum() == 0 and card.install_progress.maximum() == 100)
chk("进度条走到 43%", card.install_progress.value() == 43)
card._on_lite_pip_percent(100)
chk("进度条到 100%", card.install_progress.value() == 100)
card._lite_start_spin("安装中…")
chk("下一次仍回到走马灯(0,0)", card.install_progress.maximum() == 0)
chk("百分比状态也重置", card._lite_spin_pct == -1)

# 有真进度 → 状态行显示百分比而非秒数；没有 → 退回秒数当心跳
card._lite_start_spin("安装中…")
chk("无进度时显示秒数(心跳)", "已等" in card.install_status.text())
card._on_lite_pip_percent(43)
card._lite_spin_tick()
txt = card.install_status.text()
chk("有进度时显示百分比", "43%" in txt)
chk("有进度时不再显示秒数", "已等" not in txt)
card._on_lite_pip_percent(87)
card._lite_spin_tick()
chk("百分比随进度更新", "87%" in card.install_status.text())
card._lite_stop_spin()

# 重定向到文件后 pip 会关掉终端进度条（实测无 N/M 无 %）→ 用包计数法兜底
chk("计数法：卸载 2/3 → 66%", wk._pct_from_lines([
    "Installing collected packages: colorama, numpy, whimbox",
    "Successfully uninstalled colorama-0.4.6",
    "Successfully uninstalled numpy-1.0"]) == 66)
chk("计数法：全部卸完 → 100%", wk._pct_from_lines([
    "Installing collected packages: a, b",
    "Successfully uninstalled a-1", "Successfully uninstalled b-1"]) == 100)
chk("行内 N/M 优先于计数法", wk._pct_from_lines([
    "Installing collected packages: a, b, c", "43/100 [colorama]"]) == 43)
chk("啥都没有 → -1（保持走马灯）", wk._pct_from_lines(["Processing x.whl"]) == -1)

# 前端安装器要求管理员（WinError 740）→ 自动提权重跑，不再弹"前端安装失败"
def raise_740(cmd, **kw):
    raise OSError(740, "请求的操作需要提升", None, 740)

w4 = launcher.LiteInstallFrontendWorker("s.exe", TARGET, EXE, "2.4.7", "2.1.1",
                                        parent=None)
rec4, elev4 = {}, []
w4.finished_ok.connect(lambda c: rec4.setdefault("ok", c))
w4.failed.connect(lambda e: rec4.setdefault("fail", e))
with patch.object(launcher, "subprocess") as sp, \
     patch.object(launcher, "_exe_file_version", return_value="2.4.7"), \
     patch.object(w4, "_run_elevated_installer",
                  side_effect=lambda: (elev4.append(1) or True)):
    sp.Popen = MagicMock(side_effect=raise_740)
    sp.run = lambda *a, **k: None
    sp.CREATE_NO_WINDOW = 0
    w4.run()
chk("WinError 740 → 自动提权重跑安装器", len(elev4) == 1 and rec4.get("ok") == "ok")
chk("提权跑完仍走 FileVersion 校验", rec4.get("ok") == "ok")

# 740 且 UAC 被拒绝 → 明确报错而不是崩溃
rec4.clear(); elev4.clear()
with patch.object(launcher, "subprocess") as sp, \
     patch.object(w4, "_run_elevated_installer", side_effect=lambda: False):
    sp.Popen = MagicMock(side_effect=raise_740)
    sp.run = lambda *a, **k: None
    sp.CREATE_NO_WINDOW = 0
    w4.run()
chk("UAC 拒绝 → failed 带明确提示", "fail" in rec4 and "UAC" in rec4["fail"])

# pip 日志增量计数（真实日志已验证：总包 106 / 卸载行 106）
lg = os.path.join(tmp, "elev.log")
with open(lg, "w") as fh:
    fh.write("2026-10-02T01:06:20,859 Installing collected packages: a, b, c, d\n")
    fh.write("Successfully uninstalled a-1\nSuccessfully uninstalled b-1\n")
w3 = launcher.LitePipWorker("x", "y", parent=None)
rec3 = []
w3.progress.connect(lambda p: rec3.append(p))
w3._scan_log(lg)
chk("pip 日志计数：卸 2/4 → 50%", rec3 and rec3[-1] == 50)
with open(lg, "a") as fh:
    fh.write("Successfully uninstalled c-1\nSuccessfully uninstalled d-1\n")
w3._scan_log(lg)
chk("增量续读：卸 4/4 → 100%", rec3[-1] == 100)

# =====================================================================
# J. 后端装完立即刷新卡片（ver_hint/按钮不再停留在更新前的旧值）
# =====================================================================
card3 = launcher.AppCard(app)
card3._rebuild_lite_body()
with patch.object(launcher, "_exe_file_version", return_value="2.4.7"), \
     patch.object(launcher, "_lite_backend_version", return_value="2.5.1"), \
     patch.object(launcher.QMessageBox, "information") as info2:
    card3._on_lite_check_done({
        "tag": "3.1.0", "exe": "https://x/setup-3.1.0.exe",
        "whl": "https://x/whimbox-3.1.0-py3-none-any.whl",
        "body": "3.1.0 说明",
        "versions": [
            {"tag": "3.1.0", "exe": "https://x/setup-3.1.0.exe",
             "whl": "https://x/whimbox-3.1.0-py3-none-any.whl", "body": "3.1.0 说明"},
            {"tag": "2.5.1", "exe": "",
             "whl": "https://x/whimbox-2.5.1-py3-none-any.whl", "body": "2.5.1 说明"},
        ],
    })
    card3.ver_combo.setCurrentText("2.5.1（当前后端）")
    card3._on_lite_pip_done("out")
    hint = card3.ver_hint.text()
    chk("装完 ver_hint 立即显示新后端 2.5.1", "后端 2.5.1" in hint)
    chk("ver_hint 仍显示仓库最新 3.1.0（有更新）", "仓库最新 3.1.0" in hint and "有更新" in hint)
    chk("按钮按新状态重算（已是最新）", "已是最新" in card3.update_btn.text())
    chk("完成弹窗照常弹出", info2.called)
    chk("徽章仍按前端算可更新（3.1.0>2.4.7）", card3._lite_has_update is True)

    # 下拉标注也要跟着挪（不再等下次检查更新）
    card3._lite_selected = ("2.5.1", "", "https://x/w.whl", "2.4.7")
    with patch.object(launcher, "_lite_backend_version", return_value="2.4.8"):
        card3._on_lite_check_done({        # 先造出"后端还标在 2.4.8"的旧状态
            "tag": "3.1.0", "exe": "https://x/setup-3.1.0.exe",
            "whl": "", "body": "",
            "versions": [
                {"tag": "3.1.0", "exe": "https://x/setup-3.1.0.exe", "whl": "", "body": ""},
                {"tag": "2.5.1", "exe": "", "whl": "https://x/w.whl", "body": "2.5.1 说明"},
                {"tag": "2.4.8", "exe": "", "whl": "https://x/w8.whl", "body": "2.4.8 说明"},
            ],
        })
        chk("旧状态：后端标注在 2.4.8",
            card3.ver_combo.findText("2.4.8（当前后端）") >= 0)
        chk("旧状态：2.5.1 是无标注裸项", card3.ver_combo.findText("2.5.1") >= 0)
    with patch.object(launcher, "_lite_backend_version", return_value="2.5.1"):
        card3._on_lite_pip_done("out")     # 装完 2.5.1 → 标注应立即挪过去
        chk("装完：后端标注挪到 2.5.1",
            card3.ver_combo.findText("2.5.1（当前后端）") >= 0)
        chk("装完：旧标注已剥掉", card3.ver_combo.findText("2.4.8（当前后端）") == -1)
        chk("装完：说明文本跟着搬", card3._lite_version_map.get("2.5.1（当前后端）") == "2.5.1 说明")

print("\n%d failed" % len(fails))
_rc = 1 if fails else 0
sys.stdout.flush()
sys.stderr.flush()
os._exit(_rc)   # 避开 Qt 线程销毁污染退出码（详见 generic_app_test.py 注释）

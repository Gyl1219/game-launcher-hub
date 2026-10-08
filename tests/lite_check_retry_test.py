import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import launcher
from PySide6.QtWidgets import QApplication
qapp = QApplication(sys.argv)


class _Sig:
    def connect(self, *a, **k): pass


class _NoopWorker:
    """不启动真实线程的 worker 桩。

    必须在构造 AppCard **之前**换上：卡片 __init__ 会调 _lite_start_check()
    起真实的联网检查线程。留着它跑，测试结束时 os._exit 会撞在线程持有的
    原生锁上，偶发 0xC0000005 访问违例（实测 5 次崩 2 次）。
    从源头不建线程，才是稳定解法；事后 wait()/sleep 都只是碰运气。
    """

    def __init__(self, *a, **k):
        self.done = _Sig()
        self.failed = _Sig()

    def start(self):
        pass


_orig_check_worker = launcher.LiteReleaseCheckWorker   # 真类留个引用，便于需要时还原
launcher.LiteReleaseCheckWorker = _NoopWorker

app = [a for a in launcher.APPS if a.get("key") == "whimbox"][0]
card = launcher.AppCard(app)
card._rebuild_lite_body()

fails = []
def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

# 1) 构建时本地填充当前版本（不依赖网络）
_fe = launcher._exe_file_version(app["exe"])  # 动态取本机真实前端版本，避免断言随升级失效
hint = card.ver_hint.text()
chk("ver_hint 构建即填充: %r" % hint, "前端" in hint and "后端" in hint and _fe in hint)

# 2) 检查失败 → 按钮可点重试、说明区不再挂"正在获取"
card._on_lite_check_failed("uread timeout")
chk("失败后按钮文案", card.update_btn.text() == "检查更新失败（网络）· 点击重试")
chk("失败后按钮可点", card.update_btn.isEnabled())
chk("失败后说明区提示重试", "重试" in card.changelog_text.toPlainText()
    and "正在获取更新说明" not in card.changelog_text.toPlainText())

# 3) 重试：重置守卫并重启检查（mock worker，防真联网）
# 真实场景：失败回调触发时旧 worker 已结束，这里模拟该状态
card._lite_check_worker = None
started = {"n": 0}
class _Sig:
    def connect(self, *a, **k): pass
class FakeWorker:
    def __init__(self, *a, **k):
        self.done = _Sig(); self.failed = _Sig()
    def start(self): started["n"] += 1
orig_worker_cls = launcher.LiteReleaseCheckWorker
launcher.LiteReleaseCheckWorker = FakeWorker
card._on_lite_check_retry()
chk("重试触发了新检查", started["n"] == 1)
chk("重试后按钮进入检查中", card.update_btn.text() == "检查更新中…" and not card.update_btn.isEnabled())
card._lite_check_worker = None  # 释放 fake 引用
launcher.LiteReleaseCheckWorker = orig_worker_cls

# 4) 成功回调：按钮接回更新入口；空 tag 分支也可重试
card._on_lite_check_done({})
chk("空 tag → 可重试文案", "重试" in card.update_btn.text() and card.update_btn.isEnabled())

# 5) 完整 info → 按钮回「检查更新」，且 ver_hint 带上仓库最新
fake_info = {
    "tag": "3.1.0", "exe": "https://example/x.exe", "whl": "https://example/x.whl",
    "body": "note",
    "versions": [{"tag": "3.1.0", "body": "note",
                  "exe": "https://example/x.exe", "whl": "https://example/x.whl"}],
}
card._on_lite_check_done(fake_info)
chk("成功后按钮脱离重试态(文案=%r)" % card.update_btn.text(),
    "重试" not in card.update_btn.text() and card.update_btn.isEnabled())
chk("成功后 ver_hint 含仓库最新", "3.1.0" in card.ver_hint.text())

print("\n%d failed" % len(fails))
_rc = 1 if fails else 0
sys.stdout.flush()
sys.stderr.flush()
os._exit(_rc)   # 避开 Qt 线程销毁污染退出码（详见 generic_app_test.py 注释）

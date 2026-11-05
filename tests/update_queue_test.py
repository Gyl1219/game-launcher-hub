# -*- coding: utf-8 -*-
"""「全部更新」队列契约测试（用户定稿：串行、失败不中断、汇总上报）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LAUNCHER_TELEMETRY_NOASK", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

fails = []


def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


def job(key, display=""):
    return {"key": key, "display": display or key.upper(),
            "app": {"key": key}, "target": "v9", "git_url": "https://x/" + key}


class _Rec:
    """信号记录器。"""

    def __init__(self):
        self.started = []
        self.done = []
        self.finished = []

    def bind(self, q):
        q.item_started.connect(lambda k, d, t: self.started.append((k, d, t)))
        q.item_done.connect(lambda k, ok, m: self.done.append((k, ok, m)))
        q.finished.connect(lambda ok, fails: self.finished.append((ok, fails)))
        return self


# singleShot 改同步：队列确定性排空（真实运行里 600ms 间隔只是缓冲）
launcher.QTimer.singleShot = staticmethod(lambda ms, fn: fn())


class _FakeMirror(QObject):
    """可编程的 MirrorUpdater 替身：按 key 决定下载成败。"""

    progress = Signal(int, str)
    done = Signal(str)
    failed = Signal(str)
    fail_keys = set()

    def __init__(self, key, git_url, target, parent=None):
        super().__init__(parent)
        self.key = key

    def start(self):
        if self.key in type(self).fail_keys:
            self.failed.emit("模拟拉取失败")
        else:
            self.done.emit("/repos/" + self.key)


class _FakeApply(QObject):
    """可编程的 ApplyWorker 替身：按 app key 决定应用成败。"""

    progress = Signal(str)
    done = Signal(bool, str)
    fail_keys = set()

    def __init__(self, app, target, local_dir, parent=None):
        super().__init__(parent)
        self.key = app.get("key", "")

    def start(self):
        if self.key in type(self).fail_keys:
            self.done.emit(False, "模拟同步失败")
        else:
            self.done.emit(True, "已更新到 v9")


real_mirror, real_apply = launcher.MirrorUpdater, launcher.ApplyWorker
launcher.MirrorUpdater = _FakeMirror
launcher.ApplyWorker = _FakeApply

print("--- 1) 全部成功：串行顺序 + 汇总 ---")
q = launcher._UpdateQueue()
rec = _Rec().bind(q)
q.enqueue([job("a"), job("b"), job("c")])
q.start()
chk("三个条目按入队顺序执行",
    [s[0] for s in rec.started] == ["a", "b", "c"], rec.started)
chk("全部成功", rec.finished == [(3, [])], rec.finished)

print("\n--- 2) 下载失败不中断队列（负向对照点）---")
_FakeMirror.fail_keys = {"b"}
qq2 = launcher._UpdateQueue()
rec2 = _Rec().bind(qq2)
qq2.enqueue([job("a"), job("b"), job("c")])
qq2.start()
chk("失败项照常标记 done(ok=False)",
    ("b", False, "模拟拉取失败") in rec2.done, rec2.done)
chk("失败不影响后续（c 仍执行）", [s[0] for s in rec2.started] == ["a", "b", "c"],
    rec2.started)
chk("汇总：成功 2 个 + 失败名单含 B",
    rec2.finished == [(2, [("B", "模拟拉取失败")])], rec2.finished)

print("\n--- 3) 应用阶段失败也计入汇总 ---")
_FakeMirror.fail_keys = set()
_FakeApply.fail_keys = {"b"}
qq = launcher._UpdateQueue()
rec3 = _Rec().bind(qq)
qq.enqueue([job("a"), job("b")])
qq.start()
chk("应用失败计入失败名单", rec3.finished[0][1] == [("B", "模拟同步失败")],
    rec3.finished)

launcher.MirrorUpdater = real_mirror
launcher.ApplyWorker = real_apply

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

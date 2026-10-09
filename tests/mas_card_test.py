# -*- coding: utf-8 -*-
"""端到端验证：AUTO-MAS 卡片真的出现在界面、按钮真的能拉起后端。

这是与「ServiceWorker 单独跑通」的关键区别：证明它装进车里能开。
"""
import os, sys, io, time, subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))


# 1) 配置里有 auto-mas
keys = [a["key"] for a in launcher.APPS]
chk("1) 配置包含 auto-mas", "auto-mas" in keys, str(keys))

# 2) vendor 优先定位
repo, py = launcher.auto_mas_paths()
chk("2) 定位到 vendor 副本", repo.endswith("vendor\\auto-mas"),
    "repo=%s" % repo)
chk("2b) 解释器可用", bool(py and os.path.isfile(py)), py)

# 3) 主窗口能建、卡片存在
win = launcher.Launcher()
win.show()
app.processEvents()
chk("3) 主窗口构建成功", win is not None)
chk("3b) auto-mas 卡片已创建", "auto-mas" in win.cards, str(list(win.cards.keys())))

card = win.cards.get("auto-mas")
if card:
    chk("3c) 走 MAS 形态分支", getattr(card, "_mas", False) is True)
    chk("3d) 有启动按钮", hasattr(card, "mas_start_btn"))
    chk("3e) 按钮可点（依赖齐时）", card.mas_start_btn.isEnabled(),
        "初始状态=%s" % card._mas_state)
    chk("3f) 停按钮初始禁用", not card.mas_stop_btn.isEnabled())

    # 4) 真点「启动后端」→ 等 ready
    card._mas_start()
    end = time.time() + 120
    while time.time() < end:
        app.processEvents()
        if getattr(card, "_mas_state", "") in ("ready", "failed"):
            break
        time.sleep(0.3)
    st = getattr(card, "_mas_state", "")
    chk("4) 点启动后进入 ready", st == "ready", "状态=%s 详情=%s"
        % (st, card.mas_detail.text() if hasattr(card, "mas_detail") else ""))

    if st == "ready":
        chk("4b) 停按钮已启用", card.mas_stop_btn.isEnabled())
        pid = card._mas_worker._proc.pid if card._mas_worker and card._mas_worker._proc else None
        chk("4c) 后端进程已拉起", bool(pid), "pid=%s" % pid)

        # 5) 点「停止后端」→ 进程退出
        card._mas_stop()
        end = time.time() + 60
        while time.time() < end:
            app.processEvents()
            if getattr(card, "_mas_state", "") == "stopped":
                break
            time.sleep(0.3)
        chk("5) 点停止后回到 stopped",
            getattr(card, "_mas_state", "") == "stopped",
            "状态=%s" % getattr(card, "_mas_state", ""))
        if pid:
            # 注意时序：_mas_state 变 stopped 时进程**正在退出**，实际退出约需 1s
            # （实测 poll 在 t=1.0s 时变 0）。必须等进程真正结束再断言，
            # 否则会误判成"进程残留"。
            w = getattr(card, "_mas_worker", None)
            exited = False
            for _ in range(30):
                app.processEvents()
                if w is None or w._proc is None or w._proc.poll() is not None:
                    exited = True
                    break
                time.sleep(0.3)
            chk("5b) 后端进程已退出", exited,
                "rc=%s" % (w._proc.poll() if w and w._proc else "?"))
            alive = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=20).stdout
            chk("5c) 进程表中已无该 pid", str(pid) not in alive, "pid=%s" % pid)

# 6) 无孤儿
time.sleep(1.5)
out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace", timeout=20).stdout
orph = [l for l in out.splitlines() if "AUTO-MAS" in l]
chk("6) 无 AUTO-MAS 孤儿进程", not orph, "残留 %d" % len(orph))

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

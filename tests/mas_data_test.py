# -*- coding: utf-8 -*-
"""AUTO-MAS 融合页真数据端到端：新建脚本/队列/队列项 → 界面真显示 → 删除/停干净。

与 mas_page_test.py 的分工：那边验「不崩」，这边验「真能用」——
每一步都打真实后端 HTTP，最后断言进程退干净、无孤儿。

安全：用**临时数据目录**（monkeypatch auto_mas_home），
不碰用户真实的 auto-mas 数据（队列/账号都在那里）。
"""
import os, sys, io, time, tempfile, shutil, subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import launcher
from PySide6.QtWidgets import QApplication, QMessageBox

OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


def finish(code):
    print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
    for f in FAIL:
        print("   FAILED:", f)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


# ---------- 前置：后端源码/解释器必须在 ----------
repo, py = launcher.auto_mas_paths()
if not (repo and py and os.path.isfile(py)):
    print("SKIP: 本机没有可用的 AUTO-MAS 后端（vendor/auto-mas + Python3.12 环境）")
    print("      vendor=%r python=%r" % (repo, py))
    finish(0)

TMP = tempfile.mkdtemp(prefix="mas_home_test_")
launcher.auto_mas_home = lambda: TMP        # 必须早于 Launcher() 构造

app = QApplication.instance() or QApplication(sys.argv)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)


def wait(cond, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.2)
    app.processEvents()
    return cond()


win = launcher.Launcher()
win.show()
page = win.mas_page
page._auto_started = True
win.switch_to(launcher.AUTO_MAS_MENU_KEY)
app.processEvents()


def settle(seconds=10):
    """等本轮刷新（含第二段）结束。"""
    wait(lambda: not page._busy, seconds)
    app.processEvents()


try:
    # ---------- 1) 真启动后端 ----------
    page.start_backend()
    ok = wait(lambda: page._state in ("ready", "failed"), 180)
    chk("1) 后端进入 ready", ok and page._state == "ready",
        "状态=%s 详情=%s" % (page._state, page._detail[:100]))
    if page._state != "ready":
        finish(1)
    chk("1b) health 版本/协议正确",
        (page._health or {}).get("version") == "5.6.2"
        and (page._health or {}).get("protocol") == 1, str(page._health)[:100])
    chk("1c) 用的是临时数据目录", os.path.normcase(page._home) == os.path.normcase(TMP),
        page._home)

    # ---------- 2) 新建脚本（走本页动作 → 后端 API）----------
    page.add_script("OkNte")
    settle()
    page.reload()
    settle()
    chk("2) 界面新建脚本生效", len(page._scripts) == 1, "脚本数=%d" % len(page._scripts))
    script_uid = page._scripts[0].get("uid", "") if page._scripts else ""
    chk("2b) 脚本类型是 OkNte",
        (page._scripts[0].get("type") if page._scripts else "") == "OkNteConfig",
        str(page._scripts[:1]))

    # ---------- 3) 新建队列 ----------
    page.new_queue()
    settle()
    page.reload()
    settle()
    chk("3) 界面新建队列生效", len(page._queues) == 1, "队列数=%d" % len(page._queues))
    queue_uid = list(page._queues)[0] if page._queues else ""
    chk("3b) 队列有自动名", bool((page._queues.get(queue_uid) or {}).get("Name")),
        str(page._queues.get(queue_uid))[:80])

    # ---------- 4) 队列项 = 脚本（两步写操作）----------
    if script_uid and queue_uid:
        page.add_item_to_queue(queue_uid, script_uid)
        settle(12)
        page.reload()
        settle(12)
        items = page._items.get(queue_uid) or []
        chk("4) 队列项写入成功", len(items) == 1, "队列项=%d" % len(items))
        chk("4b) 队列项指向该脚本",
            bool(items) and ((items[0].get("Info") or {}).get("ScriptId")) == script_uid,
            str((items[0].get("Info") if items else None)))

    # ---------- 5) 界面真的渲染出卡片 ----------
    from qfluentwidgets import CaptionLabel

    def cards_of(body, cls):
        return [body.itemAt(i).widget() for i in range(body.count())
                if isinstance(body.itemAt(i).widget(), cls)]

    qcards = cards_of(page._bodies["queue"], launcher._MasQueueCard)
    scards = cards_of(page._bodies["scripts"], launcher._MasScriptCard)
    chk("5) 队列视图渲染出队列卡", len(qcards) == 1, "卡数=%d" % len(qcards))
    chk("5b) 脚本视图渲染出脚本卡", len(scards) == 1, "卡数=%d" % len(scards))

    def texts(w):
        return "\n".join(c.text() for c in w.findChildren(CaptionLabel))

    sname = page._script_names().get(script_uid, "")
    qt = texts(qcards[0]) if qcards else ""
    chk("5c) 队列卡显示了脚本名", bool(sname) and sname in qt,
        "脚本名=%r 卡文本=%s" % (sname, qt[:80].replace("\n", " / ")))
    st = texts(scards[0]) if scards else ""
    # 脱敏红线：读接口返回的是 DPAPI 解密后的明文，界面只允许白名单字段
    chk("5d) 脚本卡不泄漏凭据字段",
        ("Password" not in st) and ("Token" not in st) and ("CDK" not in st),
        st[:60].replace("\n", " / "))

    # ---------- 6) 请求体契约（用不存在的 taskId 走错误分支，且不会真跑任务）----------
    ok, data = launcher.mas_api_request(
        page._base, "/api/dispatch/start",
        {"mode": "AutoProxy", "taskId": "00000000-0000-0000-0000-000000000000"})
    chk("6) dispatch/start 请求体被后端接受（非 422）",
        ok and isinstance(data, dict) and int(data.get("code", 200)) == 500,
        str(data)[:90])
    ok2, d2 = launcher.mas_api_request(page._base, "/api/dispatch/stop", {"taskId": "ALL"})
    chk("6b) dispatch/stop ALL 可用", ok2 and isinstance(d2, dict), str(d2)[:80])
    chk("6c) 不存在的接口走错误分支不抛",
        launcher.mas_api_request(page._base, "/api/nope")[0] is False)

    # ---------- 7) 删除队列 ----------
    if queue_uid:
        page.delete_queue(queue_uid)
        settle()
        page.reload()
        settle()
        chk("7) 删除队列生效", len(page._queues) == 0, "队列数=%d" % len(page._queues))

    # ---------- 8) 停后端 + 无孤儿 ----------
    pid = page._worker._proc.pid if (page._worker and page._worker._proc) else None
    page.stop_backend()
    wait(lambda: page._state == "stopped", 60)
    chk("8) 停止后回到 stopped", page._state == "stopped", page._state)
    if pid:
        chk("8b) 后端进程真的退了",
            wait(lambda: page._worker is None or page._worker._proc is None
                 or page._worker._proc.poll() is not None, 15))
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=20).stdout
    orph = [l for l in out.splitlines() if "auto-mas" in l.lower()]
    chk("8c) 无 AUTO-MAS 孤儿进程", not orph, "残留 %d" % len(orph))
finally:
    try:
        page.shutdown()
        win.close()
        app.processEvents()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

finish(1 if FAIL else 0)

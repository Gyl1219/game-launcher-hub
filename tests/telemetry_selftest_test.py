# -*- coding: utf-8 -*-
"""遥测发送测试（③）：不部署服务端也能验证整条链路。

用户质疑得很实在："人家那是真能收到日志吧，我这能收到？"
实测答案：**收不到** —— endpoint 留空时 telemetry_send 直接返回失败，
界面上勾着开关也一条都发不出去。所以这个自测的价值是"证明链路真的通"，
而不是"界面上有个开关"。

本测试覆盖：
  · 正常路径：本机假接收端收到和真实上报同构的 payload；
  · 脱敏：路径 / CDK / 邮箱必须变成占位符，且断言"真的抹掉了"而不是"没报错"；
  · 负向：故意喂一条**未脱敏**的 payload，自测必须报 leaked（防止自测永远通过）；
  · 空 endpoint：明确返回失败 + 人话原因，不能假装成功；
  · 端点拒收（HTTP 500）：报失败而不是静默成功。
"""
import os, sys, io, json, threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtWidgets import QApplication, QMessageBox

OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


# ================= 1) 正常路径：链路真的通 =================
res = launcher.telemetry_selftest()
chk("1) 自测链路通（本机假接收端收到数据）", res["ok"], res["message"])
recv = res.get("received") or {}
chk("1b) 收到的是同构 payload（含关键字段）",
    all(k in recv for k in ("v", "app", "version", "anon_id", "kind",
                            "message", "detail", "os", "py", "ts")),
    str(sorted(recv.keys())))
chk("1c) app 标识正确", recv.get("app") == "game-launcher-hub", str(recv.get("app")))
chk("1d) kind 标明是自测（不会混进真实崩溃统计）",
    recv.get("kind") == "selftest", str(recv.get("kind")))

# ================= 2) 脱敏：真抹掉了，不是没报错 =================
blob = json.dumps(recv, ensure_ascii=False)
chk("2) 本机路径被抹成占位符",
    "<LAUNCHER_DIR>" in blob or "<HOME>" in blob, blob[:120])
chk("2b) CDK 被抹成 <redacted>", "<redacted>" in blob)
chk("2c) 邮箱被抹成 <email>", "<email>" in blob)
chk("2d) 三类敏感串一个都没漏",
    res["leaked"] == [], str(res["leaked"]))

# ================= 3) 负向：自测必须能发现"没脱敏" =================
# 这段是防"自测永远通过"的：故意构造一条未脱敏 payload，
# 用同一个接收端逻辑检查，必须报出泄漏。
def _send_raw_and_audit(raw_payload):
    """把**未经脱敏**的 payload 投给本机接收端，返回 (是否收到, 泄漏列表)。"""
    import http.server, socketserver
    got = {}
    done = threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            got["body"] = json.loads(self.rfile.read(n).decode("utf-8"))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            done.set()

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        launcher.telemetry_send(raw_payload,
                               endpoint="http://127.0.0.1:%d/collect" % port)
        done.wait(2)
    finally:
        srv.shutdown()
        srv.server_close()

    b = json.dumps(got.get("body") or {}, ensure_ascii=False)
    leaks = [p for p in ("TEST_CDK_1234567890", "someone@example.com")
             if p in b]
    return bool(got.get("body")), leaks


raw_ok, raw_leaks = _send_raw_and_audit({
    "v": 1, "kind": "selftest-raw",
    "detail": "cdk=TEST_CDK_1234567890 mail=someone@example.com",
})
chk("3) 负向对照：未脱敏的 payload 会被审计抓出来", raw_ok and raw_leaks,
    "收到=%s 泄漏=%s" % (raw_ok, raw_leaks))
chk("3b) 说明自测的 leaked 检查不是永远为空（有真实检出能力）",
    len(raw_leaks) >= 2, str(raw_leaks))

# ================= 4) 空 endpoint：明确失败，不假装成功 =================
ok, msg = launcher.telemetry_send({"v": 1}, endpoint="")
chk("4) 空 endpoint 返回失败", ok is False, str(ok))
chk("4b) 失败原因说清了（不是空字符串）",
    bool(msg) and ("endpoint" in msg or "未配置" in msg), msg)

# ================= 5) 端点拒收：报失败 =================
import http.server, socketserver


class _Reject(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.send_response(500)
        self.send_header("Content-Length", "0")
        self.end_headers()


srv2 = socketserver.TCPServer(("127.0.0.1", 0), _Reject)
port2 = srv2.server_address[1]
threading.Thread(target=srv2.serve_forever, daemon=True).start()
try:
    ok2, msg2 = launcher.telemetry_send({"v": 1},
                                        endpoint="http://127.0.0.1:%d/x" % port2)
finally:
    srv2.shutdown()
    srv2.server_close()
chk("5) HTTP 500 被报成失败（不是静默成功）", ok2 is False, str(ok2))
# 状态码不一定拿得到：有的服务端 5xx 后立刻断连，urllib 只能抛连接被中止。
# 关键契约是"必须报失败且说明可读"，而不是"必须包含 500"。
chk("5b) 失败信息可读（含状态码或说明被拒）",
    ("500" in str(msg2)) or ("拒" in str(msg2)) or ("中止" in str(msg2)), str(msg2))

# ================= 6) 界面接线（按钮真的存在且能用）=================
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

app = QApplication.instance() or QApplication(sys.argv)
win = launcher.Launcher()
win.show()
app.processEvents()
sp = win.settings_page
chk("6) 设置页有「发送测试上报」按钮", hasattr(sp, "tele_test_btn"))
chk("6b) 还有「测试已配置的端点」按钮", hasattr(sp, "tele_real_btn"))
chk("6c) 端点为空时真实端点按钮禁用（不给假动作）",
    sp.tele_real_btn.isEnabled() == bool(
        str((sp._read_cfg().get("telemetry") or {}).get("endpoint") or "").strip()),
    "enabled=%s" % sp.tele_real_btn.isEnabled())

# 点一下真实渲染结果（走线程，等它回来）
sp._show_tele_result(res)
app.processEvents()
chk("6d) 结果回显含「链路通」", "链路通" in sp.tele_test_out.text(),
    sp.tele_test_out.text()[:80])
chk("6e) 结果回显含收到的字段名", "anon_id" in sp.tele_test_out.text(),
    sp.tele_test_out.text()[:120])
sp._show_tele_result({"ok": False, "message": "boom", "received": None,
                      "leaked": ["someone@example.com"]})
app.processEvents()
chk("6f) 失败态回显 ✗ 且点名泄漏项",
    "✗" in sp.tele_test_out.text() and "someone@example.com" in sp.tele_test_out.text(),
    sp.tele_test_out.text()[:120])

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

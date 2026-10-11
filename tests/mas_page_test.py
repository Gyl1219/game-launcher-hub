# -*- coding: utf-8 -*-
"""AUTO-MAS 融合页的纯函数层：HTTP 客户端、日志尾巴、调度文案。

这些函数不值得拉起真后端就能验，而且是「静默出错」的重灾区：
  · HTTP 客户端若把异常抛进 UI 线程，界面会直接崩（QThread 里抛也没人接）；
  · 响应体不设上限，后端异常时的一大坨 HTML 会把内存/解析拖死；
  · 日志尾巴按字节截断，不切齐行就会切出半个 UTF-8 汉字（中文日志全是乱码）。
"""
import os, sys, io, json, time, socket, threading, tempfile, shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from http.server import BaseHTTPRequestHandler, HTTPServer
from PySide6.QtWidgets import QApplication, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app = QApplication.instance() or QApplication(sys.argv)

OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


# ================= 1) 本地假后端：验请求体/大小上限 =================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, code=200):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/core/health":
            self._send({"ready": True, "protocol": 1})
        elif self.path == "/api/huge":
            self._send(b"x" * (launcher.AUTO_MAS_API_MAX_BYTES + 1024))
        else:
            self._send({"detail": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = None
        self._send({"echo": payload, "ct": self.headers.get("Content-Type", "")})


srv = HTTPServer(("127.0.0.1", 0), Handler)
base = "http://127.0.0.1:%d" % srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)

ok, data = launcher.mas_api_request(base, "/api/core/health")
chk("1) GET 正常返回", ok and data.get("ready") is True, str(data))
ok, data = launcher.mas_api_request(base, "/api/queue/get", {})
chk("1b) POST 查询会带 JSON 空对象",
    ok and data.get("echo") == {} and "application/json" in data.get("ct", ""),
    str(data))
ok, data = launcher.mas_api_request(base, "/api/dispatch/start",
                                   {"mode": "AutoProxy", "taskId": "x"})
chk("1c) POST 请求体原样送达",
    ok and data.get("echo") == {"mode": "AutoProxy", "taskId": "x"}, str(data))
ok, msg = launcher.mas_api_request(base, "/api/nope")
chk("1d) 404 → (False, 'HTTP 404')", (ok is False) and msg == "HTTP 404", str(msg))
ok, msg = launcher.mas_api_request(base, "/api/huge")
chk("1e) 超大响应体被上限拦下", (ok is False) and "过大" in str(msg), str(msg))
ok, msg = launcher.mas_api_request("", "/api/core/health")
chk("1f) 空 base 不抛异常", (ok is False) and isinstance(msg, str), str(msg))
# 连不上的端口：拿一个刚关掉的端口
s = socket.socket()
s.bind(("127.0.0.1", 0))
dead_port = s.getsockname()[1]
s.close()
ok, msg = launcher.mas_api_request("http://127.0.0.1:%d" % dead_port,
                                   "/api/core/health", timeout=2)
chk("1g) 连接失败返回失败而不抛", (ok is False) and isinstance(msg, str), str(msg)[:60])
srv.shutdown()
srv.server_close()
time.sleep(0.1)      # 等 handler 线程收尾，减少退出码被 Qt/线程销毁污染的概率

# ================= 2) 日志尾巴：按行切齐 =================
tmp = tempfile.mkdtemp(prefix="mas_tail_")
try:
    log = os.path.join(tmp, "app.log")
    line = "中文日志行 %d 内容内容内容\n"
    with io.open(log, "w", encoding="utf-8") as f:
        for i in range(500):
            f.write(line % i)
    text, note = launcher._mas_tail(log, 512)
    chk("2) 尾巴能读到内容", bool(text) and not note, "note=%r" % note)
    chk("2b) 没有半个汉字（首行被丢掉）",
        "\ufffd" not in text and "中文日志行" in text, repr(text[:40]))
    chk("2c) 最后一行就是文件最后一行",
        text.strip().splitlines()[-1] == "中文日志行 499 内容内容内容",
        repr(text.strip().splitlines()[-1] if text.strip() else ""))
    chk("2d) 尾巴明显短于全文", len(text.encode("utf-8")) <= 512 + 64,
        "%d 字节" % len(text.encode("utf-8")))
    text2, note2 = launcher._mas_tail(os.path.join(tmp, "nope.log"), 512)
    chk("2e) 文件不存在时返回空 + 说明", text2 == "" and bool(note2), note2)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ================= 3) 调度文案 =================
sched = launcher._MasQueueCard._schedule_text
chk("3) 未启用 → 不参与循环", sched({"Enabled": False}) == "不参与循环")
chk("3b) 全周固定时间 → 每天 08:30",
    sched({"Enabled": True, "Mode": "fixed_time",
           "Days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                    "Saturday", "Sunday"], "Time": "08:30"}) == "每天 08:30")
chk("3c) 部分星期 → 中文缩写",
    sched({"Enabled": True, "Mode": "fixed_time",
           "Days": ["Monday", "Friday"], "Time": "20:00"}) == "周一、周五 20:00",
    sched({"Enabled": True, "Mode": "fixed_time",
           "Days": ["Monday", "Friday"], "Time": "20:00"}))
chk("3d) 间隔模式 → 每 N 分钟",
    sched({"Enabled": True, "Mode": "interval", "IntervalMinutes": 45}) == "每 45 分钟")
chk("3e) 2000-01-01 占位不显示",
    sched({"Enabled": True, "Mode": "fixed_time", "Time": "01:00",
           "Days": ["Monday"], "NextRunAt": "2000-01-01 00:00:00"}) == "周一 01:00")
chk("3f) 真实下次运行时间会显示",
    "下次 2026-10-12 08:30:00" in sched(
        {"Enabled": True, "Mode": "fixed_time", "Time": "08:30",
         "Days": ["Monday"], "NextRunAt": "2026-10-12 08:30:00"}))

# ================= 4) 其他小工具 =================
chk("4) _mas_short 截前 8 位", launcher._mas_short("abcdefgh-1234") == "abcdefgh")
chk("4b) _mas_short 容忍空值", launcher._mas_short("") == "")
hint = launcher._mas_hint("测试提示")
chk("4c) _mas_hint 返回控件", launcher._mas_hint("测试提示") is not None)


class _P:
    def __init__(self):
        self.picked = []


p = _P()
host = QWidget()      # _build_pick_menu 只用 self 当父控件，这里给个真 QWidget
menu = launcher.MasPage._build_pick_menu(host, "标题", [("a", "甲"), ("b", "乙")],
                                         lambda v: p.picked.append(v))
acts = menu.actions()
chk("4d) 菜单项数正确", len(acts) == 2, str([a.text() for a in acts]))
acts[1].trigger()
chk("4e) 菜单点击回传正确的值", p.picked == ["b"], str(p.picked))

# ================= 5) 卡片渲染：用真实形状的载荷 =================
# 运行中任务卡只有在真有任务时才渲染，端到端测试里很难稳定造出来，
# 这里直接喂一份后端 runtime-snapshot 的真实形状（字段名照 schema 抄）。
from qfluentwidgets import CaptionLabel
from PySide6.QtWidgets import QLabel


def label_text(w):
    """收集控件里所有 QLabel 文本（StrongBodyLabel/CaptionLabel/BodyLabel 都是 QLabel 子类）."""
    return "\n".join(c.text() for c in w.findChildren(QLabel))


runtime = {
    "taskId": "abcd1234-5678-90ab-cdef-1234567890ab",
    "mode": "AutoProxy", "isCycle": False, "queueId": "q-1", "scriptId": None,
    "userId": None, "stopping": True,
    "scripts": [{"scriptId": "s-1", "scriptType": "OkNteConfig"}],
    "task_info": [{"script_id": "s-1", "name": "新 OK-NTE 脚本", "status": "running",
                   "userList": [{"user_id": "u-1", "name": "账号A", "status": "running"}]}],
    "cycleNextList": [],
    "log": "第一行\n第二行\n第三行\n第四行\n第五行",
    "logSeq": 5, "logFirstLine": 1,
}
rc = launcher._MasRuntimeCard(runtime)
rtext = label_text(rc)
chk("5) 运行卡标题含任务 id 前缀", "abcd1234" in rtext, rtext[:60].replace("\n", " / "))
stopped = []
rc.sig_stop.connect(lambda t: stopped.append(t))
# 点「中止」按钮：找到带该文案的按钮
btns = [b for b in rc.findChildren(launcher.PushButton) if b.text() == "中止"]
chk("5b) 运行卡有「中止」按钮", len(btns) == 1, str([b.text() for b in rc.findChildren(launcher.PushButton)]))
if btns:
    btns[0].click()
    chk("5c) 中止回传 taskId", stopped == [runtime["taskId"]], str(stopped))
chk("5d) 运行卡显示脚本名与日志尾部",
    "新 OK-NTE 脚本" in rtext and "第五行" in rtext,
    rtext.replace("\n", " / ")[:120])
chk("5e) 运行卡标明正在停止", "正在停止" in rtext, rtext.replace("\n", " / ")[:80])

# 队列卡：循环/非循环的运行按钮文案必须不同（用错模式后端会拒）
q_cycle = launcher._MasQueueCard("q-1", {"Name": "循环队列", "CycleEnabled": True},
                                 [], [], "")
q_once = launcher._MasQueueCard("q-2", {"Name": "定时队列", "CycleEnabled": False},
                                [], [], "")
cbtns = [b.text() for b in q_cycle.findChildren(launcher.PushButton)]
obtns = [b.text() for b in q_once.findChildren(launcher.PushButton)]
chk("5f) 循环队列按钮是「启动循环」", "启动循环" in cbtns, str(cbtns))
chk("5g) 定时队列按钮是「立即运行」", "立即运行" in obtns, str(obtns))
chk("5h) 队列卡都有添加/删除按钮",
    "＋ 添加脚本" in cbtns and "删除队列" in cbtns, str(cbtns))

# 队列项摘要：脚本名 + 调度文案 + 定时项
qc = launcher._MasQueueCard(
    "q-3", {"Name": "演示队列", "TimeEnabled": True, "CycleEnabled": False,
            "StartUpMode": "DailyFirst", "AfterAccomplish": "Shutdown"},
    [{"Info": {"ScriptId": "s-1"},
      "Schedule": {"Enabled": True, "Mode": "fixed_time",
                   "Days": ["Monday"], "Time": "07:30"}}],
    [{"Info": {"Enabled": True, "Time": "23:00"}}], "",
    {"s-1": "鸣潮脚本"})
qct = label_text(qc)
chk("5i) 队列卡显示脚本名与调度", "鸣潮脚本" in qct and "周一 07:30" in qct,
    qct.replace("\n", " / ")[:120])
chk("5j) 队列卡显示定时项与完成后动作",
    "23:00" in qct and "完成后关机" in qct and "每日首次" in qct,
    qct.replace("\n", " / ")[:140])

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

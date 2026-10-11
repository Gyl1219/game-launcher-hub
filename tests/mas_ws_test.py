# -*- coding: utf-8 -*-
"""AUTO-MAS 实时通道的协议层单测（不连后端，纯字节）。

手写 RFC6455 客户端的风险全在编解码上，而且**错了不会崩、只会静默丢消息**
（帧长度读错一位，后面整条连接全错位）。所以这里把每个分支都钉死：
  · 握手 accept 用 RFC6455 官方样例向量；
  · 三种长度编码（7 位 / 16 位 / 64 位）与掩码；
  · ping / close（含 4001 让位码）/ 分片续帧；
  · socket 超时不能当"帧结束"（半帧丢失 = 后续全体错位）；
  · 超大帧必须被上限拦住；
  · 事件信封解析（非对象/非法 JSON 只能忽略，不能抛）。
"""
import os, sys, io, json, socket, struct

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher

OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


class FakeSock:
    """按小块吐字节的假 socket：用来精确复现「边界被切开 / 中途超时」。"""

    def __init__(self, data, chunk=3, timeouts=0):
        self._buf = bytearray(data)
        self._chunk = chunk
        self._timeouts = timeouts          # 先抛 N 次 socket.timeout 再给数据

    def recv(self, n):
        if self._timeouts > 0:
            self._timeouts -= 1
            raise socket.timeout("timed out")
        if not self._buf:
            return b""
        take = min(n, self._chunk, len(self._buf))
        out = bytes(self._buf[:take])
        del self._buf[:take]
        return out


def frame_no_fin(payload, opcode=0x1):
    """造一个 FIN=0 的帧（分片首片），用来验续帧拼接。"""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    n = len(payload)
    header = bytearray([opcode & 0x0F])
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    return bytes(header) + payload


def read(frame_bytes, chunk=7, timeouts=0):
    return launcher._ws_read_frame(FakeSock(frame_bytes, chunk=chunk, timeouts=timeouts))


# ---------- 1) 握手 accept 向量（RFC6455 §1.3 官方样例）----------
chk("1) accept 与 RFC6455 官方样例一致",
    launcher._ws_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
    launcher._ws_accept_key("dGhlIHNhbXBsZSBub25jZQ=="))

# ---------- 2) 造帧：三种长度编码 ----------
for n, tag in ((5, "7 位"), (300, "16 位"), (70000, "64 位")):
    payload = bytes((i % 251) for i in range(n))
    fin, op, data = read(launcher._ws_build_frame(payload, opcode=0x1))
    chk("2) %s 长度往返一致（%d 字节）" % (tag, n),
        fin and op == 0x1 and data == payload, "len=%d" % len(data))
frame = launcher._ws_build_frame(b"hello")
chk("2b) 客户端帧带掩码位", bool(frame[1] & 0x80), hex(frame[1]))
chk("2c) 帧长度字段正确", (frame[1] & 0x7F) == 5, str(frame[1] & 0x7F))
fin, op, data = read(launcher._ws_build_frame(b"hello", mask=False))
chk("2d) 不掩码的服务端帧可解析", data == b"hello", repr(data))
utf8_payload = "掩码中文".encode("utf-8")
fin, op, data = read(launcher._ws_build_frame(utf8_payload))
chk("2e) 掩码帧可解析（宽容处理）", data == utf8_payload, repr(data))

# ---------- 3) 控制帧 ----------
fin, op, data = read(launcher._ws_build_frame(b"ping-payload", opcode=0x9, mask=False))
chk("3) ping 帧可解析", op == 0x9 and data == b"ping-payload", "%s %r" % (op, data))
close_payload = struct.pack(">H", launcher.MAS_WS_CLOSE_REPLACED) + b"replaced-by-new-connection"
fin, op, data = read(launcher._ws_build_frame(close_payload, opcode=0x8, mask=False))
code = struct.unpack(">H", data[:2])[0]
chk("3b) close 帧带 4001（让位码）",
    op == 0x8 and code == 4001, "op=%s code=%s" % (op, code))

# ---------- 4) 分片续帧 ----------
fin1, op1, data1 = read(frame_no_fin("前半段", opcode=0x1))
chk("4) 首片 FIN=0 能被识别", (not fin1) and op1 == 0x1 and data1 == "前半段".encode("utf-8"),
    "fin=%s op=%s" % (fin1, op1))
fin2, op2, data2 = read(launcher._ws_build_frame("后半段", opcode=0x0))
chk("4b) 续帧 FIN=1 + opcode=0",
    fin2 and op2 == 0x0 and data2 == "后半段".encode("utf-8"),
    "op=%s data=%r" % (op2, data2))

# ---------- 5) 读满一帧：超时不能当帧结束 ----------
raw = launcher._ws_build_frame(b"0123456789")
fin, op, data = read(raw, chunk=2, timeouts=3)
chk("5) 中途超时会重试而不是截断", data == b"0123456789", repr(data))
try:
    launcher._ws_read_exact(FakeSock(b"", chunk=1, timeouts=5), 4, on_idle=lambda: True)
    chk("5b) on_idle 能中断阻塞读", False, "没抛异常")
except ConnectionError as e:
    chk("5b) on_idle 能中断阻塞读", "停止" in str(e), str(e))

# ---------- 6) 上限保护 ----------
huge_header = bytes([0x81, 127]) + struct.pack(">Q", launcher.MAS_WS_MAX_FRAME_BYTES + 1)
try:
    read(huge_header)
    chk("6) 超大帧被上限拦下", False, "没抛异常")
except ValueError as e:
    chk("6) 超大帧被上限拦下", "过大" in str(e), str(e))

# ---------- 7) 事件信封解析 ----------
class _Probe(launcher.MasEventClient):
    def __init__(self):
        super().__init__(0)
        self.got = []


p = _Probe()
p.sig_event.connect(lambda t, i, data: p.got.append((t, i, data)))
p._on_text(json.dumps({"id": "TaskManager", "type": "task.created",
                       "data": {"taskId": "t1", "mode": "AutoProxy"}}).encode("utf-8"))
chk("7) 信封解析出 type/id/data",
    p.got == [("task.created", "TaskManager", {"taskId": "t1", "mode": "AutoProxy"})],
    str(p.got))
p._on_text(b"{}")
p._on_text(b"not json")
p._on_text(b"[1,2,3]")
p._on_text(json.dumps({"id": "", "type": "", "data": {}}).encode("utf-8"))
chk("7b) 空对象/非法 JSON/非对象/空信封都被忽略且不崩", len(p.got) == 1, str(p.got))
p._on_text(json.dumps({"id": "t1", "type": "task.log.updated",
                       "data": None}).encode("utf-8"))
chk("7c) data 非对象时降级为空 dict",
    p.got[-1] == ("task.log.updated", "t1", {}), str(p.got[-1]))

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

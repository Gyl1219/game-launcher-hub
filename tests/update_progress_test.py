# -*- coding: utf-8 -*-
"""更新进度条的解析与单调性回归测试（2026-10-27 用户反馈）。

用户截图：进度条已经 **100%**，下面状态文字还在跑
`generating index: 1365/1366` —— 问「1356/1366 上面进度条不是真实的？实时的？」

根因（两个叠加）：
1. dulwich 的进度有两套格式：
    ``Receiving objects: 87% (1200/1380), 3.2 MiB | 1.1 MiB/s``   ← 带百分号
     ``generating index: 1365/1366``                              ← 只有分数
       （dulwich/object_store.py:2136，接收完 pack 后建索引）
   旧 parse_git_progress 只认 ``(\\d+)%``，第二种一律 -1；
   而 UI 收到 -1 只改文字、不动进度条 → 进度条停在接收阶段的 100%。
2. 就算把分数换成百分比，进度条也会 100% → 0% → 99% 地**倒退**。

本测试钉死三件事：
  · 分数格式能被解析（不再恒 -1）
  · 阶段分段映射后**全局单调不减**（不许倒退）
  · 速率串（`1/2 MiB`）之类的假进度不会被误认
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402

fails = []


def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


P = launcher.parse_git_progress

# ==================== 1) 核心 bug：分数格式必须能解析 ====================
print("--- 1) generating index 的分数格式（用户截图那行）---")
pct, text = P(b"generating index: 1365/1366\r")
chk("不再恒为 -1（旧实现的最大问题）", pct >= 0, pct)
chk("映射到接近完成但不冒充 100%", 90 <= pct <= 99, pct)
chk("状态文字去掉了尾部 \\r", "\r" not in text, repr(text))
chk("文字里保留原始信息（用户能看到在干什么）", "generating index" in text, text)

pct0, _ = P(b"generating index: 0/1366\r")
pctm, _ = P(b"generating index: 683/1366\r")
chk("建索引开头 < 中间 < 末尾", pct0 < pctm < pct, (pct0, pctm, pct))
chk("建索引区间落在 90~99", pct0 >= 90 and pct <= 99, (pct0, pct))

# ==================== 2) 阶段分段：全局单调不减 ====================
print("\n--- 2) 一次完整 fetch 的进度序列必须单调不减 ---")
# 注意：dulwich 的**实时** Receiving 行没有百分比（只报 MiB + 速率，见
# client.py:1177），那种行 parse 返回 -1 → UI 走忙碌态。所以这里的序列
# 只用有确定进度的行（真实 dulwich 会交替出现两类）。
SEQUENCE = [
    (b"Counting objects: 0/10\r",                    "count 0"),
    (b"Counting objects: 5/10\r",                    "count 5"),
    (b"Counting objects: 10/10\r",                   "count 10"),
    (b"Compressing objects: 0/8\r",                  "compress 0"),
    (b"Compressing objects: 4/8\r",                  "compress 4"),
    (b"Compressing objects: 8/8\r",                  "compress 8"),
    (b"Receiving objects: 0% (0/1380)\r",            "recv 0"),
    (b"Receiving objects: 25% (345/1380)\r",         "recv 25"),
    (b"Receiving objects: 50% (690/1380)\r",         "recv 50"),
    (b"Receiving objects: 99% (1366/1380)\r",        "recv 99"),
    (b"Receiving objects: 100% (1380/1380), 12 MiB", "recv 100"),
    (b"Resolving deltas: 0% (0/300)\r",              "delta 0"),
    (b"Resolving deltas: 100% (300/300)\r",          "delta 100"),
    (b"generating index: 0/1366\r",                  "index 0"),
    (b"generating index: 455/1366\r",                "index 455"),
    (b"generating index: 900/1366\r",                "index 900"),
    (b"generating index: 1365/1366\r",               "index 1365"),
    (b"generating index: 1366/1366\r",               "index 1366"),
    (b"Updating files: 50/200\r",                    "update 50"),
    (b"Updating files: 200/200\r",                   "update 200"),
]
prev = -1
bad = []
for raw, label in SEQUENCE:
    v, _ = P(raw)
    if v < 0:
        bad.append((label, v, "解析失败"))
        continue
    if v < prev:
        bad.append((label, v, "倒退（上一条 %d）" % prev))
    prev = v
chk("全程无倒退、无解析失败", not bad, bad)
print("   末值 = %d（应接近 100）" % prev)
chk("序列结束时接近 100%", prev >= 99, prev)

# 用户截图的确切场景：接收完 100% 之后进入建索引，进度条**不能**停在 100%
recv100, _ = P(b"Receiving objects: 100% (1380/1380), 12 MiB")
idx, _ = P(b"generating index: 1365/1366\r")
chk("接收 100% 时进度条还没到顶（给建索引留余量）", recv100 < 100, recv100)
chk("建索引阶段进度条继续在动（不是卡住的假 100%）", idx > recv100, (recv100, idx))

# ==================== 2b) 真实 dulwich 行：无总量 → -1（走忙碌态）====================
print("\n--- 2b) dulwich 实时行（只有 MiB/速率、无总量）必须返回 -1 ---")
BUSY_LINES = [
    b"Receiving objects:   1380 (delta 0), 3.20 MiB | 1.10 MiB/s\r",
    b"Receiving objects: 3.20 MiB | 1.10 MiB/s\r",
    b"counting objects: 512\r",
]
bad_busy = []
for raw in BUSY_LINES:
    v, _ = P(raw)
    if v != -1:
        bad_busy.append((raw, v))
chk("无总量的行返回 -1（不编假百分比，交给忙碌态）", not bad_busy, bad_busy)

# ==================== 3) 不误认假进度 ====================
print("\n--- 3) 速率/描述类数字不能被当成进度 ---")
FALSE_POSITIVES = [
    b"1/2 MiB | 3 MiB/s",
    b"2/5 files/s",
    b"plain text without numbers",
    b"",
    None,
    "下了一个 3/4 的文件（中文描述）",
]
bad_fp = []
for raw in FALSE_POSITIVES:
    v, _ = P(raw)
    if v >= 0:
        bad_fp.append((raw, v))
chk("假进度一律返回 -1", not bad_fp, bad_fp)

# 合法的分数不能漏
TRUE_POSITIVES = [
    (b"generating index: 1/1366\r", 90),
    (b"Updating files: 1/2\r", 99),
    (b"resolving deltas: 1/2\r", 85),
]
bad_tp = []
for raw, lo in TRUE_POSITIVES:
    v, _ = P(raw)
    if v < lo:
        bad_tp.append((raw, v, lo))
chk("合法分数都解析到对应阶段下限之上", not bad_tp, bad_tp)

# ==================== 4) 带百分号的老格式行为不变 ====================
print("\n--- 4) 百分号格式不回归 ---")
v, t = P(b"Receiving objects: 87% (1200/1380), 3.2 MiB | 1.1 MiB/s")
chk("百分号优先于同行分数", 10 <= v <= 85, v)
chk("文字完整保留", "Receiving objects" in t, t)
v2, _ = P("100%")
chk("裸 100% 仍是 100", v2 == 100, v2)
v3, _ = P(b"Receiving objects: 150% (1/1)")
chk("越界百分比被夹到 100 以内", 0 <= v3 <= 100, v3)

# ==================== 5) UI 单调保护（不进消息循环，只验逻辑）====================
print("\n--- 5) on_progress 的单调保护 ---")


class _FakeBar:
    def __init__(self):
        self._v = 0
        self._lo, self._hi = 0, 100

    def value(self):
        return self._v

    def setValue(self, v):
        self._v = v

    def setRange(self, lo, hi):
        self._lo, self._hi = lo, hi

    def is_busy(self):
        """Qt 的忙碌态：range 为 (0,0)。"""
        return self._lo == 0 and self._hi == 0


class _FakeLabel:
    def __init__(self):
        self._t = ""

    def setText(self, t):
        self._t = t


class _Probe:
    """把一个最小对象绑上 UpdateDialog.on_progress 所需的属性。"""
    bar = _FakeBar()
    status = _FakeLabel()
    _busy = False


_Probe.on_progress = launcher.UpdateDialog.on_progress
probe = _Probe()
chk("初始不是忙碌态", probe.bar.is_busy() is False)

probe.on_progress(50, "Receiving objects: 50%")
chk("正常前进", probe.bar.value() == 50, probe.bar.value())
probe.on_progress(83, "Receiving objects: 100%")
chk("继续前进到 83", probe.bar.value() == 83, probe.bar.value())
probe.on_progress(3, "Counting objects: 3%")
chk("倒退的百分比被拦下（进度条不回退）", probe.bar.value() == 83, probe.bar.value())
probe.on_progress(-1, "generating index: 900/1366")
chk("pct=-1 只改文字、不动进度条", probe.bar.value() == 83, probe.bar.value())
chk("pct=-1 时文字确实更新了", "generating index" in probe.status._t, probe.status._t)
probe.on_progress(98, "generating index: 1365/1366")
chk("建索引阶段进度条继续推进到 98", probe.bar.value() == 98, probe.bar.value())

# 忙碌态：dulwich 实时行没有总量 → 显示"在动但不知何时完"
probe2 = _Probe()
probe2.bar = _FakeBar()
probe2.status = _FakeLabel()
probe2._busy = False
probe2.on_progress(-1, "Receiving objects: 3.20 MiB | 1.10 MiB/s")
chk("无总量的 Receiving 进入忙碌态（不编假百分比）",
    probe2.bar.is_busy() is True, (probe2.bar._lo, probe2.bar._hi))
chk("忙碌态下进度条数值不动", probe2.bar.value() == 0, probe2.bar.value())
chk("忙碌态文字仍显示在下载什么", "MiB" in probe2.status._t, probe2.status._t)
# 出现确定进度时必须退出忙碌态
_gi_pct, _gi_text = P(b"generating index: 0/1366\r")
probe2.on_progress(_gi_pct, _gi_text)
chk("进入有确定进度的阶段后退出忙碌态",
    probe2.bar.is_busy() is False, (probe2.bar._lo, probe2.bar._hi))
chk("退出忙碌态后进度条恢复推进", probe2.bar.value() == _gi_pct, probe2.bar.value())

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

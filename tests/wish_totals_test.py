# -*- coding: utf-8 -*-
"""「我想要」全网票数：解析 / 合并 / 拉取 / UI 展示 的契约测试。

背景（2026-10-27 用户提问「这下这能显示了吗？」）：
卡片上的「N 人想要」原来只统计本机点击，全 0 会被误读成"没人想要"。
v1.3.1 起拉取服务端按匿名 ID 去重的全网汇总（GET /wish/totals，公开接口，
只有 key→数字），展示值 = max(全网汇总, 本机计数)。

负向对照（测试纪律：还原修复必须变红）：
  · merge_wish_counts 若被改回"只显示本机"→ 第 2 组的 max 断言红
  · 服务端若把 wish 重新塞进 errors / totals 重新加 token 闸门
    → telemetry-endpoint/test_wish_worker.mjs 的 1.1 / 3.1 红

测试隔离：全部网络层 monkeypatch 掉，缓存路径指到临时目录，
不碰用户真实的 .cache（项目纪律：不测用户实机状态）。
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

fails = []


def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


_tmp = tempfile.mkdtemp(prefix="wish_totals_test_")


def iso_paths(monkey_target_path, filename):
    """把某个缓存路径函数隔离到临时目录。"""
    p = os.path.join(_tmp, filename)
    monkey_target_path(lambda: p)
    return p


print("--- 1) parse_wish_totals：坏数据一律空 dict，宁可显示 0 ---")
P = launcher.parse_wish_totals
good = P(json.dumps({"ok": True, "wishes": {"maa": 2, "x": "7", "empty": 0,
                                            "neg": -3, "bad": "abc"},
                     "updated": 1}))
chk("正常解析 + 字符串数字转 int", good.get("maa") == 2 and good.get("x") == 7, good)
chk("0 / 负数 / 非数字被丢弃", "empty" not in good and "neg" not in good and "bad" not in good,
    good)
chk("坏 JSON → {}", P("not json") == {})
chk("缺 wishes 字段 → {}", P(json.dumps({"ok": True})) == {})
chk("wishes 不是 dict → {}", P(json.dumps({"wishes": [1, 2]})) == {})
chk("超长 key 截到 64",
    len(P(json.dumps({"wishes": {"k" * 200: 1}}))) == 1
    and len(list(P(json.dumps({"wishes": {"k" * 200: 1}})))[0]) == 64)

print("\n--- 2) merge_wish_counts：展示值 = max(全网, 本机) ---  【负向对照点】")
M = launcher.merge_wish_counts
chk("全网有票、本机没投 → 显示全网", M({"maa": 5}, {}).get("maa") == 5)
chk("全网没票、本机投了 → 显示本机（遥测关着也能看到自己那票）",
    M({}, {"maa": 1}).get("maa") == 1)
chk("两边都有 → 取大不重复计（本机那票已在汇总里）",
    M({"maa": 5}, {"maa": 1}).get("maa") == 5)
chk("本机比汇总大（汇总还没收到上报）→ 显示本机",
    M({"maa": 0}, {"maa": 1}).get("maa") == 1)
chk("空输入 → 空", M({}, {}) == {})
chk("None 安全", M(None, None) == {})
# 负向对照本体：如果有人把 merge 改回"只看本机"，这条立刻红
chk("【负向】全网票数必须能透传到展示值（还原修复则红）",
    M({"some_key": 42}, {"some_key": 0})["some_key"] == 42)

print("\n--- 3) 端点推导：origin 来自 telemetry.endpoint ---")
orig_cfg = launcher._telemetry_cfg
orig_enabled = launcher.telemetry_enabled
try:
    launcher._telemetry_cfg = lambda: {"endpoint": "https://glh-tele.pages.dev/collect"}
    launcher.telemetry_enabled = lambda: True
    chk("collect 端点 → origin",
        launcher._wish_totals_url() == "https://glh-tele.pages.dev/wish/totals",
        launcher._wish_totals_url())
    launcher._telemetry_cfg = lambda: {"endpoint": ""}
    chk("端点为空（彻底不上报）→ 也不去读",
        launcher._wish_totals_url() == "")
    launcher._telemetry_cfg = lambda: {"endpoint": "not a url"}
    chk("坏端点 → 空", launcher._wish_totals_url() == "")
finally:
    launcher._telemetry_cfg = orig_cfg
    launcher.telemetry_enabled = orig_enabled

print("\n--- 4) WishTotalsWorker：成功落缓存并发信号，失败静默 ---")
iso_paths(lambda f: setattr(launcher, "_wish_totals_path", f), "wish_totals.json")
launcher._load_wish_totals()   # 冒烟：隔离后的路径能读
got = []
w = launcher.WishTotalsWorker()
w.totals_ok.connect(lambda d: got.append(dict(d)))

cases = [
    # (名字, http_get 返回, telemetry 开关, 期望: 是否发信号)
    ("200 + 合法数据 → 发信号",
     (200, json.dumps({"wishes": {"maa": 5}})), True, True),
    ("404（服务端还没更新）→ 静默",
     (404, "not found"), True, False),
    ("200 + 坏 JSON → 静默",
     (200, "oops"), True, False),
]
for name, resp, enabled, expect in cases:
    got.clear()
    launcher._wish_totals_http_get = lambda url, _r=resp: _r
    launcher.telemetry_enabled = lambda: enabled
    launcher._wish_totals_url = lambda: "https://glh-tele.pages.dev/wish/totals"
    w2 = launcher.WishTotalsWorker()
    w2.totals_ok.connect(lambda d: got.append(dict(d)))
    w2.run()   # 直接跑 run()（不开线程），确定性
    chk(name, (len(got) > 0) == expect, got)

# 没开遥测 → 一次网络请求都不能有（项目纪律：没开遥测就是空操作）
calls = []
launcher.telemetry_enabled = lambda: False
launcher._wish_totals_http_get = lambda url: calls.append(url) or (200, "{}")
w3 = launcher.WishTotalsWorker()
w3.totals_ok.connect(lambda d: got.append(dict(d)))
w3.run()
chk("未开遥测 → 不发请求、不发信号", not calls and not got, calls)

# 成功路径要落缓存（离线兜底的来源）
launcher.telemetry_enabled = lambda: True
launcher._wish_totals_http_get = lambda url: (
    200, json.dumps({"wishes": {"cached_key": 9}}))
launcher._save_wish_totals = (lambda wishes: open(
    os.path.join(_tmp, "wish_totals.json"), "w", encoding="utf-8").write(
    json.dumps({"fetched_at": 1, "wishes": wishes})))
got.clear()
w4 = launcher.WishTotalsWorker()
w4.totals_ok.connect(lambda d: got.append(dict(d)))
w4.run()
saved = json.load(open(os.path.join(_tmp, "wish_totals.json"), encoding="utf-8"))
chk("成功后缓存已写（wishes 落盘）", saved["wishes"].get("cached_key") == 9, saved)
chk("成功后信号带同样数据", got and got[0].get("cached_key") == 9, got)

print("\n--- 5) UI：ReservedSection 显示 max(全网, 本机)，汇总到达后刷新 ---")
# 隔离本机计数源 + 掐掉 worker 的真实网络（否则会用真实 config 真发请求，
# 汇总到达还会异步覆盖本测试塞的数据 —— 上一版就栽在这个竞态上）
launcher._wish_counts = lambda: {"local_only": 1, "both": 2}
launcher._wish_voted = lambda: {}
launcher.telemetry_enabled = lambda: False
apps = [
    {"key": "net_only", "display": "仅全网", "ecosystem": "standalone"},
    {"key": "local_only", "display": "仅本机", "ecosystem": "standalone"},
    {"key": "both", "display": "两边都有", "ecosystem": "standalone"},
    {"key": "newone", "display": "新来的", "ecosystem": "standalone"},
]
sec = launcher.ReservedSection(apps)
sec._totals = {"net_only": 7, "both": 5}
sec.rebuild()


def card_votes(section, key):
    # 旧卡片是 deleteLater 的，要等事件循环才真正消失——不处理会抓到重建前的
    # 旧卡片（票数 0），上一版测试就栽在这。处理完仍多张时取最后一张（最新的）。
    app.processEvents()
    hits = [c for c in section.findChildren(launcher.ReservedCard)
            if c.app.get("key") == key]
    return hits[-1]._votes_label.text() if hits else None


chk("全网有票的显示全网票数", card_votes(sec, "net_only") == "7 人想要",
    card_votes(sec, "net_only"))
chk("只有本机票的显示本机票数", card_votes(sec, "local_only") == "1 人想要",
    card_votes(sec, "local_only"))
chk("两边都有的取 max（5 > 2）", card_votes(sec, "both") == "5 人想要",
    card_votes(sec, "both"))

# 模拟汇总到达（_on_totals 是 worker 信号的落点）→ 界面刷新
sec._totals = {"net_only": 8, "newone": 3}
sec._on_totals(sec._totals)
chk("汇总更新后卡片跟着刷新", card_votes(sec, "net_only") == "8 人想要",
    card_votes(sec, "net_only"))
chk("新出现的 key 也能显示", card_votes(sec, "newone") == "3 人想要",
    card_votes(sec, "newone"))

# 排序与展示同源：net_only(8) 应排在 local_only(1) 前面
order = [a["key"] for a in sec._sorted() if a["key"] in ("net_only", "local_only")]
chk("排序用合并票数（8 排在 1 前）", order.index("net_only") < order.index("local_only"),
    order)

print("\n--- 6) 点击投票：数字当场 +1（别让用户以为按钮是假的）---")
# record_wish 必须替身化：_vote 会写真缓存 —— 上一版没替身，测试把
# "clickme": 13 票写进了用户实机 .cache（隔离纪律被打脸的实证）
votes_written = []
launcher.record_wish = lambda k: votes_written.append(k)
sec2 = launcher.ReservedSection([{"key": "clickme", "display": "点我", "ecosystem": "standalone"}])
sec2._totals = {}
sec2.rebuild()
card = [c for c in sec2.findChildren(launcher.ReservedCard)
        if c.app.get("key") == "clickme"][0]
before = card._votes_label.text()
card._vote()
after = card._votes_label.text()
chk("点击前 0，点击后 1（当场可见）",
    before == "0 人想要" and after == "1 人想要", (before, after))
chk("按钮变灰已想要", card.vote_btn.text() == "已想要" and not card.vote_btn.isEnabled())
chk("投票走了 record_wish（只写内存替身，不碰实机缓存）",
    votes_written == ["clickme"], votes_written)

print("\n--- 7) worker 门控：没开遥测/没端点，连 worker 都不建 ---")
created = []


class _FakeSig:
    def connect(self, *a, **k):
        pass


class _StubWorker:
    def __init__(self, parent=None):
        created.append(self)
        self.started = False
        self.totals_ok = _FakeSig()

    def start(self):
        self.started = True


real_wtw = launcher.WishTotalsWorker
launcher.WishTotalsWorker = _StubWorker
try:
    sec3 = launcher.ReservedSection(apps)
    launcher.telemetry_enabled = lambda: False
    sec3._totals = {}
    sec3._start_totals_worker()
    chk("未开遥测 → 不建 worker", not created, created)
    launcher.telemetry_enabled = lambda: True
    launcher._wish_totals_url = lambda: "https://glh-tele.pages.dev/wish/totals"
    sec3._start_totals_worker()
    chk("开了遥测 → 建 worker 并启动", len(created) == 1 and created[0].started, created)
finally:
    launcher.WishTotalsWorker = real_wtw

print("\n--- 8) 预约榜（右栏小榜）：占位 / 过滤 / 排序 / 与预约区同源 ---")
r_apps = [
    {"key": "maa", "display": "MAA", "icon": ""},
    {"key": "aaa", "display": "AAA", "icon": ""},
    {"key": "zero", "display": "零票项", "icon": ""},
]
rail = launcher.RankRail([], reserved_apps=r_apps)
rail.show()
app.processEvents()
bw = rail.board_wish
chk("初始占位文案（不是空榜也不是错误感）",
    bw.empty_lbl.isVisible() and "虚位以待" in bw.empty_lbl.text(),
    bw.empty_lbl.text())
rail.set_wish_rows({"maa": 5, "aaa": 2, "zero": 0, "not_reserved": 9})
app.processEvents()
chk("0 票不进榜", not any(r[0] == "zero" for r in bw._rows), bw._rows)
chk("不是预约条目的 key 不进榜（防串数据）",
    not any(r[0] == "not_reserved" for r in bw._rows), bw._rows)
chk("按票数降序，榜首是 MAA",
    bw._rows and bw._rows[0][0] == "maa" and bw._rows[0][3] == "5 票", bw._rows)
chk("次名 AAA 2 票", len(bw._rows) > 1 and bw._rows[1][0] == "aaa"
    and bw._rows[1][3] == "2 票", bw._rows)
# 同票按显示名排序
rail.set_wish_rows({"aaa": 3, "maa": 3})
chk("同票按显示名排序（AAA < MAA）",
    [r[0] for r in bw._rows] == ["aaa", "maa"], bw._rows)
# 清空回到占位
rail.set_wish_rows({})
app.processEvents()
chk("清空后回到占位", bw.empty_lbl.isVisible() and not bw._rows)

# 与预约区同源：预约区票数变化时回调带的是合并后的同一份
got_counts = []
sec4 = launcher.ReservedSection(
    [{"key": "maa", "display": "MAA", "ecosystem": "standalone"}],
    on_counts=lambda c: got_counts.append(dict(c)))
launcher._wish_counts = lambda: {"maa": 2}
sec4._totals = {"maa": 5}
sec4.rebuild()
chk("预约区 rebuild 时回调带合并票数", got_counts and got_counts[-1].get("maa") == 5,
    got_counts)
sec4._on_totals({"maa": 9})
chk("汇总到达后回调也更新", got_counts[-1].get("maa") == 9, got_counts)

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

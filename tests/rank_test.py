# -*- coding: utf-8 -*-
"""总览页右侧三个小榜的回归测试。

要点固化：
- 「我的使用」是纯本地启动计数，失败静默不影响启动；
- GitHub 统计必须「先缓存后网络」：6h 内用缓存、失败 30 分钟内不重试、
  单仓失败不连累其他仓——主页加载永远不等网络。
"""
import os
import sys
import json
import shutil
import tempfile
import time as _time
import unittest.mock as mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\OKApps\launcher")

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OK, FAIL = [], []


def chk(name, cond):
    (OK if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name)


qapp = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="rank_t_")
TMP_CFG = os.path.join(TMP, "config.json")
with open(launcher._cfg_path(), "r", encoding="utf-8") as f:
    CFG = json.load(f)
launcher._cfg_path = lambda: TMP_CFG
json.dump(CFG, open(TMP_CFG, "w", encoding="utf-8"), ensure_ascii=False)

COUNTS_PATH = os.path.join(TMP, "launch_counts.json")
STATS_PATH = os.path.join(TMP, "github_stats.json")
launcher._launch_counts_path = lambda: COUNTS_PATH
launcher._github_stats_path = lambda: STATS_PATH


class FakeHeaders:
    def __init__(self, d=None):
        self._d = d or {}

    def get(self, k, default=None):
        return self._d.get(k, default)


def app_def(key, name):
    return {"key": key, "display": name, "icon": ""}


# ===== 启动计数 =====
if os.path.exists(COUNTS_PATH):
    os.remove(COUNTS_PATH)
launcher.record_launch("ok-ww")
launcher.record_launch("ok-ww")
launcher.record_launch("ok-nte")
chk("计数累加并落盘",
    launcher._load_json(COUNTS_PATH) == {"ok-ww": 2, "ok-nte": 1})
launcher.record_launch("")
chk("空 key 不记录", launcher._load_json(COUNTS_PATH).get("") is None)
json.dump({"ok-ww": "脏数据"}, open(COUNTS_PATH, "w", encoding="utf-8"))
launcher.record_launch("ok-ww")
chk("文件里的脏数据不至于崩（重置为 1）",
    launcher._load_json(COUNTS_PATH).get("ok-ww") == 1)

# ===== Link 头解析 =====
chk("标准 Link 头取到 last 页码",
    launcher._parse_last_page(
        '<https://x?page=2>; rel="next", <https://x?page=37>; rel="last"') == 37)
chk("空 Link 头 → None", launcher._parse_last_page("") is None)
chk("无 last 关系 → None",
    launcher._parse_last_page('<https://x?page=2>; rel="next"') is None)

# ===== GitHubStatsWorker =====
worker = launcher.GitHubStatsWorker()
got = []
worker.done.connect(lambda d: got.append(d))

# 缓存新鲜 → 不打网络直接用缓存
launcher._save_json(STATS_PATH, {
    "repos": {"ok-ww": {"stars": 1, "commits30d": 2}},
    "fetched_at": _time.time(), "attempted_at": _time.time()})
with mock.patch.object(launcher, "_github_fetch") as m:
    worker.run()
    chk("缓存新鲜时不打网络", m.called is False)
chk("缓存新鲜时直接发缓存数据", got and got[-1] == {"ok-ww": {"stars": 1, "commits30d": 2}})

# 最近失败过（attempted_at 很新）→ 也不重试
launcher._save_json(STATS_PATH, {
    "repos": {}, "fetched_at": 0, "attempted_at": _time.time()})
with mock.patch.object(launcher, "_github_fetch") as m:
    worker.run()
    chk("失败后 30 分钟内不反复重试", m.called is False)

# 过期 → 真正拉取：单仓失败不连累其他仓，Link 头算提交数
def fake_fetch(url, timeout=8):
    repo = url.split("/repos/")[1].split("/")[0].split("?")[0]
    if repo == "MaaEnd":
        raise OSError("network down")
    if "/commits?" in url:
        return (200, FakeHeaders({"Link": '<...>; rel="next", <...?page=42>; rel="last"'}),
                b"[]")
    return (200, FakeHeaders(), json.dumps({"stargazers_count": 7}).encode())

launcher._save_json(STATS_PATH, {"repos": {}, "fetched_at": 0, "attempted_at": 0})
with mock.patch.object(launcher, "_github_fetch", side_effect=fake_fetch):
    worker.run()
res = got[-1]
chk("拉取成功的仓都有数据", len(res) == 5)
chk("Link 头 last 页码 = 近30天提交数", res.get("ok-ww", {}).get("commits30d") == 42)
chk("star 数正确", res.get("ok-ww", {}).get("stars") == 7)
chk("失败仓不进结果（旧值也没有时不造数）", res.get("maa-end") is None)
cache = launcher._load_json(STATS_PATH)
chk("拿到新数据后 fetched_at 更新", cache.get("fetched_at", 0) > 0)
chk("attempted_at 记录本次尝试", cache.get("attempted_at", 0) > 0)

# 部分字段缺失：仓库只有 star 没有 commits 也能合入
def fake_fetch_half(url, timeout=8):
    if "/commits?" in url:
        raise OSError("no commits")
    return (200, FakeHeaders(), json.dumps({"stargazers_count": 3}).encode())

launcher._save_json(STATS_PATH, {"repos": {}, "fetched_at": 0, "attempted_at": 0})
with mock.patch.object(launcher, "_github_fetch", side_effect=fake_fetch_half):
    worker.run()
chk("只有 star 没有 commits 也合入",
    got[-1].get("ok-ww", {}).get("stars") == 3
    and got[-1].get("ok-ww", {}).get("commits30d") is None)

# 全部失败 → 不更新 fetched_at（但 attempted_at 更新，防止频繁重试）
launcher._save_json(STATS_PATH, {"repos": {"old": {"stars": 9}}, "fetched_at": 123,
                                 "attempted_at": 0})
with mock.patch.object(launcher, "_github_fetch",
                       side_effect=OSError("all down")):
    worker.run()
chk("全部失败时保留旧数据", got[-1] == {"old": {"stars": 9}})
cache = launcher._load_json(STATS_PATH)
chk("全部失败时 fetched_at 不变", cache.get("fetched_at") == 123)
chk("全部失败时 attempted_at 已更新", cache.get("attempted_at") > 0)

# ===== RankBoard / RankRail =====
apps = [app_def("ok-nte", "异环"), app_def("ok-ww", "鸣潮"),
        app_def("ok-end-field", "终末地"), app_def("whimbox", "奇想盒"),
        app_def("onedragon-zzz", "绝区零 一条龙"), app_def("maa-end", "MaaEnd")]
rail = launcher.RankRail(apps)

data = {"ok-ww": {"stars": 8900, "commits30d": 142},
        "ok-nte": {"stars": 2700, "commits30d": 98},
        "maa-end": {"stars": 4000, "commits30d": 61},
        "ghost": {"stars": 999}}   # 不在 apps 里的 key 应被过滤
rail.set_github(data)
act = rail.board_activity._rows
chk("活跃度按提交数降序", [r[0] for r in act] == ["ok-ww", "ok-nte", "maa-end"])
chk("星标按数量降序", [r[0] for r in rail.board_stars._rows] == ["ok-ww", "maa-end", "ok-nte"])
chk("未知 key 被过滤", all(r[0] != "ghost" for r in rail.board_stars._rows))
chk("Top3 默认只显示 3 行", rail.board_activity.rows_box.count() == 3)

rail.board_activity._expanded = True
rail.board_activity._render()
chk("展开后显示全部行", rail.board_activity.rows_box.count() == 3)  # 只有 3 个有数据
rail.board_activity._expanded = False   # 展开状态跨数据刷新保持，这里手动收起再测默认态
rail.board_activity._render()

more = {k: {"stars": i * 10, "commits30d": i * 10} for i, k in
        enumerate(["ok-nte", "ok-ww", "ok-end-field", "whimbox",
                   "onedragon-zzz", "maa-end"])}
rail.set_github(more)
chk("6 个都有数据时默认仍只显示 3 行", rail.board_activity.rows_box.count() == 3)
rail.board_activity._expanded = True
rail.board_activity._render()
chk("展开后显示 6 行", rail.board_activity.rows_box.count() == 6)
rail.board_activity._expanded = False
rail.board_activity._render()

# 空数据 → 占位文案
rail.set_github({})
chk("无数据显示占位文案",
    rail.board_activity.empty_lbl.isVisible() or
    not rail.board_activity.empty_lbl.isHidden())
chk("占位文案提示网络受限", "网络受限" in rail.board_activity.empty_lbl.text())

# 我的使用：读计数文件、排序、过滤陈旧 key
json.dump({"ok-nte": 31, "ok-ww": 12, "dead-key": 99},
          open(COUNTS_PATH, "w", encoding="utf-8"))
rail.refresh_usage()
usage = rail.board_usage._rows
chk("使用榜按次数降序", [r[0] for r in usage] == ["ok-nte", "ok-ww"])
chk("陈旧 key 不进使用榜", all(r[0] != "dead-key" for r in usage))
chk("使用榜带「次」单位", usage and usage[0][3] == "31 次")

json.dump({}, open(COUNTS_PATH, "w", encoding="utf-8"))
rail.refresh_usage()
chk("没有启动记录时显示引导文案",
    "启动" in rail.board_usage.empty_lbl.text())

shutil.rmtree(TMP, ignore_errors=True)
print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))

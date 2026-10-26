# -*- coding: utf-8 -*-
"""下载榜：全目录（官方 + 预约）release 累计下载量的拉取 / 格式化 / 榜单展示契约。

用户要求：下载榜要「所有的里面选前几名」，不是只有启动器适配的 6 个。
预约条目没有 repo 字段，从 website 的 github.com 链接提取（79 条里 54 条有）；
提取不到的（官网非 GitHub）是数据边界，不参与 —— 不硬造数据。

约束是 GitHub API 配额（未认证 60 次/小时）：
  按预约票数排优先级 + 每轮最多 _REPO_DL_BUDGET 个 + 单仓 7 天 TTL
  + 连续 3 个失败熔断（多半限流/断网）→ 用几天把榜单补全。

负向对照（测试纪律）：预算/TTL/熔断/换算任一被退回，对应断言立刻红。

测试隔离：网络层全部 monkeypatch，缓存路径指临时目录，不碰用户实机状态。
"""
import json
import os
import sys
import tempfile
import time

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


_tmp = tempfile.mkdtemp(prefix="download_board_test_")
launcher._repo_downloads_path = lambda: os.path.join(_tmp, "repo_downloads.json")
launcher._github_stats_path = lambda: os.path.join(_tmp, "github_stats.json")

print("--- 1) _fmt_count（复用现有格式化器）：千以下原样，以上用 k ---")
F = launcher._fmt_count
chk("0", F(0) == "0", F(0))
chk("9999 → 10.0k", F(9999) == "10.0k", F(9999))
chk("10000 → 10k", F(10000) == "10k", F(10000))
chk("12345 → 12k", F(12345) == "12k", F(12345))
chk("非数字容错 → —", F(None) == "—", F(None))

print("\n--- 2) _fetch_release_downloads：求和 / 分页 / 失败抛异常 ---")
FD = launcher._fetch_release_downloads
orig_fetch = launcher._github_fetch


def fake_fetch_factory(responses):
    calls = []

    def fake(url, timeout=8):
        calls.append(url)
        code, obj = responses[min(len(calls) - 1, len(responses) - 1)]
        return code, {"Link": ""}, json.dumps(obj).encode("utf-8")
    fake.calls = calls
    return fake


launcher._github_fetch = fake_fetch_factory(
    [(200, [{"assets": [{"download_count": 1200}]},
            {"assets": [{"download_count": 3400}]}])])
chk("单页求和", FD("x/y") == 4600)
launcher._github_fetch = fake_fetch_factory(
    [(200, [{"assets": []}] * 100), (200, [{"assets": [{"download_count": 500}]}])])
chk("满页翻页继续求和", FD("x/y") == 500)
launcher._github_fetch = fake_fetch_factory([(403, [])])
try:
    FD("x/y")
    chk("403 抛异常", False, "没有抛")
except Exception:
    chk("403 抛异常", True)
launcher._github_fetch = fake_fetch_factory([(200, [])])
try:
    FD("x/y")
    chk("空 release 列表抛异常（0 与没数据必须区分）", False, "没有抛")
except Exception:
    chk("空 release 列表抛异常（0 与没数据必须区分）", True)
launcher._github_fetch = orig_fetch

print("\n--- 3) _catalog_repos：官方在前，预约按票数，非 GitHub 剔除，重复去重 ---")
reserved = [
    {"key": "r1", "display": "一", "website": "https://github.com/foo/one"},
    {"key": "r2", "display": "二", "website": "https://github.com/bar/two/"},
    {"key": "r3", "display": "三", "website": "https://maa.plus/"},      # 非 GitHub
    {"key": "r4", "display": "四", "website": "https://github.com/foo/one"},  # 重复仓
]
order = launcher._catalog_repos(reserved, {"r2": 9, "r1": 1})
repos = [r for r, _ in order]
keys = [k for _, k in order]
chk("官方 6 个排最前", repos[:len(launcher._GITHUB_REPOS)] ==
    list(launcher._GITHUB_REPOS.values()), repos[:8])
chk("预约票数高的优先（r2 在 r1 前）", keys.index("r2") < keys.index("r1"), keys)
chk("非 GitHub 官网的条目剔除（r3）", "r3" not in keys, keys)
chk("重复仓库只留一个", repos.count("foo/one") == 1 and keys.count("r4") == 0, repos)
chk("slug 去掉尾斜杠", "bar/two" in repos, repos)

print("\n--- 4) CatalogDownloadsWorker：服务端优先 → 直连兜底 ---  【负向对照点】")
real_fd = launcher._fetch_release_downloads
# worker 拉取按**仓库 slug**（不是助手 key）：官方两个 + 预约两个
DL = {"BnanZ0/ok-nte": 33, "ok-oldking/ok-wuthering-waves": 44,
      "foo/one": 11, "bar/two": 22}


def rec_fd(repo, max_pages=3):
    calls.append(repo)
    if repo in DL:
        return DL[repo]
    raise RuntimeError("no data %s" % repo)


orig_origin = launcher._telemetry_origin
orig_enabled = launcher.telemetry_enabled
orig_post = launcher._post_json
orig_dlget = launcher._download_totals_http_get


def server_on(totals_obj):
    """打开服务端路径：origin/开关/POST/GET 全部替身化。"""
    posts = []
    launcher._telemetry_origin = lambda: "https://glh-tele.pages.dev"
    launcher.telemetry_enabled = lambda: True
    launcher._post_json = lambda url, payload: posts.append(
        (url, payload)) or 200
    launcher._download_totals_http_get = lambda url: (
        200, json.dumps({"downloads": totals_obj}))
    return posts


def server_off():
    launcher.telemetry_enabled = lambda: False   # 服务端路径直接短路


# A1) 服务端有数据 → 用共享缓存，不花直连配额
calls = []
launcher._fetch_release_downloads = rec_fd
posts = server_on({"BnanZ0/ok-nte": 33, "foo/one": 11})
open(launcher._repo_downloads_path(), "w", encoding="utf-8").write(
    json.dumps({"repos": {}, "attempted_at": 0}))
w = launcher.CatalogDownloadsWorker(reserved)
got = []
w.done.connect(lambda d: got.append(dict(d)))
w.run()
chk("服务端有数据 → 直连一次都不跑", not calls, calls)
chk("播种请求带全量 slug（公开仓库清单，无用户数据）",
    posts and posts[0][1]["repos"][:2] == ["BnanZ0/ok-nte",
                                           "ok-oldking/ok-wuthering-waves"],
    posts)
chk("服务端数据按 key 输出（官方 + 预约）",
    got and got[0].get("ok-nte") == 33 and got[0].get("r1") == 11, got)

# A2) 服务端没数据（还没拉出来）→ 自动落到直连分批
calls = []
server_on({})
open(launcher._repo_downloads_path(), "w", encoding="utf-8").write(
    json.dumps({"repos": {}, "attempted_at": 0}))
launcher._REPO_DL_BUDGET = 2
w2 = launcher.CatalogDownloadsWorker(reserved)
got2 = []
w2.done.connect(lambda d: got2.append(dict(d)))
w2.run()
chk("服务端空 → 落到直连", len(calls) == 2, calls)
chk("直连也按官方优先", calls[:2] == ["BnanZ0/ok-nte",
                                      "ok-oldking/ok-wuthering-waves"], calls)

# A3) 服务端挂了（异常/非 200）→ 同样落到直连
calls = []
launcher._download_totals_http_get = lambda url: (500, "oops")
open(launcher._repo_downloads_path(), "w", encoding="utf-8").write(
    json.dumps({"repos": {}, "attempted_at": 0}))
w3 = launcher.CatalogDownloadsWorker(reserved)
got3 = []
w3.done.connect(lambda d: got3.append(dict(d)))
w3.run()
chk("服务端 500 → 落到直连", len(calls) == 2, calls)

# B) 兜底路径：缓存新鲜（7 天内）→ 该仓不拉，过期的照拉
calls = []
server_off()
open(launcher._repo_downloads_path(), "w", encoding="utf-8").write(json.dumps(
    {"repos": {"BnanZ0/ok-nte": {"downloads": 99, "fetched_at": time.time()},
               "foo/one": {"downloads": 11, "fetched_at": time.time()}},
     "attempted_at": 0}))
w4 = launcher.CatalogDownloadsWorker(reserved)
got4 = []
w4.done.connect(lambda d: got4.append(dict(d)))
w4.run()
chk("TTL 按仓生效：新鲜的没拉", ("BnanZ0/ok-nte" not in calls)
    and ("foo/one" not in calls), calls)
chk("过期的照拉（未覆盖的仓库继续补全）",
    "ok-oldking/ok-wuthering-waves" in calls, calls)
chk("缓存值照常输出", got4 and got4[0].get("ok-nte") == 99 and got4[0].get("r1") == 11, got4)

# C) 10 分钟内已尝试过 → 直接出缓存不再开拉（attempted_at 守卫）
calls = []
open(launcher._repo_downloads_path(), "w", encoding="utf-8").write(json.dumps(
    {"repos": {}, "attempted_at": time.time()}))
w5 = launcher.CatalogDownloadsWorker(reserved)
got5 = []
w5.done.connect(lambda d: got5.append(dict(d)))
w5.run()
chk("attempted_at 守卫：不重复开拉", not calls, calls)

# D) 全部失败 → 连续 3 个就熔断（不把预算烧光）
calls = []


def always_fail(repo, max_pages=3):
    calls.append(repo)
    raise RuntimeError("down")
launcher._fetch_release_downloads = always_fail
launcher._REPO_DL_BUDGET = 25
open(launcher._repo_downloads_path(), "w", encoding="utf-8").write(
    json.dumps({"repos": {}, "attempted_at": 0}))
w6 = launcher.CatalogDownloadsWorker(reserved)
got6 = []
w6.done.connect(lambda d: got6.append(dict(d)))
w6.run()
chk("连续 3 失败熔断（不会拉满 25 个）", len(calls) == 3, calls)
launcher._fetch_release_downloads = real_fd
launcher._telemetry_origin = orig_origin
launcher.telemetry_enabled = orig_enabled
launcher._post_json = orig_post
launcher._download_totals_http_get = orig_dlget

print("\n--- 5) RankRail 下载榜：排序 / k 格式化 / 过滤 / 占位 ---")
rail = launcher.RankRail(
    [{"key": "a1", "display": "甲", "icon": ""}],
    reserved_apps=[{"key": "r1", "display": "预约甲", "icon": ""}])
rail.show()
rail.set_catalog_downloads({"a1": 12345, "r1": 9999, "neg": -5, "unknown": 1})
app.processEvents()
bd = rail.board_downloads
chk("官方 + 预约一起排，数值降序", [r[0] for r in bd._rows] == ["a1", "r1"], bd._rows)
chk("k 格式化（先数值排序再格式化）",
    bd._rows[0][3] == "12k" and bd._rows[1][3] == "10.0k", bd._rows)
chk("负数与非目录 key 都被过滤", len(bd._rows) == 2, bd._rows)
rail.set_catalog_downloads({})
app.processEvents()
chk("无数据 → 占位文案", bd.empty_lbl.isVisible(), bd.empty_lbl.text())

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

# -*- coding: utf-8 -*-
"""SelfUpdateWorker 真实联网冒烟：直接打 GitHub API（不跑 UI）。

不写死具体 tag（仓库一直在发版，写死必然过时）。校验的是「语义」：
  - 默认只认正式版，不选预发布
  - include_pre=True 才纳入预发布，且会被标记 prerelease
  - 选出的版本确实是候选里的最高，且确实存在于远端
  - has_new 与 compare_version 的结论自洽
  - exe 资产能被正确识别
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

import json  # noqa: E402
import urllib.request  # noqa: E402

REPO = "Gyl1219/game-launcher-hub"
url = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
req = urllib.request.Request(url, headers={
    "User-Agent": "game-launcher-hub",
    "Accept": "application/vnd.github+json",
})
with urllib.request.urlopen(req, timeout=30) as r:
    rels = json.loads(r.read().decode())

print("远端真实 releases:")
for x in rels:
    print("   tag=%-10s prerelease=%-5s draft=%-5s assets=%d" % (
        x.get("tag_name"), x.get("prerelease"), x.get("draft"),
        len(x.get("assets") or [])))

W = launcher.SelfUpdateWorker
print("\nAPP_VERSION =", launcher.APP_VERSION)

p1 = W(REPO, include_pre=False)._pick(rels)
print("默认(仅正式版) →", {k: p1[k] for k in ("latest", "has_new", "prerelease")})
print("   exe url =", (p1.get("url") or "")[:80])

p2 = W(REPO, include_pre=True)._pick(rels)
print("含测试版      →", {k: p2[k] for k in ("latest", "has_new", "prerelease")})
print("   exe url =", (p2.get("url") or "")[:80])

ok = True
CUR = launcher.APP_VERSION

# 断言不写死具体 tag（仓库天天在发版，写死必然过时）。
# 只校验「语义」：默认只认正式版、include_pre 才纳入预发布、
# 挑出的版本必须真的是候选里的最高、且 has_new 与版本比较结果自洽。

# 1) 默认（include_pre=False）挑出的不能是预发布
if p1["latest"] and p1["prerelease"] is not False:
    print("FAIL 默认模式下不应选中预发布")
    ok = False

# 2) include_pre=True 时若选中预发布，必须被标记 prerelease
if p2["latest"] and p2["latest"] != p1["latest"] and p2["prerelease"] is not True:
    print("FAIL include_pre 选中的非正式版未标记 prerelease")
    ok = False

# 3) include_pre 的候选集 ≥ 默认的候选集；且 include_pre 选出的版本不低于默认选出的
if p1["latest"] and p2["latest"]:
    if launcher.compare_version(p2["latest"], p1["latest"]) < 0:
        print("FAIL include_pre 选出的版本低于默认模式")
        ok = False

# 4) has_new 必须与 compare_version 的结论一致（自洽性）
for name, p in (("默认", p1), ("含测试版", p2)):
    if p["latest"]:
        expect = launcher.compare_version(p["latest"], CUR) > 0
        if p["has_new"] is not expect:
            print("FAIL %s 模式 has_new=%s 与 compare_version 结论(%s)不符"
                  % (name, p["has_new"], expect))
            ok = False

# 5) 挑出的版本必须真的是 releases 里存在的最高候选（防止 _pick 挑错）
pool = [r["tag_name"] for r in rels
        if not r["draft"] and r["tag_name"].lstrip("v")[:1].isdigit()]
if p2["latest"] and pool:
    if p2["latest"] not in pool:
        print("FAIL 选出的 %s 不在远端 releases 里" % p2["latest"])
        ok = False
    highest = max(pool, key=launcher.ver_key)
    if launcher.compare_version(p2["latest"], highest) < 0:
        print("FAIL 选出的 %s 不是最高候选 %s" % (p2["latest"], highest))
        ok = False

# 6) exe 资产应能被认出来
if p2["latest"] and not p2.get("url", "").endswith(".exe"):
    print("FAIL 未取到 exe 资产 URL")
    ok = False

print("\n" + ("ALL OK" if ok else "HAS FAILURE"))
sys.exit(0 if ok else 1)

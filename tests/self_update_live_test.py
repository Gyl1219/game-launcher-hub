# -*- coding: utf-8 -*-
"""SelfUpdateWorker 真实联网冒烟：直接打 GitHub API（不跑 UI）。

当前仓库真实状态：v0.2.0 是 prerelease、APP_VERSION=0.2.0。
预期：
  - include_pre=False（默认）→ 挑到的最高正式版是 v0.1.0 < 0.2.0 → has_new=False
  - include_pre=True → 挑到 v0.2.0 == 当前 → has_new=False，但 prerelease 标记为 True
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
# v0.1.0 是唯一的正式版，0.1.0 < 0.2.0 → 无更新
if p1["latest"] != "v0.1.0" or p1["has_new"] is not False:
    print("FAIL 默认应挑 v0.1.0 且 has_new=False")
    ok = False
# 含测试版时应挑 v0.2.0（最高），== 当前版本 → 无更新
if p2["latest"] != "v0.2.0" or p2["has_new"] is not False:
    print("FAIL include_pre 应挑 v0.2.0 且 has_new=False")
    ok = False
if p2["prerelease"] is not True:
    print("FAIL v0.2.0 应标记 prerelease")
    ok = False
# exe 资产应能被认出来
if not p2.get("url", "").endswith(".exe"):
    print("FAIL 未取到 exe 资产 URL")
    ok = False

print("\n" + ("ALL OK" if ok else "HAS FAILURE"))
sys.exit(0 if ok else 1)

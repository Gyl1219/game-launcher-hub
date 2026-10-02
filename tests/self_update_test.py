# -*- coding: utf-8 -*-
"""启动器「检查自身更新」核心逻辑单测（不联网）。

验证 SelfUpdateWorker._pick 的版本挑选规则：
  - draft 一律忽略
  - 预发布默认不参与，include_pre=True 才参与
  - 多个候选取版本号最大
  - has_new 正确反映「是否比 APP_VERSION 新」
  - 非版本号 tag（脏数据）被忽略
  - _to_dict 认 .exe 资产、跳过非 exe
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

fails = []


def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def rel(tag, pre=False, draft=False, assets=None, body=""):
    return {"tag_name": tag, "prerelease": pre, "draft": draft,
            "body": body, "assets": assets or []}


EXE = [{"name": "game-launcher-hub-v9.9.9-win64-single.exe",
        "browser_download_url": "https://x/y.exe", "size": 12345}]

W = launcher.SelfUpdateWorker
CUR = launcher.APP_VERSION
print("APP_VERSION =", CUR)

# 1) 没有更新：远端只有更低版本
p = W("o/r", parent=None)._pick([rel("v0.0.1")])
chk("低版本 → has_new=False", p["has_new"] is False and p["latest"] == "v0.0.1")

# 2) 有更新：远端更高
p = W("o/r", parent=None)._pick([rel("v99.0.0", assets=EXE)])
chk("高版本 → has_new=True", p["has_new"] is True and p["latest"] == "v99.0.0")

# 3) 多个候选取最大
p = W("o/r", parent=None)._pick(
    [rel("v1.0.0"), rel("v3.2.1", assets=EXE), rel("v2.9.9")])
chk("多候选取最大 v3.2.1", p["latest"] == "v3.2.1")

# 4) draft 一律忽略（哪怕版本号最大）
p = W("o/r", parent=None)._pick([rel("v99.0.0", draft=True), rel("v1.0.0")])
chk("draft 被忽略 → v1.0.0", p["latest"] == "v1.0.0")

# 5) 预发布默认不参与
p = W("o/r", parent=None)._pick([rel("v99.0.0-beta.1"), rel("v1.0.0")])
chk("预发布默认跳过 → v1.0.0", p["latest"] == "v1.0.0")

# 6) include_pre=True 时预发布参与，并标记 prerelease
p = W("o/r", include_pre=True, parent=None)._pick(
    [rel("v99.0.0-beta.1", pre=True), rel("v1.0.0")])
chk("include_pre 时预发布参与", p["latest"] == "v99.0.0-beta.1")
chk("预发布被标记 prerelease=True", p["prerelease"] is True)

# 6b) prerelease 字段为 false 但 tag 带 -beta（双保险）
p = W("o/r", include_pre=True, parent=None)._pick([rel("v9.0.0-rc.1", pre=False)])
chk("tag 含 -rc 也算预发布", p["prerelease"] is True)

# 7) 脏 tag（非 v+数字 开头）被忽略
p = W("o/r", parent=None)._pick([rel("nightly-build"), rel("v1.0.0")])
chk("非版本号 tag 被忽略", p["latest"] == "v1.0.0")

# 8) 空列表 → 报「未找到」，has_new=False 不崩
p = W("o/r", parent=None)._pick([])
chk("空 releases → latest=''", p["latest"] == "" and p["has_new"] is False)

# 9) _to_dict 认 exe 资产并取 size
d = W._to_dict(rel("v5.0.0", assets=EXE), "v5.0.0", False)
chk("_to_dict 取 exe URL", d["url"] == "https://x/y.exe")
chk("_to_dict 取 size", d["size"] == 12345)

# 10) 资产里没有 exe（只有 blockmap/zip）→ url 空，下载按钮应禁用
d2 = W._to_dict(rel("v5.0.0", assets=[{"name": "x.blockmap"},
                                       {"name": "y.zip"}]), "v5.0.0", False)
chk("无 exe 资产 → url 为空", d2["url"] == "" and d2["size"] == 0)

# 11) has_new 语义：远端版本 == 当前 → 无更新（边界）
p = W("o/r", parent=None)._pick([rel("v" + CUR)])
chk("远端==当前 → has_new=False", p["has_new"] is False)

# 12) body 透传
p = W("o/r", parent=None)._pick([rel("v99.0.0", assets=EXE, body="更新说明")])
chk("body 透传", p["body"] == "更新说明")

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

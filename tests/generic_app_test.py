# -*- coding: utf-8 -*-
"""generic 类型应用（独立 exe 程序，如绝区零一条龙）单测（不联网）。

验证：
  - 版本从安装目录本地 git tag 读（git describe --tags --abbrev=0）
  - 安装目录没有 .git → 返回 ""，不抛
  - 找不到 git → 返回 ""，不抛
  - generic 卡片：exe 存在即已安装、版本显示、不触发 GitHub 更新检查
  - 与 lite 共用的四个分支点（启动/强关/安装态/rebuild）都放行 generic
  - 不影响既有 lite/ok-script 路径
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from unittest.mock import patch, MagicMock  # noqa: E402

app = QApplication([])

fails = []


def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


REAL_EXE = r"D:\DZZZ-OD\OneDragon-RuntimeLauncher.exe"

# ---------- 1) _git_tag_version：真实安装目录 ----------
if os.path.isdir(r"D:\DZZZ-OD\.git") and os.path.isfile(REAL_EXE):
    appdef = {"exe": REAL_EXE}
    v = launcher._git_tag_version(appdef)
    chk("真实一条龙目录读到版本（非空）", bool(v))
    chk("版本形如 vX.Y.Z", v.startswith("v") and "." in v)
    print("   实测读到的版本 =", repr(v))
else:
    print("SKIP 本机无一条龙安装，跳过真实读取用例")

# ---------- 2) 目录没有 .git → 空串 ----------
import tempfile
tmp = tempfile.mkdtemp()
fake_exe = os.path.join(tmp, "app.exe")
open(fake_exe, "wb").write(b"MZ")
chk("目录无 .git → 空串",
    launcher._git_tag_version({"exe": fake_exe}) == "")

# ---------- 3) exe 不存在 → 空串 ----------
chk("exe 不存在 → 空串",
    launcher._git_tag_version({"exe": r"C:\nope\nope.exe"}) == "")

# ---------- 4) git 找不到 → 空串不抛 ----------
fake_exe2 = os.path.join(tmp, "g.exe")
open(fake_exe2, "wb").write(b"MZ")
os.makedirs(os.path.join(tmp, ".git"), exist_ok=True)
with patch.object(launcher.GitVersionFetcher, "_find_git", return_value=None):
    chk("找不到 git → 空串", launcher._git_tag_version({"exe": fake_exe2}) == "")

# ---------- 5) git 报错（非 git 仓库）→ 空串不抛 ----------
with patch.object(launcher.GitVersionFetcher, "_find_git", return_value="git"), \
     patch.object(launcher.subprocess, "run",
                  side_effect=Exception("git boom")):
    chk("git 调用异常 → 空串", launcher._git_tag_version({"exe": fake_exe2}) == "")

# ---------- 6) generic 卡片构建 ----------
card = None
try:
    appdef = {
        "key": "onedragon-zzz", "display": "绝区零 一条龙", "generic": True,
        "exe": REAL_EXE if os.path.isfile(REAL_EXE) else fake_exe2,
        "app_json": "", "working": "", "pythonw": "",
        "icon": "", "website": "https://example.com",
    }
    card = launcher.AppCard(appdef)
    built = True
except Exception as e:
    built = False
    print("   构建异常:", e)
chk("generic 卡片能构建", built)
if card is not None:
    chk("走了 generic 分支（非 lite）",
        getattr(card, "_generic", False) is True and getattr(card, "_lite", False) is False)
    chk("exe 存在 → 判定已安装", getattr(card, "_installed", False) is True)
    has_start = hasattr(card, "start_btn")
    has_uninst = hasattr(card, "uninstall_btn")
    chk("有启动按钮", has_start)
    chk("有卸载按钮", has_uninst)
    # 关键：不应出现 whimbox 专用的更新按钮/跑图路线按钮
    chk("没有 whimbox 专用更新按钮", not hasattr(card, "update_btn"))
    chk("没有跑图路线按钮", not hasattr(card, "script_btn"))
    chk("没有版本下拉", not hasattr(card, "ver_combo"))
    # ver_hint 文案应提到本地版本而非「前端/后端」
    hint = getattr(card, "ver_hint", None)
    if hint is not None:
        t = hint.text()
        chk("ver_hint 是「本地版本」文案", "本地版本" in t and "前端" not in t)

# ---------- 7) generic 不会触发 GitHub 更新检查 ----------
if card is not None:
    called = {"n": 0}
    with patch.object(launcher.AppCard, "_lite_start_check",
                      side_effect=lambda *a, **k: called.__setitem__("n", called["n"] + 1)):
        try:
            card._rebuild_generic_body()
        except Exception as e:
            print("   rebuild 异常:", e)
    chk("generic rebuild 不触发 lite 更新检查", called["n"] == 0)

# ---------- 8) 不影响既有 lite 路径 ----------
lite_app = {
    "key": "whimbox", "display": "奇想盒", "lite": True,
    "exe": r"C:\nonexistent\whimbox_app.exe",
    "app_json": "", "working": "", "pythonw": "", "icon": "",
}
try:
    lc = launcher.AppCard(lite_app)
    chk("lite 卡仍正常构建（未安装态）", getattr(lc, "_lite", False) is True)
except Exception as e:
    chk("lite 卡仍正常构建（未安装态）", False)
    print("   异常:", e)

ok_card = launcher.AppCard({
    "key": "ok-nte", "display": "异环",
    "exe": r"C:\nonexistent\ok-nte.exe", "app_json": "", "working": "",
    "pythonw": "", "icon": "",
})
chk("ok-script 卡仍走原路径（非 lite 非 generic）",
    getattr(ok_card, "_lite", False) is False
    and getattr(ok_card, "_generic", False) is False)

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

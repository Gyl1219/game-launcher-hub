# -*- coding: utf-8 -*-
"""generic 更新的 CNB 镜像优先 / origin 兜底 测试。

背景：一条龙 origin 是 GitHub，用户机器连 GitHub 常握手失败 → 卡片
「检查更新失败」。修复：从 origin URL 推导 CNB 镜像，fetch/pull 优先走 CNB，
失败回退 origin。这里用本地 file:// 仓库构造确定性场景（mock _cnb_git_mirror
返回镜像仓库路径），全程不依赖真实网络。
"""
import os
import sys
import shutil
import tempfile
import contextlib
import unittest.mock as mock

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


git = launcher.GitVersionFetcher._find_git()
if not git:
    print("找不到 git，跳过全部用例")
    sys.exit(0)


def run(args, cwd, timeout=120):
    return launcher._git_run(git, args, cwd, timeout)


@contextlib.contextmanager
def _mock_cnb(url):
    """把 _cnb_git_mirror 定向到指定"镜像"（file:// 裸仓库路径或坏路径）。"""
    with mock.patch.object(launcher, "_cnb_git_mirror", return_value=url):
        yield


BASE = tempfile.mkdtemp(prefix="gen_cnb_")
UPSTREAM = os.path.join(BASE, "upstream.git")   # origin（扮演 GitHub）
MIRROR = os.path.join(BASE, "mirror.git")       # CNB 镜像
WORK = os.path.join(BASE, "work")               # 用户安装目录

for d in (UPSTREAM, MIRROR):
    os.makedirs(d)
    run(["init", "--bare", "-b", "main"], d)

# ---- v1.0.0 同时推到 origin 和 mirror ----
seed = os.path.join(BASE, "seed")
os.makedirs(seed)
run(["init", "-b", "main"], seed)
run(["config", "user.email", "t@t"], seed)
run(["config", "user.name", "t"], seed)
open(os.path.join(seed, "app.py"), "w").write("v1\n")
run(["add", "."], seed)
run(["commit", "-m", "v1"], seed)
run(["tag", "v1.0.0"], seed)
for remote in (UPSTREAM, MIRROR):
    run(["push", "file:///" + remote.replace("\\", "/"), "main", "--tags"], seed)

# ---- 用户安装目录（origin = upstream）----
run(["clone", "file:///" + UPSTREAM.replace("\\", "/"), WORK], BASE)
run(["config", "user.email", "t@t"], WORK)
run(["config", "user.name", "t"], WORK)

exe = os.path.join(WORK, "app.exe")
open(exe, "w").close()
appdef = {"key": "t", "display": "t", "generic": True, "exe": exe,
          "app_json": "", "working": "", "pythonw": "", "icon": ""}

UP_URL = "file:///" + UPSTREAM.replace("\\", "/")
MIR_URL = "file:///" + MIRROR.replace("\\", "/")


def upstream_advance():
    """上游加一个提交 + tag，同时推 origin 和 mirror。"""
    open(os.path.join(seed, "app.py"), "w").write("v2\n")
    run(["add", "."], seed)
    run(["commit", "-m", "v2"], seed)
    run(["tag", "v1.1.0"], seed)
    for remote in (UPSTREAM, MIRROR):
        run(["push", "file:///" + remote.replace("\\", "/"),
             "main", "--tags"], seed)


def check_once():
    res = {}
    w = launcher.GenericUpdateCheckWorker(appdef)
    w.done.connect(lambda d: res.__setitem__("d", d))
    w.failed.connect(lambda m: res.__setitem__("f", m))
    w.run()
    return res


# =========================================================
print("--- _cnb_git_mirror 推导 ---")
# github origin → cnb URL
gh_repo = os.path.join(BASE, "gh_origin")
os.makedirs(gh_repo)
run(["init", "-b", "main"], gh_repo)
run(["remote", "add", "origin",
     "https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon.git"], gh_repo)
chk("github origin → cnb.cool 同名镜像",
    launcher._cnb_git_mirror(gh_repo, git)
    == "https://cnb.cool/OneDragon-Anything/ZenlessZoneZero-OneDragon")
# file:// origin → ""（不可推导，走 origin）
chk("file:// origin 返回空串",
    launcher._cnb_git_mirror(WORK, git) == "")
# 无 origin → ""
bare = os.path.join(BASE, "no_remote")
os.makedirs(bare)
run(["init", "-b", "main"], bare)
chk("无 origin 返回空串", launcher._cnb_git_mirror(bare, git) == "")

# =========================================================
print("--- 检查：镜像优先 ---")
upstream_advance()   # v1.1.0 同时在 origin 和 mirror

with _mock_cnb(MIR_URL):
    r = check_once()
chk("从镜像 fetch 成功（behind=1）",
    "f" not in r and r.get("d", {}).get("behind") == 1)
chk("镜像路径下远端 tag 正确(v1.1.0)",
    r.get("d", {}).get("remote_tag") == "v1.1.0")

print("--- 检查：镜像挂了 → 回退 origin ---")
with _mock_cnb(os.path.join(BASE, "no_such_mirror.git")):
    r2 = check_once()
chk("镜像不可用仍能通过 origin 取到",
    "f" not in r2 and r2.get("d", {}).get("behind") == 1)

print("--- 检查：不可推导 → 直接走 origin ---")
with _mock_cnb(""):
    r3 = check_once()
chk("返回空串时直接走 origin", "f" not in r3 and r3.get("d", {}).get("behind") == 1)

# =========================================================
print("--- 执行更新：镜像优先 ---")


def update_once():
    res = {}
    w = launcher.GenericUpdateWorker(appdef)
    w.progress.connect(lambda t: res.setdefault("p", []).append(t))
    w.done.connect(lambda t: res.__setitem__("d", t))
    w.failed.connect(lambda m: res.__setitem__("f", m))
    w.run()
    return res


with _mock_cnb(MIR_URL):
    r4 = update_once()
chk("从镜像 pull 成功 → 版本 v1.1.0", r4.get("d") == "v1.1.0")
chk("工作区文件真的变了",
    open(os.path.join(WORK, "app.py")).read().strip() == "v2")

# ---- 再造新版本只推 origin，mirror 落后但"可用" ----
# 设计语义：镜像**可用即以镜像为准**（pull 成功不回退）。官方镜像自动同步，
# 短暂滞后的表现是「暂时看不到新版本」，镜像同步后即恢复——
# 好过每次检查都去赌 GitHub 的连通性（用户机器实测常握手失败）。
open(os.path.join(seed, "app.py"), "w").write("v3\n")
run(["add", "."], seed)
run(["commit", "-m", "v3"], seed)
run(["tag", "v1.2.0"], seed)
run(["push", UP_URL, "main", "--tags"], seed)   # 只推 origin，不推 mirror！

with _mock_cnb(MIR_URL):
    r5 = update_once()
chk("镜像可用但落后 → 以镜像为准(v1.1.0, 无回退)", r5.get("d") == "v1.1.0")
chk("工作区保持 v2（等镜像同步）",
    open(os.path.join(WORK, "app.py")).read().strip() == "v2")

# 镜像**故障**（fetch/pull 失败）才会回退 origin
with _mock_cnb(os.path.join(BASE, "no_such_mirror.git")):
    r6 = update_once()
chk("镜像故障 → 回退 origin 更到 v1.2.0", r6.get("d") == "v1.2.0")
chk("工作区到 v3",
    open(os.path.join(WORK, "app.py")).read().strip() == "v3")

shutil.rmtree(BASE, ignore_errors=True)
print()
print("=" * 40)
print("失败 %d 项" % len(fails))
if fails:
    for x in fails:
        print("   -", x)
print("=" * 40)

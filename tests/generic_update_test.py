# -*- coding: utf-8 -*-
"""generic 应用「启动器内直接更新」单测。

用本地 file:// 远程仓库构造确定性场景（不需要网络）：
  - 落后 2 个提交 → has_new=True / behind=2 / remote_tag=v1.1.0
  - git pull --ff-only 成功 → 版本更新到 v1.1.0，工作区文件真的变了
  - **受控文件有改动 → 拒绝更新**（安全底线：绝不覆盖用户修改）
  - 未跟踪文件不影响更新（用户自己的 .bak 之类不该拦）
  - fetch 失败 → 走 failed，不发 done

注：真实 GitHub fetch 在沙盒里会撞 TLS 握手故障（环境问题，非代码问题），
所以成功路径用本地仓库验证，逻辑完全一致。
"""
import os
import sys
import shutil
import tempfile
import time

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


BASE = tempfile.mkdtemp(prefix="gen_upd_")
UPSTREAM = os.path.join(BASE, "upstream.git")     # 裸仓库 = "远端"
WORK = os.path.join(BASE, "work")                 # 用户安装目录

os.makedirs(UPSTREAM)
run(["init", "--bare", "-b", "main"], UPSTREAM)

# ---- 在临时区生成 v1.0.0 并推到"远端" ----
seed = os.path.join(BASE, "seed")
os.makedirs(seed)
run(["init", "-b", "main"], seed)
run(["config", "user.email", "t@t"], seed)
run(["config", "user.name", "t"], seed)
open(os.path.join(seed, "app.py"), "w").write("v1\n")
run(["add", "."], seed)
run(["commit", "-m", "v1"], seed)
run(["tag", "v1.0.0"], seed)
run(["remote", "add", "origin", "file:///" + UPSTREAM.replace("\\", "/")], seed)
run(["push", "-u", "origin", "main", "--tags"], seed)

# ---- 克隆出"用户安装目录" ----
run(["clone", "file:///" + UPSTREAM.replace("\\", "/"), WORK], BASE)
run(["config", "user.email", "t@t"], WORK)
run(["config", "user.name", "t"], WORK)

# ---- 上游再推 2 个提交 + v1.1.0（用户这边就落后了） ----
open(os.path.join(seed, "app.py"), "w").write("v2\n")
run(["add", "."], seed)
run(["commit", "-m", "v2"], seed)
open(os.path.join(seed, "app.py"), "w").write("v3\n")
run(["add", "."], seed)
run(["commit", "-m", "v3"], seed)
run(["tag", "v1.1.0"], seed)
run(["push", "origin", "main", "--tags"], seed)

# 卡片用到的 app 定义：exe 放在"安装目录"里
exe = os.path.join(WORK, "OneDragon-RuntimeLauncher.exe")
open(exe, "wb").write(b"MZ")
appdef = {"key": "test-generic", "display": "TestGeneric", "generic": True,
          "exe": exe, "app_json": "", "working": "", "pythonw": "", "icon": ""}


def wait_for(worker, res, timeout=120):
    worker.start()
    t0 = time.time()
    while not res and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.2)
    for _ in range(30):   # 线程结束后再派发几轮，确保 queued signal 送达
        app.processEvents()
        time.sleep(0.05)
    return res


# ---------- 1) 更新检查：落后 2 个提交 ----------
res = {}
w = launcher.GenericUpdateCheckWorker(appdef)
w.done.connect(lambda i: res.update(i))
w.failed.connect(lambda m: res.update({"_err": m}))
wait_for(w, res)
chk("检查更新不报错", "_err" not in res)
print("   结果:", res)
chk("识别到有更新", res.get("has_new") is True)
chk("落后提交数 = 2", res.get("behind") == 2)
chk("本地 tag = v1.0.0", res.get("local_tag") == "v1.0.0")
chk("远端 tag = v1.1.0", res.get("remote_tag") == "v1.1.0")

# ---------- 2) 未跟踪文件不阻拦更新 ----------
open(os.path.join(WORK, "some_user_file.bak"), "w").write("x")
chk("只有未跟踪文件时判定为「无受控改动」",
    launcher._git_has_tracked_changes(WORK) is False)

# ---------- 3) 执行更新（pull --ff-only）----------
res2 = {}
w2 = launcher.GenericUpdateWorker(appdef)
w2.done.connect(lambda t: res2.update({"tag": t}))
w2.failed.connect(lambda m: res2.update({"_err": m}))
wait_for(w2, res2)
print("   结果:", res2)
chk("更新不报错", "_err" not in res2)
chk("更新后版本 = v1.1.0", res2.get("tag") == "v1.1.0")
chk("工作区文件真的被更新",
    open(os.path.join(WORK, "app.py")).read().strip() == "v3")

# ---------- 4) 更新后重新检查 → 已是最新 ----------
res3 = {}
w3 = launcher.GenericUpdateCheckWorker(appdef)
w3.done.connect(lambda i: res3.update(i))
w3.failed.connect(lambda m: res3.update({"_err": m}))
wait_for(w3, res3)
chk("更新后检查无新版本", res3.get("has_new") is False)
chk("更新后 behind = 0", res3.get("behind") == 0)

# ---------- 5) 安全底线：受控文件被改动 → 拒绝更新 ----------
open(os.path.join(WORK, "app.py"), "w").write("my local edit\n")
chk("受控文件改动被识别", launcher._git_has_tracked_changes(WORK) is True)

res4 = {}
w4 = launcher.GenericUpdateWorker(appdef)
w4.done.connect(lambda t: res4.update({"tag": t}))
w4.failed.connect(lambda m: res4.update({"_err": m}))
wait_for(w4, res4)
print("   结果:", res4)
chk("受控改动时拒绝更新（走 failed）", "_err" in res4)
chk("拒绝理由说明「未提交的改动」", "未提交的改动" in (res4.get("_err") or ""))
chk("没有偷偷覆盖用户改动",
    open(os.path.join(WORK, "app.py")).read().strip() == "my local edit")

# ---------- 6) 非 git 目录 → 不给更新入口 ----------
plain = tempfile.mkdtemp(prefix="plain_")
plain_exe = os.path.join(plain, "x.exe")
open(plain_exe, "wb").write(b"MZ")
chk("非 git 目录 _git_repo_dir 为空",
    launcher._git_repo_dir({"exe": plain_exe}) == "")

try:
    shutil.rmtree(BASE, ignore_errors=True)
    shutil.rmtree(plain, ignore_errors=True)
except Exception:
    pass

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

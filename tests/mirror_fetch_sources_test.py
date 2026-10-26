# -*- coding: utf-8 -*-
"""镜像更新的「多源回退」回归测试（2026-10-26 实机 bug）。

真实事故：下拉框显示「v3.7.11 正式版（最新）」，点「开始更新」却报
`pathspec 'v3.7.11' did not match any file(s) known to git`。

根因是**取源错位**：
  - 版本列表读原启动器自带 repo（origin = CNB，国内通）→ 显示 v3.7.11 ✓
  - 实际下载却 fetch 写死的 `origin`，而启动器镜像仓库当年是用 GitHub URL clone 的
    → 走 GitHub，连不上 → tag 拉不下来 → checkout 报 pathspec 不匹配 ✗
  用户的 profile（China）git_url 明明是 CNB，却被晾在一边没用上。

本测试用本地 file:// 裸仓库构造确定性场景（不需要网络），复现并钉死这个 bug：
  镜像仓库的 origin = 一个**不可达**地址，而传入的 git_url = **可达**地址，
  目标 tag 只存在于可达远端。旧逻辑（只 fetch origin）必然失败，
  新逻辑（多源回退）必须成功。

同时覆盖：
  - 源排序（已知源在前、推导源在后）、去重
  - git 子进程**绝不弹凭据框**（GCM 弹窗会挂死无终端子进程，见 _git_no_prompt_env）
  - 全部源都失败时，错误信息里带上"远端拉不到"的原因，而不是只给一句
    误导性的 pathspec 不匹配
"""
import os
import sys
import shutil
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402

fails = []


def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


git = launcher.GitVersionFetcher._find_git()
if not git:
    print("找不到 git，跳过全部用例")
    sys.exit(0)


def run(args, cwd, timeout=60):
    return launcher._git_run(git, args, cwd, timeout)


def _file_url(path):
    """Windows 路径 → git 认的 file:/// URL。"""
    return "file:///" + os.path.abspath(path).replace("\\", "/")


BASE = tempfile.mkdtemp(prefix="mirror_src_")
UPSTREAM = os.path.join(BASE, "upstream.git")   # 可达的"远端"
DEAD = os.path.join(BASE, "dead.git")           # 不可达的"远端"
MIRROR_ROOT = os.path.join(BASE, "mirrors")     # 假扮 REPOS_DIR
MIRROR = os.path.join(MIRROR_ROOT, "testapp")

os.makedirs(MIRROR_ROOT)


def _init_bare(p):
    os.makedirs(p, exist_ok=True)
    run(["init", "--bare", "-b", "main"], p)
    return p


_init_bare(UPSTREAM)

# ---- seed 仓库：先只推 v1.0.0 ----
seed = os.path.join(BASE, "seed")
os.makedirs(seed)
run(["init", "-b", "main"], seed)
run(["config", "user.email", "t@t"], seed)
run(["config", "user.name", "t"], seed)
with open(os.path.join(seed, "app.py"), "w") as f:
    f.write("v1\n")
run(["add", "."], seed)
run(["commit", "-m", "init"], seed)
run(["tag", "v1.0.0"], seed)
run(["push", _file_url(UPSTREAM), "main"], seed)
run(["push", _file_url(UPSTREAM), "v1.0.0"], seed)

# ---- 镜像仓库：clone 自 upstream（此时只有 v1.0.0）----
run(["clone", _file_url(UPSTREAM), MIRROR], BASE)

# ---- upstream 再推 v2.0.0（镜像本地还没有这个 tag）----
with open(os.path.join(seed, "app.py"), "w") as f:
    f.write("v2\n")
run(["add", "."], seed)
run(["commit", "-m", "second"], seed)
run(["tag", "v2.0.0"], seed)
run(["push", _file_url(UPSTREAM), "main"], seed)
run(["push", _file_url(UPSTREAM), "v2.0.0"], seed)

# ---- 把镜像的 origin 改成不可达地址（模拟"origin 是 GitHub，连不上"）----
_init_bare(DEAD)
shutil.rmtree(DEAD, ignore_errors=True)     # 让它真的不存在
DEAD_URL = "file:///" + os.path.abspath(DEAD).replace("\\", "/")
run(["remote", "set-url", "origin", DEAD_URL], MIRROR)

print("=== 场景准备 ===")
print("  可达远端(git_url) :", _file_url(UPSTREAM))
print("  镜像 origin(不可达):", DEAD_URL)
print("  目标 tag v2.0.0 只存在于可达远端\n")

# ==================== 1) _github_to_cnb 纯函数 ====================
print("--- 1) _github_to_cnb ---")
chk("GitHub URL 转 CNB",
    launcher._github_to_cnb("https://github.com/a/b.git") == "https://cnb.cool/a/b")
chk("GitHub URL 无 .git 后缀也能转",
    launcher._github_to_cnb("https://github.com/a/b") == "https://cnb.cool/a/b")
chk("非 GitHub 返回空（CNB 不能再转）",
    launcher._github_to_cnb("https://cnb.cool/a/b.git") == "")
chk("file:// 返回空", launcher._github_to_cnb("file:///D:/x") == "")
chk("空串返回空", launcher._github_to_cnb("") == "")

# ==================== 2) _mirror_fetch_sources 排序/去重 ====================
print("\n--- 2) _mirror_fetch_sources 排序与去重 ---")
srcs = launcher._mirror_fetch_sources(
    "https://cnb.cool/ok-oldking/ok-ww-update2.git",
    r"D:\OKApps\launcher\repos\ok-ww", git)
chk("git_url 排第一（它是 profile 权威源）",
    srcs[0] == "https://cnb.cool/ok-oldking/ok-ww-update2.git")
chk("无重复项", len(srcs) == len(set(srcs)))
# 推导出来的 CNB 地址（ok-ww-update，实际不存在）必须排在已知源之后
idx_guess = [i for i, s in enumerate(srcs) if s == "https://cnb.cool/ok-oldking/ok-ww-update"]
chk("推导源排在已知源之后（猜测不该抢先浪费一轮超时）",
    (not idx_guess) or idx_guess[0] >= 2)

same = launcher._mirror_fetch_sources(
    "https://github.com/ok-oldking/ok-ww-update.git",
    r"D:\OKApps\launcher\repos\ok-ww", git)
chk("git_url 与 origin 相同时去重", len(same) <= 2)

empty_repo = tempfile.mkdtemp(prefix="notrepo_")
chk("目录不是仓库时不炸", len(launcher._mirror_fetch_sources(
    "https://github.com/a/b.git", empty_repo, git)) >= 1)
chk("git=None 时不炸", len(launcher._mirror_fetch_sources(
    "https://github.com/a/b.git", empty_repo, None)) >= 1)
chk("git_url 为空时仍返回 origin 兜底", len(launcher._mirror_fetch_sources(
    "", r"D:\OKApps\launcher\repos\ok-ww", git)) >= 1)

# ==================== 3) 防凭据弹窗（GCM 弹窗会挂死无终端子进程）====================
print("\n--- 3) git 子进程禁止凭据弹窗 ---")
env = launcher._git_no_prompt_env()
chk("GIT_TERMINAL_PROMPT=0", env.get("GIT_TERMINAL_PROMPT") == "0")
chk("GCM_INTERACTIVE=never", env.get("GCM_INTERACTIVE") == "never")
chk("GIT_ASKPASS 指向 echo（不弹窗）", env.get("GIT_ASKPASS") == "echo")
chk("GIT_CONFIG_NOSYSTEM=1（别让系统凭据助手把弹窗带回来）",
    env.get("GIT_CONFIG_NOSYSTEM") == "1")
cmd = launcher._git_cmd("git", ["fetch", "--tags", "x"])
chk("命令行也禁用 credential.helper", "-c" in cmd and "credential.helper=" in cmd)
chk("命令行也设 core.askPass", "core.askPass=echo" in cmd)
chk("原始参数未被破坏", cmd[-3:] == ["fetch", "--tags", "x"])

# 访问不存在的远端必须**快速失败**，不能挂在那等用户输入
import time
t0 = time.time()
rc_dead, _, err_dead = launcher._git_run(
    git, ["ls-remote", "--tags", DEAD_URL], BASE, timeout=30)
dt_dead = time.time() - t0
chk("不可达远端确实失败", rc_dead != 0)
chk("不可达远端快速失败（<20s，未挂起等输入）", dt_dead < 20)
print("   实测 %.2fs，stderr: %s" % (dt_dead, (err_dead or "(空)")[:80]))

# ==================== 4) 核心：多源回退让更新成功 ====================
print("\n--- 4) 核心回归：origin 不可达 + git_url 可达 → 必须更新成功 ---")
chk("前置：镜像本地还没有目标 tag",
    run(["tag"], MIRROR)[1].split() == ["v1.0.0"])

_old_repos = launcher.REPOS_DIR
launcher.REPOS_DIR = MIRROR_ROOT
try:
    ok_dir = None
    err = None
    try:
        ok_dir = launcher.ensure_mirror("testapp", _file_url(UPSTREAM), "v2.0.0")
    except Exception as e:                     # noqa: BLE001
        err = str(e)
    chk("ensure_mirror 成功返回（旧逻辑必失败）", ok_dir is not None)
    if err:
        print("   错误:", err[:300])
    chk("工作区真的切到目标版本",
        ok_dir is not None and
        open(os.path.join(MIRROR, "app.py")).read().strip() == "v2")

    # 目标 tag 不存在时，错误信息必须同时说清「拉不到」和「本地没有」，
    # 不能只给一句 pathspec 不匹配让人误以为版本不存在
    err2 = None
    try:
        launcher.ensure_mirror("testapp", "https://github.com/no/such-repo.git",
                               "v9.9.9")
    except Exception as e:                     # noqa: BLE001
        err2 = str(e)
    chk("目标版本不存在时抛异常（绝不静默）", err2 is not None)
    if err2:
        chk("错误信息含目标版本号（说清是哪个版本）", "v9.9.9" in err2)
        chk("错误信息含远端拉取失败的原因（不再只报 pathspec）",
            "拉取新版本均失败" in err2)
        chk("错误信息承诺未修改版本号（安抚用户）", "不会修改版本号" in err2)
finally:
    launcher.REPOS_DIR = _old_repos

# ==================== 5) 无系统 git 时不回崩 ====================
print("\n--- 5) 健壮性 ---")
chk("ensure_mirror 仍是函数", callable(launcher.ensure_mirror))

try:
    shutil.rmtree(BASE, ignore_errors=True)
    shutil.rmtree(empty_repo, ignore_errors=True)
except Exception:
    pass

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

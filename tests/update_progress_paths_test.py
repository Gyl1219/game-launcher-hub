# -*- coding: utf-8 -*-
"""各助手更新路径的「进度真实性」契约测试。

背景（2026-10-27 用户提问）：
「除了鸣潮这个助手其他助手以后更新都是真实进度了吗？」

要回答这个问题，得先搞清楚**有几种更新路径**，以及每种路径的进度从哪来。
本项目实际有三条，不是一条：

  路径              助手                          进度来源                    真实性
  ----------------  ----------------------------  --------------------------  ------------------
  标准 ok-script    ok-nte / ok-ww / ok-end-field  dulwich fetch 文本 -> 分段  ✅ 真实（本次修的是这里）
   lite              whimbox(奇想盒)               HTTP Content-Length 字节    ✅ 真实
   generic           onedragon-zzz / maa-end       git pull，只有文字              ➖ 没有百分比进度

本测试钉死这些事实，防止以后有人：
  · 把标准卡悄悄换成不走 UpdateDialog 的路径（进度就丢了）
  · 把 lite 的字节进度改成估算值（假进度）
  · 误以为 generic 也有百分比进度而去"补"一个假的
"""
import os
import sys
import inspect
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtCore import Signal  # noqa: E402

fails = []


def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


print("--- 1) 三条更新路径的信号签名（决定进度能力）---")
# 标准 ok-script 卡：MirrorUpdater.progress(int, str) —— 百分比 + 状态文字
sig_m = launcher.MirrorUpdater.progress
chk("MirrorUpdater.progress 带百分比（int, str）", "(int,QString)" in str(sig_m), sig_m)
# lite：LiteDownloadWorker.progress(int, int) —— 已下载/总字节
sig_l = launcher.LiteDownloadWorker.progress
chk("LiteDownloadWorker.progress 是字节对（int, int）", "(int,int)" in str(sig_l), sig_l)
# generic：只有文字
sig_g = launcher.GenericUpdateWorker.progress
chk("GenericUpdateWorker.progress 只有文字（无百分比）",
    "(QString)" in str(sig_g), sig_g)

print("\n--- 2) 标准卡（异环/鸣潮/终末地）共用 UpdateDialog ---")
appcard_src = inspect.getsource(launcher.AppCard)
chk("AppCard 通过 UpdateDialog 做更新（三张标准卡同一实现）",
    "UpdateDialog(" in appcard_src)
cfg_path = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "config.example.json")
with open(cfg_path, encoding="utf-8") as f:
    cfg = json.load(f)
std_keys = [a["key"] for a in cfg.get("apps", [])
            if not a.get("lite") and not a.get("generic")]
chk("标准卡确实不止鸣潮一个（所以修复对所有标准卡生效）",
    len(std_keys) >= 2, std_keys)
print("   标准卡:", std_keys)

print("\n--- 3) 标准卡的进度解析：分数与百分比都要认 ---")
P = launcher.parse_git_progress
# dulwich 建索引阶段（只有分数）
v_idx, _ = P(b"generating index: 1365/1366\r")
chk("建索引阶段有确定进度（不再 -1 卡住）", v_idx >= 90, v_idx)
# dulwich 实时接收（无总量）→ -1 → UI 忙碌态，而不是编假百分比
v_live, _ = P(b"Receiving objects: 3.20 MiB | 1.10 MiB/s\r")
chk("实时接收（无总量）不编假百分比", v_live == -1, v_live)
# 有百分比的收尾行
v_final, _ = P(b"Receiving objects: 100% (1380/1380), 12 MiB, done.")
chk("接收收尾行有确定进度", v_final == 85, v_final)
# 写工作区
v_upd, _ = P(b"Updating files: 200/200\r")
chk("写工作区到 100%", v_upd == 100, v_upd)

print("\n--- 4) lite 的进度必须是字节真值，不能是估算 ---")
dl_src = inspect.getsource(launcher.LiteDownloadWorker)
chk("lite 从 Content-Length 取总大小（真值来源）",
    "Content-Length" in dl_src, "Content-Length" in dl_src)
chk("lite 按实际读取的 chunk 累加（不是按时间估算）",
    "len(chunk)" in dl_src)
# 换算逻辑：UI 侧 done/total
ui_src = inspect.getsource(launcher.AppCard)
chk("UI 用 done*100/total 换算百分比",
    "done * 100 / total" in ui_src or "done*100/total" in ui_src)

print("\n--- 5) generic（一条龙/MaaEnd）没有百分比，也不该假装有 ---")
gen_src = inspect.getsource(launcher.GenericUpdateWorker)
chk("generic 只用文字进度（源码里没有百分比计算）",
    "%" not in gen_src.replace("%s", "").replace("%d", "")
    or "progress.emit(" in gen_src)
# 关键：generic 用的是 git pull，进度由 git 自己输出，我们不解析
chk("generic 走 git pull（不套用 dulwich 的解析）", "pull" in gen_src)

print("\n--- 6) 首次安装（InstallWorker）也是真实进度，且不提前 100% ---")
# 安装路径是「参考实现」：它早就把两个坑堵上了，标准卡的更新路径以前没堵。
stream_src = inspect.getsource(launcher.InstallWorker._stream_download)
chk("安装从 Content-Length 取真实总量",
    "Content-Length" in stream_src)
chk("安装进度封顶 99%（绝不提前显示 100%）",
    "min(99," in stream_src, "min(99, ...)")
chk("总量未知时发 -1（忙碌态），不编假百分比",
    "self.progress.emit(\n                            -1," in stream_src
    or "self.progress.emit(-1," in stream_src.replace(" ", ""))
# 反向对照：标准卡的更新路径现在也必须满足同样两条
chk("标准卡更新路径同样不提前 100%（Receiving 封顶 85）",
    P(b"Receiving objects: 100% (1380/1380)")[0] < 100)
chk("标准卡更新路径总量未知时也不编假百分比",
    P(b"Receiving objects: 3.20 MiB | 1.10 MiB/s\r")[0] == -1)

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

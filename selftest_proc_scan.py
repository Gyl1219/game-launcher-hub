# -*- coding: utf-8 -*-
"""进程扫描改动的自测脚本（纯 Win32 逻辑，不需要 GUI、不需要 PySide6）。

用法（本机双击或命令行）：
    python selftest_proc_scan.py

它做三件事：
  1. 直接执行 launcher.py 里那段「进程扫描」源码（不 import 整个 launcher，
     因此不依赖 PySide6 / qfluentwidgets），确保测的就是线上那份代码；
  2. 测 scan_running() 单次耗时 —— 这是本次性能修复的核心；
  3. 与旧的 tasklist 实现逐 key 对比结果，确保判定语义没有回归。

可选环境变量：
    LAUNCHER_PROC_FORCE_TASKLIST=1   强制走旧的 tasklist 降级路径
"""
import ast
import os
import subprocess
import sys
import time
import ctypes

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER_PY = os.path.join(HERE, "launcher.py")

# 从 config.json 里取真实的 app key 列表；取不到就用常见的兜底清单
DEFAULT_KEYS = ["ok-nte", "ok-ww", "ok-ef", "whimbox_app",
                "onedragon-runtimelauncher", "maaend"]


def detect_key(app, cfg_root):
    """算出真正用于进程判定的 key —— 这是最容易踩错的地方！

    注意：**不是 config.json 的 key**，而是对应 app.json 里的 name 字段
    （PyAppify 打包后的窗口标题用的是这个内部名）。实测差异很大：
        ok-end-field   → ok-ef
        whimbox        → whimbox_app
        onedragon-zzz  → onedragon-runtimelauncher
        maa-end        → maaend
    拿 config 的 key 去测，两边都会恒返回 False，看起来"一致"其实什么也没验证。
    逻辑与 launcher.py 的 _pyapp_title_key() 保持一致。
    """
    import json
    rel = app.get("app_json", "")
    if rel:
        path = os.path.join(cfg_root, rel.replace("/", os.sep))
        try:
            with open(path, "r", encoding="utf-8") as f:
                name = (json.load(f).get("name", "") or "").strip()
            if name:
                return name.lower()
        except Exception:
            pass
    exe = app.get("exe", "") or ""
    return os.path.basename(exe).lower().removesuffix(".exe")


def load_keys():
    """返回 [(配置 key, 真实检测 key)]。"""
    cfg = os.path.join(HERE, "config.json")
    try:
        import json
        with open(cfg, "r", encoding="utf-8") as f:
            data = json.load(f)
        root = data.get("install_root") or HERE
        apps = data.get("apps") or []
        pairs = []
        for a in apps:
            cfg_key = a.get("key", "")
            if not cfg_key:
                continue
            pairs.append((cfg_key, detect_key(a, root)))
        return pairs or [(k, k) for k in DEFAULT_KEYS]
    except Exception:
        return [(k, k) for k in DEFAULT_KEYS]


def exec_scan_module():
    """抽取 launcher.py 中「进程扫描」的纯 Python 段并执行。

    只取 _win_pid_names / _win_titles_for / _tasklist_fallback_names /
    scan_running 这一段（到 class ProcScanWorker 为止），避开 Qt 依赖。
    """
    src = open(LAUNCHER_PY, encoding="utf-8").read()
    lines = src.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        if line.startswith("PROC_SCAN_TTL"):
            start = i
            break
    for i, line in enumerate(lines):
        if line.startswith(("class ProcScanWorker", "class ProcScanner")):
            end = i
            break
    if start is None or end is None or end <= start:
        raise RuntimeError("未能从 launcher.py 中定位进程扫描模块，请检查是否被改名")

    segment = "\n".join(lines[start:end])
    ns = {
        "os": os, "subprocess": subprocess, "time": time, "ctypes": ctypes,
        "__name__": "launcher_scan_segment",
    }
    exec(compile(segment, "launcher.py[scan-segment]", "exec"), ns)
    return ns


def old_tasklist_impl(keys):
    """旧实现（改动前）的完整逻辑，用于结果对比。"""
    result = {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for key in keys:
        val = False
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq %s.exe" % key, "/NH"],
                capture_output=True, text=True, encoding="gbk",
                errors="replace", creationflags=flags, timeout=15)
            if ("%s.exe" % key) in (out.stdout or "").lower():
                val = True
            else:
                import csv as _csv
                import io as _io
                out = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq pythonw.exe",
                     "/V", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, encoding="gbk",
                    errors="replace", creationflags=flags, timeout=15)
                for row in _csv.reader(_io.StringIO(out.stdout or "")):
                    if len(row) >= 9 and key in row[8].lower():
                        val = True
                        break
        except Exception as exc:
            print("   [旧实现异常] %s: %r" % (key, exc))
        result[key] = val
    return result


def main():
    print("=" * 66)
    print("进程扫描自测 —— 目标文件 %s" % LAUNCHER_PY)
    print("=" * 66)

    ns = exec_scan_module()
    scan_running = ns["scan_running"]
    win_pid_names = ns["_win_pid_names"]
    force_flag = ns["_proc_force_tasklist"]()
    print("降级开关 LAUNCHER_PROC_FORCE_TASKLIST：%s" % ("已开启（走 tasklist）"
                                                        if force_flag else "未开启（走 Win32 API）"))

    pairs = load_keys()
    keys = [det for _, det in pairs]
    print("受测 app（%d 个，右侧为真正拿去匹配进程的关键字）：" % len(pairs))
    for cfg_key, det_key in pairs:
        note = "" if cfg_key == det_key else "   <-- 内部名与配置 key 不同"
        print("    %-20s 检测 key: %s%s" % (cfg_key, det_key, note))
    print()

    # ---- 1. 进程枚举是否可用 ----
    print("[1] 进程枚举可用性")
    names = win_pid_names()
    if names:
        print("    CreateToolhelp32Snapshot 可用，共枚举到 %d 个进程" % len(names))
        pys = [p for p, n in names.items() if n == "pythonw.exe"]
        print("    其中 pythonw.exe：%d 个 %s" % (len(pys), pys[:10]))
    else:
        print("    Win32 枚举返回 None → 已自动降级到 tasklist 路径")
    print()

    # ---- 2. 性能 ----
    print("[2] 性能：scan_running(全部 key) 单次耗时")
    n = 20
    t0 = time.perf_counter()
    for _ in range(n):
        new_res = scan_running(keys)
    new_ms = (time.perf_counter() - t0) / n * 1000.0
    print("    平均 %.2f ms" % new_ms)

    t0 = time.perf_counter()
    old_res = old_tasklist_impl(keys)
    old_ms = (time.perf_counter() - t0) * 1000.0
    print("    旧 tasklist 实现一次全查：%.2f ms（ %d 个 key 串行，各 2 次子进程）"
          % (old_ms, len(keys)))
    if old_ms > 0:
        print("    提速约 %.1f 倍" % (old_ms / new_ms if new_ms > 0 else float("inf")))
    print()

    # ---- 3. 正确性对比 ----
    print("[3] 正确性：新旧两边逐 key 对比")
    mismatch = []
    for k in keys:
        a, b = bool(new_res.get(k, False)), bool(old_res.get(k, False))
        flag = "OK " if a == b else "不一致！"
        if a != b:
            mismatch.append(k)
        print("    %-16s 新=%-5s 旧=%-5s %s" % (k, a, b, flag))
    print()

    # ---- 结论 ----
    print("=" * 66)
    ok01 = new_ms < 30
    print("耗时是否达标（<30ms）：%s" % ("是" if ok01 else "否 —— 请检查是否走了降级路径"))
    print("判定是否与旧实现一致：%s" % ("是" if not mismatch
                                      else "否 —— 不一致的 key：%s" % ", ".join(mismatch)))
    if mismatch:
        print()
        print("注意：结果不一致不一定是新逻辑错。旧实现用 tasklist /V 扫描时，"
              "对无响应窗口会在 SendMessage 上挂起甚至超时返回空，本身就可能漏判；"
              "请以「实际有没有开着这个助手」为准复核。")
    print("=" * 66)


if __name__ == "__main__":
    main()
    if sys.stdin and sys.stdin.isatty():
        try:
            input("\n按回车键退出…")
        except Exception:
            pass

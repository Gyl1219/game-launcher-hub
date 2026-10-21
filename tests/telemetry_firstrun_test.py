# -*- coding: utf-8 -*-
"""首次启动遥测询问：折中方案的行为验证。

要验的核心不是"对话框能弹出来"，而是**决策链正确**：
  · 没问过之前 → 一条都不发（不能"先收集再征求同意"）
  · 问过之后 → 记住选择，不再重复问
  · 三个按钮 → 三种落盘结果
  · 关窗口/异常 → 视为「不发」，绝不能默认成同意
"""
import json
import os
import sys
import io

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
from PySide6.QtWidgets import QApplication, QDialog

app = QApplication.instance() or QApplication(sys.argv)
OK, FAIL = [], []


def chk(n, c, extra=""):
    (OK if c else FAIL).append(n)
    print(("PASS  " if c else "FAIL  ") + n + (("  | " + extra) if extra else ""))
    sys.stdout.flush()


# ---------- 用临时 config 隔离，别动用户真实配置 ----------
CFG = launcher._cfg_path()
BAK = CFG + ".testbak"
had = os.path.isfile(CFG)
if had:
    with open(CFG, "rb") as f:
        data = f.read()
    with open(BAK, "wb") as f:
        f.write(data)


def write_cfg(d):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def read_cfg():
    with open(CFG, "r", encoding="utf-8") as f:
        return json.load(f)


try:
    # ---------- 1) 没问过 → 待询问，且此刻一条都不发 ----------
    write_cfg({"install_root": "D:/OKApps"})      # 全新配置：无 telemetry、无 telemetry_asked
    chk("1) 新用户处于「待询问」状态", launcher.telemetry_choice_pending() is True)
    chk("1b) 没问过之前 telemetry_enabled()=False（不会先收集）",
        launcher.telemetry_enabled() is False, str(launcher._telemetry_cfg()))
    chk("1c) 没问过之前 ping 也不发",
        launcher.telemetry_ping_enabled() is False)

    # ---------- 2) 三个按钮三种结果 ----------
    save = launcher.save_telemetry_choice
    cases = [
        ("同意", True, True, {"enabled": True, "ping": True}),
        ("只发崩溃", True, False, {"enabled": True, "ping": False}),
        ("不发", False, False, {"enabled": False, "ping": False}),
    ]
    for label, en, ping, expect in cases:
        write_cfg({"install_root": "D:/OKApps"})
        save(en, ping=ping)
        t = read_cfg().get("telemetry") or {}
        ok = all(t.get(k) == v for k, v in expect.items())
        chk("2) 「%s」落盘正确" % label, ok, json.dumps(t, ensure_ascii=False))

    # ---------- 3) 问过之后不再问 ----------
    write_cfg({"install_root": "D:/OKApps"})
    launcher.save_telemetry_choice(False, ping=False)
    chk("3) 问过一次后不再待询问", launcher.telemetry_choice_pending() is False)
    chk("3b) telemetry_asked 标记已写入",
        read_cfg().get(launcher.TELEMETRY_ASKED_KEY) is True,
        str(read_cfg().get(launcher.TELEMETRY_ASKED_KEY)))

    # ---------- 4) 同意时自动补 endpoint + ping ----------
    write_cfg({"install_root": "D:/OKApps"})
    launcher.save_telemetry_choice(True)          # 不显式传 ping
    t = read_cfg().get("telemetry") or {}
    chk("4) 同意时自动补默认 endpoint",
        t.get("endpoint") == launcher.TELEMETRY_DEFAULT_ENDPOINT, str(t.get("endpoint")))
    chk("4b) 同意时 ping 默认跟着开（只同意错误上报也没理由拒绝计数）",
        t.get("ping") is True, str(t.get("ping")))
    chk("4c) 同意后 telemetry_enabled()=True", launcher.telemetry_enabled() is True)

    # ---------- 5) 对话框：三个按钮的选择值 ----------
    dlg = launcher.TelemetryAskDialog()
    chk("5) 对话框默认选择是「不发」（关窗口≠同意）",
        dlg.choice == launcher.TelemetryAskDialog.CHOSEN_NO, str(dlg.choice))
    dlg2 = launcher.TelemetryAskDialog()
    dlg2._pick(launcher.TelemetryAskDialog.CHOSEN_YES)
    chk("5b) 点「同意」记录 YES",
        dlg2.choice == launcher.TelemetryAskDialog.CHOSEN_YES)
    dlg3 = launcher.TelemetryAskDialog()
    dlg3._pick(launcher.TelemetryAskDialog.CHOSEN_CRASH_ONLY)
    chk("5c) 点「只发崩溃」记录 CRASH_ONLY",
        dlg3.choice == launcher.TelemetryAskDialog.CHOSEN_CRASH_ONLY)

    # ---------- 6) 对话框里必须写清"发什么/不发什么" ----------
    from PySide6.QtWidgets import QLabel
    dlg4 = launcher.TelemetryAskDialog()
    texts = "\n".join(l.text() for l in dlg4.findChildren(QLabel))
    chk("6) 说明里列出了会发送的内容",
        "版本号" in texts and "调用栈" in texts, texts[:60].replace("\n", " / "))
    chk("6b) 说明里明确承诺不发路径/凭据",
        ("文件路径" in texts or "路径" in texts) and
        ("CDK" in texts or "密码" in texts), texts[:80].replace("\n", " / "))
    chk("6c) 说明了可以随时在设置页改", "设置" in texts)

    # ---------- 7) 已问过时不再弹（幂等）----------
    write_cfg({"install_root": "D:/OKApps"})
    launcher.save_telemetry_choice(False, ping=False)
    chk("7) 已问过 → ask 不再执行", launcher.ask_telemetry_on_first_run(None) is False)

finally:
    # 还原用户真实配置
    try:
        if had:
            with open(BAK, "rb") as f:
                data = f.read()
            with open(CFG, "wb") as f:
                f.write(data)
            os.remove(BAK)
        else:
            os.remove(CFG)
    except Exception as e:
        print("  (还原 config 失败: %s)" % e)

print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
for f in FAIL:
    print("   FAILED:", f)
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

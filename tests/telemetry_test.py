# -*- coding: utf-8 -*-
"""匿名错误上报 / 启动计数 单测（不联网）。

核心合约两条：
  1. **默认不发**：没开 telemetry.enabled 或没配 endpoint → 绝不发任何网络请求
  2. **发出去的东西必须脱敏**：CDK、本机绝对路径、用户名、邮箱一律被替换

第 2 条最重要——config.json 里有 mirrorchyan_cdk 和个人安装路径，
错误栈里带这些等于泄露密钥和隐私。
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


SENT = []  # 捕获所有实际发出的 payload


def fake_post(payload):
    SENT.append(payload)


# ---------- 1) 默认（未配置）绝不发送 ----------
with patch.object(launcher, "_load_cfg_safe", return_value={}), \
     patch.object(launcher, "_telemetry_post", fake_post):
    SENT.clear()
    chk("未配置 → telemetry_enabled=False", launcher.telemetry_enabled() is False)
    chk("未配置 → ping=False", launcher.telemetry_ping_enabled() is False)
    launcher.report_error("boom", "something failed", "detail")
    launcher.report_ping()
    chk("未配置时 report_error 不发送", len(SENT) == 0)
    chk("未配置时 report_ping 不发送", len(SENT) == 0)

# 开了 enabled 但没 endpoint → 仍不发（防止"开了就以为在发"的错觉）
with patch.object(launcher, "_load_cfg_safe",
                  return_value={"telemetry": {"enabled": True, "endpoint": ""}}), \
     patch.object(launcher, "_telemetry_post", fake_post):
    SENT.clear()
    chk("enabled 但 endpoint 空 → 视为关闭", launcher.telemetry_enabled() is False)
    launcher.report_error("boom", "x")
    chk("endpoint 空时不发送", len(SENT) == 0)

# 配了 endpoint 但 enabled=False → 不发
with patch.object(launcher, "_load_cfg_safe",
                  return_value={"telemetry": {"enabled": False,
                                              "endpoint": "https://x/y"}}), \
     patch.object(launcher, "_telemetry_post", fake_post):
    SENT.clear()
    launcher.report_error("boom", "x")
    chk("enabled=False 时不发送", len(SENT) == 0)


# ---------- 2) 启用后确实发送，且字段正确 ----------
CFG_ON = {"telemetry": {"enabled": True, "ping": True,
                        "endpoint": "https://x.example/collect"}}
with patch.object(launcher, "_load_cfg_safe", return_value=CFG_ON), \
     patch.object(launcher, "_telemetry_post", fake_post):
    SENT.clear()
    chk("配好 → telemetry_enabled=True", launcher.telemetry_enabled() is True)
    chk("配好 → ping=True", launcher.telemetry_ping_enabled() is True)
    launcher.report_error("uncaught", "ValueError: bad", "traceback...")
    chk("report_error 发送一次", len(SENT) == 1)
    p = SENT[0]
    chk("含 app 名", p.get("app") == "game-launcher-hub")
    chk("含版本号", p.get("version") == launcher.APP_VERSION)
    chk("kind 正确", p.get("kind") == "uncaught")
    chk("含 anon_id", bool(p.get("anon_id")))
    chk("含时间戳", isinstance(p.get("ts"), int))

    SENT.clear()
    launcher.report_ping()
    chk("report_ping 发送一次", len(SENT) == 1)
    chk("ping 的 kind=ping", SENT[0].get("kind") == "ping")
    chk("ping 不带 detail（最小化）", "detail" not in SENT[0])

# ping=False 时不发 ping，但错误仍发
with patch.object(launcher, "_load_cfg_safe",
                  return_value={"telemetry": {"enabled": True, "ping": False,
                                              "endpoint": "https://x/y"}}), \
     patch.object(launcher, "_telemetry_post", fake_post):
    SENT.clear()
    launcher.report_ping()
    chk("ping=False 时不发 ping", len(SENT) == 0)
    launcher.report_error("x", "y")
    chk("ping=False 时错误仍上报", len(SENT) == 1)


# ---------- 3) 脱敏（本功能最重要的一条）----------
S = launcher.sanitize_text

chk("URL 里的 cdk 被吃掉",
    "cdk=<redacted>" in S("https://a/b?cdk=SECRET123&os=win"))
chk("URL 里其它参数保留", "os=win" in S("https://a/b?cdk=SECRET123&os=win"))
chk("cdk= 值本身不残留", "SECRET123" not in S("https://a/b?cdk=SECRET123&os=win"))

chk("键值对 cdk 被吃掉", "SECRET" not in S('cdk: "MYSECRETKEY"'))
chk("token 被吃掉", "abc123xyz" not in S("token=abc123xyz"))
chk("password 被吃掉", "hunter2" not in S("password=hunter2"))

chk("邮箱被替换", "<email>" in S("contact me at foo.bar@example.com now"))
chk("邮箱原文不残留", "foo.bar@example.com" not in S("mail: foo.bar@example.com"))

# 本机路径
home = os.path.expanduser("~")
chk("HOME 目录被替换",
    home not in S("failed at %s\\AppData\\x.txt" % home) and "<HOME>" in S(home))
chk("LAUNCHER_DIR 被替换",
    launcher.LAUNCHER_DIR not in S("open %s\\config.json" % launcher.LAUNCHER_DIR))

# 组合场景：模拟真实 traceback 里同时含路径和 CDK
dirty = ('File "%s\\launcher.py", line 10, in run\n'
         '  url = "https://mirrorchyan.com/api/resources/ok-nte/latest?cdk=LEAKEDKEY123"\n'
         '  path = "%s\\config.json"\n'
         '  mail = me@corp.com' % (launcher.LAUNCHER_DIR, home))
clean = S(dirty)
chk("组合场景: CDK 已脱敏", "LEAKEDKEY123" not in clean)
chk("组合场景: HOME 已脱敏", home not in clean)
chk("组合场景: LAUNCHER_DIR 已脱敏", launcher.LAUNCHER_DIR not in clean)
chk("组合场景: 邮箱已脱敏", "me@corp.com" not in clean)
chk("组合场景: 仍保留可读结构", "launcher.py" in clean and "line 10" in clean)

chk("空输入安全", S("") == "" and S(None) == "")


# ---------- 4) 上报内容确实经过脱敏 ----------
with patch.object(launcher, "_load_cfg_safe", return_value=CFG_ON), \
     patch.object(launcher, "_telemetry_post", fake_post):
    SENT.clear()
    launcher.report_error("uncaught", "boom at %s" % home,
                          "url?cdk=MYKEY999 path=%s" % launcher.LAUNCHER_DIR)
    p = SENT[0]
    blob = (p.get("message", "") + p.get("detail", ""))
    chk("上报体不含原始 HOME", home not in blob)
    chk("上报体不含原始 LAUNCHER_DIR", launcher.LAUNCHER_DIR not in blob)
    chk("上报体不含 CDK 明文", "MYKEY999" not in blob)
    chk("上报体含占位符", "<redacted>" in blob or "<HOME>" in blob or "<LAUNCHER_DIR>" in blob)


# ---------- 5) 任何内部异常都不外泄（不抛）----------
with patch.object(launcher, "_load_cfg_safe", side_effect=Exception("cfg boom")), \
     patch.object(launcher, "_telemetry_post", fake_post):
    try:
        launcher.report_error("x", "y")
        launcher.report_ping()
        launcher.telemetry_enabled()
        ok = True
    except Exception:
        ok = False
    chk("配置读取异常时上报函数不抛", ok)

with patch.object(launcher, "_load_cfg_safe", return_value=CFG_ON), \
     patch.object(launcher, "_telemetry_post", side_effect=Exception("net boom")):
    try:
        launcher.report_error("x", "y")
        ok = True
    except Exception:
        ok = False
    chk("发送异常被吞掉不抛", ok)


# ---------- 6) anon_id 稳定且可持久化 ----------
with patch.object(launcher.Launcher, "__init__", lambda self: None):
    pass
a1 = launcher._anon_id()
a2 = launcher._anon_id()
chk("anon_id 非空的十六进制串", bool(a1) and len(a1) >= 16)
chk("anon_id 多次调用稳定", a1 == a2)

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

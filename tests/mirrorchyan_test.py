# -*- coding: utf-8 -*-
"""Mirror酱（MirrorChyan）加速源接入单测（不联网）。

核心契约：**拿不到加速直链就静默返回 None，绝不抛异常、绝不让下载失败**。
Mirror酱 是「有则更好」的可选加速源，主路径永远是万载云 / cnb / GitHub 直链。

验证：
  - rid 解析：config 覆盖 > 内置默认 > 空
  - mirrorchyan_latest：无 rid / 无 CDK / code!=0 / 无 url / 网络异常 → 一律 None
  - mirrorchyan_latest：成功时返回 (url, version, note)
  - LiteDownloadWorker 候选源：配了 rid+CDK 才带 Mirror酱，否则只有 GitHub/万载云
  - 向后兼容：不传 key 时不崩（旧调用方式）
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


def _resp(obj):
    """造一个假的 urlopen 上下文管理器，返回给定 JSON。"""
    m = MagicMock()
    m.__enter__.return_value.read.return_value = __import__("json").dumps(obj).encode()
    return m


# ---------- 1) rid 解析优先级 ----------
with patch.object(launcher, "_load_cfg_safe",
                  return_value={"mirrorchyan_res_ids": {"ok-ww": "CUSTOM_RID"}}):
    chk("config 覆盖优先: ok-ww → CUSTOM_RID",
        launcher.mirrorchyan_rid_for("ok-ww") == "CUSTOM_RID")
    chk("未覆盖的 key 用内置默认: ok-nte → ok-nte",
        launcher.mirrorchyan_rid_for("ok-nte") == "ok-nte")

with patch.object(launcher, "_load_cfg_safe", return_value={}):
    chk("无 config 时用内置默认: ok-ww → okww",
        launcher.mirrorchyan_rid_for("ok-ww") == "okww")
    chk("未知 key → 空串", launcher.mirrorchyan_rid_for("whimbox") == "")
    chk("启动器自己未配置 → 空串",
        launcher.mirrorchyan_rid_for("game-launcher-hub") == "")

with patch.object(launcher, "_load_cfg_safe", side_effect=Exception("boom")):
    chk("_load_cfg_safe 异常不影响 rid 查询", launcher.mirrorchyan_rid_for("ok-nte") == "ok-nte")


# ---------- 2) mirrorchyan_latest 各种失败 → None ----------
chk("无 rid → None", launcher.mirrorchyan_latest("", "CDK") is None)
chk("无 CDK → None", launcher.mirrorchyan_latest("ok-nte", "") is None)
chk("两者皆空 → None", launcher.mirrorchyan_latest("", "") is None)

with patch.object(launcher.urllib.request, "urlopen",
                  return_value=_resp({"code": 1, "msg": "invalid cdk"})):
    chk("code!=0 → None", launcher.mirrorchyan_latest("ok-nte", "BAD") is None)

with patch.object(launcher.urllib.request, "urlopen",
                  return_value=_resp({"code": 0, "data": {}})):
    chk("code=0 但无 url → None", launcher.mirrorchyan_latest("ok-nte", "CDK") is None)

with patch.object(launcher.urllib.request, "urlopen",
                  return_value=_resp({"code": 0, "data": {"url": "not-a-url"}})):
    chk("url 非 http 开头 → None", launcher.mirrorchyan_latest("ok-nte", "CDK") is None)

with patch.object(launcher.urllib.request, "urlopen",
                  side_effect=Exception("network down")):
    chk("网络异常 → None（不抛）", launcher.mirrorchyan_latest("ok-nte", "CDK") is None)

with patch.object(launcher.urllib.request, "urlopen", return_value=_resp("not json")):
    chk("返回非 dict → None", launcher.mirrorchyan_latest("ok-nte", "CDK") is None)


# ---------- 3) 成功路径 ----------
ok_resp = {"code": 0, "data": {
    "url": "https://mirrorchyan.com/resources/download/abc",
    "version_name": "v1.2.3",
    "release_note": "修复若干问题"}}
with patch.object(launcher.urllib.request, "urlopen", return_value=_resp(ok_resp)):
    got = launcher.mirrorchyan_latest("ok-nte", "CDK", current_version="v1.0.0")
    chk("成功返回三元组", got is not None and len(got) == 3)
    chk("url 正确", got and got[0] == "https://mirrorchyan.com/resources/download/abc")
    chk("version 正确", got and got[1] == "v1.2.3")
    chk("release_note 正确", got and got[2] == "修复若干问题")

# 请求 URL 应带上必要参数
captured = {}
def _fake_urlopen(req, *a, **k):
    captured["url"] = req.full_url
    return _resp(ok_resp)
with patch.object(launcher.urllib.request, "urlopen", _fake_urlopen):
    launcher.mirrorchyan_latest("ok-nte", "MY CDK/X", current_version="v1.0.0")
u = captured.get("url", "")
chk("API 路径含 rid", "/api/resources/ok-nte/latest" in u)
chk("带 cdk 参数且已 urlencode", "cdk=MY+CDK%2FX" in u or "cdk=MY%20CDK%2FX" in u)
chk("带 current_version", "current_version=v1.0.0" in u)
chk("带 os/arch/channel", "os=win" in u and "arch=x64" in u and "channel=stable" in u)


# ---------- 4) LiteDownloadWorker 候选源 ----------
GH = "https://github.com/o/r/releases/download/v1/x.exe"

# 4a) 无 key → 不带 Mirror酱（向后兼容旧行为）
w = launcher.LiteDownloadWorker(GH, "C:/tmp/x.exe")
cands = w._candidates()
labels = [c[0] for c in cands]
chk("无 key 时不含 Mirror酱", not any("Mirror" in l for l in labels))
chk("无 key 时仍有 GitHub 直链兜底", "GitHub 直链" in labels)

# 4b) 有 key 但没配 rid / 没 CDK → 不带 Mirror酱
w2 = launcher.LiteDownloadWorker(GH, "C:/tmp/x.exe", key="whimbox")
with patch.object(launcher, "_load_cfg_safe", return_value={}):
    labels2 = [c[0] for c in w2._candidates()]
chk("有 key 但无 rid → 不含 Mirror酱", not any("Mirror" in l for l in labels2))

# 4c) 配了 rid + CDK 且 API 成功 → 带 Mirror酱
w3 = launcher.LiteDownloadWorker(GH, "C:/tmp/x.exe", key="ok-nte")
with patch.object(launcher, "_load_cfg_safe",
                  return_value={"mirrorchyan_cdk": "CDK123"}), \
     patch.object(launcher.urllib.request, "urlopen", return_value=_resp(ok_resp)):
    cands3 = w3._candidates()
labels3 = [c[0] for c in cands3]
chk("配好 rid+CDK 且有直链 → 含 Mirror酱", any("Mirror" in l for l in labels3))
chk("同时仍保留 GitHub 直链兜底", "GitHub 直链" in labels3)

# 4d) 配了但 API 拿不到直链 → 静默跳过，不报错
w4 = launcher.LiteDownloadWorker(GH, "C:/tmp/x.exe", key="ok-nte")
with patch.object(launcher, "_load_cfg_safe",
                  return_value={"mirrorchyan_cdk": "CDK123"}), \
     patch.object(launcher.urllib.request, "urlopen",
                  return_value=_resp({"code": 1, "msg": "bad"})):
    try:
        cands4 = w4._candidates()
        ok = True
    except Exception:
        cands4, ok = [], False
chk("API 失败时不抛异常", ok)
chk("API 失败时不含 Mirror酱", not any("Mirror" in c[0] for c in cands4))
chk("API 失败时仍有 GitHub 直链", "GitHub 直链" in [c[0] for c in cands4])


# ---------- 5) InstallWorker._mirrorchyan_url 仍可用 ----------
class _FakeIW:
    REPOS = launcher.InstallWorker.REPOS
    def __init__(self, key, cdk):
        self.key, self.cdk = key, cdk
    _mirrorchyan_url = launcher.InstallWorker._mirrorchyan_url

iw = _FakeIW("ok-nte", "")
chk("InstallWorker 无 CDK → None", iw._mirrorchyan_url() is None)

iw2 = _FakeIW("ok-nte", "CDK")
with patch.object(launcher.urllib.request, "urlopen", return_value=_resp(ok_resp)):
    chk("InstallWorker 有 CDK → 拿到直链",
        iw2._mirrorchyan_url() == "https://mirrorchyan.com/resources/download/abc")

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

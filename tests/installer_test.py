# -*- coding: utf-8 -*-
"""首次安装（官方安装包下载 + 装后定位）回归测试。

覆盖两条此前完全走不通的路径：
  - lite（奇想盒）/ generic（绝区零一条龙）未安装态，以前只给「打开官网」
  - 装到的位置 ≠ config 预置路径时，必须**真正搜索**并写回，不能只信预置路径

安全约束：绝不能污染真实 config.json —— 全程把 _cfg_path 重定向到临时文件。
"""
import os
import sys
import json
import shutil
import tempfile
import unittest.mock as mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# 模态弹窗在 offscreen 下会**永远阻塞等用户点击**，必须替换成记录型桩。
# （真实使用里弹窗是正常的，这里只是无人值守测试的需要）
_MSGBOX = []
launcher.QMessageBox.warning = staticmethod(
    lambda *a, **k: _MSGBOX.append(("warning", a[2] if len(a) > 2 else "")))
launcher.QMessageBox.information = staticmethod(
    lambda *a, **k: _MSGBOX.append(("info", a[2] if len(a) > 2 else "")))
launcher.QMessageBox.question = staticmethod(
    lambda *a, **k: launcher.QMessageBox.StandardButton.Yes)

OK = []
FAIL = []


def chk(name, cond):
    (OK if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name)


# ---------- 临时 config，避免写坏真实配置 ----------
_TMP = tempfile.mkdtemp(prefix="installer_t_")
_REAL_CFG = launcher._cfg_path
_TMP_CFG = os.path.join(_TMP, "config.json")

REAL_CFG_DATA = None
try:
    with open(_REAL_CFG(), "r", encoding="utf-8") as f:
        REAL_CFG_DATA = json.load(f)
except Exception:
    REAL_CFG_DATA = {"apps": []}

# 把待测 app 的 exe 指向不存在的路径，制造「未安装」场景
for _a in REAL_CFG_DATA.get("apps", []):
    if _a.get("key") == "onedragon-zzz":
        _a["exe"] = "D:/NOPE/OneDragon-RuntimeLauncher.exe"
    if _a.get("key") == "whimbox":
        _a["exe"] = "D:/NOPE/whimbox_app.exe"
with open(_TMP_CFG, "w", encoding="utf-8") as f:
    json.dump(REAL_CFG_DATA, f, ensure_ascii=False, indent=2)

launcher._cfg_path = lambda: _TMP_CFG


def _app(key):
    for a in REAL_CFG_DATA.get("apps", []):
        if a.get("key") == key:
            return dict(a)
    return {"key": key, "display": key, "exe": "", "icon": "", "website": ""}


# =========================================================
# 1) 安装包资产解析：只认正式版 + glob 匹配
# =========================================================
print("--- 安装包资产解析 ---")

FAKE_RELEASES = [
    {  # 测试版在前：必须被跳过
        "tag_name": "v9.9.9-beta", "prerelease": True, "draft": False,
        "assets": [{"name": "whimbox_app-setup-9.9.9.exe",
                    "browser_download_url": "https://x/BAD.exe"}],
    },
    {  # 正式版：命中的是这个
        "tag_name": "v3.1.0", "prerelease": False, "draft": False,
        "assets": [
            {"name": "whimbox-3.1.0-py3-none-any.whl",
             "browser_download_url": "https://x/whl"},
            {"name": "whimbox_app-setup-3.1.0.exe",
             "browser_download_url": "https://x/setup.exe"},
        ],
    },
]


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


with mock.patch.object(launcher.urllib.request, "urlopen",
                       return_value=_Resp(FAKE_RELEASES)):
    url, name = launcher._resolve_installer_asset(launcher.INSTALLER_REPO["whimbox"])

chk("命中正式版安装包", name == "whimbox_app-setup-3.1.0.exe")
chk("跳过测试版(未误取 BAD.exe)", "BAD" not in url)
chk("返回下载 URL", url.endswith("setup.exe"))

# 网络异常 → 空结果，不抛
with mock.patch.object(launcher.urllib.request, "urlopen",
                       side_effect=OSError("network down")):
    u2, n2 = launcher._resolve_installer_asset(launcher.INSTALLER_REPO["whimbox"])
chk("网络异常返回空且不抛", u2 == "" and n2 == "")

# 一条龙 glob 也能命中
FAKE_OD = [{
    "tag_name": "v2.5.2", "prerelease": False, "draft": False,
    "assets": [
        {"name": "ZenlessZoneZero-OneDragon-v2.5.2-Full.zip",
         "browser_download_url": "https://x/full.zip"},
        {"name": "ZenlessZoneZero-OneDragon-v2.5.2-Installer.exe",
         "browser_download_url": "https://x/Installer.exe"},
    ],
}]
with mock.patch.object(launcher.urllib.request, "urlopen",
                       return_value=_Resp(FAKE_OD)):
    u3, n3 = launcher._resolve_installer_asset(
        launcher.INSTALLER_REPO["onedragon-zzz"])
chk("一条龙命中 Installer.exe", n3.endswith("Installer.exe"))
chk("一条龙未误取 Full.zip", "full.zip" not in u3)


# =========================================================
# 2) 装后搜索：找到 / 找不到
# =========================================================
print("--- 装后定位搜索 ---")

scan_root = os.path.join(_TMP, "scan")
os.makedirs(os.path.join(scan_root, "DZZZ-OD"), exist_ok=True)
target = os.path.join(scan_root, "DZZZ-OD", "OneDragon-RuntimeLauncher.exe")
open(target, "w").close()

od_app = _app("onedragon-zzz")
found = launcher._search_installed_exe(od_app, extra_dirs=[scan_root])
chk("能在子目录里找到 exe", found and os.path.isfile(found))

missing = launcher._search_installed_exe(
    {"key": "x", "exe": "Z:/nope/Nothing.exe"}, extra_dirs=[scan_root])
chk("找不到时返回空串(不误判)", missing == "")

noexe = launcher._search_installed_exe({"key": "x", "exe": ""})
chk("exe 为空时返回空串", noexe == "")


# =========================================================
# 3) config 写回
# =========================================================
print("--- config 写回 ---")

newpath = os.path.join(scan_root, "DZZZ-OD", "OneDragon-RuntimeLauncher.exe")
ok_write = launcher._save_app_exe("onedragon-zzz", newpath)
chk("_save_app_exe 返回 True", ok_write is True)

with open(_TMP_CFG, "r", encoding="utf-8") as f:
    saved = json.load(f)
od_saved = [a for a in saved["apps"] if a["key"] == "onedragon-zzz"][0]
chk("config 里 exe 已更新", od_saved["exe"].endswith("OneDragon-RuntimeLauncher.exe"))
chk("路径分隔符已归一化为 /", "\\" not in od_saved["exe"])
chk("同条目其它字段未丢(icon/website)",
    od_saved.get("icon") and od_saved.get("website"))
chk("其它 app 未被波及",
    any(a.get("key") == "whimbox" for a in saved["apps"]))
chk("未知 key 返回 False", launcher._save_app_exe("no-such-key", "C:/x.exe") is False)


# =========================================================
# 4) AppInstallerWorker：成功 / 失败路径
# =========================================================
print("--- 安装 worker ---")

app_qt = QApplication.instance() or QApplication([])


class _FakePopen:
    def __init__(self, *a, **k):
        pass

    def wait(self):
        return 0


class _DLResp:
    """假下载响应。

    关键：read() 必须在数据读完后返回空字节，否则 shutil.copyfileobj 会
    **永远循环**（它靠空 bytes 判断结束）——踩过一次，直接把进程写挂。
    """

    def __init__(self, data):
        self._d = data
        self._i = 0

    def read(self, n=-1):
        if self._i >= len(self._d):
            return b""
        chunk = self._d[self._i:] if (n is None or n < 0) \
            else self._d[self._i:self._i + n]
        self._i += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_worker(app, resolve_ret, search_ret, urlopen_side=None):
    """跑一次 worker，返回 (done_path, failed_msg, progress 列表)。"""
    res = {"done": None, "failed": None}
    prog = []

    class W(launcher.AppInstallerWorker):
        pass

    w = W(app, os.path.join(_TMP, "dl"))
    w.done.connect(lambda p: res.__setitem__("done", p))
    w.failed.connect(lambda m: res.__setitem__("failed", m))
    w.progress.connect(lambda t: prog.append(t))

    with mock.patch.object(launcher, "_resolve_installer_asset",
                           return_value=resolve_ret), \
         mock.patch.object(launcher, "_search_installed_exe",
                           return_value=search_ret), \
         mock.patch.object(launcher.subprocess, "Popen", _FakePopen), \
         mock.patch.object(launcher.urllib.request, "urlopen",
                           return_value=_DLResp(b"fake-bytes")):
        w.run()
    return res["done"], res["failed"], prog


d, f, p = _run_worker(od_app,
                      ("https://x/Installer.exe", "Installer.exe"),
                      target)
chk("成功路径发出 done(装到的路径)", d == target)
chk("成功路径不报失败", f is None)
chk("进度有文案(含下载/安装提示)",
    any("下载" in t for t in p) and any("安装程序" in t for t in p))

d2, f2, _ = _run_worker(od_app, ("", ""), "")
chk("找不到安装包 → failed", f2 is not None and "安装包" in f2)
chk("找不到安装包 → 不发 done", d2 is None)

d3, f3, _ = _run_worker(od_app,
                        ("https://x/Installer.exe", "Installer.exe"),
                        "")
chk("装完找不到 exe → failed 并提示手动指定",
    f3 is not None and "选择已安装程序" in f3)
chk("装完找不到 → 不发 done", d3 is None)

# 下载失败
res4 = {}
w4 = launcher.AppInstallerWorker(od_app, os.path.join(_TMP, "dl"))
w4.failed.connect(lambda m: res4.__setitem__("m", m))
with mock.patch.object(launcher, "_resolve_installer_asset",
                       return_value=("https://x/i.exe", "i.exe")), \
     mock.patch.object(launcher.urllib.request, "urlopen",
                       side_effect=OSError("conn reset")):
    w4.run()
chk("下载失败 → failed 含原因", "下载安装包失败" in (res4.get("m") or ""))


# =========================================================
# 5) 未安装卡片 UI：按钮齐不齐
# =========================================================
print("--- 未安装卡片 UI ---")

# 已安装态卡片会自动 spawn git fetch 线程（沙盒网络挂住 → 进程退不出），这里禁掉
launcher.AppCard._generic_start_check = lambda self: None


def _buttons(card):
    return [b.text() for b in card.findChildren(launcher.PushButton)]


for key, kind in (("onedragon-zzz", "generic"), ("whimbox", "lite")):
    a = _app(key)
    a["exe"] = "D:/NOPE/" + os.path.basename(a.get("exe") or "x.exe")
    card = launcher.AppCard(a)
    btns = _buttons(card)
    print("   %s(%s) 按钮: %s" % (key, kind, btns))
    chk("%s 未安装有「安装」按钮" % key, "安装" in btns)
    chk("%s 未安装有「选择已安装程序…」" % key, "选择已安装程序…" in btns)
    chk("%s 未安装保留「打开官网」" % key, "打开官网" in btns)
    chk("%s 未安装不显示卸载" % key, "卸载此程序" not in btns and "卸载此助手" not in btns)

# 已安装的卡不该冒出安装按钮
inst = _app("onedragon-zzz")
inst["exe"] = target          # 真实存在的文件
card_inst = launcher.AppCard(inst)
chk("已安装态不显示「安装」", "安装" not in _buttons(card_inst))


# =========================================================
# 6) 安装完成回调：exe 落内存 + 写盘 + 卡片转正
# =========================================================
print("--- 安装完成回调 ---")

a = _app("onedragon-zzz")
a["exe"] = "D:/NOPE/OneDragon-RuntimeLauncher.exe"
card = launcher.AppCard(a)
chk("回调前是未安装", "安装" in _buttons(card))
card._on_installer_done(target)
chk("回调后 app[exe] 已更新", a["exe"] == target)
chk("回调后卡片转为已安装", "安装" not in _buttons(card))
with open(_TMP_CFG, "r", encoding="utf-8") as f:
    chk("回调后已落盘 config",
        [x for x in json.load(f)["apps"]
         if x["key"] == "onedragon-zzz"][0]["exe"].endswith("OneDragon-RuntimeLauncher.exe"))

# 失败回调要把按钮恢复可用
a2 = _app("whimbox")
a2["exe"] = "D:/NOPE/whimbox_app.exe"
card2 = launcher.AppCard(a2)
card2.install_btn.setEnabled(False)
card2._on_installer_failed("测试失败")
chk("失败后按钮恢复可用", card2.install_btn.isEnabled())
chk("失败后按钮文案复位", card2.install_btn.text() == "安装")

# =========================================================
# 7) CNB 镜像优先 / GitHub 兜底
# =========================================================
print("--- CNB 镜像优先 ---")

CNB_RELS = [{
    "tag_name": "v2.5.2", "prerelease": False, "draft": False,
    "assets": [{
        "name": "ZenlessZoneZero-OneDragon-v2.5.2-Installer.exe",
        "browser_download_url": "https://cnb.cool/.../Installer.exe",
        "brower_download_url": "https://cnb.cool/.../typo.exe",   # 拼错字段
        "url": "https://api.cnb.cool/.../401.exe",
    }],
}]

u, n = launcher._pick_installer(CNB_RELS, "*-Installer.exe")
chk("取正确的 browser_download_url(非拼错字段)", "typo" not in u and "cnb.cool" in u)
chk("未误用 api.cnb.cool 的 url 字段", "api.cnb.cool" not in u)

# prerelease / draft 必须跳过
u2, _ = launcher._pick_installer(
    [{"tag_name": "v9", "prerelease": True, "draft": False,
      "assets": [{"name": "x-Installer.exe", "browser_download_url": "https://bad"}]}],
    "*-Installer.exe")
chk("跳过 prerelease", u2 == "")
u3, _ = launcher._pick_installer(
    [{"tag_name": "v9", "prerelease": False, "draft": True,
      "assets": [{"name": "x-Installer.exe", "browser_download_url": "https://bad"}]}],
    "*-Installer.exe")
chk("跳过 draft", u3 == "")

# CNB 有 → 优先用 CNB
with mock.patch.object(launcher, "_cnb_releases", return_value=CNB_RELS):
    u4, n4 = launcher._resolve_installer_asset(
        launcher.INSTALLER_REPO["onedragon-zzz"])
chk("CNB 有镜像时优先走 CNB", "cnb.cool" in u4)

# CNB 无镜像 → 回退 GitHub
with mock.patch.object(launcher, "_cnb_releases", return_value=[]), \
     mock.patch.object(launcher.urllib.request, "urlopen",
                       return_value=_Resp(FAKE_OD)):
    u5, n5 = launcher._resolve_installer_asset(
        launcher.INSTALLER_REPO["onedragon-zzz"])
chk("CNB 无镜像回退 GitHub", "github.com" in u5 or "Installer.exe" in n5)
chk("回退后仍能拿到安装包名", n5.endswith("Installer.exe"))

# CNB 异常 → 不影响，仍走 GitHub
with mock.patch.object(launcher, "_cnb_releases", side_effect=OSError("x")), \
     mock.patch.object(launcher.urllib.request, "urlopen",
                       return_value=_Resp(FAKE_OD)):
    u6, n6 = launcher._resolve_installer_asset(
        launcher.INSTALLER_REPO["onedragon-zzz"])
chk("CNB 异常不阻断(仍能取到)", n6.endswith("Installer.exe"))

# ---------- 收尾 ----------
launcher._cfg_path = _REAL_CFG
shutil.rmtree(_TMP, ignore_errors=True)

print()
print("=" * 46)
print("通过 %d / 失败 %d" % (len(OK), len(FAIL)))
if FAIL:
    print("失败项:")
    for x in FAIL:
        print("   -", x)
print("=" * 46)

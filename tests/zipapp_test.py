# -*- coding: utf-8 -*-
"""zip 分发型应用（MaaEnd 这类）安装/更新机制回归测试。"""
import os
import sys
import io
import json
import shutil
import tempfile
import zipfile
import unittest.mock as mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OK, FAIL = [], []


def chk(name, cond):
    (OK if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name)


qapp = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="zipapp_t_")

# 临时 config，绝不污染真实配置
TMP_CFG = os.path.join(TMP, "config.json")
_REAL_CFG = launcher._cfg_path
with open(_REAL_CFG(), "r", encoding="utf-8") as f:
    CFG = json.load(f)
launcher._cfg_path = lambda: TMP_CFG


def save_cfg():
    json.dump(CFG, open(TMP_CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def app_def(**over):
    a = {"key": "maa-end", "display": "MaaEnd 终末地小助手", "generic": True,
         "exe": os.path.join(TMP, "maa-end", "MaaEnd.exe").replace(os.sep, "/"),
         "release_repo": "MaaEnd/MaaEnd",
         "asset_glob": "MaaEnd-win-x86_64-*.zip",
         "app_json": "", "working": "", "pythonw": "",
         "icon": "maa-end.png", "website": "https://maaend.com/"}
    a.update(over)
    return a


# ---------- 1) 已安装版本 ----------
print("--- _zipapp_version ---")
chk("优先用 config 的 installed_version",
    launcher._zipapp_version(app_def(installed_version="v2.31.0")) == "v2.31.0")
chk("没有版本信息 → 空串", launcher._zipapp_version(app_def()) == "")

# ---------- 2) 主程序识别 ----------
print("--- _pick_main_exe ---")
d1 = os.path.join(TMP, "pick1")
os.makedirs(d1)
for n in ("vc_redist.exe", "MaaEnd.exe", "Uninstall.exe"):
    open(os.path.join(d1, n), "w").close()
chk("优先挑名字匹配 key 的 exe",
    os.path.basename(launcher._pick_main_exe(d1, "maa-end")) == "MaaEnd.exe")
d2 = os.path.join(TMP, "pick2")
os.makedirs(d2)
open(os.path.join(d2, "OnlyOne.exe"), "w").close()
chk("只有一个 exe 就用它",
    os.path.basename(launcher._pick_main_exe(d2, "zzz")) == "OnlyOne.exe")
chk("没有 exe → 空串", launcher._pick_main_exe(TMP, "zzz") == "")

# ---------- 3) 解压：摊平 / 防穿越 / 保留配置 ----------
print("--- _extract_zip_flat ---")
dest = os.path.join(TMP, "dest")
os.makedirs(os.path.join(dest, "config"))
user_cfg = os.path.join(dest, "config", "settings.json")
open(user_cfg, "w").write('{"user": "我的设置"}')

zpath = os.path.join(TMP, "pkg.zip")
with zipfile.ZipFile(zpath, "w") as zf:
    zf.writestr("MaaEnd-win-x86_64-v2.31.0/MaaEnd.exe", b"MZ fake")
    zf.writestr("MaaEnd-win-x86_64-v2.31.0/readme.md", b"hi")
    zf.writestr("MaaEnd-win-x86_64-v2.31.0/config/settings.json", '{"user":"默认"}')
    zf.writestr("../evil.txt", b"bad")          # 穿越成员，必须被过滤

chk("解压成功", launcher._extract_zip_flat(zpath, dest))
chk("顶层目录已摊平（exe 直接在 dest）",
    os.path.isfile(os.path.join(dest, "MaaEnd.exe")))
chk("穿越成员被过滤", not os.path.exists(os.path.join(dest, "evil.txt")))
chk("用户 config 保留（不被发布包覆盖）",
    open(user_cfg).read() == '{"user": "我的设置"}')
chk("新文件正常落位", os.path.isfile(os.path.join(dest, "readme.md")))

# ---------- 4) 更新检查 ----------
print("--- ZipAppCheckWorker ---")
RES = {}


def run_check(a):
    RES.clear()
    w = launcher.ZipAppCheckWorker(a)
    w.done.connect(lambda d: RES.__setitem__("d", d))
    w.failed.connect(lambda m: RES.__setitem__("f", m))
    w.run()
    return RES


with mock.patch.object(launcher, "_resolve_release_asset",
                       return_value=("https://x/pkg.zip", "pkg.zip", "v2.32.0")):
    r = run_check(app_def(installed_version="v2.31.0"))
chk("有新版本 → has_new=True / remote=v2.32.0",
    "f" not in r and r["d"]["has_new"] is True and r["d"]["remote_tag"] == "v2.32.0")

with mock.patch.object(launcher, "_resolve_release_asset",
                       return_value=("https://x/pkg.zip", "pkg.zip", "v2.31.0")):
    r2 = run_check(app_def(installed_version="v2.31.0"))
chk("同版本 → 已是最新", "f" not in r2 and r2["d"]["has_new"] is False)

with mock.patch.object(launcher, "_resolve_release_asset",
                       return_value=("https://x/pkg.zip", "pkg.zip", "v2.30.0")):
    r3 = run_check(app_def(installed_version="v2.31.0"))
chk("远端更旧 → 不提示更新", r3["d"]["has_new"] is False)

with mock.patch.object(launcher, "_resolve_release_asset",
                       return_value=("", "", "")):
    r4 = run_check(app_def(installed_version="v2.31.0"))
chk("找不到资产 → failed", "f" in r4)

# ---------- 5) 安装/更新端到端 ----------
print("--- ZipAppWorker 端到端 ---")


class _DLResp:
    def __init__(self, data):
        self._d, self._i = data, 0

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


zip_bytes = open(zpath, "rb").read()
dest2 = os.path.join(TMP, "maa-end")
os.makedirs(dest2)
os.makedirs(os.path.join(dest2, "config"))
open(os.path.join(dest2, "config", "settings.json"), "w").write('{"user": "我的设置"}')

save_cfg()
for a in CFG.get("apps", []):
    if a.get("key") == "maa-end":
        a["exe"] = app_def()["exe"]
save_cfg()

PROG, RES2 = [], {}
w = launcher.ZipAppWorker(app_def())
w.progress.connect(lambda t: PROG.append(t))
w.done.connect(lambda t: RES2.__setitem__("d", t))
w.failed.connect(lambda m: RES2.__setitem__("f", m))
with mock.patch.object(launcher, "_resolve_release_asset",
                       return_value=("https://x/pkg.zip", "pkg.zip", "v2.32.0")), \
     mock.patch.object(launcher.urllib.request, "urlopen",
                       return_value=_DLResp(zip_bytes)):
    w.run()

chk("安装完成发出版本号", RES2.get("d") == "v2.32.0")
chk("exe 解压到位",
    os.path.isfile(os.path.join(dest2, "MaaEnd.exe")))
chk("zip 临时文件已清理", not os.path.exists(os.path.join(dest2, "_update_tmp.zip")))
chk("用户 config 仍保留",
    open(os.path.join(dest2, "config", "settings.json")).read() == '{"user": "我的设置"}')

with open(TMP_CFG, "r", encoding="utf-8") as f:
    saved = [a for a in json.load(f)["apps"] if a["key"] == "maa-end"][0]
chk("exe 已写回 config", saved["exe"].endswith("MaaEnd.exe"))
chk("installed_version 已写回 config", saved["installed_version"] == "v2.32.0")

# ---------- 6) 卡片接线 ----------
print("--- 卡片 ---")
launcher.AppCard._generic_start_check = lambda self: None   # 防沙盒网络线程挂住
# 用不存在的 exe 路径构造「未安装」场景（上面的端到端测试已把 TMP/maa-end 装出来了）
card = launcher.AppCard(app_def(exe=os.path.join(TMP, "not-installed", "MaaEnd.exe")))
btns = [b.text() for b in card.findChildren(launcher.PushButton)]
chk("未安装态有「安装」按钮", "安装" in btns)
chk("未安装态有「打开官网」", "打开官网" in btns)

# _resolve_release_asset 本体：CNB 无镜像时回退 GitHub（真实逻辑，mock 网络）
FAKE_GH = [{"tag_name": "v2.31.0", "prerelease": False, "draft": False,
            "assets": [{"name": "MaaEnd-win-x86_64-v2.31.0.zip",
                        "browser_download_url": "https://github.com/x/pkg.zip"},
                       {"name": "MaaEnd-android-universal-v2.31.0.apk",
                        "browser_download_url": "https://github.com/x/apk"}]}]
with mock.patch.object(launcher, "_cnb_releases", return_value=[]), \
     mock.patch.object(launcher.urllib.request, "urlopen",
                       return_value=type("R", (), {
                           "read": lambda s: json.dumps(FAKE_GH).encode(),
                           "__enter__": lambda s: s,
                           "__exit__": lambda s, *a: False})()):
    u, n, t = launcher._resolve_release_asset("MaaEnd/MaaEnd",
                                              "MaaEnd-win-x86_64-*.zip")
chk("GitHub 兜底命中 win zip（不误取 apk）",
    n == "MaaEnd-win-x86_64-v2.31.0.zip" and t == "v2.31.0")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 46)
print("通过 %d / 失败 %d" % (len(OK), len(FAIL)))
if FAIL:
    for x in FAIL:
        print("   -", x)
print("=" * 46)

# -*- coding: utf-8 -*-
"""奇想盒「前端 exe 向下取最近可用版本」逻辑确定性单测（不联网）。

直接注入还原真实的 release 资产分布，固定本机版本，验证：
  - 选 2.4.9 / 2.4.8（无 exe）→ 前端回退到 2.4.7 的 exe
  - 选 3.0.7（无 exe）→ 前端回退到 3.0.5 的 exe
  - 选 2.4.7 / 2.4.6 / 3.1.0（有 exe）→ 直接用该版 exe
  - 按钮文案：前端动作写明「取自 X」，只列真正要装的动作
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
import launcher  # noqa: E402

# 屏蔽真实文件读取 / 网络：固定本机版本，关掉异步版本检测线程
launcher._exe_file_version = lambda *a, **k: "2.1.1"
launcher._lite_backend_version = lambda *a, **k: "2.4.9"
launcher.LiteReleaseCheckWorker.start = lambda self: None

app = QApplication([])
w = launcher.Launcher()
card = w.cards["whimbox"]

# 还原真实资产分布（实测：2.4.9/2.4.8/3.0.7 只发 whl；2.4.7/2.4.6/3.1.0/3.0.5 发 exe+whl）
assets = {
    "3.1.0": ("https://dl/whimbox_app-setup-3.1.0.exe", "https://dl/whimbox-3.1.0-py3-none-any.whl"),
    "3.0.7": ("", "https://dl/whimbox-3.0.7-py3-none-any.whl"),
    "3.0.5": ("https://dl/whimbox_app-setup-3.0.5.exe", "https://dl/whimbox-3.0.5-py3-none-any.whl"),
    "2.4.9": ("", "https://dl/whimbox-2.4.9-py3-none-any.whl"),
    "2.4.8": ("", "https://dl/whimbox-2.4.8-py3-none-any.whl"),
    "2.4.7": ("https://dl/whimbox_app-setup-2.4.7.exe", "https://dl/whimbox-2.4.7-py3-none-any.whl"),
    "2.4.6": ("https://dl/whimbox_app-setup-2.4.6.exe", "https://dl/whimbox-2.4.6-py3-none-any.whl"),
}
card._lite_assets = assets

vc = card.ver_combo
vc.clear()
for v in assets:
    vc.addItem(v)


def check(cond, msg):
    print(("[OK]   " if cond else "[FAIL] ") + msg)
    return cond


fails = []
# 1) 前端来源版本 fe_tag 必须正确
for sel, want_tag in (("3.1.0", "3.1.0"), ("3.0.7", "3.0.5"),
                      ("2.4.9", "2.4.7"), ("2.4.8", "2.4.7"),
                      ("2.4.7", "2.4.7"), ("2.4.6", "2.4.6")):
    eu, ft = card._lite_pick_frontend(sel)
    ok = (ft == want_tag) and bool(eu)
    if not check(ok, "前端来源 %s → fe_tag=%s（期望 %s, exe=%s）" % (sel, ft, want_tag, bool(eu))):
        fails.append(sel)

# 2) 按钮文案随所选版本 + 前端回退
expected = {
    "3.1.0": "更新前端到 3.1.0 + 更新后端到 3.1.0",
    "3.0.7": "更新前端（取自3.0.5）到 3.0.5 + 更新后端到 3.0.7",
    "2.4.9": "更新前端（取自2.4.7）到 2.4.7",
    "2.4.8": "更新前端（取自2.4.7）到 2.4.7 + 降级后端到 2.4.8",
    "2.4.7": "更新前端到 2.4.7 + 降级后端到 2.4.7",
    "2.4.6": "更新前端到 2.4.6 + 降级后端到 2.4.6",
}
for sel, want in expected.items():
    vc.setCurrentText(sel)
    card._lite_refresh_update_btn()
    got = card.update_btn.text()
    if not check(got == want, "按钮[%s] = %r（期望 %r）" % (sel, got, want)):
        fails.append(sel)
    # _lite_selected 必须是 4 元组且 exe 指向 fe_tag 来源
    sel4 = getattr(card, "_lite_selected", None)
    if not check(isinstance(sel4, tuple) and len(sel4) == 4,
                 "  _lite_selected 为 4 元组: %r" % (sel4,)):
        fails.append(sel + ":tuple")

# 3) 选当前版本（2.1.1）且不在 assets 里 → 已是最新
vc.clear()
vc.addItem("2.1.1（当前）")
vc.setCurrentText("2.1.1（当前）")
card._lite_refresh_update_btn()
got = card.update_btn.text()
if not check(got.startswith("已是最新"), "当前版按钮 = %r（期望以『已是最新』开头）" % got):
    fails.append("current")

# 4) 确认弹窗：标题/正文/下载目标都要与实际动作一致
#    重新灌入完整资产列表，恢复本机前端=2.1.1
launcher._exe_file_version = lambda *a, **k: "2.1.1"
vc.clear()
for v in assets:
    vc.addItem(v)

qa = {}
launcher.QMessageBox.question = staticmethod(
    lambda parent, title, body, *a, **k: qa.update(title=title, body=body)
    or launcher.QMessageBox.StandardButton.Yes)
downloads = []
card._lite_download = lambda tag, url, stage: downloads.append((tag, url, stage))
# 隔离：本测试只验证下载目标，不让 _on_lite_update 起后台 whl 预下载线程
# （否则该线程会复用被 mock 的 _download_one，向全局 tried 列表追加数据，
#  污染第 5 节的多源测速回退断言）。生产环境预下载是确认后的正确行为。
card._lite_start_whl_prefetch = lambda *a, **k: None


def run_update(sel):
    downloads.clear()
    qa.clear()
    vc.setCurrentText(sel)
    card._lite_refresh_update_btn()
    card._on_lite_update()
    return qa.get("title", ""), qa.get("body", "")


# 4a) 选 2.4.9：前端 2.1.1→2.4.7（exe 取自 2.4.7），后端被前端重置后重装回 2.4.9
t, b = run_update("2.4.9")
ok = check(t == "更新「奇想盒」：前端 2.4.7 · 后端 2.4.9", "弹窗标题[2.4.9] = %r" % t)
if not ok:
    fails.append("dlg-title-2.4.9")
ok = check("使用 2.4.7 的安装包" in b and "恢复后端到 2.4.9" in b,
           "弹窗正文[2.4.9] 讲清两个下载的原因: %r" % b[:120])
if not ok:
    fails.append("dlg-body-2.4.9")
ok = check(downloads == [("2.4.7", assets["2.4.7"][0], "exe")],
           "下载目标[2.4.9] = %r（前端 exe 用 fe_tag）" % downloads)
if not ok:
    fails.append("dl-2.4.9")
ok = check(card._lite_need_whl is True, "need_whl[2.4.9] = True（前端重置后端须重装）")
if not ok:
    fails.append("needwhl-2.4.9")

# 4a-2) 选 2.5.0（无 exe，whl 比当前后端新）：后端是「更新」不是「恢复」
assets["2.5.0"] = ("", "https://dl/whimbox-2.5.0-py3-none-any.whl")
vc.addItem("2.5.0")
t, b = run_update("2.5.0")
ok = check(t == "更新「奇想盒」：前端 2.4.7 · 后端 2.5.0", "弹窗标题[2.5.0] = %r" % t)
if not ok:
    fails.append("dlg-title-2.5.0")
ok = check("更新后端到 2.5.0" in b and "恢复" not in b,
           "弹窗正文[2.5.0] 用「更新」不用「恢复」: %r" % b[:150])
if not ok:
    fails.append("dlg-body-2.5.0")

# 4a-3) 选 2.4.8（无 exe，whl 比当前后端旧）：后端是「降级」不是「恢复」
t, b = run_update("2.4.8")
ok = check("降级后端到 2.4.8" in b and "恢复" not in b,
           "弹窗正文[2.4.8] 用「降级」不用「恢复」: %r" % b[:150])
if not ok:
    fails.append("dlg-body-2.4.8")

# 4b) 本机前端已是 2.4.7、选 2.4.7：只动后端，不下 exe
launcher._exe_file_version = lambda *a, **k: "2.4.7"
t, b = run_update("2.4.7")
ok = check(t == "更新「奇想盒」：后端 2.4.7", "弹窗标题[fe已2.4.7] = %r" % t)
if not ok:
    fails.append("dlg-title-beonly")
ok = check(downloads == [("2.4.7", assets["2.4.7"][1], "whl")],
           "下载目标[fe已2.4.7] = %r（只下 whl）" % downloads)
if not ok:
    fails.append("dl-beonly")
launcher._exe_file_version = lambda *a, **k: "2.1.1"

# 4c) 所选版本只发 exe 没发 whl（如 2.4.6 去掉 whl）：need_whl=False，前端装完即收工
assets_nowl = dict(assets)
assets_nowl["2.4.6"] = (assets["2.4.6"][0], "")
card._lite_assets = assets_nowl
t, b = run_update("2.4.6")
ok = check(t == "更新「奇想盒」：前端 2.4.6", "弹窗标题[无whl] = %r" % t)
if not ok:
    fails.append("dlg-title-nowhl")
ok = check(card._lite_need_whl is False, "need_whl[无whl] = False")
if not ok:
    fails.append("needwhl-nowhl")
card._lite_assets = assets

# 5) LiteDownloadWorker 多源测速回退（mock _probe_url / _download_one，不联网）
# 注意：绝不能用变量名 w —— 上面 w 是 Launcher 主窗口，重新绑定会 GC 掉整个 Qt
# 窗口树导致进程硬崩（exit 127）；worker 一律用 wk/w2/w3 等独立名字
gh_url = "https://github.com/nikkigallery/Whimbox/releases/download/2.4.7/whimbox_app-setup-2.4.7.exe"

wk = launcher.LiteDownloadWorker(gh_url, r"D:\tmp\_fake.exe")
cands = wk._candidates()
n_nodes = len(launcher.InstallWorker.WANZAIYUN_NODES)
base = 1 + n_nodes * 2          # 直链 + 每节点两种拼法
if not check(len(cands) in (base, base + 2),
             "候选源数 = 直链1 + %d节点×2（自定义反代配了再+2）: 实际 %d"
             % (n_nodes, len(cands))):
    fails.append("cand-count")
if not check(any(u == gh_url for _, u in cands)
             and any(u.startswith("https://gh.xmly.dev/https://github.com/") for _, u in cands)
             and any(u.startswith("https://gh.xmly.dev/github.com/") for _, u in cands),
             "候选源含直链与节点两种拼法"):
    fails.append("cand-shapes")

# 只让 3 个源探测成功：直链 1.0s / xmly 0.2s / gh-proxy.org 0.5s
URL_XMLY = "https://gh.xmly.dev/" + gh_url
URL_GHPROXY = "https://gh-proxy.org/" + gh_url


def fake_probe(url, timeout=4):
    return {gh_url: (True, 1.0, 100),
            URL_XMLY: (True, 0.2, 100),
            URL_GHPROXY: (True, 0.5, 100)}.get(url, (False, 999.0, 0))


launcher._probe_url = fake_probe
tried = []


def make_dl(ok_urls):
    def _dl(self, url):
        tried.append(url)
        if url not in ok_urls:
            raise RuntimeError("模拟失败")
    return _dl


launcher.LiteDownloadWorker._download_one = make_dl({gh_url, URL_XMLY, URL_GHPROXY})
w2 = launcher.LiteDownloadWorker(gh_url, r"D:\tmp\_fake.exe")
got = {}
w2.finished_ok.connect(lambda p: got.update(ok=p))
w2.failed.connect(lambda e: got.update(err=e))
w2.run()
if not check("ok" in got and tried == [URL_XMLY],
             "测速最快源（xmly 0.2s）优先且下载成功: tried=%r" % tried):
    fails.append("src-fastest")

# 最快源下载失败 → 回退第二快（gh-proxy.org 0.5s）
tried.clear()
launcher.LiteDownloadWorker._download_one = make_dl({gh_url, URL_GHPROXY})
w3 = launcher.LiteDownloadWorker(gh_url, r"D:\tmp\_fake.exe")
got = {}
w3.finished_ok.connect(lambda p: got.update(ok=p))
w3.failed.connect(lambda e: got.update(err=e))
w3.run()
if not check("ok" in got and tried == [URL_XMLY, URL_GHPROXY],
             "首选失败回退第二快源: tried=%r" % tried):
    fails.append("src-fallback")

# 全部下载失败 → failed 且报错带源名
tried.clear()
launcher.LiteDownloadWorker._download_one = make_dl(set())
w4 = launcher.LiteDownloadWorker(gh_url, r"D:\tmp\_fake.exe")
got = {}
w4.finished_ok.connect(lambda p: got.update(ok=p))
w4.failed.connect(lambda e: got.update(err=e))
w4.run()
if not check("err" in got and "xmly" in got["err"],
             "全部失败报错含源名: %r" % got.get("err", "")[:80]):
    fails.append("src-allfail")

print()
_rc = 0
if fails:
    print("[FAILED] 未通过: %s" % ", ".join(sorted(set(fails))))
    _rc = 1
else:
    print("[ALL OK] 前端回退逻辑全部通过")
sys.stdout.flush()
sys.stderr.flush()
os._exit(_rc)   # 避开 Qt 线程销毁污染退出码（详见 generic_app_test.py 注释）

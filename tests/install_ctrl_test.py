# -*- coding: utf-8 -*-
"""安装/更新下载的 暂停续传 + 取消 回归测试。

背景：zip 安装包动辄几百 MB（MaaEnd 309MB），却既不能暂停也不能取消——
点了安装就只能干等或强杀进程。
"""
import os
import sys
import json
import shutil
import tempfile
import threading
import unittest.mock as mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\OKApps\launcher")

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OK, FAIL = [], []


def chk(name, cond):
    (OK if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name)


qapp = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="ctrl_t_")
TMP_CFG = os.path.join(TMP, "config.json")
_REAL_CFG = launcher._cfg_path
with open(_REAL_CFG(), "r", encoding="utf-8") as f:
    CFG = json.load(f)
launcher._cfg_path = lambda: TMP_CFG
json.dump(CFG, open(TMP_CFG, "w", encoding="utf-8"), ensure_ascii=False)

DATA = bytes(range(256)) * 400          # 102400 B 测试数据


class FakeResp:
    """假 HTTP 响应：支持 Range（206 续传）与普通 200，分块 read。"""

    sent_headers = []

    def __init__(self, body, status=200):
        self._b, self._i, self.status = body, 0, status
        self.headers = {"Content-Length": str(len(body))}

    def read(self, n=-1):
        if self._i >= len(self._b):
            return b""
        chunk = self._b[self._i:] if (n is None or n < 0) \
            else self._b[self._i:self._i + n]
        self._i += len(chunk)
        return chunk

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, *a, **k):
    """按请求是否带 Range 返回 206 续传或 200 全量。"""
    hdrs = {}
    try:
        hdrs = {kk.lower(): vv for kk, vv in (req.headers or {}).items()}
    except Exception:
        hdrs = {kk.lower(): vv for kk, vv in getattr(req, "header_items", lambda: [])()}
    FakeResp.sent_headers.append(hdrs)
    rng = hdrs.get("range", "")
    if rng.startswith("bytes="):
        start = int(rng[6:].split("-")[0])
        return FakeResp(DATA[start:], status=206)
    return FakeResp(DATA, status=200)


class Ctl:
    """测试用控制器。"""

    def __init__(self):
        self.cancelled = False
        self.paused = False
        self.bytes_seen = 0

    def is_cancelled(self):
        return self.cancelled

    def is_paused(self):
        return self.paused

    def wait_resume(self):
        pass

    def on_bytes(self, done, total):
        self.bytes_seen = done


# ---------- 1) _download_chunked 基本行为 ----------
print("--- _download_chunked ---")
with mock.patch.object(launcher.urllib.request, "urlopen", side_effect=fake_urlopen):
    dest = os.path.join(TMP, "a.bin")
    c = Ctl()
    st, msg = launcher._download_chunked("https://x/a", dest, c)
    chk("正常下载完成", st == "done")
    chk("落盘字节数正确", os.path.getsize(dest) == len(DATA))
    chk("进度回调有上报", c.bytes_seen == len(DATA))

    # 取消：下到一半就停
    dest2 = os.path.join(TMP, "b.bin")
    c2 = Ctl()

    def stop_early(done, total):
        c2.bytes_seen = done
        if done >= 4096:
            c2.cancelled = True

    c2.on_bytes = stop_early
    st2, _ = launcher._download_chunked("https://x/a", dest2, c2)
    chk("中途取消 → cancelled", st2 == "cancelled")
    chk("取消时保留半截文件（由调用方清理）", os.path.isfile(dest2))

    # 暂停：保留已下部分，便于续传
    dest3 = os.path.join(TMP, "c.bin")
    c3 = Ctl()

    def pause_early(done, total):
        c3.bytes_seen = done
        if done >= 4096:
            c3.paused = True

    c3.on_bytes = pause_early
    st3, _ = launcher._download_chunked("https://x/a", dest3, c3)
    chk("中途暂停 → paused", st3 == "paused")
    partial = os.path.getsize(dest3)
    chk("暂停时已下部分留在磁盘（>0）", partial > 0)

    # 续传：带 Range 头，服务端 206，拼回完整文件
    FakeResp.sent_headers.clear()
    c4 = Ctl()
    st4, _ = launcher._download_chunked("https://x/a", dest3, c4)
    chk("续传完成", st4 == "done" and os.path.getsize(dest3) == len(DATA))
    chk("续传请求带了 Range 头",
        any(h.get("range", "").startswith("bytes=") for h in FakeResp.sent_headers))


# ---------- 2) ZipAppWorker：取消 / 暂停续传 ----------
print("--- ZipAppWorker 控制 ---")
import zipfile  # noqa: E402

zpath = os.path.join(TMP, "pkg.zip")
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("MaaEnd-win/MaaEnd.exe", b"MZ fake")
    zf.writestr("MaaEnd-win/readme.md", b"hi")
    # 塞个大文件：让下载真的分成多块，否则取消/暂停的阈值根本触发不到
    zf.writestr("MaaEnd-win/big.bin", os.urandom(300000))
zip_bytes = open(zpath, "rb").read()
print("   测试用 zip 大小:", len(zip_bytes), "字节")

dest_dir = os.path.join(TMP, "maa-end")
os.makedirs(dest_dir)


class ZipW(launcher.ZipAppWorker):
    """测试替身：把下载源固定成内存里的 zip 字节。"""
    pass


def run_worker(w, patch_bytes):
    res = {}
    w.done.connect(lambda t: res.__setitem__("d", t))
    w.failed.connect(lambda m: res.__setitem__("f", m))
    prog = []
    w.progress.connect(lambda t: prog.append(t))

    def urlopen(req, *a, **k):
        return FakeResp(patch_bytes, status=200)

    with mock.patch.object(launcher, "_resolve_release_asset",
                           return_value=("https://x/pkg.zip", "pkg.zip", "v2.32.0")), \
         mock.patch.object(launcher.urllib.request, "urlopen", side_effect=urlopen):
        w.run()
    return res, prog


def app_def(**over):
    a = {"key": "maa-end", "display": "MaaEnd", "generic": True,
         "exe": os.path.join(dest_dir, "MaaEnd.exe").replace(os.sep, "/"),
         "release_repo": "MaaEnd/MaaEnd",
         "asset_glob": "MaaEnd-win-x86_64-*.zip",
         "app_json": "", "working": "", "pythonw": "", "icon": "", "website": ""}
    a.update(over)
    return a


# 取消：下载中途 cancel → failed「已取消」+ 临时 zip 清理 + 不解压
class CancelZip(ZipW):
    def on_bytes(self, done, total):
        if done >= 1024:
            self.cancel()


w = CancelZip(app_def())
with mock.patch.object(launcher, "_download_chunked",
                       side_effect=launcher._download_chunked):
    pass
res, prog = run_worker(w, zip_bytes)
chk("取消 → 发 failed「已取消」", res.get("f") == "已取消")
chk("取消 → 不发 done", "d" not in res)
chk("取消 → 临时 zip 已清理",
    not os.path.exists(os.path.join(dest_dir, "_update_tmp.zip")))
chk("取消 → 没有解压产物", not os.path.exists(os.path.join(dest_dir, "readme.md")))

# 暂停 → 自动 resume → 装完
class PauseZip(ZipW):
    def __init__(self, app):
        super().__init__(app)
        self._did_pause = False

    def on_bytes(self, done, total):
        if not self._did_pause and done >= 512:
            self._did_pause = True
            self.pause()
            threading.Timer(0.3, self.resume).start()   # 0.3s 后自动继续


w2 = PauseZip(app_def())
res2, prog2 = run_worker(w2, zip_bytes)
chk("暂停后自动继续并完成", res2.get("d") == "v2.32.0")
chk("进度里出现过暂停提示", any("暂停" in t for t in prog2))
chk("解压产物落位", os.path.isfile(os.path.join(dest_dir, "MaaEnd.exe")))


# ---------- 3) 卡片：暂停按钮 + 取消接线 ----------
print("--- 卡片控制 ---")
launcher.AppCard._generic_start_check = lambda self: None
card = launcher.AppCard(app_def(exe=os.path.join(TMP, "nope", "MaaEnd.exe")))
chk("卡片有暂停按钮", hasattr(card, "install_pause_btn"))
chk("初始被隐藏", card.install_pause_btn.isHidden())

card._show_install_progress_ui("准备中")
# 注意：offscreen 下父窗口没显示过，isVisible() 恒为 False；
# 判断"我们有没有让它显示"要看 isHidden()（只反映显式隐藏）
chk("显示进度 UI 后暂停按钮不再隐藏", not card.install_pause_btn.isHidden())
chk("显示进度 UI 后取消按钮不再隐藏", not card.install_cancel_btn.isHidden())


class FakeW:
    """替身 worker。字段名必须和真实 worker 一致（代码读的是 _paused）。"""

    def __init__(self):
        self.canceled = False
        self._paused = False

    def cancel(self):
        self.canceled = True

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def isRunning(self):
        return False

    class _Sig:
        def disconnect(self):
            pass

    progress = _Sig()
    done = _Sig()
    failed = _Sig()


fw = FakeW()
card._installer_worker = fw
card._on_install_pause_clicked()
chk("点暂停 → worker.pause() 被调用", fw._paused is True)
chk("按钮文案变为「继续」", "继续" in card.install_pause_btn.text())
card._on_install_pause_clicked()
chk("再点 → resume，文案变回暂停",
    fw._paused is False and "暂停" in card.install_pause_btn.text())

card._on_install_cancel_clicked()
chk("取消按钮能接到 _installer_worker（新路线）", fw.canceled is True)

# 隐藏后按钮复位
card._hide_install_progress_ui()
chk("隐藏后暂停按钮被隐藏", card.install_pause_btn.isHidden())
chk("隐藏后文案复位", card.install_pause_btn.text() == "⏸ 暂停")

# ---------- 1b) 416 Range Not Satisfiable 处理 ----------
print("--- 416 处理（残留 ≥ 服务器文件）---")
import urllib.error  # noqa: E402


def _416(url):
    return urllib.error.HTTPError(url, 416, "Range Not Satisfiable", None, None)


# 场景 A：本地残留 == 服务器大小（上次下到 100% 被杀）→ 直接当下载完成
dest_a = os.path.join(TMP, "done.bin")
open(dest_a, "wb").write(DATA)
calls_a = {"head": 0, "get": 0}


def urlopen_a(req, *a, **k):
    if req.get_method() == "HEAD":
        calls_a["head"] += 1
        r = FakeResp(b"", status=200)
        r.headers = {"Content-Length": str(len(DATA))}   # HEAD 必须报真实大小
        return r
    calls_a["get"] += 1
    raise _416("https://x/a")


cA = Ctl()
with mock.patch.object(launcher.urllib.request, "urlopen", side_effect=urlopen_a):
    stA, _ = launcher._download_chunked("https://x/a", dest_a, cA)
chk("残留==远端大小 → 直接视为下载完成", stA == "done")
chk("残留文件保留（没白白重下）", os.path.getsize(dest_a) == len(DATA))

# 场景 B：本地残留大小不对（半截/别的版本）→ 删掉重下成功
dest_b = os.path.join(TMP, "bad.bin")
open(dest_b, "wb").write(DATA[:5000])       # 只有 5000 字节
calls_b = {"get": 0}


def urlopen_b(req, *a, **k):
    if req.get_method() == "HEAD":
        r = FakeResp(b"", status=200)
        r.headers = {"Content-Length": str(len(DATA))}
        return r
    calls_b["get"] += 1
    if calls_b["get"] == 1:
        raise _416("https://x/a")
    return FakeResp(DATA, status=200)


cB = Ctl()
with mock.patch.object(launcher.urllib.request, "urlopen", side_effect=urlopen_b):
    stB, _ = launcher._download_chunked("https://x/a", dest_b, cB)
chk("残留大小不符 → 删掉重下成功", stB == "done")
chk("重下后文件完整", os.path.getsize(dest_b) == len(DATA))
chk("确实重试了一次", calls_b["get"] == 2)

shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 46)
print("通过 %d / 失败 %d" % (len(OK), len(FAIL)))
if FAIL:
    for x in FAIL:
        print("   -", x)
print("=" * 46)

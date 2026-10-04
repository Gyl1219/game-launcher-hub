# -*- coding: utf-8 -*-
"""
游戏助手启动器 - 统一管理窗口（WeGame 风格游戏库）

设计原则：本窗口只做「启动器」该做的事，默认不碰原启动器的目录；但 working/ 属于
官方仓库范畴（用户已授权可写），仅在用户明确点击「应用到 working 目录」时才写入：
  - 不碰 <app>/repo（git 仓库，镜像 git 只在本启动器 repos/<key> 内）
  - <app>/working 默认只读；「应用到 working 目录」= 覆盖代码文件 + 保留运行数据，
    单次弹窗确认、先终止进程、不产生备份（用户明确不要备份，省空间）
  - <app>/app.json 只读展示；仅应用成功后才写回 current_version（清残留更新中间态）

WeGame 风格卡片：
  - 封面区（渐变底 + 游戏图标）
  - 状态徽章：未安装 / 已安装 / 运行中 / 可更新
  - 按钮：未安装 ->「安装」（打开官方下载页）；已安装 ->「▶ 启动应用」（直开本体，不再单列原版管理窗口）
  - 只读展示：版本下拉 + 版本说明（changelog，GitHub compare，失败回退 update_note）
  - 窗口内更新：点「更新到 vX」把目标版本下载到本启动器目录 repos/<key>（真实进度条，
    原启动器目录零触碰）；下载完成后可一键「应用到 working 目录」（覆盖代码、保留运行数据、
    更新 app.json 当前版本），或交回「原版管理窗口」由原启动器完成

已收录游戏助手：
  - 异环 (ok-nte)
  - 鸣潮 (ok-ww)
  - 终末地 (ok-end-field) —— 未安装时显示「安装」，点击打开官方下载页
"""

import sys
import os
import re
import json
import fnmatch
import struct
import base64
import stat as _stat
import ctypes
import subprocess
import traceback
import threading
import urllib.request
import urllib.error
import urllib.parse
import zipfile
import shutil
import time

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl, QPoint
from PySide6.QtGui import QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QHBoxLayout, QVBoxLayout, QGridLayout,
    QMessageBox, QLabel, QScrollArea, QTextEdit, QProgressBar, QProgressDialog,
    QStackedWidget, QCheckBox, QFileDialog,
)
from qfluentwidgets import (
    setTheme, Theme, CardWidget, IconWidget, StrongBodyLabel,
    CaptionLabel, PushButton, ComboBox, FluentIcon, IndeterminateProgressBar,
    LineEdit, InfoBar, InfoBarPosition, RoundMenu, Action,
    TransparentToolButton,
)


# ===== 无需自提权（见下方说明） =====
# 早期版本曾在此处用 runas 重启自己（弹 UAC）以管理员身份运行，因为当时 changelog
# 走 spawn ok-*.exe 的 PyAppify API，而 ok-*.exe 的 manifest 要求管理员（740）。
# 现已改为直接读本地 git 仓库（GitVersionFetcher），只读本地文件、不需要管理员，
# 故删除自提权逻辑：既消除每次启动的 UAC 弹窗 + 命令行闪烁，也不再无谓地重启进程。

# 启动器自身版本（打包版 / 源码版共用）。发新版时只改这一处，
# 显示在「设置」页页脚，便于报 bug 时说清自己在跑哪个版本。
APP_VERSION = "0.2.3"

# ===== 应用配置（从 config.json 加载，避免硬编码路径） =====
# 打包后（PyInstaller）两个目录必须分开算，否则图标全找不到：
#   APP_DIR = exe 所在目录  → 放用户数据（config.json / repos / logs / .cache）
#   RES_DIR = sys._MEIPASS  → 放随包只读资源（assets 图标、config.example.json）
# 源码直接运行时两者都是脚本所在目录，行为与以前完全一致。
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = RES_DIR = os.path.dirname(os.path.abspath(__file__))

LAUNCHER_DIR = APP_DIR
# 图标统一使用 ok-script 官网 project-icons（已缓存到启动器自身 assets 目录），
# 各 app 的 app.json / working 默认只读展示；「应用到 working 目录」为用户主动授权的写入动作。
ASSETS_DIR = os.path.join(RES_DIR, "assets")
# 独立镜像仓库目录：clone / fetch  ️只发生在这里，原启动器的 repo/ 完全不碰。
# 目录结构：LAUNCHER_REPOS_DIR/<key>/  （即一份独立的 git 仓库）
REPOS_DIR = os.path.join(LAUNCHER_DIR, "repos")
# GitHub 仓库对照表：key → (owner, repo)。changelog 数据源走这里。
# 之前用 git log -1 --format=%B <tag> 取 tag commit message 作为「版本说明」，
# 但 squash merge 会把上一版本到当前版本之间的所有 commit 累积到一个 commit message 里
# （如 v3.6.6-beta.1 显示几十条 commit），跟 GitHub release 页那种「作者手工编辑的简洁
# 更新日志」完全对不上。这里改成 GitHub releases API 拿 release body 里 ### 更新日志 段。
GITHUB_RELEASE_REPO = {
    "ok-nte":      ("BnanZ0",      "ok-nte"),
    "ok-ww":       ("ok-oldking",   "ok-wuthering-waves"),
    "ok-end-field": ("AliceJump",   "ok-end-field"),
    # lite 助手同样走 GitHub Releases 检测更新：奇想盒的 App 安装包（whimbox_app-setup-
    # <ver>.exe）自 3.1.0 起随主仓库 Whimbox 一起发布，版本号与 Python 后端统一为 3.x
    "whimbox":     ("nikkigallery", "Whimbox"),
}

# 支持「启动器内首次安装」的应用：key -> (owner, repo, 安装包文件名 glob)
#
# 与上面的 GITHUB_RELEASE_REPO（**更新检测**用）是两回事：那边找的是更新包，
# 这里找的是**从零安装**用的官方安装程序。lite / generic 两张卡的未安装态靠这个
# 才能真装起来，否则只能给个「打开官网」把人打发走。
#
# 两个 glob 都是**实测核对过**的（不是猜的仓库/文件名）：
#   whimbox   -> whimbox_app-setup-3.1.0.exe                      （约 119 MB）
#   onedragon -> ZenlessZoneZero-OneDragon-v2.5.2-Installer.exe   （约 102 MB）
# 刻意只取**正式版** release：测试版安装包可能不完整，首次安装不该拿它。
INSTALLER_REPO = {
    "whimbox":       ("nikkigallery", "Whimbox",
                      "whimbox_app-setup-*.exe"),
    "onedragon-zzz": ("OneDragon-Anything", "ZenlessZoneZero-OneDragon",
                      "*-Installer.exe"),
}
# 7-Zip 便携版持久化目录（与 install_root/_dl_<key>/ 解耦）。
# 旧 bug：7z 装到 tmp/7zportable/，run() 成功后 shutil.rmtree(tmp) 把它一起删了，
# 下次 install → 系统无 7z → 又自动下 1.6MB → 又被下次 rmtree 删，无限循环。
# 改成放 LAUNCHER_DIR/.cache/7zportable/，rmtree(tmp) 碰不到,一次装好永久复用。
LAUNCHER_7Z_DIR = os.path.join(LAUNCHER_DIR, ".cache", "7zportable")
# release 查询缓存目录：GitHub API（api.github.com/repos/.../releases/latest）未登录限 60 次/小时，
# 反复安装/刷新会很快打满 → 403 rate limit。把查询结果落盘缓存（带 TTL），
# 同一次会话内重试、跨次重启都直接读缓存，几乎不再打 API。
LAUNCHER_CACHE_DIR = os.path.join(LAUNCHER_DIR, ".cache")
RELEASE_CACHE_TTL = 30 * 60  # 30 分钟


def load_apps():
    """从 config.json 加载应用列表，并将相对路径拼成绝对路径。

    config.json 里的 exe/app_json/working/pythonw/icon 都相对于 install_root，
    这样他人 clone 后只需改 config.json 的 install_root 即可，无需改动代码。
    """
    cfg_path = os.path.join(LAUNCHER_DIR, "config.json")
    # 首次运行（典型场景：打包版解压后直接双击 exe）还没有 config.json —— 从随包带的
    # config.example.json 复制一份当初始配置，免得一启动就抛错把人劝退。
    if not os.path.isfile(cfg_path):
        example_path = os.path.join(RES_DIR, "config.example.json")
        try:
            if os.path.isfile(example_path):
                shutil.copyfile(example_path, cfg_path)
        except Exception:
            pass
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        raise RuntimeError(f"读取配置文件失败: {cfg_path} ({e})")

    root = cfg.get("install_root", "D:/OKApps").replace("/", os.sep)
    apps = []
    for a in cfg.get("apps", []):
        def absify(p):
            if not p:
                return ""
            if os.path.isabs(p):
                return p
            return os.path.join(root, p.replace("/", os.sep))
        app = dict(a)
        app["install_root"] = root
        app["exe"] = absify(a.get("exe", ""))
        app["app_json"] = absify(a.get("app_json", ""))
        app["working"] = absify(a.get("working", ""))
        app["pythonw"] = absify(a.get("pythonw", ""))
        # icon：先用配置路径解析，文件不存在则回退到启动器自带 assets 目录下的同名文件
        # （注意：图标是跟启动器打包走的，始终在 ASSETS_DIR，不应依赖 install_root 下的 assets）
        icon = a.get("icon", "")
        if icon:
            cand = absify(icon) if (os.path.isabs(icon) or "/" in icon) else \
                os.path.join(ASSETS_DIR, icon)
            app["icon"] = cand if os.path.isfile(cand) else \
                os.path.join(ASSETS_DIR, f"{a.get('key', 'app')}.png")
        else:
            app["icon"] = os.path.join(ASSETS_DIR, f"{a.get('key', 'app')}.png")
        apps.append(app)
    return apps


APPS = load_apps()


def ver_key(v):
    """把版本字符串转成可排序的元组，正式版排在 pre/beta/alpha/rc 前面。

    例: v1.3.4 -> (1,3,4,0,0)；v1.3.4-beta.1 -> (1,3,4,1,1)
    """
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", v or "")
    nums = [int(m.group(i)) if m and m.group(i) else 0 for i in (1, 2, 3)]
    if any(k in v for k in ("beta", "pre", "alpha", "rc", "-b")):
        pre = 0  # 预发布：排在正式版后面（正式版用 999）
        pm = re.search(r"(?:beta|pre|alpha|rc)[.\-]?(\d*)", v)
        prenum = int(pm.group(1)) if pm and pm.group(1) else 0
    else:
        pre = 999  # 正式版：永远排在预发布前面
        prenum = 0
    return (nums[0], nums[1], nums[2], pre, prenum)


def is_prerelease(v):
    """判断版本是否为预发布（beta/alpha/rc/pre）。"""
    return any(k in (v or "").lower() for k in ("beta", "alpha", "rc", "pre"))


def compare_version(a, b):
    """比较两个版本：a > b 返回 1，a < b 返回 -1，相等返回 0。"""
    ka, kb = ver_key(a), ver_key(b)
    return (ka > kb) - (ka < kb)


def format_version_display(version, current):
    """生成下拉框显示文本：vX.Y.Z 正式版（升级/降级/当前）。

    主卡片 ComboBox 和 UpdateDialog 复用此函数，保证标记一致。
    """
    type_label = "测试版" if is_prerelease(version) else "正式版"
    cmp = compare_version(version, current) if current else 0
    if version == current:
        action_label = "当前"
    elif cmp > 0:
        action_label = "升级"
    elif cmp < 0:
        action_label = "降级"
    else:
        action_label = ""
    if action_label:
        return f"{version} {type_label}（{action_label}）"
    return f"{version} {type_label}"


def parse_repo_from_git_url(git_url):
    """从 git_url 解析 owner/repo；支持 GitHub 与 cnb.cool（后者按同路径试 GitHub）。"""
    for pat in [
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        r"https?://cnb\.cool/([^/]+)/([^/]+?)(?:\.git)?/?$",
    ]:
        m = re.match(pat, git_url)
        if m:
            return m.group(1), m.group(2)
    return None, None


# ⚠️ 重要：cnb.cool 源现在**直接走 cnb.cool 自己的 Gitea 兼容 API** 拉 changelog，
# 不再映射到 GitHub。原因：某些 cnb 镜像在 GitHub 上是独立仓库（名字不同），
# 强制映射会拉到错误内容。典型例子：鸣潮 China 源 cnb 仓库名为 `ok-ww-update2`，
# 而 GitHub 对应仓库是 `ok-ww-update`（无 2），两者更新历史不同——映射到 GitHub
# 后 changelog 内容与原启动器（读 cnb 自身）对不上。
# 异环的 cnb 仓库 `BnanZ0/ok-nte-update` 恰好与 GitHub 同名同内容，是特例，
# 此前误以为是普遍规律。故此处映射表留空，cnb 源一律用 cnb API。
CNB_GITHUB_REPO_MAP = {}


def resolve_github_repo(owner, repo):
    """若 cnb.cool 源有已知的 GitHub 真实仓库，返回真实 owner/repo；否则原样返回。"""
    return CNB_GITHUB_REPO_MAP.get((owner, repo), (owner, repo))


def _normalize_tag(tag):
    """去掉 git peeled ref 后缀 '^{}'，避免 v3.5.28^{} 这种脏 tag 混进列表。"""
    if not tag:
        return tag
    if tag.endswith("^{}"):
        tag = tag[:-3]
    return tag


def fetch_versions_from_git_url(git_url):
    """从 git 远程只读拉取所有 tags，按版本号从新到旧排序。失败返回空列表。"""
    if not git_url:
        return []

    owner, repo = parse_repo_from_git_url(git_url)

    # 1) GitHub API 分页拉全量 tags（最快、最完整；cnb.cool 按同路径走 GitHub）
    if owner and repo:
        tags = []
        try:
            for page in range(1, 11):  # 最多 10 页 = 1000 个版本
                url = f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=100&page={page}"
                req = urllib.request.Request(url, headers={"User-Agent": "ok-launcher/1.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if not data:
                    break
                tags.extend(_normalize_tag(t["name"]) for t in data if "name" in t)
            if tags:
                return sorted(tags, key=ver_key, reverse=True)
        except Exception:
            pass

    # 2) dulwich 兜底（通吃 GitHub / cnb.cool 等 smart HTTP）
    try:
        from dulwich.client import get_transport_and_path

        client, path = get_transport_and_path(git_url)
        refs = client.get_refs(path)
        tags = []
        for ref_name in refs.keys():
            if isinstance(ref_name, bytes):
                ref_name = ref_name.decode("utf-8", "replace")
            if ref_name.startswith("refs/tags/"):
                tag = _normalize_tag(ref_name.replace("refs/tags/", ""))
                if tag and tag not in tags:
                    tags.append(tag)
        if tags:
            return sorted(tags, key=ver_key, reverse=True)
    except Exception:
        pass

    return []


def fetch_changelog(owner, repo, base, head, limit=10):
    """用 GitHub compare API 拉取 base...head 之间的 commits 列表（只读）。

    返回格式化的多行文本；失败抛异常。limit 控制显示最近 N 条。
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base}...{head}"
    req = urllib.request.Request(url, headers={"User-Agent": "ok-launcher/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    commits = data.get("commits", [])
    lines = []
    for c in reversed(commits):  # 从新到旧，和原版窗口一致
        msg = c.get("commit", {}).get("message", "").split("\n")[0].strip()
        author = c.get("commit", {}).get("author", {}).get("name", "")
        if not author:
            author = c.get("author", {}).get("login", "") or ""
        if msg:
            lines.append(f"• {msg}" + (f"（{author}）" if author else ""))
    if not lines:
        return "该版本暂无更新说明。"
    return "\n".join(lines[:limit])


def fetch_changelog_cnb(owner, repo, base, head, limit=10):
    """用 cnb.cool 的 Gitea 兼容 API 拉取 head 版本附近的更新 commits（只读）。

    对应 China 源：changelog 直接来自 cnb 镜像仓库本身（与原启动器一致），
    不再映射到 GitHub（否则会拉到不同仓库的内容）。cnb.cool 的 commits API 形如
    /api/v1/repos/{owner}/{repo}/commits?sha={head}&limit={n}，返回从 head 往前
    的 commit 列表（Gitea 格式），正好对应「目标版本的更新说明」。
    """
    sha = urllib.parse.quote(head, safe="")
    url = (f"https://cnb.cool/api/v1/repos/{owner}/{repo}/commits"
           f"?sha={sha}&limit={limit}")
    req = urllib.request.Request(url, headers={"User-Agent": "ok-launcher/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    lines = []
    for c in data:
        msg = c.get("commit", {}).get("message", "").split("\n")[0].strip()
        author = c.get("author", {}).get("login", "") or ""
        if not author:
            author = c.get("commit", {}).get("author", {}).get("name", "")
        if msg:
            lines.append(f"• {msg}" + (f"（{author}）" if author else ""))
    if not lines:
        return "该版本暂无更新说明。"
    return "\n".join(lines[:limit])


class ChangelogFetcher(QThread):
    """后台拉取 changelog（只读，不影响任何本地文件）。

    根据 git_url 来源分发：
      - cnb.cool 源 → cnb.cool 自身 Gitea API（与原启动器一致，不映射到 GitHub）
      - 其它（github.com 等）→ GitHub compare API
    """
    fetched = Signal(str)
    failed = Signal(str)

    def __init__(self, git_url, owner, repo, base, head, parent=None):
        super().__init__(parent)
        self.git_url = git_url
        self.owner = owner
        self.repo = repo
        self.base = base
        self.head = head

    def run(self):
        try:
            if self.git_url.rstrip("/").startswith("https://cnb.cool/"):
                text = fetch_changelog_cnb(self.owner, self.repo, self.base, self.head)
            else:
                text = fetch_changelog(self.owner, self.repo, self.base, self.head)
            self.fetched.emit(text)
        except Exception as e:
            self.failed.emit(str(e))


def calculate_update_notes(update_notes, current_version, target_version):
    """复刻 PyAppify 的 pyappify.calculate_update_notes：

    从版本列表中取 current → target（含两端）区间内每个版本的 update_note，
    拼接成更新说明。版本列表顺序须与 ``--get-version-list`` 返回一致。
    """
    if not isinstance(update_notes, list):
        return []
    versions = [item for item in update_notes
                if isinstance(item, dict) and item.get("version")]

    def normalize(version):
        return str(version or "").lstrip("v")

    def find_index(version):
        normalized = normalize(version)
        for index, item in enumerate(versions):
            if normalize(item["version"]) == normalized:
                return index
        return None

    target_index = find_index(target_version)
    if target_index is None:
        return []

    current_index = find_index(current_version)
    if current_index is None:
        selected = versions[target_index:]
    else:
        first = min(current_index, target_index)
        last = max(current_index, target_index)
        selected = versions[first:last + 1]

    notes = []
    for item in selected:
        raw = item.get("update_note") or []
        if isinstance(raw, list):
            notes.extend(str(n) for n in raw)
        else:
            notes.append(str(raw))
    return notes


class GitVersionFetcher(QThread):
    """后台从各游戏**本地 git 仓库**读取「版本 + 更新说明」列表。

    为什么不用原启动器的 PyAppify ``--get-version-list`` exe API：
    ok-ww / ok-nte 是 Tauri **单实例**应用，该 API 只能在**已运行的实例内部**被处理
    （单实例插件把参数转发给运行中的实例，再由它的 PyAppify 运行时写回 response 文件）。
    从外部 spawn exe 永远进不了这个模式——要么变成 GUI 首实例（弹出原启动器界面），
    要么参数被单实例插件丢弃，导致 response 为空。证据见 ``ok-ww/logs/app.2026-08-20``：
    我们 spawn 的 ok-ww.exe 直接以 ``running with tauri ui`` 启动成完整 GUI，全程无视
    ``--get-version-list`` 参数。

    因此改为直接读本地仓库：tags -> 版本、tag 提交信息 -> 更新说明，
    这正是 PyAppify 自身用的同一份数据（已用 ``git log -1 --format=%B <tag>`` 与原启动器
    ``get_update_notes`` 输出逐字核对一致，如 ok-ww v3.6.4 的 11 条说明完全吻合）。
    不需要 git 在 PATH——优先用 WorkBuddy 自带的 PortableGit（用户机器位于
    ``~/.workbuddy/binaries/PortableGit``），找不到再回退 app.json 缓存。
    只读本地文件、读本地仓库，**绝不启动任何 exe**，因此不会再弹出原启动器。
    """
    fetched = Signal(list)   # list of {version, update_note}
    failed = Signal(str)

    def __init__(self, exe_path, parent=None):
        super().__init__(parent)
        self.exe_path = exe_path

    @staticmethod
    def _find_git():
        import glob, shutil
        base = os.path.join(os.path.expanduser("~"), ".workbuddy",
                            "binaries", "PortableGit", "versions")
        cands = []
        # PortableGit 版本目录：versions/<ver>/mingw64/bin/git.exe
        cands += glob.glob(os.path.join(base, "*", "mingw64", "bin", "git.exe"))
        which = shutil.which("git")
        if which:
            cands.append(which)
        for p in (r"C:\Program Files\Git\bin\git.exe",
                  r"C:\Program Files (x86)\Git\bin\git.exe"):
            if os.path.isfile(p):
                cands.append(p)
        for c in cands:
            if os.path.isfile(c):
                return c
        return None

    def _emit_cached(self, app_json):
        """git 不可用 / 仓库缺失时的兜底：用 app.json 的 available_versions +
        当前版本 update_note，保证下拉框可用、绝不报“获取失败”。"""
        try:
            with open(app_json, "r", encoding="utf-8") as f:
                aj = json.load(f)
            av = aj.get("available_versions") or []
            cur = aj.get("current_version")
            cur_note = aj.get("update_note") or []
            items = []
            for v in av:
                notes = cur_note if v == cur else []
                items.append({"version": v, "update_note": notes})
            if items:
                self.fetched.emit(items)
                return
        except Exception:
            pass
        self.failed.emit("无法读取版本信息（git 不可用且 app.json 缓存缺失）")

    def run(self):
        exe = self.exe_path
        try:
            key = os.path.splitext(os.path.basename(exe))[0]
            app_root = os.path.dirname(exe)
            repo = os.path.join(app_root, "data", "apps", key, "repo")
            app_json = os.path.join(app_root, "data", "apps", key, "app.json")
            git = self._find_git()
            if not git or not os.path.isdir(repo):
                self._emit_cached(app_json)
                return
            # 版本顺序以 app.json 的 available_versions 为准（最新在前），与 get_version_list 一致
            order = []
            try:
                with open(app_json, "r", encoding="utf-8") as f:
                    order = (json.load(f).get("available_versions") or [])
            except Exception:
                order = []
            # 先增量 fetch 新 tags（10 秒超时、失败容忍），避免本地 tag 陈旧漏报新版本。
            # 不用 --depth=1：是 fetch 不是 clone，不裁剪历史，不影响 PyAppify 自己 checkout 旧版本。
            try:
                subprocess.run([git, "-C", repo, "fetch", "--tags", "origin"],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                pass
            out = subprocess.run([git, "-C", repo, "tag"],
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace",
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if out.returncode != 0:
                self._emit_cached(app_json)
                return
            tags = [t.strip() for t in out.stdout.splitlines() if t.strip()]
            tag_set = set(tags)
            ordered = [v for v in order if v in tag_set]
            extra = [t for t in tags if t not in set(ordered)]
            ordered += sorted(extra, reverse=True)   # 仓库有但 app.json 未列的，按版本倒序补在后面
            # 优先用 GitHub releases API 的 release body（作者手工编辑的简洁更新日志）；
            # 拉失败 / dict 为 None / dict 没这个 tag → fallback 到 git log -1 --format=%B <tag>。
            # 见 parse_release_changelog / fetch_release_changelogs 注释：squash merge 会把累积
            # commit 全堆到 tag commit message 里，跟 release 页的简洁 changelog 对不上。
            changelog_map = None
            gh_repo = GITHUB_RELEASE_REPO.get(key)
            if gh_repo:
                changelog_map = fetch_release_changelogs(key, gh_repo[0], gh_repo[1])
            items = []
            for v in ordered:
                notes = changelog_map.get(v) if changelog_map else None
                if not notes:
                    msg = subprocess.run([git, "-C", repo, "log", "-1",
                                          "--format=%B", v],
                                         capture_output=True, text=True,
                                         encoding="utf-8", errors="replace",
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if msg.returncode != 0:
                        notes = []
                    else:
                        notes = [ln.strip() for ln in msg.stdout.splitlines()
                                 if ln.strip()]
                items.append({"version": v, "update_note": notes})
            if not items:
                self._emit_cached(app_json)
                return
            # 落盘一份原始结果（覆盖写），方便核对，也便于排查与 git 上游的差异
            try:
                _ld = os.path.join(LAUNCHER_DIR, "logs")
                os.makedirs(_ld, exist_ok=True)
                with open(os.path.join(_ld, "versions-{}.json".format(key)),
                          "w", encoding="utf-8") as _f:
                    json.dump(items, _f, ensure_ascii=False, indent=1)
            except Exception:
                pass
            self.fetched.emit(items)
        except Exception as e:
            self.failed.emit(str(e))


def parse_release_changelog(body):
    """从 GitHub release body 提取「更新日志」段，过滤掉下载说明/镜像链接等无关段落。

    body 形如：
        ### 更新日志 v3.6.5 -> v3.6.6-beta.1:
          * fix(workshop): sanitize team URLs ... (ok-oldking)
        ### 下载包说明
          * [ok-ww-win32-China-setup.exe](...)

    只返回首个「### 更新日志」段下的非空行列表，便于与 git log 输出格式对齐。
    """
    if not body:
        return []
    out, in_log = [], False
    for ln in body.splitlines():
        s = ln.strip()
        if not in_log:
            if s.startswith("### 更新日志"):
                in_log = True
            continue
        if s.startswith("### "):
            break
        out.append(ln.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def fetch_release_changelogs(key, owner, repo):
    """拉 GitHub releases list API，按 tag_name → 解析后的 changelog 列表 建 dict。

    带本地文件缓存（TTL=RELEASE_CACHE_TTL=30 分钟），避免未登录 60 次/小时限流。
    - 缓存命中未过期 → 直接返回缓存的 dict，零 API 请求；
    - 打 list API 成功 → 解析所有 release body，写回缓存；
    - 失败（网络/限流/解析）→ 用旧缓存兜底，没有就返回 None（调用方 fallback 到 git log）。

    返回 dict 形如 {"v3.6.6-beta.1": ["* fix(workshop): ..."]}；None 表示完全失败。
    """
    cache_file = os.path.join(LAUNCHER_CACHE_DIR, f"changelogs_{owner}_{repo}.json")
    os.makedirs(LAUNCHER_CACHE_DIR, exist_ok=True)
    # 1) 缓存命中（带 _fetched_at TTL）
    if os.path.isfile(cache_file):
        try:
            cached = json.load(open(cache_file, encoding="utf-8"))
            ts = cached.get("_fetched_at", 0)
            if (time.time() - ts) < RELEASE_CACHE_TTL:
                return cached.get("map", {}) or {}
        except Exception:
            pass
    # 2) 打 list API（per_page=100，覆盖最近所有 release）
    api = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=100"
    req = urllib.request.Request(api, headers={"User-Agent": "WorkBuddy-OKLauncher"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
    except Exception:
        # 失败兜底：用旧缓存
        if os.path.isfile(cache_file):
            try:
                cached = json.load(open(cache_file, encoding="utf-8"))
                return cached.get("map", {}) or {}
            except Exception:
                pass
        return None
    out = {}
    for rel in data or []:
        tag = rel.get("tag_name", "")
        body = rel.get("body", "")
        parsed = parse_release_changelog(body)
        if tag and parsed:
            out[tag] = parsed
    # 3) 写回缓存（即便空 map 也写，避免每启动器都重打 API）
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"_fetched_at": time.time(), "map": out},
                      f, ensure_ascii=False)
    except Exception:
        pass
    return out


def parse_git_progress(line):
    """从 dulwich / git 进度文本解析出百分比（取最后一个 N%）。无则 -1。"""
    if isinstance(line, bytes):
        line = line.decode("utf-8", "replace")
    pct = -1
    for m in re.finditer(r"(\d+)%", line):
        pct = int(m.group(1))
    return pct, (line or "").strip()


def ensure_mirror(key, git_url, target_tag=None, progress_cb=None):
    """在 LAUNCHER_REPOS_DIR/<key> 维护一份独立镜像仓库。

    只写启动器自己的目录，原启动器的 repo/working/app.json 完全不碰。
    首次 clone，之后增量 fetch；可选 checkout 到 target_tag。返回本地仓库目录。
    """
    repo_dir = os.path.join(REPOS_DIR, key)
    os.makedirs(repo_dir, exist_ok=True)
    from dulwich import porcelain
    from dulwich.repo import Repo
    from dulwich.client import get_transport_and_path

    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        porcelain.clone(git_url, repo_dir, progress=progress_cb)
    else:
        repo = Repo(repo_dir)
        try:
            client, path = get_transport_and_path(git_url)
            client.fetch(path, repo, progress=progress_cb)
        except Exception:
            # 增量 fetch 失败不致命：本地已有旧镜像，仍可 checkout 已有 tag
            pass
    if target_tag:
        # 2026-09-07 修复（「app.json 写 v3.6.7、实际代码还是 v3.6.4」假版本号事故的
        # 另一半根因）：dulwich 的 porcelain.checkout 对 **tag 名** 支持有坑，常常静默
        # 失败——实测表现为 .git 有 146MB、工作区却 0 个文件。而原来的
        # `except Exception: pass` 把失败吞掉，函数照常返回，调用方以为已经切到目标版本，
        # 于是后面 _sync_repo_to_working 同步 0 个文件、app.json 却被写成目标版本。
        #
        # 现改为：
        #   ① 优先用系统 git（PortableGit，_find_git 已验证可用）——对 tag/checkout 语义最可靠
        #   ② 拿不到 git 才回退 dulwich
        #   ③ 无论走哪条路，**失败必须抛异常**，让 MirrorUpdater.failed 把错误显示给用户，
        #      绝不静默返回（静默 = 后面同步 0 文件 = 写假版本号）
        git = None
        try:
            git = GitVersionFetcher._find_git()
        except Exception:
            git = None
        if git:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            # 先确保目标 tag 在本地（clone 时未必把 tag 带全）
            try:
                subprocess.run(
                    [git, "-C", repo_dir, "fetch", "--tags", "origin"],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=60, creationflags=flags)
            except Exception:
                pass
            r = subprocess.run(
                [git, "-C", repo_dir, "checkout", "-f", target_tag],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=60, creationflags=flags)
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip()
                raise RuntimeError(
                    f"切换到目标版本 {target_tag} 失败：{err}\n"
                    f"仓库：{repo_dir}\n"
                    f"已中止更新，不会修改版本号。"
                )
        else:
            # 无系统 git 时回退 dulwich；这里不 try/except，失败即抛出，同样不静默
            repo = Repo(repo_dir)
            porcelain.checkout(repo, target_tag, force=True)
    return repo_dir


def _probe_url(url, timeout=4):
    """对单个候选下载源做「零流量探测」，返回 (ok, latency_s, content_length)。

    ok=False 表示超时 / 非 200/206 / 连不上，调用方直接跳过。

    零流量策略（彻底消除「下完了又下」的 bug）：
    1) 优先 HEAD 请求——只收响应头，完全不收 body，零字节浪费；
    2) 若源不支持 HEAD（返回 405/400 等），回退 Range: bytes=0-0 且只读 1 字节即断，
       最多白收 1 个 TCP 窗口（约几十 KB），远小于旧逻辑（旧逻辑 Range 0-131071 会
       把不支持 Range 的源整个文件推过来，等于每次测速白下完整安装包）。
    排序以「延迟最低」为准（就近 CDN 即最快），不再用实测吞吐。
    """
    # 1) HEAD：零 body
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": "WorkBuddy-OKLauncher"},
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status not in (200, 206):
                raise urllib.error.HTTPError(url, r.status, "head", r.headers, None)
            latency = time.time() - t0
            cl = int(r.headers.get("Content-Length") or 0)
            return (True, latency, cl)
    except urllib.error.HTTPError:
        # 2) 回退 Range 0-0（极少数只支持 GET 的源）
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "WorkBuddy-OKLauncher",
                    "Range": "bytes=0-0",
                },
            )
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status not in (200, 206):
                    return (False, 999.0, 0)
                r.read(1)  # 只读 1 字节即断
                latency = time.time() - t0
                cl = int(r.headers.get("Content-Length") or 0)
                return (True, latency, cl)
        except Exception:
            return (False, 999.0, 0)
    except Exception:
        return (False, 999.0, 0)


# ===== Mirror酱（MirrorChyan）加速源 =====
# 官方 API：GET https://mirrorchyan.com/api/resources/{rid}/latest
#   ?os=win&arch=x64&channel=stable&cdk=<CDK>&user_agent=<来源标识>&current_version=<当前版本>
# 成功返回 {code:0, data:{version_name, url, release_note}}，其中 url 是带时效的直链。
#
# 关键行为（对接时必须知道，否则会误判）：
#   - 没填 CDK / CDK 无效 / 该 rid 不存在 / 无新版本 → code!=0 或 data.url 为空
#     → 统一返回 None，让调用方回退万载云 / cnb / GitHub 直链，绝不因此报错
#   - 官方文档明确：即使不填 CDK 也建议用它查版本（连通性比 GitHub 好），
#     只是不返回加速直链。所以「查版本」和「拿直链」要分开用。
MIRRORCHYAN_API = "https://mirrorchyan.com/api/resources/{rid}/latest"

# 各项目在 Mirror酱 的资源 ID（rid），取自各项目官方 README 链接里带的 rid。
# 用户可在 config.json 的 mirrorchyan_res_ids 里覆盖或补充（例如给启动器自己配一个）。
# 注意：rid 不一定等于 launcher 的 key（如鸣潮 key=ok-ww 但 rid=okww）。
MIRRORCHYAN_RIDS = {
    "ok-nte": "ok-nte",
    "ok-ww": "okww",
    "ok-end-field": "ok-end-field",
}


def _load_cfg_safe():
    """读 config.json，任何异常都返回 {}（供下载源这类「可有可无」的配置用）。"""
    try:
        with open(os.path.join(LAUNCHER_DIR, "config.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def mirrorchyan_rid_for(key):
    """取某项目在 Mirror酱 的 rid。

    优先级：config.json 的 mirrorchyan_res_ids[key] > 内置 MIRRORCHYAN_RIDS > ""
    返回 "" 表示未配置，调用方应跳过 Mirror酱 候选源。
    """
    try:
        cfg = _load_cfg_safe()
    except Exception:
        cfg = {}
    override = cfg.get("mirrorchyan_res_ids") or {}
    if isinstance(override, dict):
        rid = str(override.get(key) or "").strip()
        if rid:
            return rid
    return MIRRORCHYAN_RIDS.get(key, "")


# ===== 首次安装：官方安装包定位 / 下载 / 装后搜索 =====

def _cfg_path():
    return os.path.join(LAUNCHER_DIR, "config.json")


def _save_app_field(key, field, value):
    """把某个 app 的字段写回 config.json（exe / installed_version / …）。

    注意：exe 这类路径统一存正斜杠；版本号原样存。
    """
    try:
        with open(_cfg_path(), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        hit = False
        for a in cfg.get("apps", []):
            if a.get("key") == key:
                a[field] = str(value).replace("\\", "/")
                hit = True
                break
        if not hit:
            return False
        with open(_cfg_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _save_app_exe(key, exe_path):
    """写回 exe 路径。

    为什么必须写回：config 里的 exe 是**预置**路径，而安装包装到哪由用户决定
    （一条龙可能装 D:\\DZZZ-OD，也可能装别的盘）。不落盘的话，这次能认出来，
    下次启动卡片又变回「未安装」——等于白装一次。
    """
    return _save_app_field(key, "exe", exe_path)


def _pick_installer(rels, pattern):
    """在 releases 列表里找最新**正式版**中匹配 glob 的安装包 → (url, name)。"""
    for rel in rels:
        if rel.get("prerelease") or rel.get("draft"):
            continue
        for a in (rel.get("assets") or []):
            name = a.get("name", "")
            if not fnmatch.fnmatch(name, pattern):
                continue
            # CNB 同时存在拼错的 brower_download_url 与正确的 browser_download_url；
            # 另有 url 字段指向 api.cnb.cool（未授权会 401），不能用。
            url = (a.get("browser_download_url")
                   or a.get("brower_download_url") or "")
            if url:
                return (url, name)
    return ("", "")


def _cnb_releases(owner, repo):
    """从 CNB 镜像拉 releases 列表。没有镜像 / 网络异常都返回 []（不抛）。

    CNB 是 Gitea 兼容的国内镜像，实测一条龙在 CNB 上的安装包与 GitHub **字节一致**
    （v2.5.2 Installer.exe = 102027760 字节），国内下载快得多，所以优先用它。
    注意：不是每个仓库都有 CNB 镜像（奇想盒就没有），所以必须能优雅回退。
    """
    try:
        req = urllib.request.Request(
            "https://cnb.cool/%s/%s/-/releases" % (owner, repo),
            headers={"User-Agent": "OKLauncher/%s" % APP_VERSION,
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _resolve_installer_asset(repo_tuple):
    """取安装包下载地址：CNB 镜像优先（国内快），没有则回退 GitHub。

    返回 (下载URL, 文件名)；都找不到返回 ("", "")。
    """
    owner, repo, pattern = repo_tuple

    # CNB 优先。这里再包一层 try 是刻意的：镜像源挂了绝不能连累 GitHub 兜底，
    # 不能只靠 _cnb_releases 内部自己吞异常（那是它的事，这里是调用方该守的边界）。
    try:
        cnb = _cnb_releases(owner, repo)
    except Exception:
        cnb = []
    if cnb:
        url, name = _pick_installer(cnb, pattern)
        if url:
            return (url, name)

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/%s/releases?per_page=10"
            % (owner, repo),
            headers={"User-Agent": "OKLauncher/%s" % APP_VERSION,
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            rels = json.loads(r.read().decode("utf-8"))
    except Exception:
        return ("", "")
    return _pick_installer(rels, pattern)


# ===== zip 分发型应用（如 MaaEnd 终末地小助手）=====
# 这类程序发布的是 **zip 压缩包**（无安装器、解压后也不是 git 仓库），
# 所以一条龙那套 git fetch/pull 的更新路线在它身上用不了，
# 必须走「release 拉资产 → 下载 zip → 解压到安装目录」这条路。

def _resolve_release_asset(repo, glob, cnb_first=True):
    """取最新**正式版** release 里匹配 glob 的资产 → (url, name, tag)。

    repo 形如 "MaaEnd/MaaEnd"。CNB 镜像优先（国内快），无镜像回退 GitHub。
    找不到返回 ("", "", "")。
    """
    owner, name = (repo.split("/", 1) + [""])[:2]
    if not (owner and name):
        return ("", "", "")
    if cnb_first:
        try:
            cnb = _cnb_releases(owner, name)
        except Exception:
            cnb = []
        for rel in cnb:
            if rel.get("prerelease") or rel.get("draft"):
                continue
            for a in (rel.get("assets") or []):
                if fnmatch.fnmatch(a.get("name", ""), glob):
                    u = (a.get("browser_download_url")
                         or a.get("brower_download_url") or "")
                    if u:
                        return (u, a.get("name", ""), rel.get("tag_name", ""))
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/%s/releases?per_page=10"
            % (owner, name),
            headers={"User-Agent": "OKLauncher/%s" % APP_VERSION,
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            rels = json.loads(r.read().decode("utf-8"))
    except Exception:
        return ("", "", "")
    for rel in rels:
        if rel.get("prerelease") or rel.get("draft"):
            continue
        for a in (rel.get("assets") or []):
            if fnmatch.fnmatch(a.get("name", ""), glob):
                u = a.get("browser_download_url") or ""
                if u:
                    return (u, a.get("name", ""), rel.get("tag_name", ""))
    return ("", "", "")


def _zipapp_version(app):
    """zip 分发型应用的**已安装版本**。

    优先级：config 里我们写回的 installed_version > exe 的版本资源 > ""。
    刚解压完还没跑过检查时，installed_version 就是安装时写入的那个 tag。
    """
    v = str(app.get("installed_version") or "").strip()
    if v:
        return v
    exe = app.get("exe", "") or ""
    if exe and os.path.isfile(exe):
        try:
            v = _exe_file_version(exe) or ""
        except Exception:
            v = ""
    return v or ""


def _pick_main_exe(dirpath, key=""):
    """在安装目录里挑主程序 exe。

    发布包里的 exe 名字我们不该猜（MaaEnd 到底是 MaaEnd.exe 还是 MaaPiCli.exe
    取决于上游打包），所以装完后**实际扫一遍**：优先名字带 key/应用名的，
    否则根目录只有一个 exe 就用它，再否则按名字排序取第一个。
    """
    try:
        exes = [f for f in sorted(os.listdir(dirpath))
                if f.lower().endswith(".exe") and
                os.path.isfile(os.path.join(dirpath, f))]
    except OSError:
        return ""
    if not exes:
        return ""
    k = (key or "").lower().replace("-", "")
    for f in exes:
        if k and k in f.lower().replace("-", "").replace(" ", ""):
            return os.path.join(dirpath, f)
    if len(exes) == 1:
        return os.path.join(dirpath, exes[0])
    return os.path.join(dirpath, exes[0])


def _remote_content_length(url, timeout=30):
    """HEAD 拿远端文件大小；失败返回 None（不能因为探测失败就中断下载）。"""
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": "OKLauncher/%s" % APP_VERSION})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            n = int(r.headers.get("Content-Length") or 0)
            return n or None
    except Exception:
        return None


def _download_chunked(url, dest, ctl, timeout=1800, chunk=65536):
    """（外层）处理 416 Range Not Satisfiable。

    典型场景：上次下载到 ~100% 时程序被关掉，临时 zip 留在盘上；
    再点安装带着它的尺寸去续传 → Range 起点不小于服务端文件大小 → 416。
    处理：本地大小 == 远端大小 → 其实已经下完整了，直接当下载完成
    （省得重下几百 MB）；否则删掉残留从头下（只重试一次，防死循环）。
    """
    last = ("error", "")
    for attempt in range(2):
        st, msg = _download_chunked_once(url, dest, ctl, timeout, chunk)
        if st != "error" or "416" not in str(msg):
            return (st, msg)
        last = (st, msg)
        local = os.path.getsize(dest) if os.path.isfile(dest) else -1
        remote = _remote_content_length(url)
        if remote and local == remote:
            return ("done", "")
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass
    return last


def _download_chunked_once(url, dest, ctl, timeout=1800, chunk=65536):
    """分块下载，支持**暂停续传**与**取消**。

    ctl 是控制器（一般是 worker），需提供：
        is_cancelled() / is_paused() / wait_resume() / on_bytes(done, total)

    续传靠 Range 头：暂停时保留已下部分，继续时带 `Range: bytes=<已下>-` 请求；
    服务端返回 206 就接着写，返回 200 说明不支持续传（或首次下载）则从头写。

    返回 (status, msg)：
        done      下载完成
        paused    被暂停（已下部分保留在 dest，可续传）
        cancelled 被取消（dest 已删除）
        error     失败，msg 为原因
    """
    try:
        done = os.path.getsize(dest) if os.path.isfile(dest) else 0
        headers = {"User-Agent": "OKLauncher/%s" % APP_VERSION}
        mode = "wb"
        if done > 0:
            headers["Range"] = "bytes=%d-" % done
            mode = "ab"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            # 状态码：某些响应包装/测试替身没有 status/getcode，取不到就按 200 处理
            # （不能因此抛异常中断下载——这只是"无法判断是否续传"，不是下载失败）
            try:
                code = getattr(r, "status", None)
                if code is None:
                    code = r.getcode() if hasattr(r, "getcode") else 200
            except Exception:
                code = 200
            try:
                total = int(r.headers.get("Content-Length") or 0)
            except Exception:
                total = 0

            if code == 206:
                pass                    # 续传，保留已下部分
            elif code == 200:
                done = 0                # 不支持 Range 或首次：从头写
                mode = "wb"
            else:
                return ("error", "HTTP %s" % code)

            with open(dest, mode) as f:
                while True:
                    if ctl.is_cancelled():
                        return ("cancelled", "")
                    if ctl.is_paused():
                        return ("paused", "")
                    buf = r.read(chunk)
                    if not buf:
                        return ("done", "")
                    f.write(buf)
                    done += len(buf)
                    try:
                        ctl.on_bytes(done, total)
                    except Exception:
                        pass
    except Exception as e:
        return ("error", str(e) or "下载失败")


def _extract_zip_flat(zip_path, dest, preserve_dirs=None):
    """把 zip 解压到 dest，若包内只有一层顶层目录则**摊平**（不嵌套一层）。

    安全：过滤掉 ../ 这类穿越路径的成员。
    preserve_dirs：这些目录名解压时**保留原有内容**（用户的配置/缓存），
    默认只保 "config"——发布包覆盖写会把用户设置冲掉，这是 zip 更新最大的坑。
    """
    preserve = set(preserve_dirs or ["config"])
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError:
        return False

    tmp = dest + "_unpack_tmp"
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            for m in zf.infolist():
                n = m.filename.replace("\\", "/")
                if n.startswith("/") or ".." in n.split("/"):
                    continue        # 路径穿越防护
                zf.extract(m, tmp)
        # 顶层若只有一个目录且里面才是内容 → 摊平
        entries = os.listdir(tmp)
        src = tmp
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
            src = os.path.join(tmp, entries[0])
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dest, item)
            if os.path.isdir(s):
                if item.lower() in {p.lower() for p in preserve} and os.path.isdir(d):
                    continue        # 保留用户配置目录
                if os.path.isdir(d):
                    shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
        return True
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _search_installed_exe(app, extra_dirs=None):
    """在常见位置按 exe 基名搜索已安装的程序。

    装完必须**实际搜索**：官方安装包把程序放哪我们说了不算，
    只信 config 预置路径的话，装到别处就会漏判成「未安装」。
    只扫根目录一层 + 每种子目录一层，不做全盘遍历（避免卡死）。
    """
    base = os.path.basename(app.get("exe", "") or "")
    if not base:
        return ""

    roots = []
    cfg_exe = app.get("exe", "") or ""
    if cfg_exe:
        roots.append(os.path.dirname(cfg_exe))              # 预置路径优先
    try:
        root = str(_load_cfg_safe().get("install_root") or "").strip()
        if root:
            roots.append(root.replace("/", os.sep))
    except Exception:
        pass
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        d = os.environ.get(env)
        if d:
            roots.append(os.path.join(d, "Programs")
                         if env == "LOCALAPPDATA" else d)
    for drv in ("D:\\", "C:\\"):
        roots.append(drv)
    roots.extend(extra_dirs or [])

    seen = set()
    for rt in roots:
        try:
            if not rt or not os.path.isdir(rt):
                continue
            key = os.path.normcase(os.path.abspath(rt))
            if key in seen:
                continue
            seen.add(key)
            entries = sorted(os.listdir(rt))
        except Exception:
            continue
        # 根目录下直接命中
        for e in entries:
            p = os.path.join(rt, e)
            try:
                if os.path.isfile(p) and os.path.normcase(e) == os.path.normcase(base):
                    return p
            except Exception:
                continue
        # 再往各子目录找一层
        for e in entries:
            sub = os.path.join(rt, e)
            try:
                if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, base)):
                    return os.path.join(sub, base)
            except Exception:
                continue
    return ""


# ===== 桌面快捷方式：.lnk 写入（齿轮菜单用） =====

def _desktop_dir():
    """桌面真实路径。必须走 SHGetFolderPathW(CSIDL_DESKTOP)：
    本机桌面被系统重定向到 D:\\桌面，拿 USERPROFILE 拼 Desktop 会指错地方。"""
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0000, None, 0, buf) == 0:
            d = buf.value
            if d and os.path.isdir(d):
                return d
    except Exception:
        pass
    return ""


def _norm_path_text(s):
    """路径文本归一化：分隔符统一成 / 再小写。

    用于 .lnk 二进制内容匹配——不走文件系统 API，必须自己把 \\ 和 / 归一，
    否则 lnk 里存的 \\ 路径和调用方给的路径格式稍有差异就漏匹配。
    """
    return str(s).replace("\\", "/").lower().rstrip("/")


def _scan_related_shortcuts(install_dir):
    """扫描 桌面 + 开始菜单 里指向 install_dir 内程序的 .lnk。

    卸载后这些快捷方式全是死链，应一并清理。匹配：读 lnk 原始字节，
    按 utf-16-le / latin-1 两种编码解码、\\ 归一成 / 后找安装目录文本。
    返回 [lnk 绝对路径]；异常返回 []。
    """
    t = _norm_path_text(install_dir or "")
    if not t:
        return []
    roots = []
    for env in ("APPDATA", "ProgramData"):
        d = os.path.join(os.environ.get(env, ""),
                         "Microsoft", "Windows", "Start Menu", "Programs")
        if os.path.isdir(d):
            roots.append(d)
    try:
        dd = _desktop_dir()
        if dd and os.path.isdir(dd):
            roots.append(dd)
    except Exception:
        pass
    hits = []
    for root in roots:
        try:
            walker = os.walk(root)
            for dirpath, _dirs, files in walker:
                for f in files:
                    if not f.lower().endswith(".lnk"):
                        continue
                    p = os.path.join(dirpath, f)
                    try:
                        raw = open(p, "rb").read()
                    except OSError:
                        continue
                    for enc in ("utf-16-le", "latin-1"):
                        try:
                            blob = raw.decode(enc, "ignore").replace("\\", "/").lower()
                        except Exception:
                            continue
                        if t in blob:
                            hits.append(p)
                            break
        except Exception:
            continue
    return hits


def _hard_delete(path):
    """直接删除（不进回收站）：目录 rmtree（顺手解只读属性），文件 os.remove。

    返回 (是否成功, 失败原因)。失败的常见原因是文件被占用。
    """
    def _onerr(func, p, _exc):
        try:
            os.chmod(p, _stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, onerror=_onerr)
        else:
            os.chmod(path, _stat.S_IWRITE)
            os.remove(path)
        if os.path.exists(path):
            return (False, "删除失败（可能被其它程序占用）")
        return (True, "")
    except Exception as e:
        return (False, str(e) or "删除失败")


def _write_lnk_struct(lnk_path, target, workdir, args="", icon=""):
    """纯 struct 写 .lnk（与 rebuild_lnk.py 同一实现，零依赖零子进程，本机已验证可用）。

    限制：ANSI LocalBasePath，四个路径参数必须**全 ASCII**——
    含中文路径会 UnicodeEncodeError，这正是存在 PowerShell 回退的原因。
    """
    def ustr(s):
        b = s.encode("utf-16-le") + b"\x00\x00"
        return struct.pack("<H", len(b)) + b

    localbase = target.encode("ascii") + b"\x00"
    volume_id = struct.pack("<IIII", 16, 3, 0, 16)
    linkinfo_body = volume_id + localbase
    linkinfo = struct.pack("<IIIIIII",
                           28 + len(linkinfo_body), 28, 0x1, 28,
                           28 + len(volume_id), 0, 0) + linkinfo_body

    LinkFlags = 0x2 | 0x8 | 0x10 | 0x20 | 0x40 | 0x80   # LinkInfo|RelPath|WorkDir|Args|Icon|Unicode
    clsid = bytes.fromhex("0002140100000000c000000000000046")
    header = struct.pack("<I", 76) + clsid
    header += struct.pack("<I", LinkFlags)
    header += struct.pack("<I", 0x20)                 # FileAttributes NORMAL
    header += b"\x00" * 24
    header += struct.pack("<I", 0)                    # FileSize
    header += struct.pack("<I", 0)                    # IconIndex
    header += struct.pack("<I", 0x1)                  # SW_SHOWNORMAL
    header += struct.pack("<H", 0) + struct.pack("<H", 0)
    header += struct.pack("<I", 0) + struct.pack("<I", 0)

    stringdata = (ustr(os.path.basename(lnk_path)[:-4] or "App")
                  + ustr(workdir) + ustr(args) + ustr(icon))
    with open(lnk_path, "wb") as f:
        f.write(header + linkinfo + stringdata)
    return os.path.isfile(lnk_path)


def _write_lnk_powershell(lnk_path, target, workdir, args="", icon=""):
    """非 ASCII 路径的回退：PowerShell WScript.Shell COM。

    用 -EncodedCommand（UTF-16LE base64）传整段脚本，绕开一切引号转义问题；
    -WindowStyle Hidden + CREATE_NO_WINDOW 防黑窗闪烁。
    """
    def q(s):
        return str(s).replace("'", "''")

    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          "$s.TargetPath='{t}';$s.Arguments='{a}';$s.WorkingDirectory='{w}';"
          "$s.IconLocation='{i},0';$s.Save()").format(
        lnk=q(lnk_path), t=q(target), a=q(args), w=q(workdir), i=q(icon))
    enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-WindowStyle", "Hidden", "-EncodedCommand", enc],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True, timeout=60)
        return os.path.isfile(lnk_path)
    except Exception:
        return False


def _write_lnk(lnk_path, target, workdir, args="", icon=""):
    """写 .lnk：路径全 ASCII 走纯 struct 快路径；含非 ASCII 回退 PowerShell。"""
    icon = icon or target
    try:
        (target + workdir + args + icon).encode("ascii")
        return _write_lnk_struct(lnk_path, target, workdir, args, icon)
    except UnicodeEncodeError:
        return _write_lnk_powershell(lnk_path, target, workdir, args, icon)


class AppInstallerWorker(QThread):
    """首次安装：下载官方安装包 → 运行安装程序 → 装完定位 exe。

    与 InstallWorker（ok-script 系的 NSIS 整包直解）路线不同：
    这里走**官方自己的安装程序**（GUI，用户点下一步），装完我们再去找它落在哪。
    这样不用复制各家的安装逻辑，也不会和他们后续的自更新打架——
    我们只负责「把安装程序送到用户面前 + 装完认出它」。
    """

    progress = Signal(str)
    percent = Signal(int)
    done = Signal(str)     # 已安装 exe 的绝对路径
    failed = Signal(str)   # 失败原因（人类可读）

    def __init__(self, app, tmp_dir, parent=None):
        super().__init__(parent)
        self.app = app
        self.tmp_dir = tmp_dir
        self._cancelled = False
        self._paused = False
        self._last_pct = -1

    def cancel(self):
        self._cancelled = True
        self._paused = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def is_cancelled(self):
        return self._cancelled

    def is_paused(self):
        return self._paused

    def wait_resume(self):
        while self._paused and not self._cancelled:
            time.sleep(0.2)

    def on_bytes(self, done, total):
        if total:
            pct = int(done * 100 / total)
            if pct != self._last_pct:
                self._last_pct = pct
                self.percent.emit(pct)
                self.progress.emit(
                    "%d%%（%s / %s）" % (pct, _human_size(done), _human_size(total)))
        else:
            self.percent.emit(-1)
            self.progress.emit("已下载 %s" % _human_size(done))

    def _cleanup(self, path):
        """取消/失败时清掉半截安装包，不留垃圾。"""
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    def run(self):
        repo = INSTALLER_REPO.get(self.app.get("key", ""))
        if not repo:
            self.failed.emit("该应用没有配置官方安装包，无法一键安装。")
            return

        self.progress.emit("正在查找官方安装包…")
        url, name = _resolve_installer_asset(repo)
        if not url:
            self.failed.emit(
                "未能从官方仓库找到安装包（网络不通，或该仓库暂未发布安装包）。")
            return

        try:
            os.makedirs(self.tmp_dir, exist_ok=True)
        except Exception:
            pass
        save = os.path.join(self.tmp_dir, name or "installer.exe")

        self.progress.emit("正在下载安装包…")
        # 下载循环：暂停 → 等 resume 后续传；取消 → 删半截文件并退出
        while True:
            st, msg = _download_chunked(url, save, self)
            if st == "done":
                break
            if st == "cancelled":
                self._cleanup(save)
                self.failed.emit("已取消")
                return
            if st == "paused":
                self.progress.emit("已暂停（可点「继续」接着下）")
                self.wait_resume()
                if self._cancelled:
                    self._cleanup(save)
                    self.failed.emit("已取消")
                    return
                self.progress.emit("继续下载…")
                continue
            self._cleanup(save)
            self.failed.emit("下载安装包失败：%s" % msg)
            return

        if self._cancelled:
            self._cleanup(save)
            self.failed.emit("已取消")
            return

        # 以下进入官方安装程序（GUI，用户自己点）：暂停/取消不再适用，
        # 这一步由用户决定，我们只等它结束。
        self.progress.emit("正在启动安装程序，请在弹出窗口里完成安装…")
        try:
            subprocess.Popen([save]).wait()
        except Exception as e:
            self.failed.emit("启动安装程序失败：%s" % e)
            return

        self.progress.emit("安装程序已结束，正在定位…")
        found = _search_installed_exe(self.app)
        if not found:
            self.failed.emit(
                "安装程序已运行，但没在常见位置找到 %s。\n"
                "如果装到了其它目录，请点「选择已安装程序…」手动指定。"
                % os.path.basename(self.app.get("exe", "") or "程序"))
            return
        self.done.emit(found)


def mirrorchyan_latest(rid, cdk, current_version="", user_agent="WorkBuddy-OKLauncher"):
    """查 Mirror酱 拿加速直链。任何失败一律返回 None（调用方回退其它源）。

    返回 (url, version_name, release_note)，或 None。
    """
    if not rid or not cdk:
        return None
    params = {
        "os": "win", "arch": "x64", "channel": "stable",
        "cdk": cdk, "user_agent": user_agent,
    }
    if current_version:
        params["current_version"] = current_version
    api = (MIRRORCHYAN_API.format(rid=urllib.parse.quote(rid, safe=""))
           + "?" + urllib.parse.urlencode(params))
    try:
        req = urllib.request.Request(api, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=30) as r:
            info = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(info, dict) or info.get("code") != 0:
        return None
    data = info.get("data") or {}
    url = data.get("url") or ""
    if not url.startswith("http"):
        return None
    return url, str(data.get("version_name") or ""), str(data.get("release_note") or "")


# ===== 匿名错误上报 / 启动计数（可选，默认关）=====
# 目的只有一个：帮作者修 bug，以及知道有多少人在用。不是行为追踪。
#
# 设计底线（硬编码，不接受任何配置绕过）：
#   1. 只发「版本号 + 异常类型 + 脱敏后的调用栈」；不发配置内容、不发 CDK、
#      不发安装路径原文、不发任何能定位到个人的信息
#   2. 所有文本过一遍 sanitize_text()：本机绝对路径、用户名目录、CDK/token、
#      邮箱一律替换成占位符
#   3. 用本地随机生成的匿名 ID 做去重（只用于算独立用户数），不做跨会话身份关联
#   4. 未启用 / 没配 endpoint / 发送失败 → 一律静默：不弹窗、不阻塞、不影响主流程
#
# config.json 形态（默认全关，行为完全不变）：
#   "telemetry": {"enabled": false, "endpoint": "", "ping": false}

TELEMETRY_PAYLOAD_LIMIT = 4000


def _telemetry_cfg():
    """读 telemetry 配置，任何异常都返回 {enabled:False}（关掉上报）。"""
    try:
        t = _load_cfg_safe().get("telemetry")
        return t if isinstance(t, dict) else {}
    except Exception:
        return {}


def telemetry_enabled():
    """是否启用匿名错误上报。未配置端点一律视为关闭。"""
    t = _telemetry_cfg()
    return bool(t.get("enabled")) and bool(str(t.get("endpoint") or "").strip())


def telemetry_ping_enabled():
    """是否发送启动计数（用于统计活跃用户）。依赖 telemetry 主开关。"""
    return telemetry_enabled() and bool(_telemetry_cfg().get("ping"))


def _anon_id():
    """本地持久化的随机匿名 ID（首次生成后存 .cache/anon_id）。

    只用于「算有多少独立用户在用」，不含任何机器特征，可随时删除文件重置。
    """
    path = os.path.join(LAUNCHER_CACHE_DIR, "anon_id")
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    try:
        import uuid
        os.makedirs(LAUNCHER_CACHE_DIR, exist_ok=True)
        v = uuid.uuid4().hex
        with open(path, "w", encoding="utf-8") as f:
            f.write(v)
        return v
    except Exception:
        return ""


def _path_aliases():
    """(真实路径, 占位符) 列表，用于脱敏本机路径。"""
    aliases = []
    try:
        home = os.path.expanduser("~")
        if home and len(home) > 3:
            aliases.append((home, "<HOME>"))
    except Exception:
        pass
    if LAUNCHER_DIR and len(LAUNCHER_DIR) > 3:
        aliases.append((LAUNCHER_DIR, "<LAUNCHER_DIR>"))
    try:
        root = str(_load_cfg_safe().get("install_root") or "").strip()
        if len(root) > 3:
            aliases.append((root, "<INSTALL_ROOT>"))
    except Exception:
        pass
    return aliases


def sanitize_text(text):
    """脱敏：CDK/token、本机绝对路径、邮箱 → 占位符。

    错误栈里常带 D:\\Users\\<用户名>\\... 这类路径，以及拼在 URL 里的 cdk=xxx，
    直接上报等于泄露个人信息与密钥，所以这里是硬性处理。
    """
    if not text:
        return ""
    out = str(text)
    # 1) URL 查询参数里的 cdk/token/key
    out = re.sub(r'(?i)([?&](?:cdk|token|key|secret)=)[^&\s"\']+',
                 r'\1<redacted>', out)
    # 2) 键值对形式的 cdk/token/密码
    out = re.sub(r'(?i)\b(cdk|token|secret|password|passwd|pwd)\s*[:=]\s*["\']?[A-Za-z0-9_\.\-]{4,}["\']?',
                 lambda m: "%s=<redacted>" % m.group(1), out)
    # 3) 本机路径（先长后短，避免短路径先被替换导致长路径失配）
    for real, alias in sorted(_path_aliases(), key=lambda x: -len(x[0])):
        if real:
            out = out.replace(real, alias)
            out = out.replace(real.replace("\\", "/"), alias)
    # 4) 邮箱
    out = re.sub(r'[\w\.\-]+@[\w\.\-]+\.\w+', '<email>', out)
    return out


def log_error_local(kind, message, detail=""):
    """把脱敏后的错误写到本地 logs/error.log（与是否上报无关，方便自己排查）。"""
    try:
        os.makedirs(os.path.join(LAUNCHER_DIR, "logs"), exist_ok=True)
        line = ("[%s] %s | %s\n%s\n\n"
                % (time.strftime("%Y-%m-%d %H:%M:%S"), kind,
                   sanitize_text(message)[:500],
                   sanitize_text(detail)[:TELEMETRY_PAYLOAD_LIMIT]))
        with open(os.path.join(LAUNCHER_DIR, "logs", "error.log"),
                  "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _telemetry_post(payload):
    """在后台线程 POST 一次上报。任何失败静默。"""
    def _run():
        try:
            ep = str(_telemetry_cfg().get("endpoint") or "").strip()
            if not ep:
                return
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                ep, data=data, method="POST",
                headers={"Content-Type": "application/json",
                         "User-Agent": "game-launcher-hub"})
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
        except Exception:
            pass
    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


def report_error(kind, message, detail=""):
    """上报一次异常。未启用则只写本地日志；启用则异步 POST。

    调用方无需关心是否联网、是否配置——本函数保证不抛、不阻塞。
    """
    try:
        log_error_local(kind, message, detail)
        if not telemetry_enabled():
            return
        import platform
        _telemetry_post({
            "v": 1,
            "app": "game-launcher-hub",
            "version": APP_VERSION,
            "anon_id": _anon_id(),
            "kind": str(kind)[:64],
            "message": sanitize_text(message)[:500],
            "detail": sanitize_text(detail)[:TELEMETRY_PAYLOAD_LIMIT],
            "os": platform.platform()[:120],
            "py": platform.python_version()[:32],
            "ts": int(time.time()),
        })
    except Exception:
        pass


def report_ping():
    """启动计数（仅一个版本号 + 匿名 ID），用于统计活跃用户数。"""
    try:
        if not telemetry_ping_enabled():
            return
        import platform
        _telemetry_post({
            "v": 1, "app": "game-launcher-hub", "version": APP_VERSION,
            "anon_id": _anon_id(), "kind": "ping",
            "os": platform.platform()[:120],
            "py": platform.python_version()[:32],
            "ts": int(time.time()),
        })
    except Exception:
        pass


def install_excepthook():
    """接管未捕获异常：写本地日志 + （若启用）匿名上报，然后仍走默认行为。"""
    def _hook(etype, value, tb):
        try:
            import traceback as _tb
            detail = "".join(_tb.format_exception(etype, value, tb))
            report_error("uncaught", "%s: %s" % (getattr(etype, "__name__", "?"), value),
                         detail)
        except Exception:
            pass
        sys.__excepthook__(etype, value, tb)
    try:
        sys.excepthook = _hook
    except Exception:
        pass


def _cnb_git_mirror(repo, git):
    """从仓库 origin URL 推导 CNB 镜像地址（仅 GitHub origin 可推）。

    背景：一条龙 origin 是 github.com，但同一 owner/repo 在 CNB 上有官方镜像，
    实测 git fetch / 安装包都与 GitHub 字节一致，而国内连 GitHub 很不稳——
    用户机器上「检查更新失败」的根因就是 fetch origin 超时/握手失败。
    返回 CNB URL 字符串；origin 不是 GitHub（file://、gitee 等）或出错返回 ""。
    """
    try:
        rc, url, _ = _git_run(git, ["remote", "get-url", "origin"],
                              repo, timeout=15)
        if rc != 0:
            return ""
        m = re.match(r"https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
                     (url or "").strip())
        if not m:
            return ""
        return "https://cnb.cool/%s/%s" % (m.group(1), m.group(2))
    except Exception:
        return ""


class ZipAppCheckWorker(QThread):
    """zip 分发型应用的更新检查：拉 release 资产，跟已安装版本比。

    与 git 路线（GenericUpdateCheckWorker）的差异：zip 发布**没有提交数**，
    "落后几个提交"无从谈起，改用版本号比较；这也更贴近用户认知。
    """

    done = Signal(object)   # {has_new, behind, local_tag, remote_tag, reason}
    failed = Signal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app

    def run(self):
        repo = (self.app.get("release_repo") or "").strip()
        glob = (self.app.get("asset_glob") or "").strip()
        if not repo or not glob:
            self.done.emit({"has_new": False, "behind": 0,
                            "local_tag": _zipapp_version(self.app),
                            "remote_tag": "", "reason": "norepo"})
            return
        try:
            url, _name, tag = _resolve_release_asset(repo, glob)
            if not url:
                self.failed.emit("未能从发布页找到匹配的安装包。")
                return
            local = _zipapp_version(self.app)
            has_new = bool(tag) and (not local or compare_version(tag, local) > 0)
            self.done.emit({
                "has_new": has_new,
                "behind": 1 if has_new else 0,   # zip 发布无提交数，1 表示"有新版本"
                "local_tag": local,
                "remote_tag": tag,
                "reason": "" if has_new else "uptodate",
            })
        except Exception as e:
            self.failed.emit(str(e))


class ZipAppWorker(QThread):
    """zip 分发型应用的安装 / 更新：下载 zip → 解压到安装目录 → 写回版本与 exe。

    安装和更新是同一套动作（覆盖式解压，保留用户配置目录），
    区别只在于目标目录此前存不存在。

    刻意**不猜主程序文件名**：解压完用 _pick_main_exe 实际扫一遍再写回 config，
    免得上游哪天改了 exe 名字就整张卡失效。
    """

    progress = Signal(str)   # 阶段文案
    percent = Signal(int)    # 下载百分比（没有总长度时发 -1）
    done = Signal(str)       # 装/更到的版本 tag
    failed = Signal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._cancelled = False
        self._paused = False
        self._last_pct = -1

    # ---- 暂停 / 继续 / 取消（供卡片按钮调用）----
    def cancel(self):
        self._cancelled = True
        self._paused = False      # 取消时解除暂停等待，别让线程卡在 sleep 里

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def is_cancelled(self):
        return self._cancelled

    def is_paused(self):
        return self._paused

    def wait_resume(self):
        while self._paused and not self._cancelled:
            time.sleep(0.2)

    def on_bytes(self, done, total):
        if total:
            pct = int(done * 100 / total)
            if pct != self._last_pct:
                self._last_pct = pct
                self.percent.emit(pct)
                self.progress.emit(
                    "%d%%（%s / %s）" % (pct, _human_size(done), _human_size(total)))
        else:
            self.percent.emit(-1)
            self.progress.emit("已下载 %s" % _human_size(done))

    def _cleanup(self, zpath):
        """取消/失败时清掉半截临时 zip，不留垃圾、不占盘。"""
        try:
            if zpath and os.path.isfile(zpath):
                os.remove(zpath)
        except OSError:
            pass

    def run(self):
        repo = (self.app.get("release_repo") or "").strip()
        glob = (self.app.get("asset_glob") or "").strip()
        exe = self.app.get("exe", "") or ""
        dest = os.path.dirname(exe) if exe else ""
        if not repo or not glob or not dest:
            self.failed.emit("配置缺少 release_repo / asset_glob / exe，无法安装。")
            return

        self.progress.emit("正在查找安装包…")
        url, name, tag = _resolve_release_asset(repo, glob)
        if not url:
            self.failed.emit("未能从发布页找到匹配的安装包。")
            return

        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as e:
            self.failed.emit("无法创建安装目录 %s：%s" % (dest, e))
            return

        zpath = os.path.join(dest, "_update_tmp.zip")
        self.progress.emit("正在下载 %s…" % (name or "安装包"))
        # 下载循环：暂停 → 等 resume 后续传；取消 → 删临时文件并退出
        while True:
            st, msg = _download_chunked(url, zpath, self)
            if st == "done":
                break
            if st == "cancelled":
                self._cleanup(zpath)
                self.failed.emit("已取消")
                return
            if st == "paused":
                self.progress.emit("已暂停（可点「继续」接着下）")
                self.wait_resume()
                if self._cancelled:
                    self._cleanup(zpath)
                    self.failed.emit("已取消")
                    return
                self.progress.emit("继续下载…")
                continue
            self._cleanup(zpath)
            self.failed.emit("下载失败：%s" % msg)
            return

        if self._cancelled:
            self._cleanup(zpath)
            self.failed.emit("已取消")
            return

        self.progress.emit("正在解压到 %s…" % dest)
        ok = _extract_zip_flat(zpath, dest, self.app.get("preserve_dirs"))
        try:
            os.remove(zpath)
        except OSError:
            pass
        if not ok:
            self.failed.emit("解压失败（安装包可能损坏）。")
            return

        key = self.app.get("key", "")
        found = _pick_main_exe(dest, key)
        if found:
            self.app["exe"] = found
            _save_app_field(key, "exe", found)
        if tag:
            self.app["installed_version"] = tag
            _save_app_field(key, "installed_version", tag)

        self.progress.emit("完成")
        self.done.emit(tag or _zipapp_version(self.app) or "")


class GenericUpdateCheckWorker(QThread):
    """generic 应用（本地 git 仓库）更新检查。

    流程：git fetch（只下载对象，不碰工作区）→ 比较 HEAD 与远端落后几个提交 →
    顺带取远端最新 tag 用于展示。全程不修改任何文件，失败也不影响用户。
    """

    done = Signal(object)   # {has_new, behind, local_tag, remote_tag, reason}
    failed = Signal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app

    def run(self):
        repo = _git_repo_dir(self.app)
        git = GitVersionFetcher._find_git()
        if not repo or not git:
            self.done.emit({"has_new": False, "behind": 0,
                            "local_tag": _git_tag_version(self.app),
                            "remote_tag": "", "reason": "nogit"})
            return
        try:
            # 当前分支
            rc, branch, _ = _git_run(git, ["rev-parse", "--abbrev-ref", "HEAD"],
                                     repo, timeout=30)
            if rc != 0 or not branch:
                branch = "main"

            # fetch：只拉对象，工作区零改动。
            # 必须带 --tags：实测不带的话新 tag 不会同步过来，
            # git describe 会永远停在旧版本号（表现为「更新了但版本没变」）。
            #
            # 源选择：CNB 镜像优先（国内连 GitHub 常握手失败/超时，用户机器实测），
            # CNB 没镜像或 fetch 失败再回退 origin，绝不让镜像故障连累兜底。
            rc, _, err = 1, "", "尚未尝试"
            cnb_url = _cnb_git_mirror(repo, git)
            if cnb_url:
                rc, _, err = _git_run(git, ["fetch", "--tags", cnb_url, branch],
                                      repo, timeout=120)
            if rc != 0:
                rc, _, err = _git_run(git, ["fetch", "--tags", "origin", branch],
                                      repo, timeout=180)
            if rc != 0:
                self.failed.emit(err or "git fetch 失败")
                return

            # 落后多少个提交（远端有而本地没有的）
            rc, behind_s, _ = _git_run(
                git, ["rev-list", "--count", "HEAD..FETCH_HEAD"], repo, timeout=60)
            behind = int(behind_s) if rc == 0 and behind_s.isdigit() else 0

            # 本地 / 远端最新 tag
            local_tag = _git_tag_version(self.app)
            rc, rt, _ = _git_run(git, ["describe", "--tags", "--abbrev=0", "FETCH_HEAD"],
                                 repo, timeout=30)
            remote_tag = rt if rc == 0 else ""

            self.done.emit({
                "has_new": behind > 0,
                "behind": behind,
                "local_tag": local_tag,
                "remote_tag": remote_tag or local_tag,
                "reason": "" if behind > 0 else "uptodate",
            })
        except Exception as e:
            self.failed.emit(str(e))


class GenericUpdateWorker(QThread):
    """generic 应用更新：git pull --ff-only。

    为什么只用 --ff-only：绝不产生 merge/rebase，本地一旦有分叉就直接失败并报错，
    而不是悄悄改写用户的提交历史。这正是“能直接更新”与“安全”的平衡点。
    """

    progress = Signal(str)
    done = Signal(str)      # 更新后的最新 tag
    failed = Signal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        repo = _git_repo_dir(self.app)
        git = GitVersionFetcher._find_git()
        if not repo or not git:
            self.failed.emit("安装目录不是 git 仓库，或找不到 git")
            return
        try:
            # 前置检查：受控文件有改动就拒绝，避免覆盖用户修改
            self.progress.emit("检查本地改动…")
            if _git_has_tracked_changes(repo):
                self.failed.emit(
                    "本地有未提交的改动，已中止更新。\n"
                    "请先处理这些改动（提交或还原），再点更新。\n"
                    "这样设计是为了不覆盖你修改过的文件。")
                return

            rc, branch, _ = _git_run(git, ["rev-parse", "--abbrev-ref", "HEAD"],
                                     repo, timeout=30)
            if rc != 0 or not branch:
                branch = "main"

            if self._cancelled:
                self.failed.emit("已取消")
                return

            self.progress.emit("正在拉取最新代码…")
            # 同样带 --tags，否则更新后版本号不刷新（与检查阶段同理）。
            # 源选择与检查阶段一致：CNB 镜像优先，失败回退 origin。
            rc, out, err = 1, "", "尚未尝试"
            cnb_url = _cnb_git_mirror(repo, git)
            if cnb_url:
                rc, out, err = _git_run(
                    git, ["pull", "--ff-only", "--tags", cnb_url, branch],
                    repo, timeout=300)
            if rc != 0:
                if cnb_url:
                    self.progress.emit("CNB 镜像不可用，改走 GitHub…")
                rc, out, err = _git_run(
                    git, ["pull", "--ff-only", "--tags", "origin", branch],
                    repo, timeout=300)
            if rc != 0:
                # 常见原因：本地分叉（--ff-only 拒绝）
                if "not possible to fast-forward" in (err + out).lower() \
                        or "diverging" in (err + out).lower():
                    self.failed.emit(
                        "本地与远端已分叉（无法快进），已中止更新。\n"
                        "请打开该程序的官方启动器完成更新，或手动处理本地提交。")
                else:
                    self.failed.emit(err or out or "git pull 失败")
                return

            if self._cancelled:
                self.failed.emit("已取消")
                return

            new_tag = _git_tag_version(self.app)
            self.done.emit(new_tag)
        except Exception as e:
            self.failed.emit(str(e))


class InstallWorker(QThread):
    """后台从 GitHub release 下载 win32.zip 就地解压到目标安装目录（进度协议同 MirrorUpdater）。"""

    # ===== 同 key 并发硬锁（进程内） =====
    # 旧版「重复下载」根因：用户点取消后 worker 还在后台跑（cancel 标志要等到下载循环才传到），
    # 旧 _on_cancel 没清 self._install_worker 引用，UI 信号 disconnect 后不动了，用户以为停了又点，
    # 守卫看旧 worker 还活着就拦住，等旧 worker 一结束再点又起新 worker——多个 worker 并发各自下整包，
    # 进度互相覆盖看起来就像「一直在换源重复下载」。这里加进程内按 key 的锁 + 落盘日志双保险。
    _locks = {}  # key -> Lock，确保同一 key 同时只有一个 worker 在跑
    _SEVENZIP_PATH = None  # 进程内缓存：一次成功后,所有后续 install 直接复用,不再重下 1.6MB

    def _log(self, msg):
        """下载过程落盘日志，写到 logs/install-<key>.log，方便排查「换源/重复下载」。"""
        try:
            _d = os.path.join(LAUNCHER_DIR, "logs")
            os.makedirs(_d, exist_ok=True)
            _p = os.path.join(_d, f"install-{self.key}.log")
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(_p, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    progress = Signal(int, str)
    done = Signal(str, str)        # (install_dir, version_tag)
    failed = Signal(str)

    # key -> (github_repo, zip 前缀, mirrorchyan_rid, pyappify_内部名)
    #   - 第 3 个是 MirrorChyan 的 rid（README 官方链接）
    #   - 第 4 个是 PyAppify 打包出来的内部名（= 解压后 data/apps/<名> 与 <名>.exe），
    #     它和 launcher key 不一定相同：终末地内部叫 ok-ef，但 launcher 配置用 ok-end-field。
    #     整包(China-setup)解压后需要把 ok-ef 改名/复制对齐成 launcher 期望的名字。
    REPOS = {
        "ok-nte":       ("BnanZ0/ok-nte",                 "ok-nte-win32",      "ok-nte",      "ok-nte"),
        "ok-ww":        ("ok-oldking/ok-wuthering-waves", "ok-ww-win32",        "okww",        "ok-ww"),
        "ok-end-field": ("AliceJump/ok-end-field",         "ok-ef-win32",        "ok-end-field","ok-ef"),
    }

    # 万载云 GitHub 反代（国内直连、免登录免 key、覆盖全部游戏）。
    # 实测：GET <WANZAIYUN_PROXY><原始github链接> 直接 200 吐 octet-stream。
    # 主域名若失效，改 config.json 的 wanzaiyun_proxy 即可，无需改代码。
    WANZAIYUN_PROXY = "https://github.top-host.top/"

    # 万载云页面下拉框「节点」里的全部加速入口（2026-08-28 从 wanzaiyun.com github.js
    # 解混淆 PROXY_LIST 取得，共 17 个）。其中 github.top-host.top / proxy.gitwarp.top
    # 是万载云自家 CDN，其余 15 个是第三方公共 gh-proxy。安装前会并发测速，挑最快的用。
    # 顺序无关紧要——安装时会按实测吞吐重排。
    WANZAIYUN_NODES = [
        "https://gh.xmly.dev/",
        "https://gh-proxy.org/",
        "https://v4.gh-proxy.org/",
        "https://v6.gh-proxy.org/",
        "https://cdn.gh-proxy.org/",
        "https://github.xxlab.tech/",
        "https://gh-proxy.com/",
        "https://gh.b52m.cn/",
        "https://g.blfrp.cn/",
        "https://gh.jasonzeng.dev/",
        "https://gitproxy.mrhjx.cn/",
        "https://github.geekery.cn/",
        "https://ghproxy.sakuramoe.dev/",
        "https://github.cnxiaobai.com/",
        "https://ghproxy.net/",
        "https://proxy.gitwarp.top/",
        "https://github.top-host.top/",
    ]

    def __init__(self, key, install_root, install_dir, cdk="", proxy=None, app=None, parent=None):
        super().__init__(parent)
        self.key = key
        self.install_root = install_root
        # 目标安装目录（绝对路径）。win32.zip 解完后整目录或顶层单层目录应落到这里。
        # 调用方按 config.app["exe"] 反推得出（已实测符合 PyAppify install 行为）。
        self.install_dir = install_dir
        # MirrorChyan CDK（空=不启用快源，run() 自动回退 cnb/GitHub）
        self.cdk = (cdk or "").strip()
        # 万载云反代域名（None=用默认 WANZAIYUN_PROXY）
        self.proxy = (proxy or "").strip() or self.WANZAIYUN_PROXY
        # 调用方传进来的 app dict（含 config["exe"] 期望名）。解完后用来对齐 host 名。
        self.app = app or {}
        # 取消标志位：用户点对话框的「取消」按钮时设为 True，下载/解压循环每 chunk 检查并 early return。
        # 之前是 None 取消按钮 + 无标志位 → 用户被下载困死、连点会多 worker 并发下整包。
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _cleanup_tmp(self, tmp):
        """取消时清理下载临时目录，避免留半截 zip/7z_installer.exe/7zportable 占空间。"""
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
        # 发一个静默的「已取消」标记,run() 不会发 failed,UI 不弹错误框
        self.progress.emit(-1, "已取消下载,临时文件已清理")

    def _get_latest_release(self, repo):
        """查 GitHub releases/latest，返回完整 release JSON。

        带本地文件缓存（TTL=RELEASE_CACHE_TTL），避免在「反复安装/刷新」场景里
        把未登录 60 次/小时的 api.github.com 配额打满 → 403 rate limit。
        - 缓存未过期：直接返回缓存，零 API 请求；
        - 缓存过期/缺失：打 API；若命中 403 且本地有缓存，则用缓存兜底（并记日志），
          没有缓存才把 403 作为异常抛出，让 run() 给出清晰提示。
        """
        owner, name = repo.split("/")
        cache_file = os.path.join(LAUNCHER_CACHE_DIR, f"release_{owner}_{name}.json")
        os.makedirs(LAUNCHER_CACHE_DIR, exist_ok=True)

        # 1) 缓存命中且未过期 → 直接用，不再打 API
        if os.path.isfile(cache_file):
            try:
                cached = json.load(open(cache_file, encoding="utf-8"))
                ts = cached.get("_fetched_at", 0)
                if (time.time() - ts) < RELEASE_CACHE_TTL:
                    self._log(f"release 缓存命中（{name}，{int((time.time()-ts))}s 前），跳过 API")
                    return cached
            except Exception:
                pass

        # 2) 打 API
        api = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(api, headers={"User-Agent": "WorkBuddy-OKLauncher"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                self._log(f"GitHub API 403 限流（{repo}），尝试用本地缓存兜底")
                if os.path.isfile(cache_file):
                    try:
                        return json.load(open(cache_file, encoding="utf-8"))
                    except Exception:
                        pass
                raise RuntimeError(
                    "GitHub API 触发限流（HTTP 403: rate limit exceeded）。\n"
                    "未登录调用 api.github.com 限 60 次/小时，反复安装/刷新已打满。\n"
                    "请稍等约 1 小时再试；或填 MirrorChyan CDK 走国内快源绕开 GitHub。"
                )
            raise
        except Exception:
            # 网络异常：有缓存就用缓存兜底，没有就原样抛出
            if os.path.isfile(cache_file):
                self._log(f"GitHub API 异常，用本地缓存兜底（{name}）")
                try:
                    return json.load(open(cache_file, encoding="utf-8"))
                except Exception:
                    pass
            raise

        # 3) 成功 → 写缓存
        data["_fetched_at"] = time.time()
        try:
            json.dump(data, open(cache_file, "w", encoding="utf-8"), ensure_ascii=False)
            self._log(f"release 已缓存（{name}，{len(data.get('assets', []))} 个资产）")
        except Exception:
            pass
        return data

    def _asset_for(self):
        """调 GitHub releases/latest，找一个 .zip 资产。返回 (url, name, size, tag)。"""
        if self.key not in self.REPOS:
            raise RuntimeError(f"未配置 {self.key} 的 release 仓库")
        repo, *_ = self.REPOS[self.key]
        data = self._get_latest_release(repo)
        for a in data.get("assets", []):
            n = a.get("name", "") or ""
            if n.lower().endswith(".zip"):
                return a["browser_download_url"], n, int(a.get("size", 0) or 0), data.get("tag_name", "")
        raise RuntimeError(f"未在 {repo} 找到 .zip 资产")

    def _scan_local_installer(self, tmp, key):
        """扫描 _dl_<key>/ 里是否已存在上一次下好的安装包，直接复用，完全不打 GitHub API、不重下。

        返回 (zip_path, zip_name, zip_size, is_full) 或 None。
        判定：优先 china-setup 整包(.exe)；否则任意 >50MB 的 .exe 当整包；>5MB 的 .zip 当 host 引导包。
        关键用途：用户之前下到一半/下完但解压失败留下的 _dl_<key>/<name>，本次重装时
        如果不复用就会再去打 api.github.com 查 release（未登录限流 403）→ 卡死。
        所以「本地已有包」时一律优先复用，绕开 API 与下载。
        """
        if not tmp or not os.path.isdir(tmp):
            return None
        cands = []
        for fn in os.listdir(tmp):
            fp = os.path.join(tmp, fn)
            if not os.path.isfile(fp):
                continue
            low = fn.lower()
            sz = os.path.getsize(fp)
            if "china-setup" in low and low.endswith(".exe") and sz > 50 * 1024 * 1024:
                cands.append((fp, fn, sz, True))
            elif low.endswith(".exe") and sz > 50 * 1024 * 1024:
                cands.append((fp, fn, sz, True))
            elif low.endswith(".zip") and sz > 5 * 1024 * 1024:
                cands.append((fp, fn, sz, False))
        if not cands:
            return None
        # 取最大的那个（最可能是完整安装的）
        cands.sort(key=lambda x: x[2], reverse=True)
        fp, fn, sz, is_full = cands[0]
        return fp, fn, sz, is_full

    def _mirror_url(self, tag, asset_name):
        """cnb.cool 镜像直链（国内快）。作者没在 cnb 开 release 镜像时此链接会 404，由 run() 回退 GitHub。"""
        repo, *_ = self.REPOS[self.key]
        owner, name = repo.split("/")
        return f"https://cnb.cool/{owner}/{name}/-/releases/download/{tag}/{asset_name}"

    def _mirrorchyan_url(self):
        """MirrorChyan CDK 加速源。config 填了有效 CDK 才返回临时下载直链，否则返回 None（run() 跳过此项）。

        域名已实测可达；无/无效 CDK 时 API 返回 code!=0，本函数返回 None 让 run() 回退 cnb/GitHub。
        rid 取自各游戏 README 官方链接：ok-nte=ok-nte / ok-ww=okww / ok-end-field=ok-end-field。
        """
        if not self.cdk:
            return None
        # rid 允许 config.json 覆盖（内置值只对已知的 ok-script 系有效）
        rid = mirrorchyan_rid_for(self.key) or (self.REPOS[self.key][2] if self.key in self.REPOS else "")
        if not rid:
            return None
        got = mirrorchyan_latest(rid, self.cdk, user_agent="WorkBuddy-OKLauncher")
        return got[0] if got else None

    # ===== 万载云多节点测速选源 =====
    def _probe(self, url, timeout=4):
        """零流量探测单个源（实现见模块级 _probe_url，供 LiteDownloadWorker 复用）。"""
        return _probe_url(url, timeout)

    def _select_fastest(self, github_url, tag="", asset_name=""):
        """并发测速所有候选源，挑「延迟最低」的那个返回 (label, url, latency_s)。

        候选源 = MirrorChyan(填了CDK) + 万载云 17 节点(两种拼法) + cnb + GitHub 直链。
        万载云节点拼法：<node><github_url>（带协议）优先，失败再试 <node><去协议路径>；
        哪种形式 200 就用哪种。返回 None 表示全部失败。
        """
        import concurrent.futures as _cf

        cands = []  # (label, url)
        # MirrorChyan（私有快源，有 CDK 才进候选）
        mc = self._mirrorchyan_url()
        if mc:
            cands.append(("MirrorChyan(CDK)", mc))
        # 万载云 17 节点：带协议 + 去协议两种拼法都试
        if github_url.startswith("https://github.com/"):
            no_proto = github_url[len("https://"):]
            for nd in self.WANZAIYUN_NODES:
                cands.append((f"万载云 {nd}", nd + github_url))
                cands.append((f"万载云 {nd}(noproto)", nd + no_proto))
            # config.json 里单独配的自定义万载云域名（覆盖默认节点列表）
            custom = (self.proxy or "").strip()
            if custom and custom not in self.WANZAIYUN_NODES:
                cands.append((f"万载云自定义 {custom}", custom + github_url))
                cands.append((f"万载云自定义 {custom}(noproto)", custom + no_proto))
        # cnb 镜像（仅 win32.zip 这类常规资产，整包通常没有）
        if not self._is_full and tag and asset_name:
            mirror = self._mirror_url(tag, asset_name)
            if mirror:
                cands.append(("cnb.cool", mirror))
        # GitHub 直链（兜底，永远能进候选）
        cands.append(("GitHub 直链", github_url))

        self.progress.emit(-1, f"正在测速 {len(cands)} 个下载源（并发，每源只读 1 字节）…")

        def _test(item):
            label, url = item
            ok, lat, cl = self._probe(url)
            return (label, url, ok, lat, cl)

        scored = []
        with _cf.ThreadPoolExecutor(max_workers=20) as ex:
            for res in ex.map(_test, cands):
                label, url, ok, lat, cl = res
                # 必须探测成功且拿到真实文件大小（Content-Length>0 说明该源真有这个文件）
                if ok and cl > 0:
                    scored.append((label, url, lat))
        if not scored:
            return None
        # 按延迟升序，取最近（最快）的源
        scored.sort(key=lambda x: x[2])
        # 测速结束查一次取消标志：避免用户在 17 节点测速阶段点取消后,
        # 选完源继续跑 _stream_download 整包下载,造成"取消无效还在下"的假象
        if getattr(self, "_cancelled", False):
            return None
        return scored  # 返回按延迟升序的完整候选列表 [(label, url, latency_s), ...]

    def _stream_download(self, url, zip_path, total_hint):
        """实际下载循环，复用速度/ETA 进度。返回 total(字节)。失败抛异常（含 urllib.error.HTTPError）。"""
        req = urllib.request.Request(url, headers={"User-Agent": "WorkBuddy-OKLauncher"})
        t0 = time.time()
        host = url.split("//", 1)[-1].split("/", 1)[0]
        self.progress.emit(0, f"正在连接 {host}…")
        # timeout=60：连接或读取任一步超过 60 秒无数据即超时。万载云节点抽风时会卡在
        # "连接建立但不推数据"，旧值 600 会让单次下载挂 10 分钟、用户以为卡死又点 → 并发。
        # 60 秒足够暴露坏源，配合 run() 的「前 3 名换源重试」快速失败退出。
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or total_hint or 0)
            got = 0
            chunk = 64 * 1024
            last_emit = 0.0
            with open(zip_path, "wb") as f:
                while True:
                    # 用户点取消则立即中断下载。半截 zip 调用方会清掉 tmp，不会留垃圾。
                    if getattr(self, "_cancelled", False):
                        return 0
                    b = resp.read(chunk)
                    if not b:
                        break
                    f.write(b)
                    got += len(b)
                    now = time.time()
                    if now - last_emit < 0.3 and b:
                        continue
                    last_emit = now
                    elapsed = max(now - t0, 1e-6)
                    speed = got / elapsed
                    speed_mb = speed / 1048576
                    if total > 0:
                        pct = min(99, int(got * 100 / total))
                        remain_b = total - got
                        eta_s = int(remain_b / speed) if speed > 0 else 0
                        eta_str = (
                            f"{eta_s//60}分{eta_s%60}秒" if eta_s >= 60
                            else f"{eta_s}秒"
                        )
                        self.progress.emit(
                            pct,
                            f"下载中 {got/1048576:.1f}/{total/1048576:.1f}MB "
                            f"({pct}%) · {speed_mb:.2f}MB/s · 约剩 {eta_str}",
                        )
                    else:
                        self.progress.emit(
                            -1,
                            f"下载中 {got/1048576:.1f}MB · {speed_mb:.2f}MB/s",
                        )
        return total

    # ===== 完整 NSIS 整包安装支持 =====
    def _setup_asset_for(self):
        """在 release 资产里找「完整安装包」（NSIS setup.exe）。

        优先匹配 *china-setup*.exe（国内版整包，含完整 Python venv + working + cache，
        解压后 working/main.py 直接存在，启动按钮即可直开本体，无需再跑 host 初始化）；
        其次匹配 *setup*.exe。返回 (url, name, size, tag) 或 None（没有整包时回退 win32.zip host）。
        """
        if self.key not in self.REPOS:
            return None
        repo, *_ = self.REPOS[self.key]
        try:
            data = self._get_latest_release(repo)
        except Exception:
            return None
        tag = data.get("tag_name", "")
        best = None
        for a in data.get("assets", []):
            n = (a.get("name", "") or "").lower()
            if not n.endswith(".exe"):
                continue
            if "china-setup" in n:
                return a["browser_download_url"], n, int(a.get("size", 0) or 0), tag
            if "setup" in n and best is None:
                best = (a["browser_download_url"], n, int(a.get("size", 0) or 0), tag)
        return best

    def _ensure_7z(self, tmp=None):
        """返回可用的 7z.exe 路径（解 NSIS 必须 full 7z.exe；7za/7zr 解不了 NSIS）。

        优先级：
          1) 进程内缓存 _SEVENZIP_PATH（一次成功后后续 install 复用,不再装/下）
          2) 持久化 LAUNCHER_7Z_DIR\\7z.exe（成功装好后保留,跨次复用,跨进程复用）
          3) 已知位置：launcher .cache/7zportable/ + PATH + 全局 Program Files
          4) 兜底：下 NSIS 7z2602-x64.exe (1.58 MB),ShellExecuteW+runas 提权静默装
             到 LOCALAPPDATA\\Programs\\7-Zip\\ → 需要用户点一次 UAC 弹窗"是"。
             装好后 7z.exe 落到用户目录,主进程（无论是否 admin）都能直接调,
             后续所有 install 都直接命中 step 2。

        旧 step 4 链路（下 7zr.exe → 解 extra.7z 拿 7z.exe）已彻底删除：
        extra.7z 实际**不含** 7z.exe（os.walk 永远找不到）,UI 看上去一直在
        "测速/连接"，但实际永远解不出能解 NSIS 的 7z.exe。跑 6 次 740 全失败
        也是这条链路的副作用。

        返回 None 表示 4 步全失败（调用方应让用户手动装 7-Zip）。
        """
        import shutil as _sh
        LAUNCHER_CACHE_DIR = os.path.join(LAUNCHER_DIR, ".cache")

        def _verify(path, min_kb=500):
            """检查文件存在且 > min_kb KB, 可信返回 path, 否则 None。"""
            try:
                if path and os.path.isfile(path) and os.path.getsize(path) > min_kb * 1024:
                    return path
            except Exception:
                pass
            return None

        # 1) 进程内缓存
        cached = _verify(InstallWorker._SEVENZIP_PATH)
        if cached:
            return cached
        # 2) 持久化便携目录（成功装好后保留,跨 worker/跨 install 复用）
        persistent = _verify(os.path.join(LAUNCHER_7Z_DIR, "7z.exe"))
        if persistent:
            InstallWorker._SEVENZIP_PATH = persistent
            self._log(f"复用持久化 7z.exe: {persistent}")
            return persistent

        # 3) 已知位置：先扫 launcher 自己的 .cache/7zportable/（用户通常会装 7za）,
        #    再扫 PATH（scoop/choco 等可能装着 full 7z.exe）,再扫全局 Program Files。
        candidates = []
        # 3a) launcher .cache/7zportable/ 子目录
        if os.path.isdir(LAUNCHER_7Z_DIR):
            for name in ("7z.exe", "7za.exe", "7zr.exe"):
                p = _verify(os.path.join(LAUNCHER_7Z_DIR, name))
                if p:
                    candidates.append((f"launcher/.cache/7zportable/{name}", p))
        # 3b) PATH（含 7za/7zr 等独立控制台版,以及 scoop/choco 装的 7z）
        for name in ("7z", "7za", "7zr", "7z.exe", "7za.exe", "7zr.exe"):
            p = _verify(_sh.which(name) or "")
            if p:
                candidates.append((f"PATH/{name}", p))
        # 3c) 全局常见安装位置（含 x86、x64、ProgramW6432、显式 7-Zip 目录）
        roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 "C:/Program Files", "C:/Program Files (x86)",
                 os.environ.get("ProgramW6432"),
                 os.environ.get("LOCALAPPDATA"), "C:/Program Files/7-Zip"]
        seen = set()
        for base in roots:
            if not base or not os.path.isdir(base):
                continue
            for sub in ("7-Zip", ""):
                for name in ("7z.exe", "7za.exe", "7zr.exe"):
                    p = _verify(os.path.join(base, sub, name) if sub else os.path.join(base, name))
                    if p and p not in seen:
                        seen.add(p)
                        candidates.append((f"{base}/{sub}/{name}".replace("//", "/"), p))

        # 3-final) 任何候选如果是 full 7z.exe,直接返回（它已能解 NSIS）。
        # 按 candidates 顺序 = 偏好顺序（launcher > PATH > 全局）。
        for label, p in candidates:
            if os.path.basename(p).lower() == "7z.exe":
                InstallWorker._SEVENZIP_PATH = p
                self._log(f"复用 7z.exe: {label} -> {p}")
                return p

        # 没有任何 full 7z.exe（只有 7za/7zr 不行 → 它们解不了 NSIS）
        if candidates:
            self._log(
                f"已知位置只有 7za/7zr（不解 NSIS）：{[(c[0], os.path.basename(c[1])) for c in candidates[:5]]}"
            )
        else:
            self._log("已知位置都未发现 7-Zip，准备提权装 7z2602-x64.exe")

        # 4) 兜底：下 NSIS 7z2602-x64.exe + ShellExecuteW+runas 提权静默装到 LOCALAPPDATA。
        #    任何失败/取消都返回 None，调用方应报错让用户手动装 7-Zip 或放弃。
        return self._admin_install_7zip()

    def _admin_install_7zip(self):
        """兜底：下 NSIS 7z2602-x64.exe → ShellExecuteW+runas 提权静默装到 LOCALAPPDATA。

        NSIS installer (manifest=requiresAdministrator) 静默安装 /S 必须 admin,
        所以即使是写 LOCALAPPDATA 用户目录,也需要先弹一次 UAC 弹窗。
        ShellExecuteW("runas", ...) 触发 UAC,用户同意后 admin 子进程装到:
            %LOCALAPPDATA%\\Programs\\7-Zip\\7z.exe
        装好后主进程（non-admin）也能调,且落到用户目录不受系统保护。

        返回 7z.exe 路径或 None（失败/取消）。
        """
        import ctypes as _ct

        # 准备 installer 保存位置（避免污染 _dl_<key>/ 临时目录,跨 install/跨用户保留）
        installer_dir = os.path.join(LAUNCHER_DIR, ".cache")
        os.makedirs(installer_dir, exist_ok=True)
        setup_exe = os.path.join(installer_dir, "7z_installer.exe")

        # 0) 如果本地已有完整 NSIS installer (>1.4MB,典型 1.58MB),复用,不重下
        if os.path.isfile(setup_exe) and os.path.getsize(setup_exe) > 1_400_000:
            self._log(f"复用本地 NSIS installer: {setup_exe} ({os.path.getsize(setup_exe)/1048576:.1f}MB)")
        else:
            # 下 NSIS 7z2602-x64.exe (1.58MB)。优先测速 → 下到 installer_dir,
            # 总耗时通常 < 3s,且只下一次,跨次复用 (大缓存,跨次零下载)
            url_direct = "https://github.com/ip7z/7zip/releases/download/26.02/7z2602-x64.exe"
            cands = [(f"万载云 {nd}", nd + url_direct) for nd in self.WANZAIYUN_NODES]
            custom = (self.proxy or "").strip()
            if custom and custom not in self.WANZAIYUN_NODES:
                cands.append((f"万载云自定义 {custom}", custom + url_direct))
            _KNOWN_GH_PROXY = [
                "https://gh-proxy.org/",
                "https://ghproxy.com/",
                "https://cdn.gh-proxy.org/",
                "https://gh.xmly.dev/",
            ]
            for nd in _KNOWN_GH_PROXY:
                cands.append((f"备用 {nd}", nd + url_direct))
            cands.append(("GitHub 直链", url_direct))
            self.progress.emit(-1, f"准备 7-Zip NSIS installer：测速 {len(cands)} 个源…")
            scored = []
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=20) as ex:
                for r in ex.map(lambda it: (it[0], it[1], self._probe(it[1])), cands):
                    label, url, prob = r
                    ok, lat, cl = prob
                    if ok and cl > 0:
                        scored.append((label, url, lat))
                # 上面是 list comprehension 风格,等价的 map+filter:留给未来重构
            if not scored:
                self._log("7z2602-x64.exe 所有候选源都不可达,放弃自动准备")
                return None
            scored.sort(key=lambda x: x[2])
            last_err = None
            for label, url, lat in scored[:3]:  # 最多试 3 个源,够用
                if getattr(self, "_cancelled", False):
                    return None
                try:
                    self.progress.emit(-1, f"下 7-Zip installer：{label}（{lat*1000:.0f}ms）…")
                    if os.path.isfile(setup_exe):
                        try: os.remove(setup_exe)
                        except Exception: pass
                    self._stream_download(url, setup_exe, 0)
                    if getattr(self, "_cancelled", False):
                        return None
                    if not os.path.isfile(setup_exe) or os.path.getsize(setup_exe) < 1_400_000:
                        self._log(f"NSIS installer 文件异常（{os.path.getsize(setup_exe) if os.path.isfile(setup_exe) else 0}B）")
                        continue
                    self._log(f"NSIS installer 就绪: {setup_exe} ({os.path.getsize(setup_exe)/1048576:.1f}MB)")
                    break
                except Exception as e:
                    last_err = e
                    self._log(f"下 NSIS installer 失败({label}): {e}")
                    continue
            else:
                # 三个源都失败
                self._log(f"NSIS installer 全部失败: {last_err}")
                return None
            if not os.path.isfile(setup_exe) or os.path.getsize(setup_exe) < 1_400_000:
                self._log("NSIS installer 未达成,放弃")
                return None

        # 1) 提权静默装到 LOCALAPPDATA
        install_target = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "Programs", "7-Zip"
        )
        # NSIS /D= 路径必须无空格且 forward slashes；UNC/带空格路径常引发 NSIS 自身 bug,
        # 把 LOCALAPPDATA 一般是 C:\\Users\\<name>\\AppData\\Local,安全。
        # 若路径含空格：用短路径 \\?\\,否则直接用绝对路径。
        install_target_nsis = install_target.replace("/", "\\")
        # 如果子目录不存在,有些 NSIS installer 会自动创建,为稳我们 mkdir:
        try:
            os.makedirs(install_target_nsis, exist_ok=True)
        except Exception:
            pass

        args = f'/S /D="{install_target_nsis}"'
        self.progress.emit(-1, f"需要点一次 UAC 弹窗以安装 7-Zip（一次性）→ {install_target_nsis}")
        self._log(f"提权静默装 7-Zip NSIS: {setup_exe} {args}")
        try:
            rc = _ct.windll.shell32.ShellExecuteW(None, "runas", setup_exe, args, None, 0)  # SW_HIDE
        except Exception as e:
            self._log(f"ShellExecuteW 异常: {e}")
            return None
        # ShellExecuteW 返回值 > 32 表示成功(>32 = success),<=32 = error
        if rc <= 32:
            self._log(f"ShellExecuteW runas 失败 rc={rc} (用户可能点了'否'或未登录)")
            return None
        # ShellExecuteW 异步：我们轮询 7z.exe 是否出现在 install_target。
        # 静默 NSIS /S 通常 2-5 秒完成,最长 30 秒（防御性等更久）。
        self.progress.emit(-1, "等待 UAC + NSIS 静默安装完成…")
        target_7z = os.path.join(install_target_nsis, "7z.exe")
        for tick in range(120):  # 60 秒
            if getattr(self, "_cancelled", False):
                return None
            if os.path.isfile(target_7z) and os.path.getsize(target_7z) > 500 * 1024:
                InstallWorker._SEVENZIP_PATH = target_7z
                self._log(f"7-Zip 装好: {target_7z}")
                self.progress.emit(-1, f"7-Zip 就绪：{target_7z}")
                return target_7z
            time.sleep(0.5)
        self._log(f"提权装 7-Zip 超时未发现 7z.exe: {target_7z}")
        return None


    def _extract_nsis(self, setup_file, extract_dir):
        """用 7z 解 NSIS 整包到 extract_dir（NSIS 是公开格式，7z 23+ 直接支持）。"""
        sevenzip = self._ensure_7z(os.path.dirname(setup_file))
        if not sevenzip:
            raise RuntimeError(
                "解压完整安装包需要 7-Zip，但本机未找到且无法自动下载。\n"
                "请到 https://www.7-zip.org 安装 7-Zip 后重试，或重新打开原版启动器完成安装。"
            )
        os.makedirs(extract_dir, exist_ok=True)
        self.progress.emit(-1, "正在解压完整安装包（NSIS，约需 1-2 分钟）…")
        rc = subprocess.run(
            [sevenzip, "x", setup_file, f"-o{extract_dir}", "-y"],
            capture_output=True, text=True,
            creationflags=0x08000000,  # CREATE_NO_WINDOW：不弹黑窗
        )
        if rc.returncode != 0:
            raise RuntimeError(
                "7z 解压完整安装包失败：\n" + (rc.stderr or "")[:500]
                + "\n请把这段发我看看。"
            )

    def run(self):
        # 同 key 并发硬锁：拿不到锁直接退出（调用方守卫已拦，这里是兜底，防 worker 内部重入）
        _lock = InstallWorker._locks.setdefault(self.key, threading.Lock())
        if not _lock.acquire(blocking=False):
            self._log(f"同 key({self.key}) 已有 worker 在跑，本次直接放弃（防并发重复下载）")
            return
        try:
            self._log(f"==== 开始安装 {self.key} ====")
            tmp         = os.path.join(self.install_root, f"_dl_{self.key}")
            extract_dir = os.path.join(tmp, "_extract")
            install_dir = self.install_dir
            for q in (tmp, extract_dir):
                os.makedirs(q, exist_ok=True)

            # 1) 优先复用上次已下好的安装包（_dl_<key>/ 里），完全不打 GitHub API、不重下。
            #    用户之前下到一半/下完但解压失败留下的整包，本次重装直接复用，
            #    既能绕开「反复打 api.github.com 触发 403 限流」，又省 440MB 重下 + D 盘空间。
            local = self._scan_local_installer(tmp, self.key)
            need_download = True
            if local:
                zip_path, zip_name, zip_size, self._is_full = local
                tag = ""
                total = zip_size
                need_download = False
                self._log(f"发现本地安装包，直接复用（跳过 API+下载）：{zip_name} {zip_size/1048576:.0f}MB")
                self.progress.emit(100, f"已存在安装包（{zip_size/1048576:.0f}MB），跳过下载")
            else:
                # 2) 打 GitHub release API（带缓存，避免限流 403）查最新包
                self.progress.emit(-1, "正在查询最新 release…")
                setup = self._setup_asset_for()
                if setup:
                    zip_url, zip_name, zip_size, tag = setup
                    self._is_full = True
                else:
                    zip_url, zip_name, zip_size, tag = self._asset_for()
                    self._is_full = False
                zip_path = os.path.join(tmp, zip_name)
                total = 0
                # 文件名恰好匹配 API 返回的资产名 → 也算复用（不重复下）
                if os.path.isfile(zip_path):
                    _sz = os.path.getsize(zip_path)
                    _enough = (zip_size and _sz >= zip_size * 0.99) or (not zip_size and _sz > 100 * 1024)
                    if _enough:
                        total = _sz
                        need_download = False
                        self._log(f"复用已下载的安装包（{_sz/1048576:.1f}MB），跳过下载")
                        self.progress.emit(100, f"已存在完整安装包（{_sz/1048576:.1f}MB），跳过下载")

            # 用户在查 release / 测速 / 下载前就按了「取消」→ 收工
            if getattr(self, "_cancelled", False):
                self._cleanup_tmp(tmp)
                return

            # 目标已存在：可能是半装(host 引导包)。整包安装直接覆盖——先备份旧目录。
            if os.path.isdir(install_dir):
                if self._is_full:
                    bak = f"{install_dir}.host-bak-{int(time.time())}"
                    try:
                        shutil.move(install_dir, bak)
                        self.progress.emit(-1, f"已备份旧目录到 {bak}")
                    except Exception as e:
                        raise RuntimeError(
                            f"安装目录已存在且无法备份覆盖：{install_dir}\n"
                            f"请先卸载后再装。({e})"
                        )
                else:
                    raise RuntimeError(f"目标已存在：{install_dir}\n请先卸载旧版本后再装。")

            total_mb = zip_size / 1048576 if zip_size else 0
            kind_label = "完整安装包" if self._is_full else "host 引导包"

            if need_download:
                self.progress.emit(-1, f"准备下载 {zip_name}（约 {total_mb:.1f} MB）…")
                # 并发测速所有候选源（万载云 17 节点 + MirrorChyan + cnb + GitHub 直链），挑最快的
                scored = self._select_fastest(zip_url, tag, zip_name)
                if not scored:
                    raise RuntimeError(
                        "所有下载源测速均失败（万载云 17 节点 / MirrorChyan / cnb / GitHub 全超时）。\n"
                        "请检查本机网络是否能访问 GitHub，或稍后重试。"
                    )
                # 取前 3 名源依次尝试（失败换下一个，最多 3 次），避免单源抽风时无限重试/
                # 看起来「一直在换源重复下载」。每次失败删半截 zip，下次从头下。
                top = scored[:3]
                self._log(f"测速完成，候选 {len(scored)} 个，取前 {len(top)} 名依次尝试："
                          + "；".join(f"{l}({lt*1000:.0f}ms)" for l, _, lt in top))
                last_err = None
                for attempt, (label, cu, latency_s) in enumerate(top, 1):
                    if getattr(self, "_cancelled", False):
                        self._cleanup_tmp(tmp)
                        return
                    self._log(f"第{attempt}次下载，选源：{label}（延迟 {latency_s*1000:.0f}ms）")
                    self.progress.emit(
                        -1,
                        f"🚀 第{attempt}次下载，选源：{label}（延迟 {latency_s*1000:.0f}ms）",
                    )
                    try:
                        total = self._stream_download(cu, zip_path, zip_size)
                        break  # 成功即跳出重试循环
                    except Exception as e:
                        last_err = e
                        self._log(f"第{attempt}次下载失败：{e}")
                        self.progress.emit(-1, f"下载失败，换下一个源重试（{attempt}/{len(top)}）")
                        try:
                            if os.path.isfile(zip_path):
                                os.remove(zip_path)
                        except Exception:
                            pass
                    continue
                else:
                    # 3 次都失败：明确报错退出，不再静默重试
                    raise RuntimeError(
                        f"3 次下载均失败（已换 {len(top)} 个源）：{last_err}\n"
                        "请检查网络后重试，或填 MirrorChyan CDK 进一步加速。"
                    )

            real_size = os.path.getsize(zip_path) if os.path.isfile(zip_path) else 0
            if total <= 0:
                total = real_size
            self.progress.emit(100, f"下载完成 {real_size/1048576:.1f}MB, 准备解压")

            if not os.path.isfile(zip_path) or os.path.getsize(zip_path) < 100 * 1024:
                # 下载途中被取消：zip 不完整,直接清理 tmp 退出
                if getattr(self, "_cancelled", False):
                    self._cleanup_tmp(tmp)
                    return
                raise RuntimeError("下载失败或文件过小，请检查网络后重试")

            if getattr(self, "_cancelled", False):
                self._cleanup_tmp(tmp)
                return
            if self._is_full:
                # 整包：用 7z 解 NSIS，再做 PyAppify 内部名 → launcher key 对齐
                self._extract_nsis(zip_path, extract_dir)
                pyapp_key = self.REPOS[self.key][3]      # 如 ok-ef
                expected_exe = os.path.basename(self.app.get("exe", "") or "")
                launcher_key = os.path.splitext(expected_exe)[0] or self.key  # 如 ok-end-field
                # 对齐 data/apps/<pyapp_key> -> <launcher_key>
                inner_src = os.path.join(extract_dir, "data", "apps", pyapp_key)
                inner_dst = os.path.join(extract_dir, "data", "apps", launcher_key)
                if os.path.isdir(inner_src) and not os.path.exists(inner_dst):
                    try:
                        os.rename(inner_src, inner_dst)
                        self.progress.emit(-1, f"已对齐应用目录：{pyapp_key} → {launcher_key}")
                    except Exception as e:
                        self.progress.emit(-1, f"对齐应用目录失败（{e}），将尝试直接启动")
                # 对齐 host exe：<pyapp_key>.exe -> <launcher_key>.exe
                src_exe = os.path.join(extract_dir, pyapp_key + ".exe")
                if os.path.isfile(src_exe) and expected_exe and not os.path.isfile(os.path.join(extract_dir, expected_exe)):
                    try:
                        shutil.copy2(src_exe, os.path.join(extract_dir, expected_exe))
                        self.progress.emit(-1, f"已对齐 host 名：{pyapp_key}.exe → {expected_exe}")
                    except Exception as e:
                        self.progress.emit(-1, f"对齐 host 名失败（{e}），不影响启动")
                # 清理：删掉对齐后多余的旧 host exe（避免 install_dir 里残留两个 exe）
                if os.path.isfile(src_exe) and expected_exe:
                    try:
                        os.remove(src_exe)
                    except Exception:
                        pass
            else:
                # host 引导包：直接解 zip
                self.progress.emit(-1, "正在解压…")
                try:
                    with zipfile.ZipFile(zip_path) as zf:
                        zf.extractall(extract_dir)
                except zipfile.BadZipFile:
                    raise RuntimeError("下载到的不是有效 zip（可能被墙/被代理截断）。可尝试代理或 MirrorChyan CDK 重新下载。")

            self.progress.emit(-1, "正在整理文件…")
            # 自适应平铺：解压目录扫顶层
            #   - 顶层只有一个目录（如 ok-nte\ok-nte\... 或 ok-ef\ok-ef.exe）→ 整目录 move 到 install_dir
            #   - 顶层是多个文件/目录（如 ok-ww.exe, data\, python\）→ 整 extract move 到 install_dir
            top = sorted(os.listdir(extract_dir))
            if len(top) == 1 and os.path.isdir(os.path.join(extract_dir, top[0])):
                shutil.move(os.path.join(extract_dir, top[0]), install_dir)
            else:
                shutil.move(extract_dir, install_dir)

            # host 引导包（非整包）才需要做 host 名对齐；整包已在上面对齐过。
            if not self._is_full:
                expected_exe = os.path.basename(self.app.get("exe", "") or "")
                if expected_exe and os.path.isdir(install_dir):
                    target_exe = os.path.join(install_dir, expected_exe)
                    if not os.path.isfile(target_exe):
                        exes = sorted(
                            f for f in os.listdir(install_dir)
                            if f.lower().endswith(".exe") and os.path.isfile(os.path.join(install_dir, f))
                        )
                        if len(exes) == 1:
                            try:
                                shutil.copy2(os.path.join(install_dir, exes[0]), target_exe)
                                self.progress.emit(-1, f"已对齐 host 名：{exes[0]} → {expected_exe}")
                            except Exception as e:
                                self.progress.emit(-1, f"对齐 host 名失败（不影响解压）：{e}")

            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass

            if not os.path.isdir(install_dir):
                raise RuntimeError(f"安装目录未生成：{install_dir}")

            self.progress.emit(100, f"安装完成：{install_dir}")
            self.done.emit(install_dir, tag or "")
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            # 释放同 key 并发锁（覆盖 try 内所有 return / raise / 正常结束）
            try:
                _lock.release()
            except Exception:
                pass
            self._log(f"==== 结束安装 {self.key} ====")


class MirrorUpdater(QThread):
    """后台把目标 tag 拉到本地镜像仓库（只写 launcher/repos/<key>），发真实进度。"""
    progress = Signal(int, str)   # percent（-1 表示未知），text
    done = Signal(str)            # 本地仓库目录
    failed = Signal(str)

    def __init__(self, key, git_url, target_tag, parent=None):
        super().__init__(parent)
        self.key = key
        self.git_url = git_url
        self.target_tag = target_tag

    def _on_progress(self, line):
        pct, text = parse_git_progress(line)
        self.progress.emit(pct, text)

    def run(self):
        try:
            local = ensure_mirror(
                self.key, self.git_url, self.target_tag, self._on_progress
            )
            self.done.emit(local)
        except Exception as e:
            self.failed.emit(str(e))


# ===== 应用：把本地镜像同步到原启动器的 working/（直接覆盖，不备份）=====
# 说明：写的是官方 app 的 working/，属于官方本地安装目录，可写（用户已授权）。
# 不做整目录备份（占空间），但同步只覆盖"代码文件"，运行数据目录/数据库一律保留，
# 且原启动器本身可从仓库 checkout 任意版本做回滚，无需额外备份。

# working/ 里需要保留、绝不从镜像覆盖的运行数据路径（名匹配或后缀匹配）
# 运行数据目录：仅 working **顶层** 才保留（src/data/、src/configs/ 等嵌套同名源码目录必须同步，
# 不能被当成运行数据跳过——ok-end-field 的 src/data/skill_allowlist.py 就栽在这）。
_PRESERVE_TOPLEVEL = {
    "cache", "logs", "config", "configs", "custom_chars", "ok_tasks",
    "screenshots", "data", "ok_templates", "gift_configs",
}
# 工具 / 构建产物目录：任意层级都保留（嵌套的 __pycache__/.git/venv 也要跳过，
# 否则会误删源码目录里的 __pycache__ 触发批量删除拦截）。
_PRESERVE_ANYWHERE = {"__pycache__", ".git", "venv", ".venv"}
_PRESERVE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _is_preserved(rel):
    """rel 是相对 working 的路径（Path.parts）。顶层运行数据目录 OR 任意层工具目录 → 保留。"""
    return rel.parts[0] in _PRESERVE_TOPLEVEL or any(p in _PRESERVE_ANYWHERE for p in rel.parts)


def _sync_repo_to_working(src_dir, dst_dir):
    """从镜像 src_dir 智能同步到 dst_dir：覆盖代码文件，保留运行数据目录/数据库，
    并删除 working/ 中镜像已移除的孤儿代码文件（仅非保留路径）。

    返回 (ok: bool, msg: str)。返回前会对 dst 目录做最小写入（仅代码文件）+ 删除孤儿。
    """
    import shutil
    from pathlib import Path

    src = Path(src_dir)
    dst = Path(dst_dir)
    if not src.is_dir():
        return False, f"镜像目录不存在: {src_dir}"
    if not dst.is_dir():
        return False, f"目标 working 目录不存在: {dst_dir}"

    copied = skipped = 0
    for src_file in src.rglob("*"):
        if src_file.is_dir():
            continue
        rel = src_file.relative_to(src)
        # 跳过运行数据目录 / 数据库（顶层运行数据 + 任意层工具目录，见 _is_preserved）。
        if _is_preserved(rel):
            skipped += 1
            continue
        if src_file.suffix in _PRESERVE_SUFFIXES:
            skipped += 1
            continue
        dst_file = dst / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        copied += 1
    # 2026-09-07 修复（「app.json 写 v3.6.7、实际代码还是 v3.6.4」假版本号事故的一半根因）：
    # 镜像仓库如果只有 .git、工作区是空的（checkout 失败但被静默吞掉，见 ensure_mirror），
    # src.rglob("*") 什么都遍历不到 → copied=0，而原来照样 return True，
    # 于是 apply_mirror_to_working 以为同步成功，把 app.json 的 current_version 写成目标版本，
    # 可 working/ 里的代码压根没动 → 启动器显示 v3.6.7、跑起来窗口还是 v3.6.4。
    # 同步 0 个文件 = 明确失败，必须拦住，绝不写假版本号。
    if copied == 0:
        return False, (
            f"镜像目录里没有任何可同步的代码文件：{src_dir}\n"
            f"这通常意味着目标版本 checkout 失败（镜像仓库只有 .git、工作区为空）。\n"
            f"已中止更新，不会修改 app.json 的版本号。"
        )

    # 2026-09-07 修复（异环 v1.3.6→v1.3.12 暴露的第三种静默失败）：
    # 上游版本经常删文件（重构、重命名），只覆盖不删 → working/ 留下"新版本里已经不存在、
    # 但 working/ 里还活着"的孤儿代码文件。轻则 import 报错，重则启动器 UI 走老路径跑到死代码。
    # 例如 ok-nte v1.3.6→v1.3.12 中删了 src/ui/TeamScanner.py / src/ui/common.py /
    # src/ui/midi_player/__init__.py 三个文件，working/ 全留下来了——既不是 v1.3.6 也不是
    # v1.3.12，是个混合鬼胎。
    # 这里扫一遍 working/ 里非保留路径的文件，凡镜像目标版本已删的，一并清掉。
    deleted = 0
    src_files_norm = {str(p.relative_to(src)).replace("\\", "/")
                      for p in src.rglob("*") if p.is_file()}
    for dst_file in dst.rglob("*"):
        if dst_file.is_dir():
            continue
        rel = dst_file.relative_to(dst)
        # 保留路径（运行数据 / 用户配置 / 缓存 / DB / 工具目录）一概不动，见 _is_preserved。
        if _is_preserved(rel):
            continue
        if dst_file.suffix in _PRESERVE_SUFFIXES:
            continue
        rel_norm = str(rel).replace("\\", "/")
        if rel_norm not in src_files_norm:
            try:
                dst_file.unlink()
                deleted += 1
            except OSError:
                # 文件被占用 / 只读等；不强求，宁可留到下次更新
                pass
    return True, (
        f"已同步 {copied} 个代码文件，保留 {skipped} 个运行数据文件，"
        f"清理 {deleted} 个上游已删除的孤儿文件"
    )


def _proc_alive(key):
    """复查：进程表里还有没有该 key 的运行中实例（exe 镜像名 or pythonw 窗口标题）。

    与 _is_process_running 同源（tasklist /V CSV + GBK），只是这里没有 self，
    直接按 key 查。用于 kill 之后验证「真的杀掉了没有」。
    """
    try:
        import csv as _csv
        import io as _io
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {key}.exe", "/NH"],
            capture_output=True, text=True,
            encoding="gbk", errors="replace", creationflags=flags,
        )
        if f"{key}.exe" in out.stdout.lower():
            return True
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq pythonw.exe",
             "/V", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
            encoding="gbk", errors="replace", creationflags=flags,
        )
        for row in _csv.reader(_io.StringIO(out.stdout)):
            # CSV: image,pid,session,ses#,mem,status,user,cpu,window title
            if len(row) >= 9 and key in row[8].lower():
                return True
        return False
    except Exception:
        # 查不动就保守认定「还活着」，让调用方中止，绝不留下不一致状态
        return True


def _kill_app_process(app):
    """终止本 app 正在运行的原启动器进程。

    2026-09-07 修复（「已装 v3.6.7 / 实际跑着 v3.6.4」错位状态的根因）：
    原实现 **只** 用 PowerShell CIM 按 CommandLine 匹配 working 目录，但 PyAppify 打包的
    进程 **CommandLine 在 wmic/CIM 视角下被清空**（token 降权）——这一点 `_kill_app_by_title`
    自己的 docstring 里就写着。于是：
        Where-Object { $_ .CommandLine -like "*working_dir*" }   → 永远筛出 0 条
        Stop-Process -ErrorAction SilentlyContinue              → 一次都不执行
        PowerShell 退出码 0                                     → 函数 return True
    `apply_mirror_to_working` 误以为进程已死，继续 `_sync_repo_to_working` 覆盖 working/
    并写 `current_version=v3.6.7`，而 v3.6.4 进程全程活着 → 用户看到版本错位。

    现改为三段：
      ① 先试 CIM CommandLine（对非 PyAppify 的普通 python 进程仍然有效）
      ② 无条件再按窗口标题兜底（_kill_app_by_title —— 窗口标题稳定可见，PyAppify 也吃这招）
      ③ 收尾复查：仍有该 key 存活 → 明确 **return False**，让调用方中止更新，
         绝不留下「文件已换、进程还是老的」不一致状态。
    """
    working_dir = app.get("working", "")
    exe = app.get("exe", "")
    key = _pyapp_title_key(app)
    if not working_dir and not key:
        return True, "无 working / exe 路径，跳过终止"

    # ① CIM CommandLine（对普通 python 进程有效；PyAppify 进程 CommandLine 为空会漏掉，
    #    所以下面 ② 无条件补一次窗口标题兜底，不靠它的返回值）
    if working_dir:
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' or "
            "Name = 'pythonw.exe'\" | Where-Object { $_.CommandLine -like "
            f"\"*{working_dir}*\" }} | ForEach-Object {{ Stop-Process -Id "
            "$_.ProcessId -Force -ErrorAction SilentlyContinue }}"
        )
        try:
            # text=True 解码 PowerShell 输出可能因 GBK/UTF-8 不匹配抛 UnicodeDecodeError，
            # 显式 errors="replace" 保证 reader 线程不炸、主流程稳定。
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, errors="replace", timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            # 不致命：② 还有窗口标题兜底
            pass

    # ② 窗口标题兜底（PyAppify 唯一可靠线索，与「强制关闭」按钮同源）
    if key:
        try:
            _kill_app_by_title(key)
        except Exception:
            pass

    # ③ 复查：还有存活就明确报失败，让调用方中止更新而不是留下不一致状态
    if key and _proc_alive(key):
        return False, (
            f"仍有 {key} 进程在运行，未能终止。\n"
            f"可能原因：权限不足，或 UAC 提权弹窗被取消。\n"
            f"请手动关闭 {key} 窗口后重试更新。"
        )
    return True, "已终止运行中的进程"


def _kill_app_by_title(key):
    """按窗口标题关键字精确终止正在运行的原启动器进程。

    与 _is_process_running 监测同源：PyAppify 打包的启动器运行时进程名是内嵌
    pythonw.exe（无独立 ok-nte.exe 镜像名），且 CommandLine 在 wmic 视角被降权清空，
    无法靠 working 目录匹配——但 tasklist /V 的窗口标题稳定可见（如 "ok-nte v1.3.7"）。
    故直接 tasklist 拿 PID 列表后用 taskkill /PID /F 终止，纯 cmd、GBK、零编码坑。

    返回 (ok: bool, msg: str)。
    """
    try:
        import csv as _csv
        import io as _io
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq pythonw.exe", "/V", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
            encoding="gbk", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        killed = 0
        requested = 0
        for row in _csv.reader(_io.StringIO(out.stdout)):
            # CSV: image,pid,session,ses#,mem,status,user,cpu,window title
            if len(row) >= 9 and key in row[8].lower():
                pid = row[1].strip()
                if pid.isdigit():
                    r = subprocess.run(
                        ["taskkill", "/PID", pid, "/F", "/T"],
                        capture_output=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if r.returncode == 0:
                        killed += 1
                    else:
                        err = (r.stderr or r.stdout).decode("gbk", "replace")
                        if "拒绝访问" in err or r.returncode == 1:
                            # 普通权限被杀拒绝，按需提权重试（弹一次 UAC）。
                            # 注意：runas 是异步的、用户可能取消 UAC，
                            # 绝不能假装已杀掉——只计数「已发起请求」，
                            # 真正是否成功交给调用方 _proc_alive 复查兜底。
                            runas(
                                "taskkill.exe",
                                ["/PID", pid, "/F", "/T"],
                                os.environ.get("SystemRoot", ""),
                            )
                            requested += 1
        if killed or requested:
            parts = [f"已强制关闭 {killed} 个" ] if killed else []
            if requested:
                parts.append(f"已向管理员请求关闭 {requested} 个（若弹窗被取消，请在任务管理器手动结束）")
            return True, "；".join(parts) if parts else "未发现运行中的进程"
        return True, "未发现运行中的进程"
    except Exception as e:  # noqa: BLE001
        return False, f"终止进程失败: {e}"


def _read_working_version(app):
    """回读 working/ 里代码的**真实**版本号（不是 app.json 的展示字段，是 config.py 里
    `version = "..."` 那一行）。

    返回版本字符串（含可选 v 前缀）或 None（找不到/读不出）。
    这是「防假更新」的终检：同步完必须让这里读到的版本 == 目标版本，才允许写 app.json。
    候选路径按各 ok-script 系实际布局：顶层 config.py（ok-ww）与 src/config.py（ok-nte）。
    """
    import re as _re
    working_dir = app.get("working", "")
    if not working_dir:
        return None
    candidates = [
        os.path.join(working_dir, "config.py"),
        os.path.join(working_dir, "src", "config.py"),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            txt = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', txt, _re.M)
        if m:
            return m.group(1)
    return None


def apply_mirror_to_working(app, target_version, mirror_dir):
    """把 launcher/repos/<key>/ 镜像的 target_version 应用到原启动器 working/。

    流程：①终止运行进程 ②从镜像同步代码文件到 working/ ③**回读 working 真实版本核对**
         ④ 一致才更新 app.json 的 current_version，不一致则**拒绝写入**（绝不留假更新）。
    返回 (ok: bool, msg: str)。失败时绝不半途修改 app.json。
    """
    import json

    working_dir = app.get("working", "")
    app_json = app.get("app_json", "")
    if not working_dir or not app_json:
        return False, "缺少 working/app_json 路径配置"

    ok, msg = _kill_app_process(app)
    if not ok:
        return False, msg

    ok, msg = _sync_repo_to_working(mirror_dir, working_dir)
    if not ok:
        return False, msg

    # 2026-09-07 终极防假更新：**回读 working/ 里代码的真实版本**，必须 == 目标版本。
    # 同步 0 文件（镜像空）、或配置/版本文件没被覆盖、或镜像本身 corrupt，都会在这里被抓出来；
    # 抓出来就**绝不写 app.json**——宁可让用户看到「更新失败」，也不要留下
    # 「显示 v1.3.12、跑起来却是 v1.3.6」的薛定谔状态（本案两次事故的同一张脸）。
    real_version = _read_working_version(app)
    if real_version is None:
        return False, (
            f"代码文件已同步，但 working/ 里读不到真实版本号（config.py version 字段缺失）。\n"
            f"已中止写入 app.json，未留下假版本号。请检查 working/ 是否完整。"
        )
    if _normalize_tag(real_version) != _normalize_tag(target_version):
        return False, (
            f"同步完成但 working/ 真实版本（{real_version}）≠ 目标版本（{target_version}）。\n"
            f"这通常意味着版本文件没被覆盖（镜像可能不完整）。\n"
            f"已中止写入 app.json，未留下假版本号。"
        )

    # 同步成功且真实版本核对一致，再更新 app.json 的当前版本（失败也不影响已同步的代码）
    try:
        with open(app_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["current_version"] = target_version
        # 清掉原启动器可能残留的更新中间态
        for k in ("update_state", "update_target_version", "update_error"):
            data.pop(k, None)
        with open(app_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        return False, f"代码已同步成功且版本核对通过，但 app.json 写入失败：{e}（可手动修改 current_version）"

    return True, f"已应用 {target_version} 到 working/（已回读核对 working 真实版本一致）"


class ApplyWorker(QThread):
    """后台执行 apply_mirror_to_working，发进度/完成/失败信号。"""
    progress = Signal(str)
    done = Signal(bool, str)   # ok, msg

    def __init__(self, app, target_version, mirror_dir, parent=None):
        super().__init__(parent)
        self.app = app
        self.target_version = target_version
        self.mirror_dir = mirror_dir

    def run(self):
        try:
            self.progress.emit("正在终止应用进程…")
            ok, msg = _kill_app_process(self.app)
            if not ok:
                self.done.emit(False, msg)
                return
            self.progress.emit("正在同步代码到 working 目录（保留运行数据）…")
            ok, msg = _sync_repo_to_working(self.mirror_dir, self.app["working"])
            if not ok:
                self.done.emit(False, msg)
                return
            self.progress.emit("正在更新 app.json 当前版本…")
            import json
            with open(self.app["app_json"], "r", encoding="utf-8") as f:
                data = json.load(f)
            data["current_version"] = self.target_version
            for k in ("update_state", "update_target_version", "update_error"):
                data.pop(k, None)
            with open(self.app["app_json"], "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.done.emit(True, f"已应用 {self.target_version} 到 working/")
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, f"应用失败：{e}")


# ===== 仅读取的工具函数（不写任何 app 目录） =====
def load_app_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _git_run(git, args, repo_dir, timeout=120):
    """跑一条 git 命令，返回 (returncode, stdout, stderr)。

    统一：CREATE_NO_WINDOW（不弹黑窗）、UTF-8 解码 + errors=replace
    （路径可能含中文，GBK/UTF-8 混排也不能崩）。
    """
    import subprocess as _sp
    r = _sp.run([git] + list(args), cwd=repo_dir,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _git_repo_dir(app):
    """generic 应用的 git 仓库目录（就是 exe 所在目录）。目录不是 git 仓库返回 ""。"""
    exe = app.get("exe", "") or ""
    d = os.path.dirname(exe) or ""
    if d and os.path.isdir(os.path.join(d, ".git")):
        return d
    return ""


def _git_has_tracked_changes(repo_dir):
    """是否有**受控文件**被改动/暂存。

    注意只看非 '??' 行：未跟踪文件（如用户自己的 .bak、临时脚本）不影响 pull，
    但受控文件被改过就不能自动更新，否则 git 会拒绝甚至覆盖用户改动。
    """
    git = GitVersionFetcher._find_git()
    if not git or not repo_dir:
        return True  # 判不出来按“有改动”处理，宁可不更新
    try:
        rc, out, _ = _git_run(git, ["status", "--porcelain"], repo_dir, timeout=30)
        if rc != 0:
            return True
        for line in out.splitlines():
            # porcelain 前两字符是状态；'??' = 未跟踪，'!!' = 已忽略
            if line[:2].strip() and not line.startswith("??") and not line.startswith("!!"):
                return True
        return False
    except Exception:
        return True


def _git_tag_version(app):
    """通用程序（generic）版本：从安装目录的本地 git 仓库读最新 tag。

    适用场景：既不是 ok-script 系（无 app.json），也不是奇想盒那种 exe+whl
    形态的独立程序。典型如绝区零一条龙——它自带 git 仓库并自行增量更新，
    exe 又是 PyInstaller 打包（**没有 Windows 版本资源**，_exe_file_version
    读出来是空），所以唯一可靠的版本来源就是本地 git tag。

    返回干净版本号（如 'v2.5.1'）；读不到返回 ""（调用方回退占位文案）。
    全程只读本地仓库、不联网、不启动任何 exe。
    """
    exe = app.get("exe", "") or ""
    repo_dir = os.path.dirname(exe) or ""
    if not repo_dir or not os.path.isdir(os.path.join(repo_dir, ".git")):
        return ""
    git = GitVersionFetcher._find_git()
    if not git:
        return ""
    try:
        import subprocess as _sp
        r = _sp.run([git, "describe", "--tags", "--abbrev=0"], cwd=repo_dir,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
        v = (r.stdout or "").strip()
        return v if v else ""
    except Exception:
        return ""


def _pyapp_title_key(app):
    """返回用于匹配 PyAppify 窗口标题的内部名（运行态判定 / 强制关闭共用）。

    PyAppify 启动后的窗口标题固定为 '{name} v{ver}'，name 取自 app.json 的 name
    字段，**不等于 exe 文件名**。例如 ok-end-field 的 exe 叫 ok-end-field.exe，但窗口
    标题是 'ok-ef v1.0.83'（app.json name='ok-ef'）。若仍用 exe 基名做标题匹配，会
    永远匹配不到 → 运行态判定 / 强制关闭全部失效（终末地永远显示「已安装」即此因）。
    故优先读 app.json 的 name；读不到（旧包 / 缺配置）才回退 exe 基名，保证不回归。
    """
    try:
        name = (load_app_json(app.get("app_json", "")).get("name", "") or "").strip()
    except Exception:
        name = ""
    if name:
        return name.lower()
    exe = app.get("exe", "") or ""
    return os.path.basename(exe).lower().removesuffix(".exe")


def get_current_profile(data):
    """返回当前 profile 字典（根据 current_profile 从 profiles 里找）。"""
    name = data.get("current_profile", "China")
    for p in data.get("profiles", []) or []:
        if p.get("name") == name:
            return p
    if data.get("profiles"):
        return data["profiles"][0]
    return {}


def make_icon(path):
    try:
        if path and os.path.isfile(path):
            pm = QPixmap(path)
            if not pm.isNull():
                return QIcon(pm)
    except Exception:
        pass
    try:
        return FluentIcon.GAME.icon()
    except Exception:
        return QIcon()


def _sum_size(path):
    """递归计算文件/目录字节数。不存在返回 0；被占用的文件跳过不抛异常。"""
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def _human_size(n):
    """字节数转人类可读（B / KB / MB / GB）。"""
    try:
        n = int(n)
    except Exception:
        return "?"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n/1024/1024:.1f} MB"
    return f"{n/1024/1024/1024:.2f} GB"


# ================= 本地游戏本体扫描（显卡驱动式「检测到游戏→引导装助手」） =================
# 2026-08-29 在用户本机实测过的识别方式（证据）：
#   - WeGame 鸣潮：注册表 HKLM\...\Uninstall\鸣潮 的 InstallSource 直接就是游戏根
#     （D:\WeGameApps\rail_apps\Wuthering Waves(2002137)），本体 exe 在
#     Client\Binaries\Win64\Client-Win64-Shipping.exe（深 3）
#   - TapTap 异环：D:\Taptap\PC Games\714119\Neverness To Everness\...，
#     本体 exe 在 Client\WindowsNoEditor\HT\Binaries\Win64\HTGame.exe（深 6，无注册表项）
#   - TapTap 终末地：D:\Taptap\PC Games\232326\games\Endfield Game\Endfield.exe（深 2）
# 原则：**注册表/渠道目录只当「线索」，最终以标志性 exe 的存在为准**——
#   实测注册表里「鸣潮助手」（WeGame 官方 aki 助手）也含"鸣潮"二字，但它的目录里
#   没有游戏本体 exe，天然不会误报；关键词 "NTE" 会误命中 "Python Interpreter"，
#   已从关键词表剔除。
GAME_SIGNATURES = {
    "ok-nte": {
        "display": "异环",
        "keywords": ["异环", "neverness to everness"],   # 注册表 DisplayName 小写匹配
        "game_exe": "HTGame.exe",
    },
    "ok-ww": {
        "display": "鸣潮",
        "keywords": ["鸣潮", "wuthering waves"],
        "game_exe": "Client-Win64-Shipping.exe",
    },
    "ok-end-field": {
        "display": "终末地",
        "keywords": ["终末地", "endfield"],
        "game_exe": "Endfield.exe",
    },
}

# walk 找 exe 的最大目录深度（异环 HTGame.exe 从渠道 id 目录起算深 6，留 1 层余量）
_GAME_SCAN_MAX_DEPTH = 7
# walk 剪枝：纯工程/缓存目录直接跳过，省时间
_GAME_SCAN_PRUNE = {".git", "__pycache__", "tcls", "wegamelauncher", "engine",
                    "content", "paks", "plugins"}


def _iter_uninstall_entries():
    """遍历 3 个 Uninstall 键，yield (DisplayName, InstallSource, InstallLocation, UninstallString)。"""
    import winreg
    for hive, path in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ):
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i); i += 1
            except OSError:
                break
            try:
                k = winreg.OpenKey(root, sub)
            except OSError:
                continue

            def _q(name, _k=k):
                try:
                    v, _ = winreg.QueryValueEx(_k, name)
                    return str(v)
                except OSError:
                    return ""
            yield (_q("DisplayName"), _q("InstallSource"), _q("InstallLocation"),
                   _q("UninstallString"))


def _channel_game_roots():
    """常见渠道游戏库根目录（存在才返回）。实测用户本机有效的是 TapTap 与 WeGame rail_apps。"""
    roots = []
    for drv in "CDEF":
        for rel in ("Taptap/PC Games", "WeGameApps/rail_apps"):
            p = f"{drv}:/{rel}"
            if os.path.isdir(p):
                roots.append(p)
    return roots


def _find_exe_limited(root, exe_name, max_depth=_GAME_SCAN_MAX_DEPTH):
    """限深 walk 找 exe。命中返回完整路径，否则 ""。"""
    root = os.path.normpath(root)
    base = root.count(os.sep)
    exe_low = exe_name.lower()
    for cur, dirs, files in os.walk(root):
        if cur.count(os.sep) - base >= max_depth:
            dirs[:] = []          # 到深限，不再下钻
        low = {f.lower() for f in files}
        if exe_low in low:
            p = os.path.join(cur, exe_name)
            if os.path.isfile(p):
                return p
        dirs[:] = [d for d in dirs if d.lower() not in _GAME_SCAN_PRUNE]
    return ""


def scan_local_game(key):
    """扫描本机某个游戏本体。命中返回游戏 exe 完整路径，否则 ""。

    线索来源（按序）：
      1) 注册表 Uninstall 项里 DisplayName 含关键词 → 取 InstallSource/InstallLocation/
         UninstallString 所在目录当候选根
      2) 渠道游戏库（Taptap/PC Games、WeGameApps/rail_apps）下每个子目录当候选根
    对每个候选根限深 walk 找标志性 exe——exe 存在才算数（线索会骗人，exe 不会）。
    """
    sig = GAME_SIGNATURES.get(key)
    if not sig:
        return ""
    exe = sig["game_exe"]
    kws = sig["keywords"]
    cands = []

    # 1) 注册表线索
    for name, src, loc, unins in _iter_uninstall_entries():
        if not name or not any(kw in name.lower() for kw in kws):
            continue
        for p in (src, loc, os.path.dirname((unins or "").strip('"'))):
            p = (p or "").strip().strip('"')
            if p and os.path.isdir(p):
                cands.append(os.path.normpath(p))

    # 2) 渠道库兜底
    for base in _channel_game_roots():
        try:
            for sub in os.listdir(base):
                p = os.path.join(base, sub)
                if os.path.isdir(p):
                    cands.append(os.path.normpath(p))
        except OSError:
            continue

    # 逐候选找（去重防重复 walk 大目录）
    seen = set()
    for root in cands:
        if root in seen:
            continue
        seen.add(root)
        hit = _find_exe_limited(root, exe)
        if hit:
            return hit
    return ""


def _exe_file_version(path):
    """读 exe 的 FileVersion 资源（如 "2.1.1"），读不到返回 ""。"""
    try:
        from ctypes import wintypes  # 局部导入：模块级未引入 wintypes（与 send_to_trash 同风格）
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, data):
            return ""
        val = ctypes.c_void_p()
        ln = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(
                data, "\\VarFileInfo\\Translation", ctypes.byref(val), ctypes.byref(ln)):
            return ""
        trans = ctypes.cast(val, ctypes.POINTER(wintypes.WORD * 2)).contents
        key = "\\StringFileInfo\\%04x%04x\\FileVersion" % (trans[0], trans[1])
        if not ctypes.windll.version.VerQueryValueW(data, key, ctypes.byref(val), ctypes.byref(ln)):
            return ""
        return ctypes.wstring_at(val, ln.value - 1).strip()
    except Exception:
        return ""


def _site_pkg_version(lib_dir, pkg):
    """从 site-packages 里的 <pkg>-<ver>.dist-info 目录名读已安装包版本。"""
    try:
        pre = (pkg + "-").lower()
        for n in os.listdir(lib_dir):
            ln = n.lower()
            if ln.startswith(pre) and ln.endswith(".dist-info"):
                return n[len(pkg) + 1:-len(".dist-info")]
    except Exception:
        pass
    return ""


def _dir_writable(d):
    """真写一个临时文件测可写性——os.access 在 Windows UAC 虚拟化下会谎报 True。"""
    try:
        if not os.path.isdir(d):
            return False
        p = os.path.join(d, "__wb_wtest__")
        with open(p, "w") as f:
            f.write("x")
        os.remove(p)
        return True
    except Exception:
        return False


def _embedded_user_site(py_dir):
    """内嵌 python 对应的「用户级」site-packages（pip 不可写时的静默回退落点）。

    %APPDATA%\\Python\\Python3xx\\site-packages。实测（2026-10-02）：该目录在
    sys.path 里排在内嵌 site-packages **之前**，两边都装时 App import 到的是它。
    """
    try:
        best = ""
        for n in os.listdir(py_dir):
            ln = n.lower()
            # 注意：目录里同时有 python3.dll（ABI 转发壳）和 python312.dll（真身），
            # 必须取版本号最长的那个，否则会拼出不存在的 Python3 用户目录
            if ln.startswith("python3") and ln.endswith(".dll"):
                v = ln[6:-4]
                if v.isdigit() and len(v) > len(best):
                    best = v
        if best:
            base = os.environ.get("APPDATA", "")
            if base:
                return os.path.join(base, "Python",
                                    "Python%s" % best, "site-packages")
    except Exception:
        pass
    return ""


def _lite_backend_version(app):
    """lite 助手的后端版本——按 sys.path 的真实 import 优先级找：用户目录 > 内嵌。

    注意：奇想盒有**三套互不相干的版本号**：前端 App（exe FileVersion，如 2.1.1）、
    后端 Python 包（如 2.4.9）、仓库 release tag（如 3.1.0）。必须分开显示，
    否则用户会以为「选了 2.4.6 却更新成 2.4.9」。

    2026-10-02 实测教训：pip 在目标目录不可写时会静默把包装进用户目录并返回 0
    （启动器曾误报"后端更新完成"，卡片却显示"未知"）——而用户目录在 sys.path
    里排在 site-packages 之前、App 真正 import 的就是它，所以必须先查它。
    """
    emb = os.path.join(os.path.dirname(app.get("exe", "") or ""), "python-embedded")
    us = _embedded_user_site(emb)
    v = _site_pkg_version(us, "whimbox") if us else ""
    if v:
        return v
    return _site_pkg_version(os.path.join(emb, "Lib", "site-packages"), "whimbox")


class SelfUpdateWorker(QThread):
    """启动器自身更新检查：查本项目 GitHub releases → 与 APP_VERSION 比较。

    与 LiteReleaseCheckWorker 的区别：
      - 查的是启动器自己的仓库（不是被管理的游戏）
      - 关心「有没有比 APP_VERSION 新的正式版」，预发布（prerelease）默认不提示，
        除非用户显式要求（include_pre=True）
      - 资产认 game-launcher-hub-*.exe（单文件 exe），下载复用 LiteDownloadWorker
        （万载云多节点测速），所以国内直连 GitHub 被掐也能下

    同样带本地缓存（TTL=RELEASE_CACHE_TTL）：api.github.com 未登录限 60 次/小时，
    启动就查一次的话必须缓存，否则一天开几十次就 403 了。
    """

    done = Signal(object)   # dict: {current, latest, has_new, prerelease, body, url, size, from_cache}
    failed = Signal(str)

    def __init__(self, repo, include_pre=False, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._include_pre = include_pre

    def run(self):
        try:
            owner, name = self._repo.split("/")
            cache_file = os.path.join(LAUNCHER_CACHE_DIR,
                                      f"selfrelease_{owner}_{name}.json")
            os.makedirs(LAUNCHER_CACHE_DIR, exist_ok=True)

            data = None
            from_cache = False
            # 1) 缓存命中且未过期 → 直接用，零 API 请求
            if os.path.isfile(cache_file):
                try:
                    with open(cache_file, encoding="utf-8") as f:
                        cached = json.load(f)
                    if (time.time() - cached.get("_fetched_at", 0)) < RELEASE_CACHE_TTL:
                        data, from_cache = cached.get("data"), True
                except Exception:
                    pass

            # 2) 打 API（用 releases 而非 /latest：要自己过滤 draft/prerelease）
            if data is None:
                url = (f"https://api.github.com/repos/{owner}/{name}"
                       f"/releases?per_page=20")
                req = urllib.request.Request(url, headers={
                    "User-Agent": "game-launcher-hub",
                    "Accept": "application/vnd.github+json",
                })
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        rels = json.loads(resp.read().decode())
                except urllib.error.HTTPError as e:
                    if e.code == 403:
                        # 限流：有缓存就拿过期缓存兜底，没有才报错
                        if os.path.isfile(cache_file):
                            try:
                                with open(cache_file, encoding="utf-8") as f:
                                    data = json.load(f).get("data")
                                if data:
                                    from_cache = True
                            except Exception:
                                pass
                        if not data:
                            raise RuntimeError(
                                "GitHub API 触发限流（HTTP 403: rate limit exceeded）。\n"
                                "未登录调用 api.github.com 限 60 次/小时。\n"
                                "请稍等约 1 小时再试。")
                    else:
                        raise

                if data is None:
                    data = self._pick(rels or [])
                    try:
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump({"_fetched_at": time.time(), "data": data},
                                      f, ensure_ascii=False)
                    except Exception:
                        pass

            data = dict(data or {})
            data["current"] = APP_VERSION
            data["from_cache"] = from_cache
            self.done.emit(data)
        except Exception as e:
            self.failed.emit(str(e))

    def _pick(self, rels):
        """从 releases 列表里挑「应该提示的那个版本」。

        规则：draft 一律忽略；预发布只在 include_pre 时才参与；其余按版本号取最大。
        """
        cur = APP_VERSION
        best = None
        for r in rels:
            if r.get("draft"):
                continue
            tag = (r.get("tag_name") or "").strip()
            if not tag:
                continue
            pre = bool(r.get("prerelease")) or is_prerelease(tag)
            if pre and not self._include_pre:
                continue
            if not re.match(r"^v?\d", tag):
                continue
            if best is None or compare_version(tag, best["latest"]) > 0:
                best = self._to_dict(r, tag, pre)
        if best is None:
            return {"latest": "", "has_new": False, "prerelease": False,
                    "body": "", "url": "", "size": 0}
        best["has_new"] = compare_version(best["latest"], cur) > 0
        return best

    @staticmethod
    def _to_dict(r, tag, pre):
        """取出下载所需的 exe 资产信息（认 .exe，跳过 .blockmap 等附属文件）。"""
        url, size = "", 0
        for a in r.get("assets") or []:
            name = (a.get("name") or "").lower()
            if name.endswith(".exe"):
                url = a.get("browser_download_url") or ""
                try:
                    size = int(a.get("size") or 0)
                except Exception:
                    size = 0
                break
        return {"latest": tag, "prerelease": pre,
                "body": r.get("body") or "", "url": url, "size": size}


class LiteReleaseCheckWorker(QThread):
    """lite 助手更新检查：GitHub releases/latest → (tag, 安装包资产 URL, release body)。"""

    done = Signal(object)   # dict: {tag, exe, whl, body, exe_size, whl_size}
    failed = Signal(str)

    def __init__(self, owner, repo, parent=None):
        super().__init__(parent)
        self._owner, self._repo = owner, repo

    def run(self):
        try:
            # 一次拉最近 20 个 release：首个即 latest；每个 release 自带前端 exe /
            # 后端 whl 资产信息，同时供「查看版本」下拉与「更新到任意版本」使用
            url = ("https://api.github.com/repos/%s/%s/releases?per_page=20"
                   % (self._owner, self._repo))
            req = urllib.request.Request(url, headers={
                "User-Agent": "game-launcher-hub",
                "Accept": "application/vnd.github+json",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                rels = json.loads(resp.read().decode())

            def pick(assets):
                """从 release 资产里取 (前端 exe URL, 后端 whl URL)。"""
                exe_u, whl_u = "", ""
                for a in assets or []:
                    an = (a.get("name") or "").lower()
                    if an.startswith("whimbox_app-setup-") and an.endswith(".exe"):
                        exe_u = a.get("browser_download_url") or ""
                    elif an.endswith(".whl"):
                        whl_u = a.get("browser_download_url") or ""
                return exe_u, whl_u

            versions = []
            for r in rels or []:
                t = (r.get("tag_name") or "").strip()
                if not t:
                    continue
                exe_u, whl_u = pick(r.get("assets"))
                versions.append({"tag": t, "body": r.get("body") or "",
                                 "exe": exe_u, "whl": whl_u})

            latest = versions[0] if versions else {
                "tag": "", "body": "", "exe": "", "whl": ""}
            self.done.emit({"tag": latest["tag"], "exe": latest["exe"],
                            "whl": latest["whl"], "body": latest["body"],
                            "versions": versions})
        except Exception as e:
            self.failed.emit(str(e))


class LiteDownloadWorker(QThread):
    """lite 助手更新包下载：万载云多节点测速选源，按延迟名次依次回退。

    直连 GitHub release 资产在国内会被掐（Remote end closed connection without
    response），所以复用 ok-script 卡同款方案：并发零流量探测（HEAD / Range 0-0）
    万载云节点（带协议 + 去协议两种拼法）+ config.json 自定义反代 + GitHub 直链，
    按延迟挑最快的下；下载中途断掉换下一名（前 3 名），全部失败才报错。
    """

    progress = Signal(int, int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, url, save_path, parent=None, key=""):
        super().__init__(parent)
        self._url = url
        self._save = save_path
        self._cancelled = False
        # key 用于查 Mirror酱 的 rid；不传就跳过 Mirror酱 候选源（保持旧行为）
        self._key = key

    def cancel(self):
        self._cancelled = True

    def _candidates(self):
        """(label, url) 候选源列表，顺序无关（之后按实测延迟排序）。"""
        cands = [("GitHub 直链", self._url)]
        # Mirror酱（有 CDK + 该 key 配了 rid 才进候选；拿不到直链就静默跳过）
        rid = mirrorchyan_rid_for(getattr(self, "_key", "") or "")
        cdk = ""
        try:
            cdk = (_load_cfg_safe().get("mirrorchyan_cdk") or "").strip()
        except Exception:
            cdk = ""
        if rid and cdk:
            got = mirrorchyan_latest(rid, cdk, user_agent="WorkBuddy-OKLauncher")
            if got:
                cands.append(("Mirror酱(CDK)", got[0]))
        if self._url.startswith("https://github.com/"):
            no_proto = self._url[len("https://"):]
            nodes = list(InstallWorker.WANZAIYUN_NODES)
            # config.json 里单独配的万载云反代域名，排最前（用户特意配的）
            custom = ""
            try:
                cfg_path = os.path.join(LAUNCHER_DIR, "config.json")
                if os.path.isfile(cfg_path):
                    with open(cfg_path, encoding="utf-8") as f:
                        custom = (json.load(f).get("wanzaiyun_proxy", "") or "").strip()
            except Exception:
                custom = ""
            if custom and custom not in nodes:
                nodes.insert(0, custom)
            for nd in nodes:
                cands.append(("万载云 %s" % nd, nd + self._url))
                cands.append(("万载云 %s(noproto)" % nd, nd + no_proto))
        return cands

    def run(self):
        try:
            cands = self._candidates()
            # 并发零流量测速：只收响应头 / 1 字节，挑延迟最低且有真文件的源
            import concurrent.futures as _cf

            def _test(item):
                label, url = item
                ok, lat, cl = _probe_url(url)
                return (label, url, ok, lat, cl)

            scored = []
            with _cf.ThreadPoolExecutor(max_workers=20) as ex:
                for label, url, ok, lat, cl in ex.map(_test, cands):
                    # Content-Length>0 说明该源真有这个文件（防代理对坏 URL 返回 200 空响应）
                    if ok and cl > 0:
                        scored.append((label, url, lat))
            if self._cancelled:
                self.failed.emit("已取消")
                return
            scored.sort(key=lambda x: x[2])
            order = scored[:3] or [("GitHub 直链", self._url, 0.0)]
            errs = []
            for label, url, _lat in order:
                if self._cancelled:
                    self.failed.emit("已取消")
                    return
                try:
                    self._download_one(url)
                except InterruptedError:
                    self.failed.emit("已取消")
                    return
                except Exception as e:
                    errs.append("%s：%s" % (label, e))
                    continue
                self.finished_ok.emit(self._save)
                return
            # 全部失败：汇总每个试过的源的报错（最快的源排最前）
            self.failed.emit("；".join(errs) or "所有下载源均失败（含 GitHub 直链）")
        except Exception as e:
            self.failed.emit(str(e))

    def _download_one(self, url):
        """从单个源下载，成功返回（文件>0 字节），失败/取消抛异常。"""
        os.makedirs(os.path.dirname(self._save), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "game-launcher-hub"})
        with urllib.request.urlopen(req, timeout=60) as resp, \
                open(self._save, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if self._cancelled:
                    raise InterruptedError("已取消")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    self.progress.emit(done, total)
        if self._cancelled:
            raise InterruptedError("已取消")
        if os.path.getsize(self._save) <= 0:
            raise RuntimeError("下载的文件为空")


class LitePipWorker(QThread):
    """用奇想盒内嵌 python 执行 pip install whl（官方「手动更新后端」的等价操作）。

    后端实测装在 <App目录>/python-embedded/Lib/site-packages/whimbox，
    所以内嵌 python 装 whl 与官方按钮效果一致。
    """

    finished_ok = Signal(str)
    failed = Signal(str)
    progress_text = Signal(str)   # pip 实时输出的一行尾巴 → UI 拼进卡片状态里
    progress = Signal(int)        # 从 pip 输出解析出的真实百分比（0-100，-1=解析不到）

    def __init__(self, python_exe, whl_path, parent=None):
        super().__init__(parent)
        self._py = python_exe
        self._whl = whl_path
        self._cancelled = False
        self._proc = None
        self._ps = None
        self._poll_interval = 1.0   # 轮询 pip 输出的间隔（测试可置 0）
        self._log_off = 0           # pip 日志已读到的位置（增量读）
        self._uninst_done = 0       # 已卸载包数
        self._pkg_total = 0         # Installing collected packages 里的总包数

    def cancel(self):
        self._cancelled = True
        for p in (self._proc, self._ps):
            if p:
                try:
                    p.kill()
                except Exception:
                    pass

    @staticmethod
    def _parse_percent(text):
        """从 pip 的一行输出里解析真实进度：优先 "43/100"，其次 "45%"，都没有返回 -1。"""
        import re as _re
        m = _re.search(r"(\d+)\s*/\s*(\d+)", text or "")
        if m:
            try:
                a, b = int(m.group(1)), int(m.group(2))
                if b > 0 and a <= b:
                    return max(0, min(100, int(a * 100 / b)))
            except Exception:
                pass
        m = _re.search(r"(\d{1,3})\s*%", text or "")
        if m:
            try:
                return max(0, min(100, int(m.group(1))))
            except Exception:
                pass
        return -1

    def _pct_from_lines(self, lines):
        """从已收到的 pip 行里算百分比。

        注意：输出被重定向到文件/管道（非 TTY）时 pip 会关掉终端进度条，行内没有
        N/M 也没有 %（已实测）。此时改用包计数法：
          - 总数 ← "Installing collected packages: a, b, c" 里的包数
          - 已完成 ← 逐行的 "Successfully uninstalled X"（--force-reinstall 会逐个卸载）
        """
        for ln in reversed(lines[-5:]):
            p = self._parse_percent(ln)
            if p >= 0:
                return p
        total = 0
        for ln in reversed(lines):
            if ln.startswith("Installing collected packages:"):
                total = len([x for x in ln.split(":", 1)[1].split(",") if x.strip()])
                break
        if total:
            done = sum(1 for ln in lines
                       if ln.startswith("Successfully uninstalled")
                       or ln.startswith("Successfully installed"))
            if done:
                return max(0, min(100, int(done * 100 / total)))
        return -1

    def _emit_line(self, line, lines=None):
        """发一行进度给 UI：文本 + 百分比（让卡片进度条像终端一样会涨）。"""
        line = (line or "").strip()
        if not line:
            return
        self.progress_text.emit(line[-90:])
        pct = self._pct_from_lines(list(lines or []) + [line])
        if pct >= 0:
            self.progress.emit(pct)

    def _scan_log(self, path):
        """增量读 pip --log，用「已卸载包数 / 总包数」算真实百分比。

        控制台输出被重定向后不一定有逐包的卸载行，但 pip 日志里一定有
        （已用你这次真实提权安装的日志验证：总包 106、卸载行 106、完成 1）。
        只读上次之后的新增字节，避免每秒重扫几十 MB 的日志。
        """
        try:
            with open(path, "rb") as f:
                f.seek(self._log_off)
                data = f.read().decode("utf-8", "replace")
                self._log_off = f.tell()
        except Exception:
            return
        if not data:
            return
        self._uninst_done += data.count("Successfully uninstalled")
        idx = data.find("Installing collected packages:")
        if idx >= 0:
            head = data[idx:].split("\n", 1)[0]
            try:
                self._pkg_total = len(
                    [x for x in head.split(":", 1)[1].split(",") if x.strip()])
            except Exception:
                pass
        if self._pkg_total:
            self.progress.emit(max(0, min(100,
                int(self._uninst_done * 100 / self._pkg_total))))

    def _emit_tail(self, path):
        """读 pip 输出文件：最后一行给文本，整份算一次百分比。"""
        try:
            with open(path, "rb") as f:
                data = f.read().decode("utf-8", "replace")
            lines = [x.strip() for x in data.replace("\r", "\n").split("\n")
                     if x.strip()]
            if lines:
                self._emit_line(lines[-1], lines)
        except Exception:
            pass

    def run(self):
        try:
            lib = os.path.join(os.path.dirname(self._py), "Lib", "site-packages")
            if not _dir_writable(lib):
                # 目标目录不可写：pip 不会报错，而是静默把包装进 C 盘用户目录还返回 0
                # （2026-10-02 实测的假成功，且用户目录在 sys.path 里会压过本尊）。
                # 直接 UAC 提权，一步装进内嵌 site-packages，不制造 C 盘残留。
                ok, msg = self._run_elevated()
                (self.finished_ok if ok else self.failed).emit(msg)
                return
            # 流式读 pip 输出（CREATE_NO_WINDOW 不弹窗）：进度实时发卡片，
            # 不再等装完才一次性拿到输出
            buf = []
            self._proc = subprocess.Popen(
                [self._py, "-m", "pip", "install", "--upgrade",
                 "--force-reinstall", "--no-warn-script-location",
                 # raw：非 TTY 时也让 pip 打出纯文本百分比（默认会关掉进度条）
                 "--progress-bar", "raw", self._whl],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            last_t = 0.0
            for line in self._proc.stdout:
                if self._cancelled:
                    self._proc.kill()
                    self.failed.emit("已取消")
                    return
                line = (line or "").strip()
                if line:
                    buf.append(line)
                    if time.time() - last_t >= 0.5:   # 限频，别刷爆 UI 事件队列
                        last_t = time.time()
                        self._emit_line(line, buf)
            rc = self._proc.wait()
            out = "\n".join(buf)
            low = out.lower()
            permfail = ("permission denied" in low or "winerror 5" in low
                        or "access is denied" in low)
            if rc == 0 and self._target_reached(lib):
                self.finished_ok.emit(out[-1500:])
                return
            if permfail or rc == 0:
                # 两种情况都提权重跑：①明确的权限报错；②退出码 0 但包没落在目标
                # 目录（pip 静默回退到用户目录的另一种假成功形态）
                ok, msg = self._run_elevated()
                (self.finished_ok if ok else self.failed).emit(msg)
                return
            self.failed.emit((out[-600:] or "").strip()
                             or "pip 返回码 %s" % rc)
        except Exception as e:
            self.failed.emit(str(e))

    def _target_reached(self, lib):
        """硬验证：whl 的目标版本必须真的出现在内嵌 site-packages。"""
        import re as _re
        # 注意从 whl 文件名解析版本（whimbox-2.4.7-py3-none-any.whl），
        # 不能套用 dist-info 的正则——whl 名里没有 ".dist-info"
        m = _re.search(r"whimbox-([0-9][\w.]*)", os.path.basename(self._whl))
        ver = m.group(1) if m else ""
        got = _site_pkg_version(lib, "whimbox")
        return got == ver if ver else bool(got)

    def _run_elevated(self):
        """权限不足时以管理员重跑 pip。

        写临时 .cmd（缓存目录全 ASCII，无编码风险）→ PowerShell
        Start-Process -Verb RunAs -WindowStyle Hidden 弹一次 UAC 并等待 →
        pip 输出重定向到文件（父进程每秒取尾巴，把原本黑窗里的进度实时搬进卡片）
        → 用 site-packages 里 dist-info 的实际版本做硬验证（比退出码可靠）。

        注意 -WindowStyle Hidden 不能省：提权进程不继承父进程的"无窗口"属性，
        之前漏了它，pip 卸载/安装上百个依赖包的黑窗会一直挂在屏幕上（用户截图）。
        """
        import re as _re
        log = self._whl + ".elevated.log"
        bat = self._whl + ".elevated.cmd"
        prog = self._whl + ".elevated.out"
        try:
            with open(bat, "w", encoding="ascii") as f:
                f.write('@echo off\r\n"%s" -m pip install --upgrade '
                        '--force-reinstall --no-warn-script-location '
                        # raw：非 TTY 时也让 pip 打出纯文本百分比（默认会关掉进度条）
                        '--progress-bar raw --log "%s" "%s" > "%s" 2>&1\r\n'
                        'echo EXITCODE=%%ERRORLEVEL%%>>"%s"\r\n'
                        % (self._py, log, self._whl, prog, prog))
            self._ps = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command",
                 "Start-Process -FilePath '%s' -Verb RunAs -WindowStyle Hidden -Wait"
                 % bat],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            while self._ps.poll() is None:
                if self._cancelled:
                    try:
                        self._ps.kill()
                    except Exception:
                        pass
                    return False, "已取消"
                self._emit_tail(prog)   # 黑窗藏了，控制台那行文本实时进卡片
                self._scan_log(log)     # 真实百分比：已卸载包数 / 总包数
                time.sleep(self._poll_interval)
            self._emit_tail(prog)
        except Exception as e:
            return False, "管理员重跑 pip 失败：%s" % e
        try:
            logtxt = open(log, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            logtxt = ""
        # 硬验证：目标版本必须真的出现在 site-packages
        # （从 whl 文件名解析版本，不能套 dist-info 正则——whl 名里没有它）
        m = _re.search(r"whimbox-([0-9][\w.]*)", os.path.basename(self._whl))
        ver = m.group(1) if m else ""
        lib = os.path.join(os.path.dirname(self._py), "Lib", "site-packages")
        installed = _site_pkg_version(lib, "whimbox")
        if ver and installed == ver:
            return True, "后端 %s 已安装（管理员模式）" % installed
        if ver and installed and installed != ver:
            return False, ("管理员重跑后版本仍不符：装到 %s，目标 %s。\n%s"
                           % (installed, ver, logtxt[-400:]))
        return False, (logtxt[-600:].strip() or "UAC 被拒绝或安装未完成")


class LiteInstallFrontendWorker(QThread):
    """一条龙第 2 步：静默装前端（NSIS /S /D= 锁目录）并校验 FileVersion。

    在子线程跑 subprocess，UI 线程用走马灯进度 + 每秒文案提示"没卡死"。
    校验：匹配目标→ok；变了但不等于目标→tolerant；没变→查默认落点是否出现
    新 exe（防 /D 失效装去系统盘），否则→unchanged。
    """
    finished_ok = Signal(str)   # ok / tolerant:<v> / wrong_location:<path> / unchanged
    failed = Signal(str)

    def __init__(self, setup_path, target_dir, exe, fe_tag, old_ver, parent=None):
        super().__init__(parent)
        self._setup = setup_path
        self._target = target_dir
        self._exe = exe
        self._fe = fe_tag
        self._old = old_ver
        self._cancelled = False
        self._proc = None
        self._ps = None
        # 不按猜测时长自动杀安装器：写一半被杀会留下残缺安装，比多等一会儿糟得多。
        # 安装器真卡死时由用户点「取消」（_lite_cancel_install → cancel）决定。
        self._timeout = None

    def cancel(self):
        self._cancelled = True
        for p in (self._proc, self._ps):
            if p:
                try:
                    p.kill()
                except Exception:
                    pass

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def run(self):
        try:
            cno = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            exe_name = os.path.basename(self._exe) or "whimbox_app.exe"
            subprocess.run(["taskkill", "/IM", exe_name, "/F", "/T"],
                           capture_output=True, text=True, encoding="gbk",
                           errors="replace", creationflags=cno)
            if self._cancelled:
                self.failed.emit("已取消")
                return
            # NSIS 规范：/D 必须是最后一个参数、裸路径不加引号（含空格也别加）
            cmd = '"%s" /S /D=%s' % (self._setup, self._target)
            try:
                self._proc = subprocess.Popen(cmd, shell=False, creationflags=cno)
            except OSError as e:
                if not (getattr(e, "winerror", None) == 740 or "740" in str(e)):
                    raise
                # WinError 740（请求的操作需要提升）：安装器清单要求管理员。
                # 直接 CreateProcess 会立刻抛 740 —— 改走 PowerShell -Verb RunAs
                # 提权启动并等待（与 pip 提权同一套路；旧版 run_exe 的 740 分支
                # 在改造成 worker 时曾被弄丢，2026-10-02 用户实测踩回）。
                if not self._run_elevated_installer():
                    if not self._cancelled:
                        self.failed.emit("提权启动安装器失败：UAC 被拒绝或出错。"
                                         "可手动运行安装包重试。")
                    return
            else:
                t0 = time.time()
                while self._proc.poll() is None:
                    if self._cancelled:
                        self._proc.kill()
                        self.failed.emit("已取消")
                        return
                    if self._timeout and time.time() - t0 > self._timeout:
                        # 仅当调用方显式给了上界才生效（默认 None = 不自动杀）
                        self._proc.kill()
                        self.failed.emit("安装超时：超过 %d 秒仍未结束，已终止安装器。"
                                         "可手动运行安装包重试。" % self._timeout)
                        return
                    time.sleep(1)
            if self._cancelled:
                return
            self._verify()
        except Exception as e:
            self.failed.emit(str(e))

    def _run_elevated_installer(self):
        """740 时提权启动安装器：PowerShell -Verb RunAs -WindowStyle Hidden -Wait。

        -Wait 会等提权后的安装器跑完（含 GUI 子系统进程），返回后走常规
        FileVersion 校验。-WindowStyle Hidden 必须带，否则黑窗挂屏。
        PS 5.1 不会给 ArgumentList 里的参数自动加引号，/D= 裸路径正好原样透传。
        """
        try:
            ps_cmd = ("Start-Process -FilePath '%s' -ArgumentList '/S','/D=%s' "
                      "-Verb RunAs -WindowStyle Hidden -Wait"
                      % (self._setup, self._target))
            self._ps = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            while self._ps.poll() is None:
                if self._cancelled:
                    try:
                        self._ps.kill()
                    except Exception:
                        pass
                    return False
                time.sleep(1)
            return True
        except Exception:
            return False

    def _verify(self):
        """装完校验 FileVersion：ok / tolerant / wrong_location / unchanged。"""
        v = _exe_file_version(self._exe)
        if v and v == self._fe:
            self.finished_ok.emit("ok")
            return
        if v and v != self._old:
            self.finished_ok.emit("tolerant:%s" % v)
            return
        # 没变：查默认落点是否出现新装（/D 失效的征兆）
        locs = [
            r"C:\Program Files\whimbox_app\whimbox_app.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                         "whimbox_app", "whimbox_app.exe"),
        ]
        for loc in locs:
            if os.path.isfile(loc):
                try:
                    mt = os.path.getmtime(loc)
                except Exception:
                    mt = 0
                if time.time() - mt < 600:
                    self.finished_ok.emit("wrong_location:%s" % loc)
                    return
        self.finished_ok.emit("unchanged")


class LiteScriptUpdateWorker(QThread):
    """更新跑图路线脚本：列 nikkigallery/WhimboxScripts 的 json 并下载到奇想盒脚本目录。

    对应官方「更新脚本」一节：从路线仓库下载脚本 → 放进 App 的脚本目录 → 点「刷新脚本」。
    最后一步「刷新脚本」是 App 内的 GUI 按钮，无法代劳，下载完会提示用户。
    """

    API = "https://api.github.com/repos/nikkigallery/WhimboxScripts/contents/"

    progress = Signal(int, int)      # (已完成文件数, 总文件数)
    finished_ok = Signal(int, str)   # (写入文件数, 脚本目录)
    failed = Signal(str)

    def __init__(self, script_dir, parent=None):
        super().__init__(parent)
        self._dir = script_dir

    def run(self):
        try:
            os.makedirs(self._dir, exist_ok=True)
            req = urllib.request.Request(self.API, headers={
                "User-Agent": "game-launcher-hub",
                "Accept": "application/vnd.github+json",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                items = json.loads(resp.read().decode())
            files = [i for i in items
                     if i.get("type") == "file"
                     and (i.get("name") or "").lower().endswith(".json")
                     and i.get("download_url")]
            total, done = len(files), 0
            for it in files:
                if self.isInterruptionRequested():
                    raise InterruptedError("已取消")
                raw = urllib.request.Request(
                    it["download_url"], headers={"User-Agent": "game-launcher-hub"})
                with urllib.request.urlopen(raw, timeout=60) as r:
                    data = r.read()
                if not data:
                    continue
                with open(os.path.join(self._dir, it["name"]), "wb") as f:
                    f.write(data)
                done += 1
                self.progress.emit(done, total)
            self.finished_ok.emit(done, self._dir)
        except InterruptedError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(str(e))


class GameScanWorker(QThread):
    """后台扫描多个游戏本体，避免注册表枚举 + 大目录 walk 卡 UI。"""

    done = Signal(dict)   # {key: game_exe_path}

    def __init__(self, keys, parent=None):
        super().__init__(parent)
        self.keys = list(keys)

    def run(self):
        found = {}
        for k in self.keys:
            try:
                p = scan_local_game(k)
            except Exception:
                p = ""
            if p:
                found[k] = p
        self.done.emit(found)


def send_to_trash(path):
    """把文件或目录移入 Windows 回收站（可撤销）。返回 (success, message)。"""
    if not os.path.exists(path):
        return False, f"路径不存在：{path}"

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 0x0003
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_SILENT = 0x0004

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = path + "\0\0"
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None

    ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if ret == 0 and not op.fAnyOperationsAborted:
        return True, "已移入回收站"
    return False, f"操作失败或已被取消（错误码：{ret}）"


def runas(exe, args_list, cwd):
    """以管理员身份运行（弹 UAC）。args_list 为字符串列表。"""
    params = subprocess.list2cmdline(args_list) if args_list else ""
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, cwd, 1)
    return ret > 32


def run_exe(parent, exe, args=None, cwd=None, need_admin=False, show_errors=True):
    """运行程序：普通方式失败(740)或 need_admin=True 时用 runas 提权。"""
    if not os.path.isfile(exe):
        if show_errors:
            QMessageBox.critical(parent, "失败", f"找不到可执行文件：\n{exe}")
        return False
    args = args or []
    cwd = cwd or os.path.dirname(exe)
    if need_admin:
        return runas(exe, args, cwd)
    try:
        # 不用 DETACHED_PROCESS(0x8)：Electron/Chromium 系（奇想盒 whimbox_app.exe）
        # 依赖从父进程继承的句柄映射 ICU 数据，DETACHED_PROCESS 会切断该句柄继承，
        # 导致启动即报 "Invalid file descriptor to ICU data received" 后直接退出。
        # 父进程是 pythonw（无控制台），不传该标志也不会闪黑窗。
        subprocess.Popen(
            [exe] + args, cwd=cwd, shell=False,
        )
        return True
    except OSError as e:
        if getattr(e, "winerror", None) == 740 or "740" in str(e):
            return runas(exe, args, cwd)
        if show_errors:
            QMessageBox.critical(parent, "失败", f"无法启动：\n{exe}\n\n错误：{e}")
        return False
    except Exception as e:
        if show_errors:
            QMessageBox.critical(parent, "失败", f"无法启动：\n{exe}\n\n错误：{e}")
        return False


class TagLabel(QLabel):
    def __init__(self, text, bg="#3a3a44", fg="#ffffff"):
        super().__init__(text)
        self.setStyleSheet(
            f"background-color:{bg}; color:{fg}; border-radius:6px; "
            f"padding:2px 8px; font-size:11px;"
        )
        self.setAlignment(Qt.AlignCenter)


class StatusBadge(QLabel):
    """WeGame 风格状态徽章。"""

    def __init__(self, text, color="#cfcfcf", bg="rgba(255,255,255,0.15)"):
        super().__init__(text)
        self.setStyleSheet(
            f"background-color:{bg}; color:{color}; border-radius:9px; "
            f"padding:3px 12px; font-size:12px; font-weight:600;"
        )
        self.setAlignment(Qt.AlignCenter)


class AppCard(CardWidget):
    """一张游戏卡片。静态部分（封面/名称/徽章/状态行）固定，动态部分按安装状态重建。"""

    def __init__(self, app):
        super().__init__()
        self.app = app
        # 单列竖排：只固定宽度（匹配 760px 容器 - 32px 边距），高度随 changelog 内容自动撑开。
        # 之前 setFixedSize(440, 560) 是为 2 列网格设计的，写死高 560 导致长 changelog 被截。
        # 不再写死 720：改成侧栏布局后由游戏页的居中容器弹性决定宽度，仅设最小宽防压扁
        self.setMinimumWidth(560)

        self._version_map = {}  # display text -> raw tag
        self._changelog_worker = None
        self._version_fetcher = None
        self._version_notes_list = None  # 原启动器返回的 [{version, update_note}]（同源）
        self.game_found_path = ""        # 本地游戏本体扫描结果（""=未检测到）

        # 静态骨架
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        root.setAlignment(Qt.AlignTop)

        # 封面区（渐变底 + 游戏图标）
        self.cover = QLabel()
        self.cover.setFixedHeight(150)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #3b4256, stop:1 #262b3a); border-radius:10px;"
        )
        root.addWidget(self.cover)

        # 名称 + 状态徽章
        head = QHBoxLayout()
        head.setSpacing(10)
        name = StrongBodyLabel(app["display"])
        name.setStyleSheet("font-size:20px; font-weight:700;")
        head.addWidget(name)
        head.addStretch(1)
        self.badge = StatusBadge("已安装", color="#8dffb0", bg="rgba(45,125,50,0.25)")
        head.addWidget(self.badge)
        # 独立运行态标签：仅运行中时显示「● 运行中」，与徽章（已安装/可更新）、
        # 按钮（强制关闭）三者分工互不重复。
        self.run_tag = QLabel("● 运行中")
        self.run_tag.setStyleSheet(
            "color:#8dffb0; font-size:12px; font-weight:600; padding:2px 4px;"
        )
        self.run_tag.setVisible(False)
        head.addWidget(self.run_tag)
        # 右上角齿轮：更多操作（快捷方式/浏览安装位置/卸载），见 _build_card_menu
        self.gear_btn = TransparentToolButton(FluentIcon.SETTING)
        self.gear_btn.setFixedSize(30, 30)
        self.gear_btn.setIconSize(self.gear_btn.size() * 0.55)
        self.gear_btn.setToolTip("更多操作")
        self.gear_btn.setCursor(Qt.PointingHandCursor)
        self.gear_btn.clicked.connect(self._show_card_menu)
        head.addWidget(self.gear_btn)
        root.addLayout(head)

        # 信息行：版本 / 配置
        info_row = QHBoxLayout()
        info_row.setSpacing(6)
        self.ver_tag = TagLabel("未知", bg="#616161")
        info_row.addWidget(self.ver_tag)
        self.profile_tag = TagLabel("", bg="#3a3a44")
        info_row.addWidget(self.profile_tag)
        info_row.addStretch(1)
        root.addLayout(info_row)

        self.status_label = CaptionLabel("")
        root.addWidget(self.status_label)

        # 更新进度区（持久，不随 body_box 重建）：原启动器更新时实时反映
        self.update_bar = IndeterminateProgressBar()
        self.update_bar.setFixedHeight(6)
        self.update_bar.setVisible(False)
        root.addWidget(self.update_bar)
        self.update_label = CaptionLabel("")
        self.update_label.setVisible(False)
        root.addWidget(self.update_label)

        # 动态内容容器：根据安装状态重建
        self.body_box = QVBoxLayout()
        self.body_box.setSpacing(10)
        root.addLayout(self.body_box)

        # ===== 安装进度区（持久，默认隐藏，install_app 启动时显示并驱动） =====
        # 不再用 QProgressDialog 模态弹窗——之前那个弹窗在 PySide6 自定义窗口主题下
        # 居中渲染时与窗口本体撞色/撞焦点，截图里顶部那条"刷新检测/安装"长条就是它
        # 被窗口遮住上半截、label 文字被挤在按钮区里渲染造成的视错觉（"界面也出 bug 了"）。
        # 改成内嵌在卡片底部，用户随时看到进度、随时点"取消"，不会被模态抢焦点。
        self.install_progress = QProgressBar()
        self.install_progress.setRange(0, 100)
        self.install_progress.setValue(0)
        self.install_progress.setFixedHeight(8)
        self.install_progress.setTextVisible(False)
        self.install_progress.setStyleSheet(
            "QProgressBar { background-color:rgba(255,255,255,0.10); border-radius:4px; }"
            "QProgressBar::chunk { background-color:#1976d2; border-radius:4px; }"
        )
        self.install_progress.setVisible(False)
        root.addWidget(self.install_progress)
        self.install_status = CaptionLabel("")
        self.install_status.setWordWrap(True)
        self.install_status.setStyleSheet("color:#9ec5ff; font-size:12px;")
        self.install_status.setVisible(False)
        root.addWidget(self.install_status)
        self.install_cancel_btn = PushButton("✕ 取消下载")
        self.install_cancel_btn.setFixedHeight(32)
        self.install_cancel_btn.setStyleSheet(
            "QPushButton { background-color:#455a64; color:white; border-radius:6px; "
            "font-weight:600; } QPushButton:hover { background-color:#37474f; }"
        )
        self.install_cancel_btn.setVisible(False)
        self.install_cancel_btn.clicked.connect(self._on_install_cancel_clicked)
        root.addWidget(self.install_cancel_btn)

        # 暂停/继续：zip 安装包动辄几百 MB，不给暂停用户就只能干等或强杀
        self.install_pause_btn = PushButton("⏸ 暂停")
        self.install_pause_btn.setFixedHeight(32)
        self.install_pause_btn.setStyleSheet(
            "QPushButton { background-color:#5d4037; color:white; border-radius:6px; "
            "font-weight:600; } QPushButton:hover { background-color:#4e342e; }"
        )
        self.install_pause_btn.setVisible(False)
        self.install_pause_btn.clicked.connect(self._on_install_pause_clicked)
        root.addWidget(self.install_pause_btn)

        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_data)
        self._timer.start(5000)

        self.rebuild_body()  # 首次填充

    # ===== 动态内容 =====
    def clear_body(self):
        """彻底清空 body_box 里的所有子项（widget + layout 都要清）。

        旧版只 widget().deleteLater()，但 build_*_body 加进去的是 QHBoxLayout
        （btn_row / ver_row），item.widget() 对 layout item 返回 None，被跳过——
        残留的 layout item 仍占位且引用上一次的 child widget，反复 rebuild_body 后
        上一组的按钮组（"启动 + 原版管理"）+ 下一组的（"安装 + 刷新检测"）并存，
        UI 看起来就是「按钮挤一起重叠」（用户最新截图就是这个症状）。
        """
        while self.body_box.count():
            item = self.body_box.takeAt(0)
            if item is None:
                break
            # 子 widget：直接销毁
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
                continue
            # 子 layout：清掉 layout 自己的子 widget（递归一层够用），再 setParent(None)
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    si = sub.takeAt(0)
                    if si is None:
                        break
                    sw = si.widget()
                    if sw is not None:
                        sw.setParent(None)
                        sw.deleteLater()

    def _resolve_host_exe(self, install_dir=None):
        """定位 install_dir 里的 host exe（PyAppify 引导包）。

        返回 (expected_path, actual_path)：
        - expected_path：config["exe"] 的预期路径
        - actual_path  ：install_dir 里实际存在的 .exe（PyAppify host）
          若 config 期望的名字已存在，actual = expected；否则 = 唯一 .exe；
          若 install_dir 不存在或没有 .exe，返回 (expected, None)。

        win32.zip 解出的 host 命名可能跟 config 不一致
        （如 ok-end-field 解出 ok-ef.exe，config 期望 ok-end-field.exe），
        故优先以 config 名为准，找不到再退而求其次。
        """
        cfg_exe = self.app.get("exe", "") or ""
        install_dir = install_dir or os.path.dirname(cfg_exe)
        if not install_dir or not os.path.isdir(install_dir):
            return (cfg_exe, None)
        expected = cfg_exe
        if os.path.isfile(expected):
            return (expected, expected)
        # 找唯一 .exe 作为 host
        exes = sorted(
            f for f in os.listdir(install_dir)
            if f.lower().endswith(".exe") and os.path.isfile(os.path.join(install_dir, f))
        )
        if len(exes) == 1:
            return (expected, os.path.join(install_dir, exes[0]))
        if len(exes) > 1:
            # 多个 exe：挑名字跟 key 接近的那个
            key = self.app.get("key", "")
            for e in exes:
                if key and key in e.lower():
                    return (expected, os.path.join(install_dir, e))
            return (expected, os.path.join(install_dir, exes[0]))
        return (expected, None)

    def rebuild_body(self):
        """根据当前 app.json 是否有效，重建动态区。"""
        # lite 模式（非 ok-script 系助手，如奇想盒 Whimbox）：没有 app_json/working/pythonw，
        # 不参与版本与更新体系，只保留「启动 / 强制关闭 / 运行状态 / 卸载」四件套。
        if self.app.get("lite"):
            return self._rebuild_lite_body()
        if self.app.get("generic"):
            return self._rebuild_generic_body()

        self.data = load_app_json(self.app["app_json"])
        self.profile = get_current_profile(self.data)
        # 三态：
        #   - installed   : working/main.py 存在（PyAppify 完整初始化过）
        #   - host_ready  : working/main.py 不在，但 install_dir 里有任意 .exe（半装——刚解压完）
        #   - not_installed: 啥都没有
        cfg_exe = self.app.get("exe", "") or ""
        install_dir = os.path.dirname(cfg_exe) or ""
        app_json_dir = os.path.dirname(self.app.get("app_json", "") or "")
        working_main = os.path.join(app_json_dir, "working", "main.py") if app_json_dir else ""
        # _resolve_host_exe 返回 (expected, actual)；只要 actual 不为空就是有 host
        _, host_actual = self._resolve_host_exe(install_dir)
        working_main_exists = bool(working_main) and os.path.isfile(working_main)
        host_exists = bool(host_actual) and os.path.isfile(host_actual)
        self._installed = working_main_exists
        self._host_ready = host_exists and not working_main_exists
        self._host_actual = host_actual if host_exists else ""
        self._install_dir = install_dir

        # 封面图标（装好后才有真实图标，未安装用默认）
        self.cover.setPixmap(make_icon(self.app["icon"]).pixmap(96, 96))

        # 徽章与信息行
        if self._installed:
            self.ver_tag.setText(self.data.get("current_version") or "未知")
            self.ver_tag.setStyleSheet(
                "background-color:#2e7d32; color:#ffffff; border-radius:6px; "
                "padding:2px 8px; font-size:11px;"
            )
            prof = self.data.get("current_profile", "")
            self.profile_tag.setText(prof)
            self.profile_tag.setVisible(bool(prof))
            # 已安装态：先把 status_label 清空，避免上次未安装态写入的「未检测到本地
            # 安装」/「待初始化」等文字残留造成「badge 已安装 / 文案未安装」自相矛盾
            # 的诡异状态（用户最新截图就是这个症状）。运行中会由 launch_app 的
            # QTimer.singleShot(5s, clear) 短暂占位「已发起启动」，下次轮询会自然清空。
            self.status_label.setText("")
            if not self.status_label.text():
                self.status_label.setText(self.get_status_text())
            self.refresh_badge()
        elif self._host_ready:
            # 半装：host.exe 已就位、但 working/main.py 还没生成
            self.ver_tag.setText("待初始化")
            self.ver_tag.setStyleSheet(
                "background-color:#e65100; color:#ffffff; border-radius:6px; "
                "padding:2px 8px; font-size:11px;"
            )
            self.profile_tag.clear()
            self.profile_tag.setVisible(False)
            self.status_label.setText("已解压 host 引导包，需运行一次完成初始化")
            self.badge.setText("待初始化")
            self.badge.setStyleSheet(
                "background-color:#e65100; color:#ffffff; border-radius:9px; "
                "padding:3px 12px; font-size:12px; font-weight:600;"
            )
        else:
            self.ver_tag.setText("未安装")
            self.ver_tag.setStyleSheet(
                "background-color:#616161; color:#ffffff; border-radius:6px; "
                "padding:2px 8px; font-size:11px;"
            )
            self.profile_tag.clear()
            self.profile_tag.setVisible(False)
            self.status_label.setText("未检测到本地安装")
            self.badge.setText("未安装")
            self.badge.setStyleSheet(
                "background-color:rgba(255,255,255,0.15); color:#cfcfcf; "
                "border-radius:9px; padding:3px 12px; font-size:12px; font-weight:600;"
            )

        # 动态区
        self.clear_body()
        if self._installed:
            self.build_installed_body()
        elif self._host_ready:
            self.build_half_installed_body()
        else:
            self.build_uninstalled_body()

        # 兜底：每次 rebuild 都强制 hide 安装进度三件套，防止 install_app 在
        # _on_failed / cancel 等异常路径未跑到 _hide_install_progress_ui 时，
        # 残留的 install_progress/install_status/install_cancel_btn 跟新按钮挤一起。
        self._hide_install_progress_ui()

        # 更新进度（含未安装时若 app.json 仍含更新状态，也显示）
        self.update_progress_ui()

    def _rebuild_lite_body(self):
        """lite 模式专用重建：exe 存在即视为「已安装」，全程不读 app.json。"""
        cfg_exe = self.app.get("exe", "") or ""
        self._lite = True
        self._installed = bool(cfg_exe) and os.path.isfile(cfg_exe)
        self._host_ready = False
        self._host_actual = ""
        self._install_dir = os.path.dirname(cfg_exe) or ""
        self.data = {}
        self.profile = {}

        self.cover.setPixmap(make_icon(self.app["icon"]).pixmap(96, 96))
        self.profile_tag.clear()
        self.profile_tag.setVisible(False)

        if self._installed:
            # 显示真实版本（exe 版本资源，如 2.1.1）；读不到再回退 "lite" 占位
            self.ver_tag.setText(_exe_file_version(cfg_exe) or "lite")
            self.ver_tag.setStyleSheet(
                "background-color:#455a64; color:#ffffff; border-radius:6px; "
                "padding:2px 8px; font-size:11px;"
            )
            self.status_label.setText("")
            self.badge.setText("已安装")
            self.badge.setStyleSheet(
                "background-color:#2e7d32; color:#ffffff; border-radius:9px; "
                "padding:3px 12px; font-size:12px; font-weight:600;"
            )
        else:
            self.ver_tag.setText("未安装")
            self.ver_tag.setStyleSheet(
                "background-color:#616161; color:#ffffff; border-radius:6px; "
                "padding:2px 8px; font-size:11px;"
            )
            self.status_label.setText("未检测到本地安装")
            self.badge.setText("未安装")
            self.badge.setStyleSheet(
                "background-color:rgba(255,255,255,0.15); color:#cfcfcf; "
                "border-radius:9px; padding:3px 12px; font-size:12px; font-weight:600;"
            )

        self.clear_body()
        self.build_lite_body()

        # 兜底：与 ok-script 卡一致，强制隐藏安装进度三件套
        self._hide_install_progress_ui()
        self.update_progress_ui()
        # 立即刷一次运行态（refresh_badge 内部会调 _refresh_start_btn + run_tag，
        # 否则按钮要等下一轮 5 秒轮询才有槽，点了没反应）
        self.refresh_badge()
        # lite 更新检查（内部有一次性守卫，5s 轮询不会重复触发）
        if self._installed:
            self._lite_start_check()

    # ===== 未安装态通用操作区（lite / generic 共用） =====
    def _build_uninstalled_actions(self):
        """未安装时给三条出路：一键装 / 手动指定已有安装 / 打开官网。

        ok-script 卡不走这里——它有自己的 InstallWorker（NSIS 整包直解）路线。
        """
        key = self.app.get("key", "")

        # 装法有两种：官方安装包（Installer.exe）走 AppInstallerWorker；
        # zip 发布的（如 MaaEnd）走 ZipAppWorker 下载解压。都没配就只给官网。
        if key in INSTALLER_REPO or self.app.get("release_repo"):
            self.install_btn = PushButton("安装")
            self.install_btn.setFixedHeight(42)
            self.install_btn.setStyleSheet(
                "QPushButton { background-color:#1976d2; color:white; "
                "border-radius:8px; font-weight:600; } "
                "QPushButton:hover { background-color:#1565c0; }"
            )
            self.install_btn.setCursor(Qt.PointingHandCursor)
            self.install_btn.clicked.connect(self._on_install_from_official)
            self.body_box.addWidget(self.install_btn)

            self.install_bar = IndeterminateProgressBar()
            self.install_bar.setFixedHeight(4)
            self.install_bar.setVisible(False)
            self.body_box.addWidget(self.install_bar)

            hint = CaptionLabel(
                "点「安装」会下载官方安装包并启动它，按提示装完即可。"
                "装好后本卡片会自动定位到程序。")
            hint.setWordWrap(True)
            self.body_box.addWidget(hint)

        self.locate_btn = PushButton("选择已安装程序…")
        self.locate_btn.setFixedHeight(36)
        self.locate_btn.setCursor(Qt.PointingHandCursor)
        self.locate_btn.setToolTip(
            "如果你已经装好了、只是路径和预置的不同，用这个手动指定")
        self.locate_btn.clicked.connect(self._on_locate_exe)
        self.body_box.addWidget(self.locate_btn)

        site = self.app.get("website", "")
        if site:
            btn = PushButton("打开官网")
            btn.setFixedHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda *a, url=site: QDesktopServices.openUrl(QUrl(url)))
            self.body_box.addWidget(btn)

    def _on_install_from_official(self):
        if getattr(self, "_installer_worker", None) is not None and \
                self._installer_worker.isRunning():
            return
        self.install_btn.setEnabled(False)
        self._show_install_progress_ui("正在准备…")
        if hasattr(self, "install_bar"):
            self.install_bar.setVisible(False)
        self.install_btn.setText("正在准备…")
        if self.app.get("release_repo") and not _git_repo_dir(self.app):
            w = ZipAppWorker(self.app, parent=self)
            w.progress.connect(self._on_installer_progress)
            w.percent.connect(self._on_installer_percent)
            w.done.connect(self._on_zip_done)
            w.failed.connect(self._on_installer_failed)
        else:
            w = AppInstallerWorker(
                self.app, os.path.join(LAUNCHER_DIR, "_install_tmp"), parent=self)
            w.progress.connect(self._on_installer_progress)
            w.percent.connect(self._on_installer_percent)
            w.done.connect(self._on_installer_done)
            w.failed.connect(self._on_installer_failed)
        self._installer_worker = w
        w.start()

    def _on_installer_progress(self, text):
        if not text:
            return
        if hasattr(self, "install_btn"):
            self.install_btn.setText(text)
        if hasattr(self, "install_status"):
            self.install_status.setText(text)

    def _on_installer_done(self, exe_path):
        self._installer_worker = None
        self._hide_install_progress_ui()
        # 装到的位置未必等于 config 预置路径 → 写回，否则下次启动又变「未安装」
        self.app["exe"] = exe_path
        _save_app_exe(self.app.get("key", ""), exe_path)
        self.rebuild_body()
        try:
            InfoBar.success("安装完成", "已定位到 %s" % exe_path,
                            duration=4000, parent=self,
                            position=InfoBarPosition.TOP_RIGHT)
        except Exception:
            pass

    def _on_zip_done(self, tag):
        """zip 安装/更新完成：exe 与版本号已由 worker 写回 config，这里只重建卡片。"""
        self._installer_worker = None
        self._hide_install_progress_ui()
        self.rebuild_body()
        try:
            InfoBar.success("安装完成", "已安装 %s" % (tag or "最新版本"),
                            duration=4000, parent=self,
                            position=InfoBarPosition.TOP_RIGHT)
        except Exception:
            pass

    def _on_installer_failed(self, msg):
        self._installer_worker = None
        self._hide_install_progress_ui()
        if hasattr(self, "install_btn"):
            self.install_btn.setEnabled(True)
            self.install_btn.setText("安装")
        QMessageBox.warning(self, "安装未完成", msg)

    def _on_locate_exe(self):
        start = os.path.dirname(self.app.get("exe", "") or "") or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择程序主程序", start,
            "应用程序 (*.exe);;所有文件 (*.*)")
        if not path:
            return
        self.app["exe"] = path
        _save_app_exe(self.app.get("key", ""), path)
        self.rebuild_body()

    # ===== 右上角齿轮：添加快捷方式 / 浏览安装位置 / 卸载 =====
    def _build_card_menu(self):
        """齿轮下拉菜单。测试友好：只构建不 exec（exec 是模态，会阻塞无人值守测试）。"""
        menu = RoundMenu(parent=self)
        inst = bool(getattr(self, "_installed", False))
        exe = self.app.get("exe", "") or ""

        a_add = Action(FluentIcon.LINK, "添加桌面快捷方式")
        a_add.triggered.connect(self._create_desktop_shortcut)
        a_add.setEnabled(bool(exe) and os.path.isfile(exe))
        menu.addAction(a_add)

        a_open = Action(FluentIcon.FOLDER, "浏览安装位置")
        a_open.triggered.connect(self._open_install_dir)
        a_open.setEnabled(inst)
        menu.addAction(a_open)

        menu.addSeparator()

        a_un = Action(FluentIcon.DELETE, "卸载")
        a_un.triggered.connect(self.uninstall_app)
        a_un.setEnabled(inst)
        menu.addAction(a_un)
        return menu

    def _show_card_menu(self):
        self._build_card_menu().exec(
            self.gear_btn.mapToGlobal(QPoint(0, self.gear_btn.height() + 4)))

    def _open_install_dir(self):
        d = (getattr(self, "_install_dir", "")
             or os.path.dirname(self.app.get("exe", "") or ""))
        if d and os.path.isdir(d):
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        else:
            QMessageBox.information(self, "浏览安装位置",
                                    "未找到安装目录（可能尚未安装）。")

    def _create_desktop_shortcut(self):
        exe = self.app.get("exe", "") or ""
        if not exe or not os.path.isfile(exe):
            QMessageBox.information(self, "添加快捷方式",
                                    "未找到程序（可能尚未安装）。")
            return
        desktop = _desktop_dir()
        if not desktop:
            QMessageBox.warning(self, "添加快捷方式", "未能定位桌面目录。")
            return
        name = self.app.get("display") or self.app.get("key") or "App"
        lnk = os.path.join(desktop, name + ".lnk")
        if _write_lnk(lnk, exe, os.path.dirname(exe)):
            try:
                InfoBar.success("已创建快捷方式", lnk, duration=3000,
                                parent=self,
                                position=InfoBarPosition.TOP_RIGHT)
            except Exception:
                pass
        else:
            QMessageBox.warning(self, "添加快捷方式", "创建失败：" + lnk)

    def build_lite_body(self):
        """lite 模式动态区：已安装 = 启动/强关 + 卸载；未安装 = 通用操作区。"""
        if self._installed:
            self.start_btn = PushButton("▶  启动应用")
            # 当前 / 最新版本提示：ok-script 卡的版本信息由 app.json 提供，
            # lite 卡这里显式列出，免得最新版本只藏在按钮文案里。
            # 前端/后端本地就能读（exe 版本资源 + site-packages dist-info），
            # 构建时立即填充，不等网络检查——检查失败（GitHub API 超时/限流）
            # 也不会出现「当前版本 —」一直空着的僵局。
            self.ver_hint = CaptionLabel("前端 %s · 后端 %s" % (
                _exe_file_version(self.app.get("exe", "")) or "未知",
                _lite_backend_version(self.app) or "未知"))
            self.body_box.addWidget(self.ver_hint)
            self.start_btn.setFixedHeight(42)
            self.start_btn.setStyleSheet(
                "QPushButton { background-color:#2e7d32; color:white; border-radius:8px; "
                "font-weight:600; } QPushButton:hover { background-color:#1b5e20; }"
            )
            # 槽随运行态切换（见 _refresh_start_btn），与 ok-script 卡一致
            self.body_box.addWidget(self.start_btn)

            # 卸载已收进右上角齿轮菜单（_build_card_menu），卡身不再放重复按钮

            # 更新按钮：lite 助手走 GitHub Releases 检测（奇想盒 App 安装包随主仓库发布）
            self.update_btn = PushButton("检查更新中…")
            self.update_btn.setFixedHeight(38)
            self.update_btn.setEnabled(False)
            self.update_btn.setCursor(Qt.PointingHandCursor)
            self.update_btn.clicked.connect(self._on_lite_update)
            self.body_box.addWidget(self.update_btn)

            # 更新跑图路线（官方「更新脚本」一节）：路线仓库 json → App 脚本目录
            self.script_btn = PushButton("更新跑图路线")
            self.script_btn.setFixedHeight(38)
            self.script_btn.setCursor(Qt.PointingHandCursor)
            self.script_btn.clicked.connect(self._on_lite_script_update)
            self.body_box.addWidget(self.script_btn)

            # 查看版本（只读下拉）：与 ok-script 卡一致，可翻看各版本的更新说明
            ver_row = QHBoxLayout()
            ver_row.setSpacing(10)
            ver_row.addWidget(CaptionLabel("查看版本"))
            self.ver_combo = ComboBox()
            self.ver_combo.setMinimumWidth(200)
            self.ver_combo.setPlaceholderText("选择版本查看说明...")
            ver_row.addWidget(self.ver_combo)
            self.body_box.addLayout(ver_row)

            # 更新日志：展示在卡片里（不塞进确认弹窗），跟随上方下拉选择
            self.body_box.addWidget(CaptionLabel("更新说明"))
            self.changelog_text = QTextEdit()
            self.changelog_text.setReadOnly(True)
            self.changelog_text.setMinimumHeight(110)
            self.changelog_text.setPlainText("正在获取更新说明…")
            self.body_box.addWidget(self.changelog_text)
        else:
            self.status_label.setText("未检测到本地安装")
            self._build_uninstalled_actions()

    def _rebuild_generic_body(self):
        """generic 模式重建：独立 exe 程序（非 ok-script、非奇想盒形态）。

        与 lite 的区别：
          - 版本来自本地 git tag（_git_tag_version），不是 exe 版本资源/后端包
          - **不做 GitHub 更新检查**：这类程序自带更新机制（如一条龙自行 git
            增量更新），我们再去拉 release 并静默安装，容易和它自己的更新打架
          - 不做「更新到任意版本 / 跑图路线」这类只有奇想盒才有的按钮
        保留四件套：运行状态 / 启动 / 强制关闭 / 卸载。
        """
        cfg_exe = self.app.get("exe", "") or ""
        self._lite = False
        self._generic = True
        self._installed = bool(cfg_exe) and os.path.isfile(cfg_exe)
        self._host_ready = False
        self._host_actual = ""
        self._install_dir = os.path.dirname(cfg_exe) or ""
        self.data = {}
        self.profile = {}

        self.cover.setPixmap(make_icon(self.app["icon"]).pixmap(96, 96))
        self.profile_tag.clear()
        self.profile_tag.setVisible(False)

        if self._installed:
            ver = _git_tag_version(self.app)
            self.ver_tag.setText(ver or "已安装")
            self.ver_tag.setStyleSheet(
                "background-color:#455a64; color:#ffffff; border-radius:6px; "
                "padding:2px 8px; font-size:11px;"
            )
            self.status_label.setText("")
            self.badge.setText("已安装")
            self.badge.setStyleSheet(
                "background-color:#2e7d32; color:#ffffff; border-radius:9px; "
                "padding:3px 12px; font-size:12px; font-weight:600;"
            )
        else:
            self.ver_tag.setText("未安装")
            self.ver_tag.setStyleSheet(
                "background-color:#616161; color:#ffffff; border-radius:6px; "
                "padding:2px 8px; font-size:11px;"
            )
            self.status_label.setText("未检测到本地安装")
            self.badge.setText("未安装")
            self.badge.setStyleSheet(
                "background-color:rgba(255,255,255,0.15); color:#cfcfcf; "
                "border-radius:9px; padding:3px 12px; font-size:12px; font-weight:600;"
            )

        self.clear_body()
        self.build_generic_body()

        self._hide_install_progress_ui()
        self.update_progress_ui()
        # 立即刷一次运行态（否则按钮要等下一轮 5s 轮询才有槽，点了没反应）
        self.refresh_badge()
        # 更新检查（内部有一次性守卫，5s 轮询不会重复 fetch）
        if self._installed:
            self._generic_start_check()

    def build_generic_body(self):
        """generic 模式动态区：已安装 = 启动/强关 + 卸载；未安装 = 提示 + 官网。

        刻意不放更新相关控件：这类程序自带更新机制，本启动器只负责
        「装没装、能不能起来、是不是在跑」。
        """
        if self._installed:
            self.start_btn = PushButton("▶  启动应用")
            ver = _git_tag_version(self.app)
            self.ver_hint = CaptionLabel("本地版本 %s" % (ver or "未知"))
            self.ver_hint.setWordWrap(True)
            self.body_box.addWidget(self.ver_hint)

            # 更新区：git 仓库（就地 pull）或 release zip（下载解压）二选一，
            # 两种都不是就无法在启动器内更新，不给按钮。
            if _git_repo_dir(self.app) or self.app.get("release_repo"):
                self.gen_update_btn = PushButton("检查更新中…")
                self.gen_update_btn.setFixedHeight(38)
                self.gen_update_btn.setEnabled(False)
                self.gen_update_btn.setCursor(Qt.PointingHandCursor)
                self.gen_update_btn.clicked.connect(self._on_generic_update)
                self.body_box.addWidget(self.gen_update_btn)

                self.gen_update_bar = IndeterminateProgressBar()
                self.gen_update_bar.setFixedHeight(4)
                self.gen_update_bar.setVisible(False)
                self.body_box.addWidget(self.gen_update_bar)

            self.start_btn.setFixedHeight(42)
            self.start_btn.setStyleSheet(
                "QPushButton { background-color:#2e7d32; color:white; border-radius:8px; "
                "font-weight:600; } QPushButton:hover { background-color:#1b5e20; }"
            )
            self.body_box.addWidget(self.start_btn)

            # 卸载已收进右上角齿轮菜单（_build_card_menu），卡身不再放重复按钮

            # 官方站点（一条龙这类自带更新，指回它自己的更新入口最省事）
            site = self.app.get("website", "")
            if site:
                site_btn = PushButton("打开官方站点（更新请走它自己的启动器）")
                site_btn.setFixedHeight(36)
                site_btn.setCursor(Qt.PointingHandCursor)
                site_btn.clicked.connect(
                    lambda *a, url=site: QDesktopServices.openUrl(QUrl(url)))
                self.body_box.addWidget(site_btn)
        else:
            self.status_label.setText("未检测到本地安装")
            self._build_uninstalled_actions()

    # ===== generic 更新：本地 git 仓库 fetch + pull --ff-only =====
    def _generic_start_check(self):
        """启动更新检查。每次 rebuild 只触发一次，避免 5s 轮询反复 fetch。"""
        if getattr(self, "_gen_check_started", False):
            return
        self._gen_check_started = True
        if not hasattr(self, "gen_update_btn"):
            return
        # 两条更新路线：本地 git 仓库 → pull；release zip 发布 → 下载解压。
        # 一条龙走前者，MaaEnd 这类走后者。都不是就明说无法更新，别给假按钮。
        if _git_repo_dir(self.app):
            if not GitVersionFetcher._find_git():
                self.gen_update_btn.setText("未找到 git，无法更新")
                self.gen_update_btn.setEnabled(False)
                return
            w = GenericUpdateCheckWorker(self.app, parent=self)
        elif self.app.get("release_repo"):
            w = ZipAppCheckWorker(self.app, parent=self)
        else:
            self.gen_update_btn.setText("非 git 仓库且未配置发布源，无法更新")
            self.gen_update_btn.setEnabled(False)
            return
        self._gen_check_worker = w
        self._gen_check_worker.done.connect(self._on_generic_check_done)
        self._gen_check_worker.failed.connect(self._on_generic_check_failed)
        self._gen_check_worker.start()

    def _on_generic_check_done(self, info):
        self._gen_check_worker = None
        if not hasattr(self, "gen_update_btn"):
            return
        behind = info.get("behind", 0)
        rt = info.get("remote_tag") or ""
        lt = info.get("local_tag") or ""
        if behind > 0:
            self.gen_update_btn.setText("有新版本，点此更新（落后 %d 个提交）" % behind)
            self.gen_update_btn.setEnabled(True)
            self.ver_hint.setText("本地版本 %s　·　最新 %s（落后 %d 个提交）"
                                  % (lt or "未知", rt, behind))
        else:
            self.gen_update_btn.setText("已是最新")
            self.gen_update_btn.setEnabled(False)
            self.ver_hint.setText("本地版本 %s　·　已是最新" % (lt or "未知"))
        self._gen_has_update = behind > 0

    def _on_generic_check_failed(self, msg):
        self._gen_check_worker = None
        if not hasattr(self, "gen_update_btn"):
            return
        self.gen_update_btn.setText("检查更新失败（点击重试）")
        self.gen_update_btn.setEnabled(True)
        self._gen_retry = True

    def _on_generic_update(self):
        """点更新按钮：失败态 → 重试检查；有新版 → 关进程后拉取。"""
        # 失败态的按钮点了是「重新检查」
        if getattr(self, "_gen_retry", False):
            self._gen_retry = False
            self._gen_check_started = False
            self.gen_update_btn.setText("检查更新中…")
            self.gen_update_btn.setEnabled(False)
            self._generic_start_check()
            return

        if not getattr(self, "_gen_has_update", False):
            return

        # 更新前必须关掉程序：它运行中是 git 仓库被占用 + 代码正在被使用
        if self._is_process_running():
            ans = QMessageBox.question(
                self, "需要先关闭程序",
                "该程序正在运行，更新会修改它的代码，必须先关闭。\n\n"
                "是否关闭它并继续更新？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            exe_name = os.path.basename(self.app.get("exe", "")) or ""
            if exe_name:
                subprocess.run(["taskkill", "/IM", exe_name, "/F", "/T"],
                               capture_output=True, text=True, encoding="gbk",
                               errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                time.sleep(2)

        if getattr(self, "_gen_update_worker", None) is not None and \
                self._gen_update_worker.isRunning():
            return

        self.gen_update_btn.setEnabled(False)
        self.gen_update_btn.setText("更新中…")
        # 更新同样要下载几百 MB，用带百分比/暂停/取消的那套进度 UI
        self._show_install_progress_ui("准备更新…")
        if hasattr(self, "gen_update_bar"):
            self.gen_update_bar.setVisible(False)

        # 更新路线与检查路线必须一致：git 仓库走 pull，zip 发布走下载解压
        if _git_repo_dir(self.app):
            w = GenericUpdateWorker(self.app, parent=self)
            w.progress.connect(self._on_generic_update_progress)
            w.done.connect(self._on_generic_update_done)
            w.failed.connect(self._on_generic_update_failed)
        else:
            w = ZipAppWorker(self.app, parent=self)
            w.progress.connect(self._on_generic_update_progress)
            w.percent.connect(self._on_installer_percent)
            w.done.connect(self._on_zip_done)
            w.failed.connect(self._on_generic_update_failed)
        self._gen_update_worker = w
        w.start()

    def _on_generic_update_progress(self, text):
        if not text:
            return
        if hasattr(self, "gen_update_btn"):
            self.gen_update_btn.setText(text)
        if hasattr(self, "install_status"):
            self.install_status.setText(text)

    def _on_generic_update_done(self, new_tag):
        self._gen_update_worker = None
        self._hide_install_progress_ui()
        # 重新读版本并刷新整张卡（检查状态也要重置，否则按钮停在“有新版本”）
        self._gen_check_started = False
        self._gen_has_update = False
        self._gen_retry = False
        self.rebuild_body()
        try:
            InfoBar.success("更新完成", "已更新到 %s" % (new_tag or "最新版本"),
                            duration=3000, parent=self,
                            position=InfoBarPosition.TOP_RIGHT)
        except Exception:
            QMessageBox.information(self, "更新完成",
                                    "已更新到 %s" % (new_tag or "最新版本"))

    def _on_generic_update_failed(self, msg):
        self._gen_update_worker = None
        self._hide_install_progress_ui()
        if hasattr(self, "gen_update_btn"):
            self.gen_update_btn.setEnabled(True)
            self.gen_update_btn.setText("更新失败，点击重试")
            self._gen_retry = True
        QMessageBox.warning(self, "更新失败", msg)

    # ===== lite 更新：exe 版本资源 + GitHub Releases latest =====
    def _lite_start_check(self):
        """lite 更新检查。每次 rebuild 只触发一次，避免 5s 轮询打爆 GitHub API
        （releases/latest 未登录限 60 次/小时）。"""
        if getattr(self, "_lite_check_started", False):
            return
        self._lite_check_started = True
        repo = GITHUB_RELEASE_REPO.get(self.app.get("key", ""))
        if not repo:
            self._lite_set_btn("版本检测不可用")
            return
        self._lite_check_worker = LiteReleaseCheckWorker(repo[0], repo[1], parent=self)
        self._lite_check_worker.done.connect(self._on_lite_check_done)
        self._lite_check_worker.failed.connect(self._on_lite_check_failed)
        self._lite_check_worker.start()

    def _lite_set_btn(self, text, enabled=False, style=None):
        if not hasattr(self, "update_btn"):
            return
        self.update_btn.setText(text)
        self.update_btn.setEnabled(enabled)
        if style:
            self.update_btn.setStyleSheet(style)

    def _rewire_update_btn_retry(self):
        """把更新按钮临时接到「重试检查」上（检查失败/异常时的统一恢复入口）。"""
        if not hasattr(self, "update_btn"):
            return
        try:
            self.update_btn.clicked.disconnect()
        except Exception:
            pass
        self.update_btn.clicked.connect(self._on_lite_check_retry)

    def _on_lite_check_failed(self, err):
        # 失败不再灰死按钮：改成可点击重试（GitHub API 未登录限 60 次/小时 +
        # 国内网络波动，一次失败很常见，必须给用户重试入口）
        self._lite_set_btn("检查更新失败（网络）· 点击重试", enabled=True)
        self._rewire_update_btn_retry()
        if hasattr(self, "changelog_text"):
            self.changelog_text.setPlainText(
                "更新检查失败（网络）：%s\n\n点击上方「检查更新失败」按钮重试。" % err)

    def _on_lite_check_retry(self):
        """检查失败后的手动重试入口：重置一次性守卫后重新走 _lite_start_check。"""
        w = getattr(self, "_lite_check_worker", None)
        if w is not None and w.isRunning():
            return  # 上一次检查还在跑，防连点
        self._lite_check_started = False
        self._lite_set_btn("检查更新中…", enabled=False)
        self._lite_start_check()

    def _on_lite_check_done(self, info):
        # 恢复按钮 → 更新入口：失败路径会把按钮改接到「重试」，成功后必须接回来
        if hasattr(self, "update_btn"):
            try:
                self.update_btn.clicked.disconnect()
            except Exception:
                pass
            self.update_btn.clicked.connect(self._on_lite_update)
        info = info or {}
        tag = (info.get("tag") or "").strip()
        if not tag:
            self._lite_set_btn("检查更新失败 · 点击重试", enabled=True)
            self._rewire_update_btn_retry()
            return
        cur = _exe_file_version(self.app.get("exe", ""))
        if not cur:
            self._lite_set_btn("无法识别本机版本 · 点击重试", enabled=True)
            self._rewire_update_btn_retry()
            return
        self._lite_remote = (tag, info.get("exe") or "", info.get("body") or "")
        self._lite_whl = info.get("whl") or ""
        # 各版本资产映射：选哪个版本，就下哪个版本的包
        self._lite_assets = {v["tag"]: (v.get("exe") or "", v.get("whl") or "")
                             for v in (info.get("versions") or [])}
        # 版本下拉 + 更新说明（与 ok-script 卡同款交互：选版本 → 看该版本说明）
        latest_item = tag          # 最新项可能被标成「3.1.0（最新）」，选中/看说明要用标注后的文本
        self._lite_version_map = {}
        if hasattr(self, "ver_combo"):
            try:
                self.ver_combo.currentTextChanged.disconnect()
            except Exception:
                pass
            self.ver_combo.clear()
            for v in (info.get("versions") or []):
                self._lite_version_map[v["tag"]] = v.get("body") or ""
                self.ver_combo.addItem(v["tag"])
            if tag and tag not in self._lite_version_map:
                # 列表没拉到时至少把 latest 放进去
                self._lite_version_map[tag] = info.get("body") or ""
                self.ver_combo.insertItem(0, tag)
            # 下拉标注「哪个是哪个」：奇想盒三条版本线（前端 exe / 后端 whl /
            # release tag）互不相干、经常不同步，只标一个「（当前）」会让人以为是 bug
            # （2026-10-02 用户反馈：前端 2.4.7 + 后端 2.4.8 时下拉看着怪）。
            # 现在分别标：当前前端 / 当前后端 / 最新。
            latest_item = self._lite_mark_combo(tag)
            self.ver_combo.currentTextChanged.connect(self._on_lite_version_changed)
            if latest_item and self.ver_combo.findText(latest_item) >= 0:
                self.ver_combo.setCurrentText(latest_item)
        self._lite_show_changelog(latest_item)
        self._lite_refresh_version_info(tag)
        # 按钮按「当前选中项」刷新（默认选中 latest）
        self._lite_refresh_update_btn()

    def _lite_refresh_version_info(self, tag=None):
        """重算卡片上的三条版本线提示（前端/后端/仓库最新）+ 徽章 + 有更新标志。

        后端刚装完时必须调一次：否则「后端 X」停留在更新前 check 时的旧值，
        用户会以为启动器没刷新（2026-10-02 用户截图反馈）。
        """
        cur = _exe_file_version(self.app.get("exe", ""))
        latest = tag or (getattr(self, "_lite_remote", ("", ""))[0]
                         if getattr(self, "_lite_remote", None) else "")
        try:
            has_new = bool(latest) and compare_version(
                _normalize_tag(latest), _normalize_tag(cur)) > 0
        except Exception:
            has_new = False
        # 存标志位供 snapshot() 用：QStackedWidget 里非当前页控件 isVisible()
        # 恒为 False，靠 update_btn.isVisible() 判断会让总览页永远看不到更新提示
        self._lite_has_update = has_new
        if hasattr(self, "ver_hint"):
            be = _lite_backend_version(self.app)
            self.ver_hint.setText(
                "前端 %s · 后端 %s · 仓库最新 %s%s"
                % (cur, be or "未知", latest or "—",
                   "（有更新）" if has_new else "（已是最新）"))
        # 徽章同步一次：rebuild 时调的那次还不知道有没有更新，这里补刷成「可更新 <tag>」
        self.refresh_badge()

    def _lite_mark_one(self, ver, suffix):
        """给某个版本号打标注：在列表里就改名，不在就按版本号倒序插一项。返回新项文本。"""
        item = "%s%s" % (ver, suffix)
        idx = self.ver_combo.findText(ver)
        if idx >= 0:
            # 说明文本跟着搬到新 key（选标注项仍能看到该版官方说明）
            self._lite_version_map[item] = self._lite_version_map.pop(ver, "")
            self.ver_combo.setItemText(idx, item)
            return item
        self._lite_version_map[item] = ""
        pos = self.ver_combo.count()
        try:
            vn = _normalize_tag(ver)
            for i in range(self.ver_combo.count()):
                if compare_version(_normalize_tag(self.ver_combo.itemText(i)), vn) < 0:
                    pos = i
                    break
        except Exception:
            pos = self.ver_combo.count()
        self.ver_combo.insertItem(pos, item)
        return item

    def _lite_mark_combo(self, latest_tag):
        """按当前真实版本给下拉打标注（当前前端 / 当前后端 / 最新）。

        约定：调用前 combo 里必须是**裸版本号**、_lite_version_map 的 key 亦然
        （_on_lite_check_done 刚重建完、或 _lite_remark_after_install 刚剥完标注）。
        返回标注后的「最新」项文本，供选中/显示说明使用。
        """
        cur = _exe_file_version(self.app.get("exe", ""))
        cur_be = _lite_backend_version(self.app)
        marks = {}
        if cur:
            marks.setdefault(cur, []).append("当前前端")
        if cur_be:
            marks.setdefault(cur_be, []).append("当前后端")
        latest_item = latest_tag
        for ver, kinds in marks.items():
            item = self._lite_mark_one(ver, "（%s）" % "·".join(kinds))
            if ver == latest_tag:
                latest_item = item
        if latest_tag and latest_tag not in marks and self.ver_combo.findText(latest_tag) >= 0:
            latest_item = self._lite_mark_one(latest_tag, "（最新）")
        return latest_item

    def _lite_remark_after_install(self):
        """装完（前端/后端）立即重标下拉，别等下次检查更新。

        步骤：剥掉所有旧标注（map 的 key 一并还原成裸版本号）→ 按当前版本重标 →
        恢复到原来选中的那一项。
        """
        if not hasattr(self, "ver_combo") or self.ver_combo.count() == 0:
            return
        strip = lambda t: re.sub(r"（[^（）]*）\s*$", "", t or "").strip()
        sel_raw = strip(self.ver_combo.currentText())
        try:
            self.ver_combo.currentTextChanged.disconnect()
        except Exception:
            pass
        items = [self.ver_combo.itemText(i) for i in range(self.ver_combo.count())]
        self.ver_combo.clear()
        for it in items:
            raw = strip(it)
            if raw != it:
                self._lite_version_map[raw] = self._lite_version_map.pop(it, "")
            self.ver_combo.addItem(raw)
        latest = (getattr(self, "_lite_remote", ("", ""))[0]
                  if getattr(self, "_lite_remote", None) else "")
        self._lite_mark_combo(latest)
        self.ver_combo.currentTextChanged.connect(self._on_lite_version_changed)
        # 恢复原来选中的项（按裸版本号找，选中它重标后的文本）
        for i in range(self.ver_combo.count()):
            if strip(self.ver_combo.itemText(i)) == sel_raw:
                self.ver_combo.setCurrentIndex(i)
                return
        self._lite_refresh_update_btn()

    def _lite_pick_frontend(self, sel):
        """前端 exe 的实际来源版本——所选版本没发 exe 时向下取最近一个带 exe 的版本。

        官方只给部分版本发 setup exe（实测 2.4.9、2.4.8 都只发了 whl），而后端 whl
        每个版本都有。所以按官方思路：选 2.4.9 → 2.4.8 也没有 → 用 2.4.7 的 exe。
        返回 (exe_url, 实际前端版本 tag)；找不到返回 ("", "")。
        """
        assets = getattr(self, "_lite_assets", {}) or {}
        e = assets.get(sel, ("", ""))[0]
        if e:
            return e, sel
        best = ""
        try:
            sel_n = _normalize_tag(sel)
            for t, (eu, _w) in assets.items():
                if not eu:
                    continue
                try:
                    if compare_version(_normalize_tag(t), sel_n) <= 0 and (
                            not best
                            or compare_version(_normalize_tag(t), _normalize_tag(best)) > 0):
                        best = t
                except Exception:
                    continue
        except Exception:
            best = ""
        return (assets.get(best, ("", ""))[0], best) if best else ("", "")

    def _lite_refresh_update_btn(self):
        """更新按钮跟随「查看版本」下拉的选中项。

        奇想盒有前端（exe）与后端（whl）两条独立版本线，所以对每个组件**分别**
        评估方向（升 / 降 / 已是该版 / 无资产），再组合成按钮文案：
          - 所选版本没发前端 exe 时，前端 exe 向下取最近一个带 exe 的版本
            （如选 2.4.9 → 2.4.8 也没有 → 用 2.4.7 的 exe），按钮写明「取自 X」
          - 后端 whl 每个版本都有，直接用所选版本
          - 例：选 2.4.9 → 「更新前端（取自2.4.7）到 2.4.7 + 后端已是 2.4.9（无可执行更新）」
                选 2.4.7 → 「更新前端到 2.4.7 + 降级后端到 2.4.7」
          - 全部无可执行动作 → 灰禁用并写明原因
        """
        if not hasattr(self, "update_btn") or not hasattr(self, "ver_combo"):
            return
        cur_fe = _exe_file_version(self.app.get("exe", ""))
        cur_be = _lite_backend_version(self.app)
        # 剥掉下拉里的一切标注后缀（（当前前端）/（当前后端）/（最新）/（当前）…）
        sel = re.sub(r"（[^（）]*）\s*$", "", self.ver_combo.currentText()).strip()
        if not sel:
            return

        assets = getattr(self, "_lite_assets", {}) or {}
        whl_u = assets.get(sel, ("", ""))[1]          # 后端 whl 直接用所选版本
        exe_u, fe_tag = self._lite_pick_frontend(sel)  # 前端向下取最近带 exe 的版本
        self._lite_selected = (sel, exe_u, whl_u, fe_tag)

        def _cmp(a, b):
            try:
                return compare_version(_normalize_tag(a), _normalize_tag(b))
            except Exception:
                return 0

        grey = ("QPushButton { background-color:rgba(255,255,255,0.10); "
                "color:#9aa0a6; border-radius:8px; font-weight:600; }")
        orange = ("QPushButton { background-color:#e65100; color:white; "
                  "border-radius:8px; font-weight:600; } "
                  "QPushButton:hover { background-color:#bf360c; }")
        blue = ("QPushButton { background-color:#1976d2; color:white; "
                "border-radius:8px; font-weight:600; } "
                "QPushButton:hover { background-color:#0d47a1; }")

        # 选中「（当前）」且该版本没有任何官方资产：无操作
        if cur_fe and sel == cur_fe and not exe_u and not whl_u:
            self._lite_set_btn("已是最新（%s）" % cur_fe, enabled=False, style=grey)
            return

        # 分别评估前端 / 后端方向：
        #   - 前端方向基于「实际来源版本 fe_tag」vs 当前前端（所选版可能没发 exe，
        #     此时 fe_tag 低于 sel，按钮里要写明「取自 fe_tag」）
        #   - 后端方向基于 sel vs 当前后端
        # 只把「真正要装」的组件（更新/降级）放进按钮；「已是该版」的组件不占位置
        parts = []
        if exe_u:
            fe = _cmp(fe_tag, cur_fe) if (cur_fe and fe_tag) else 1
            if fe != 0:
                src = "（取自%s）" % fe_tag if fe_tag != sel else ""
                parts.append("%s前端%s到 %s" % ("更新" if fe > 0 else "降级", src, fe_tag))
        if whl_u:
            be = _cmp(sel, cur_be) if cur_be else 1
            if be != 0:
                parts.append("%s后端到 %s" % ("更新" if be > 0 else "降级", sel))
        if not parts:
            # 所选版本前后端都已是该版，或该版本两类资产都不可用
            self._lite_set_btn("所选版本已是最新（%s）" % sel, enabled=False, style=grey)
            return
        # 颜色：全是「降级」 → 蓝；含「更新」 → 橙
        style = blue if all(p.startswith("降级") for p in parts) else orange
        self._lite_set_btn(" + ".join(parts), enabled=True, style=style)

    def _on_lite_update(self):
        """按官方手动更新流程：先装前端（exe），再装后端（whl）。

        顺序不能反——官方明确要求先跑 exe 更新前端、再更新后端；倒过来会被前端
        安装覆盖掉刚装好的后端（后端就装在内嵌 python 的 site-packages 里）。
        更新目标跟随「查看版本」下拉的选中项（可与官方流程一样升到最新，也可降级）。
        """
        _sel = getattr(self, "_lite_selected", ("", "", "", ""))
        sel, exe_url, whl_url, fe_tag = (_sel + ("", "", "", ""))[:4]
        if not sel:
            return
        if not exe_url and not whl_url:
            # 该版本两类资产都没有：引导去 releases 页手动处理
            repo = GITHUB_RELEASE_REPO.get(self.app.get("key", ""))
            url = ("https://github.com/%s/%s/releases/tag/%s" % (repo + (sel,))) if repo \
                else (self.app.get("website", "") or "")
            if url:
                QDesktopServices.openUrl(QUrl(url))
            return
        cur_fe = _exe_file_version(self.app.get("exe", ""))
        cur_be = _lite_backend_version(self.app)

        def _cmp(a, b):
            try:
                return compare_version(_normalize_tag(a), _normalize_tag(b))
            except Exception:
                return 0

        fe_act = bool(exe_url and fe_tag and (not cur_fe or _cmp(fe_tag, cur_fe) != 0))
        # 后端 whl 两种情况都要装：①所选后端与当前不同；②前端要动——
        # 前端安装程序会重置内嵌后端，装完必须重装 whl 才能把后端恢复到所选版本
        be_act = bool(whl_url and (fe_act or not cur_be or _cmp(sel, cur_be) != 0))
        if not fe_act and not be_act:
            return
        self._lite_need_whl = be_act
        steps = []
        targets = []
        if fe_act:
            targets.append("前端 %s" % fe_tag)
            note = ("所选 %s 未发布前端 exe，使用 %s 的安装包" % (sel, fe_tag)
                    if fe_tag != sel else "前端 %s → %s" % (cur_fe or "?", fe_tag))
            steps.append("1. 前端安装包（exe）：%s" % note)
        if be_act:
            targets.append("后端 %s" % sel)
            be_down = bool(cur_be and _cmp(sel, cur_be) < 0)
            if not fe_act:
                # 只动后端：说清从哪到哪
                note = "后端 %s → %s" % (cur_be or "?", sel)
            elif cur_be and _cmp(sel, cur_be) == 0:
                # 后端本来就是所选版本：前端装完被重置，重装 whl 属于「恢复」
                note = ("前端安装程序会重置内嵌后端，装完前端后重装 whl，"
                        "恢复后端到 %s" % sel)
            else:
                # 后端版本随所选变化：这是真正的更新/降级，不是恢复
                note = ("前端安装程序会重置内嵌后端，装完前端后安装 whl，"
                        "%s后端到 %s" % ("降级" if be_down else "更新", sel))
            steps.append("%d. 后端包（whl）：%s" % (len(steps) + 1, note))
        ans = QMessageBox.question(
            self.window(), "更新「%s」：%s"
            % (self.app.get("display", ""), " · ".join(targets)),
            "确认后将全自动一条龙完成（只需这一次确认）：\n"
            "① 下载并静默安装前端到当前安装目录「%s」（跟随本机实际安装位置，"
            "可能弹出一次系统授权）\n"
            "② 自动下载并安装后端（whl）\n"
            "全程只写入该安装目录，不会安装到系统盘。\n\n"
            "%s\n\n更新说明请见卡片内的「更新说明」。\n\n是否开始？"
            % (os.path.dirname(self.app.get("exe", "")), "\n".join(steps)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        if fe_act:
            # 前端包的路径按实际来源版本 fe_tag 命名（如选 2.4.9 实际装 2.4.7 的 exe）
            if be_act and whl_url:
                self._lite_start_whl_prefetch(sel, whl_url)  # 前端装期间并行预下载后端
            self._lite_download(fe_tag or sel, exe_url, "exe")
        else:
            self._lite_download(sel, whl_url, "whl")

    def _lite_download(self, tag, url, stage):
        """下载更新包（exe 或 whl），下载完按 stage 分派到对应安装步骤。"""
        self._lite_stage = stage
        cache = os.path.join(LAUNCHER_CACHE_DIR, "whimbox-update")
        fname = ("whimbox_app-setup-%s.exe" if stage == "exe"
                 else "whimbox-%s-py3-none-any.whl") % tag.lstrip("v")
        save = os.path.join(cache, fname)
        if os.path.isfile(save) and os.path.getsize(save) > 0:
            # 已下过直接进入下一步（重复点击不重复下载）
            self._lite_after_download(save)
            return
        # 复用 ok-script 卡的持久进度三件套（lite 分支 rebuild 时已隐藏）
        self.install_progress.setRange(0, 100)
        self.install_progress.setValue(0)
        self.install_progress.setVisible(True)
        self.install_status.setText("正在测速下载源（万载云节点 + 直链）…")
        self.install_status.setVisible(True)
        self.install_cancel_btn.setText("✕ 取消下载")
        self.install_cancel_btn.setVisible(True)
        try:
            self.install_cancel_btn.clicked.disconnect()
        except Exception:
            pass
        self.install_cancel_btn.clicked.connect(self._lite_cancel_download)
        self.update_btn.setEnabled(False)

        self._lite_dl_worker = LiteDownloadWorker(url, save, parent=self,
                                                  key=self.app.get("key", ""))
        self._lite_dl_worker.progress.connect(self._on_lite_progress)
        self._lite_dl_worker.finished_ok.connect(self._on_lite_downloaded)
        self._lite_dl_worker.failed.connect(self._on_lite_dl_failed)
        self._lite_dl_worker.start()

    def _on_lite_progress(self, done, total):
        pct = int(done * 100 / total) if total else 0
        self.install_progress.setValue(pct)
        self.install_status.setText("正在下载更新包… %d%%（%.1f / %.1f MB）"
                                    % (pct, done / 1048576, max(total, 1) / 1048576))

    def _on_lite_downloaded(self, path):
        self._hide_install_progress_ui()
        self.install_status.setText("下载完成")
        self.install_status.setVisible(True)
        self._lite_after_download(path)

    def _lite_after_download(self, path):
        if getattr(self, "_lite_stage", "exe") == "exe":
            self._lite_run_installer(path)
        else:
            self._lite_install_backend(path)

    def _lite_install_backend(self, whl_path):
        """官方「手动更新后端」的等价自动化：用奇想盒内嵌 python 装 whl。

        官方流程是 App 设置里选 whl 文件后自动安装；后端实际装在内嵌 python 的
        site-packages（实测有 whimbox + whimbox-<ver>.dist-info），所以用内嵌
        python 跑 pip install 是同一效果。
        """
        exe = self.app.get("exe", "")
        py = os.path.join(os.path.dirname(exe), "python-embedded", "python.exe")
        if not os.path.isfile(py):
            QMessageBox.warning(
                self.window(), "后端更新",
                "找不到奇想盒内嵌 Python：\n%s\n\n请打开奇想盒 → 设置 →「手动更新后端」，"
                "选择已下载的 whl 文件：\n%s" % (py, whl_path),
            )
            return
        # 先关掉奇想盒，避免占用正在替换的后端文件
        subprocess.run(
            ["taskkill", "/IM", os.path.basename(exe), "/F", "/T"],
            capture_output=True, text=True, encoding="gbk", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # pip 阶段同样给心跳（不设超时上界：装到一半被杀会留下残缺后端）
        self._lite_start_spin("正在安装后端（pip install whl）…（秒数停住不动=卡住了）")

        self._lite_pip_worker = LitePipWorker(py, whl_path, parent=self)
        self._lite_pip_worker.finished_ok.connect(self._on_lite_pip_done)
        self._lite_pip_worker.failed.connect(self._on_lite_pip_failed)
        self._lite_pip_worker.progress_text.connect(self._on_lite_pip_progress)
        self._lite_pip_worker.progress.connect(self._on_lite_pip_percent)
        self._lite_pip_worker.start()

    def _on_lite_pip_progress(self, text):
        """pip 的实时输出尾巴 → 下一秒的 spin 心跳里带出来（替代被隐藏的黑窗）。"""
        self._lite_spin_detail = text

    def _on_lite_pip_percent(self, pct):
        """pip 的真实进度 → 把走马灯切成会涨的确定进度条（和终端里一样）。"""
        self._lite_spin_pct = max(0, min(100, int(pct)))   # 状态行也跟着显示百分比
        bar = self.install_progress
        if bar.minimum() == 0 and bar.maximum() == 0:
            bar.setRange(0, 100)          # 走马灯 → 0-100 确定进度
        bar.setValue(self._lite_spin_pct)

    def _on_lite_pip_done(self, out):
        self._lite_stop_spin()
        self._hide_install_progress_ui()
        _sel = getattr(self, "_lite_selected", ("", "", "", "")) or ("", "", "", "")
        tag = _sel[0]
        fe_tag = _sel[3] if len(_sel) > 3 else tag
        self.install_status.setText("后端更新完成")
        self.install_status.setVisible(True)
        # 后端刚装完：立即重算 ver_hint / 徽章 / 按钮，别让卡片停留在更新前的旧值
        # （此前只弹完成框不刷新，「后端 X」一直显示装之前的版本，像没刷新一样）
        self._lite_refresh_version_info()
        self._lite_refresh_update_btn()
        self._lite_remark_after_install()   # 下拉的「（当前后端）」标注挪到刚装的版本
        # 所选版本没发前端 exe 时，前端实际装的是更低的 fe_tag，提示里写清楚
        fe_note = "" if (fe_tag and fe_tag == tag) else "（前端实际为 %s）" % fe_tag
        QMessageBox.information(
            self.window(), "更新完成",
            "奇想盒已更新到 %s%s，重新打开奇想盒即可生效。" % (tag, fe_note),
        )

    def _on_lite_pip_failed(self, err):
        self._lite_stop_spin()
        self._hide_install_progress_ui()
        self.update_btn.setEnabled(True)
        self.install_status.setText("后端安装失败：%s" % err)
        self.install_status.setVisible(True)
        QMessageBox.warning(
            self.window(), "后端更新失败",
            "%s\n\n可改用官方方式：打开奇想盒 → 设置 →「手动更新后端」，"
            "选择已下载的 whl 文件。" % err,
        )

    def _on_lite_dl_failed(self, err):
        self._hide_install_progress_ui()
        self.update_btn.setEnabled(True)
        self.install_status.setText("下载失败：%s" % err)
        self.install_status.setVisible(True)

    def _lite_cancel_download(self):
        w = getattr(self, "_lite_dl_worker", None)
        if w and w.isRunning():
            w.cancel()
        pw = getattr(self, "_lite_whl_prefetch_worker", None)
        if pw and pw.isRunning():
            pw.cancel()
        fe = getattr(self, "_lite_fe_worker", None)
        if fe and fe.isRunning():
            fe.cancel()
        self._hide_install_progress_ui()
        self.update_btn.setEnabled(True)

    # ---- 一条龙进度反馈：走马灯 + 每秒递减的倒计时（心跳） ----
    # 倒计时是"有没有卡住"的最直观信号：数字每秒都在动=活着，
    # 数字停住不动=UI 线程被阻塞/子进程卡死（用户原话：只要倒计时不动了我就知道是卡了）。
    def _lite_start_spin(self, base_text, timeout=None):
        """timeout=None（默认、绝大多数场景）：时长不可预测，只显示递增的「已等 Ns」心跳。

        不编造"剩余时间"——安装包/pip 每次耗时都可能差好几倍，拿单次测量当通用预算
        既没有意义，到点强杀还会把 --force-reinstall 的安装打断成半成品。
        只有确实存在已知上界的操作才传 timeout，那时才显示倒计时。
        """
        self._lite_stop_spin()
        self._lite_spin_base = base_text
        self._lite_spin_detail = ""   # 子进程实时输出的一行（如 Successfully uninstalled …）
        self._lite_spin_pct = -1      # 真实百分比（-1=还没拿到，此时秒数仍当心跳）
        self._lite_spin_start = time.time()
        self._lite_spin_deadline = (self._lite_spin_start + timeout) if timeout else None
        self.install_progress.setRange(0, 0)   # 不确定进度走马灯
        self.install_progress.setVisible(True)
        self.install_status.setVisible(True)
        self._lite_spin_timer = QTimer(self)
        self._lite_spin_timer.timeout.connect(self._lite_spin_tick)
        self._lite_spin_timer.start(1000)
        self._lite_spin_tick()   # 立刻显示一次，不用等第一秒

    def _lite_spin_tick(self):
        now = time.time()
        el = int(now - getattr(self, "_lite_spin_start", now))
        detail = getattr(self, "_lite_spin_detail", "")
        dl = getattr(self, "_lite_spin_deadline", None)
        pct = getattr(self, "_lite_spin_pct", -1)
        # 拿到真进度就显示百分比（不再当秒表）；拿不到的阶段（如 pip 收集依赖）
        # 仍用递增秒数当心跳，好让人看得出没卡死
        num = ("%d%%" % pct) if pct >= 0 else "已等 %ds" % el
        parts = ([detail] if detail else []) + [num]
        if dl is not None:
            remain = int(dl - now)
            parts.append("倒计时 %02d:%02d" % (remain // 60, remain % 60)
                         if remain > 0 else "已超时（仍在等待）")
        self.install_status.setText("%s【%s】"
                                    % (getattr(self, "_lite_spin_base", ""),
                                       " · ".join(parts)))

    def _lite_stop_spin(self):
        t = getattr(self, "_lite_spin_timer", None)
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        self._lite_spin_timer = None

    def _lite_run_installer(self, setup_path):
        """一条龙第 2 步：静默装前端到当前安装目录（锁定，绝不装系统盘）。

        不再弹"运行安装程序""继续更新后端"两次确认——这些已在 _on_lite_update 的
        唯一确认弹窗里一并告知。本方法纯自动：关进程 → 静默安装 → 校验 → 装后端。
        """
        exe = self.app.get("exe", "")
        target_dir = os.path.dirname(exe)
        _sel = getattr(self, "_lite_selected", ("", "", "", "")) or ("", "", "", "")
        fe_tag = _sel[3] if len(_sel) > 3 else ""

        self.install_cancel_btn.setText("✕ 取消安装")
        self.install_cancel_btn.setVisible(True)
        try:
            self.install_cancel_btn.clicked.disconnect()
        except Exception:
            pass
        self.install_cancel_btn.clicked.connect(self._lite_cancel_install)
        self.update_btn.setEnabled(False)

        # 静默安装可能数十秒~数分钟：走马灯 + 每秒递减的倒计时做心跳
        self._lite_start_spin(
            "正在静默安装前端到 %s …（请勿关闭，可能弹出一次系统授权；"
            "秒数停住不动=卡住了）" % target_dir)

        self._lite_fe_worker = LiteInstallFrontendWorker(
            setup_path, target_dir, exe, fe_tag, _exe_file_version(exe), parent=self)
        self._lite_fe_worker.finished_ok.connect(self._lite_on_frontend_done)
        self._lite_fe_worker.failed.connect(self._lite_on_frontend_failed)
        self._lite_fe_worker.start()

    def _lite_on_frontend_done(self, code):
        self._lite_stop_spin()
        _sel = getattr(self, "_lite_selected", ("", "", "", "")) or ("", "", "", "")
        fe_tag = _sel[3] if len(_sel) > 3 else (_sel[0] if _sel else "")
        if code.startswith("wrong_location:"):
            loc = code[len("wrong_location:"):]
            self._hide_install_progress_ui()
            self.update_btn.setEnabled(True)
            self.install_status.setText("前端装错位置：%s" % loc)
            self.install_status.setVisible(True)
            QMessageBox.warning(
                self.window(), "前端安装位置异常",
                "前端安装器未使用指定目录，装到了：\n%s\n\n"
                "本启动器已强制用 /D=%s 指定安装位置，仍出现此情况说明该版本安装器"
                "不支持 /D 参数。\n请手动卸载/删除该位置的奇想盒后重试，或改用官方更新。"
                % (loc, os.path.dirname(self.app.get("exe", ""))))
            return
        if code == "unchanged":
            self._hide_install_progress_ui()
            self.update_btn.setEnabled(True)
            cur = _exe_file_version(self.app.get("exe", ""))
            self.install_status.setText("前端未更新成功（仍为 %s）" % cur)
            self.install_status.setVisible(True)
            QMessageBox.warning(
                self.window(), "前端更新失败",
                "安装完成后前端版本号仍为 %s，未变成目标版本。\n\n"
                "可能原因：安装器未成功覆盖文件，或被系统/杀软拦截。\n"
                "可手动运行安装包重试，或改用官方更新。" % cur)
            return
        # ok / tolerant：继续后端（若需要）
        if code.startswith("tolerant:"):
            newv = code[len("tolerant:"):]
            self.install_status.setText("前端已安装（实际版本 %s，与目标略有出入，已继续）" % newv)
            self.install_status.setVisible(True)
        self._lite_remark_after_install()   # 前端装完：「（当前前端）」标注立即跟上
        if getattr(self, "_lite_need_whl", False):
            # 第 3 步：自动装后端（whl 并行预下载的此时多半已就绪）
            self._continue_backend()
        else:
            self._hide_install_progress_ui()
            self.update_btn.setEnabled(True)
            self.install_status.setText("前端已更新完成（无需更新后端）")
            self.install_status.setVisible(True)
            QMessageBox.information(
                self.window(), "更新完成",
                "奇想盒前端已更新到 %s，重新打开即可生效。" % fe_tag)

    def _lite_on_frontend_failed(self, err):
        self._lite_stop_spin()
        self._hide_install_progress_ui()
        self.update_btn.setEnabled(True)
        self.install_status.setText("前端安装失败：%s" % err)
        self.install_status.setVisible(True)
        QMessageBox.warning(self.window(), "前端安装失败", err)

    def _lite_cancel_install(self):
        fe = getattr(self, "_lite_fe_worker", None)
        if fe and fe.isRunning():
            fe.cancel()

    def _lite_start_whl_prefetch(self, tag, whl_url):
        """一条龙优化：前端安装期间并行预下载后端 whl。"""
        cache = os.path.join(LAUNCHER_CACHE_DIR, "whimbox-update")
        fname = "whimbox-%s-py3-none-any.whl" % tag.lstrip("v")
        save = os.path.join(cache, fname)
        self._lite_whl_ready = ""
        self._lite_whl_prefetch_failed = ""
        self._lite_whl_connected = False
        if os.path.isfile(save) and os.path.getsize(save) > 0:
            self._lite_whl_ready = save
            return
        w = LiteDownloadWorker(whl_url, save, parent=self,
                               key=self.app.get("key", ""))
        w.finished_ok.connect(lambda p: setattr(self, "_lite_whl_ready", p))
        w.failed.connect(lambda e: setattr(self, "_lite_whl_prefetch_failed", e))
        self._lite_whl_prefetch_worker = w
        w.start()

    def _continue_backend(self):
        """一条龙第 3 步：装后端 whl（已并行预下载则直接装，否则等/报错）。"""
        whl = getattr(self, "_lite_whl_ready", "")
        if whl and os.path.isfile(whl):
            self._lite_install_backend(whl)
            return
        if getattr(self, "_lite_whl_prefetch_failed", ""):
            self._hide_install_progress_ui()
            self.update_btn.setEnabled(True)
            self.install_status.setText("后端包下载失败：%s" % self._lite_whl_prefetch_failed)
            self.install_status.setVisible(True)
            QMessageBox.warning(
                self.window(), "后端更新失败",
                "后端（whl）包下载失败：%s\n\n可改用官方方式手动更新后端。"
                % self._lite_whl_prefetch_failed)
            return
        # 预下载还在跑：提示等待，等其 finished_ok 自动再次进入本方法
        self._lite_start_spin(
            "前端已装好，正在等待后端包下载完毕后自动安装…（秒数停住不动=卡住了）")
        w = getattr(self, "_lite_whl_prefetch_worker", None)
        if w and w.isRunning() and not getattr(self, "_lite_whl_connected", False):
            w.finished_ok.connect(self._continue_backend)
            w.failed.connect(self._lite_on_prefetch_failed)
            self._lite_whl_connected = True

    def _lite_on_prefetch_failed(self, err):
        self._lite_whl_prefetch_failed = err
        self._lite_stop_spin()
        self._hide_install_progress_ui()
        self.update_btn.setEnabled(True)
        self.install_status.setText("后端包下载失败：%s" % err)
        self.install_status.setVisible(True)
        QMessageBox.warning(
            self.window(), "后端更新失败",
            "后端（whl）包下载失败：%s\n\n可改用官方方式手动更新后端。" % err)

    def _on_lite_version_changed(self, text):
        """下拉切换版本 → 更新说明与更新按钮目标都跟着切换。"""
        self._lite_show_changelog(text)
        self._lite_refresh_update_btn()

    def _lite_show_changelog(self, tag):
        if not hasattr(self, "changelog_text"):
            return
        body = (getattr(self, "_lite_version_map", {}) or {}).get(tag, "").strip()
        if not body:
            body = ("这是本机当前安装的版本，官方 release 列表里没有它的更新说明。"
                    if "（当前" in (tag or "") else "（该版本未提供更新说明）")
        self.changelog_text.setPlainText("【%s】\n%s" % (tag, body))

    def _lite_script_dir(self):
        """奇想盒脚本目录（App 设置里「打开脚本目录」指向的就是 <App目录>/scripts）。"""
        return os.path.join(os.path.dirname(self.app.get("exe", "") or ""), "scripts")


    def _on_lite_script_update(self):
        d = self._lite_script_dir()
        if not os.path.isdir(d):
            QMessageBox.warning(
                self.window(), "更新跑图路线",
                "找不到奇想盒脚本目录：\n%s\n\n请先手动打开一次奇想盒（它会自动创建）。" % d)
            return
        ans = QMessageBox.question(
            self.window(), "更新跑图路线",
            "将从 nikkigallery/WhimboxScripts 下载全部路线脚本到：\n%s\n\n"
            "同名文件会被覆盖。\n\n完成后最后一步要在奇想盒 → 设置 里点「刷新脚本」才能生效"
            "（那是 App 内的按钮，本启动器无法代劳）。\n\n继续吗？" % d,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.install_progress.setRange(0, 100)
        self.install_progress.setValue(0)
        self.install_progress.setVisible(True)
        self.install_status.setText("正在获取路线列表…")
        self.install_status.setVisible(True)
        self.install_cancel_btn.setText("✕ 取消")
        self.install_cancel_btn.setVisible(True)
        try:
            self.install_cancel_btn.clicked.disconnect()
        except Exception:
            pass
        self.install_cancel_btn.clicked.connect(self._lite_script_cancel)
        self.script_btn.setEnabled(False)

        self._lite_script_worker = LiteScriptUpdateWorker(d, parent=self)
        self._lite_script_worker.progress.connect(self._on_lite_script_progress)
        self._lite_script_worker.finished_ok.connect(self._on_lite_script_done)
        self._lite_script_worker.failed.connect(self._on_lite_script_failed)
        self._lite_script_worker.start()

    def _on_lite_script_progress(self, done, total):
        pct = int(done * 100 / total) if total else 0
        self.install_progress.setValue(pct)
        self.install_status.setText("下载路线脚本 %d/%d" % (done, total))

    def _on_lite_script_done(self, count, d):
        self._hide_install_progress_ui()
        self.script_btn.setEnabled(True)
        self.install_status.setText("路线脚本已更新：%d 个" % count)
        self.install_status.setVisible(True)
        QMessageBox.information(
            self.window(), "路线更新完成",
            "已写入 %d 个路线脚本到：\n%s\n\n最后一步：打开奇想盒 → 设置 →「刷新脚本」。\n\n"
            "（官方提示：朝夕心愿 / 星海拾光 / 家园日常 开头的脚本是一条龙必需项，务必保留）"
            % (count, d),
        )

    def _on_lite_script_failed(self, err):
        self._hide_install_progress_ui()
        self.script_btn.setEnabled(True)
        self.install_status.setText("路线更新失败：%s" % err)
        self.install_status.setVisible(True)

    def _lite_script_cancel(self):
        w = getattr(self, "_lite_script_worker", None)
        if w and w.isRunning():
            w.requestInterruption()
        self._hide_install_progress_ui()
        self.script_btn.setEnabled(True)

    def build_installed_body(self):
        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.start_btn = PushButton("▶  启动应用")
        self.start_btn.setFixedHeight(42)
        self.start_btn.setStyleSheet(
            "QPushButton { background-color:#2e7d32; color:white; border-radius:8px; "
            "font-weight:600; } QPushButton:hover { background-color:#1b5e20; }"
        )
        # 槽随运行态切换（见 _refresh_start_btn），这里不固定 connect
        btn_row.addWidget(self.start_btn, stretch=1)
        self.body_box.addLayout(btn_row)

        # 卸载已收进右上角齿轮菜单（_build_card_menu），卡身不再放重复按钮

        # 更新按钮：已安装卡片总是显示，根据真实完整版本列表判断"是否有可更新版本"
        self.update_btn = PushButton("检查更新中…")
        self.update_btn.setFixedHeight(38)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self.open_update_dialog)
        self.body_box.addWidget(self.update_btn)
        self.refresh_update_button()  # 用当前已知信息立即刷一次

        # 查看版本（只读下拉）
        ver_row = QHBoxLayout()
        ver_row.setSpacing(10)
        ver_row.addWidget(CaptionLabel("查看版本"))
        self.ver_combo = ComboBox()
        self.ver_combo.setMinimumWidth(200)
        self.ver_combo.setPlaceholderText("选择版本查看说明...")
        self.populate_versions()
        ver_row.addWidget(self.ver_combo)

        self.refresh_btn = PushButton("↻ 刷新")
        self.refresh_btn.setFixedHeight(32)
        self.refresh_btn.setFixedWidth(78)
        self.refresh_btn.setToolTip("重新从网络拉取最新版本列表与更新说明")
        self.refresh_btn.clicked.connect(self.manual_refresh)
        ver_row.addWidget(self.refresh_btn)
        ver_row.addStretch(1)
        self.body_box.addLayout(ver_row)

        # 版本说明（changelog，只读）
        self.body_box.addWidget(CaptionLabel("版本说明"))
        self.changelog_text = QTextEdit()
        self.changelog_text.setReadOnly(True)
        # 自适应高度：内容少时 ≥120px 紧凑显示；内容多时按 commit 行数自动撑开。
        # 单列竖排布局下卡片可自由变高，不再设 maxHeight 截断（之前 360px 对长 commit 列表仍不够）。
        # QTextEdit 默认 sizeHint 基于 viewport，不会随 document 增长——需要监听 contentsChanged
        # 主动把 minHeight 调成「document 高度 + 边框 + 内边距」，才能让卡片随 changelog 自由撑高。
        self.changelog_text.setMinimumHeight(120)
        self.changelog_text.setPlaceholderText("选择目标版本后显示更新内容...")
        self.changelog_text.setStyleSheet(
            "QTextEdit { background-color: rgba(0,0,0,0.12); border-radius:6px; "
            "padding:6px; border:none; }"
        )
        self.changelog_text.document().contentsChanged.connect(self._adjust_changelog_height)
        self.body_box.addWidget(self.changelog_text)

        self.ver_combo.currentTextChanged.connect(self.on_version_changed)
        self.load_changelog()  # 初始状态也加载一次

    def build_uninstalled_body(self):
        # 未安装：「安装」按钮 + 「🔄 刷新检测」小按钮（让用户跑完外部初始化后能主动 trigger rebuild）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.install_btn = PushButton("安装")
        self.install_btn.setFixedHeight(42)
        self.install_btn.setStyleSheet(
            "QPushButton { background-color:#1976d2; color:white; border-radius:8px; "
            "font-weight:600; } QPushButton:hover { background-color:#1565c0; }"
        )
        self.install_btn.clicked.connect(self.install_app)
        btn_row.addWidget(self.install_btn, stretch=1)

        self.rescan_btn = PushButton("🔄 刷新检测")
        self.rescan_btn.setFixedHeight(42)
        self.rescan_btn.setFixedWidth(120)
        self.rescan_btn.setStyleSheet(
            "QPushButton { background-color:#37474f; color:white; border-radius:8px; "
            "font-weight:600; } QPushButton:hover { background-color:#455a64; }"
        )
        self.rescan_btn.setToolTip("如果你已经在外部装好了，点这里重新检测本机状态")
        self.rescan_btn.clicked.connect(self.rebuild_body)
        btn_row.addWidget(self.rescan_btn)
        self.body_box.addLayout(btn_row)

        # 游戏本体扫描提示（显卡驱动式：检测到游戏 → 引导装助手）。常驻显示直到装好。
        if getattr(self, "game_found_path", ""):
            sig = GAME_SIGNATURES.get(self.app.get("key", ""), {})
            gname = sig.get("display") or self.app.get("display", "游戏")
            found_hint = CaptionLabel(
                f"🎮 检测到本机已安装《{gname}》游戏本体：\n{self.game_found_path}\n"
                f"点「安装」装上本助手后，即可自动化日常任务。"
            )
            found_hint.setWordWrap(True)
            found_hint.setStyleSheet(
                "color:#64b5f6; background-color:rgba(25,118,210,0.10); "
                "border-radius:6px; padding:8px;"
            )
            self.body_box.addWidget(found_hint)

        hint = CaptionLabel(
            "点击「安装」即可装助手：优先下载完整安装包（解压即可直开本体）；"
            "若官方只提供 host 包，则解压后需再点一次「启动 host 初始化」。\n"
            "没检测到游戏本体不影响安装——助手装好后靠窗口自动找到游戏，装在哪都行。"
        )
        hint.setWordWrap(True)
        self.body_box.addWidget(hint)

    def set_game_found(self, exe_path):
        """游戏本体扫描命中后由主窗口回调。已装态忽略；未装态记录并重绘显示提示条。"""
        if not exe_path:
            return
        if getattr(self, "_installed", False) or getattr(self, "_host_ready", False):
            return  # 已装好助手，不需要引导
        self.game_found_path = exe_path
        self.rebuild_body()

    def build_half_installed_body(self):
        """半装状态：host.exe 已就位但 working/main.py 尚未生成。

        主动作改为「装完整版」——让聚合启动器自己下载完整 NSIS 整包并 7z 解好，
        解压后 working/main.py 就位，「启动应用」即可直开本体，彻底跳过 PyAppify host。
        仅在整包下载失败时才用「启动 host 初始化（兜底）」让 host 自己拉一次运行时。
        """
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        full_btn = PushButton("▶  装完整版（推荐）")
        full_btn.setFixedHeight(42)
        full_btn.setStyleSheet(
            "QPushButton { background-color:#2e7d32; color:white; border-radius:8px; "
            "font-weight:600; } QPushButton:hover { background-color:#1b5e20; }"
        )
        full_btn.setToolTip(
            "聚合启动器自己下载完整 NSIS 整包（~440MB，走镜像/反代）并 7z 解好，\n"
            "解压后 working/main.py 就位，之后「启动应用」直接开本体，永不弹 PyAppify host 小窗。"
        )
        full_btn.clicked.connect(self.install_app)
        btn_row.addWidget(full_btn, stretch=2)

        host_btn = PushButton("启动 host 初始化（兜底）")
        host_btn.setFixedHeight(42)
        host_btn.setStyleSheet(
            "QPushButton { background-color:#e65100; color:white; border-radius:8px; "
            "font-weight:600; } QPushButton:hover { background-color:#ef6c00; }"
        )
        host_btn.setToolTip(
            "仅当「装完整版」因网络/镜像失败时才用：启动 host.exe 让 PyAppify\n"
            "自己拉运行时（约几百 MB、需联网数分钟），结束后回这里点「🔄 刷新」。"
        )
        host_btn.clicked.connect(self.open_manager)  # 复用原版启动器入口（它会 runas 启动 host.exe）
        btn_row.addWidget(host_btn, stretch=2)

        self.rescan_btn = PushButton("🔄 刷新")
        self.rescan_btn.setFixedHeight(42)
        self.rescan_btn.setFixedWidth(120)
        self.rescan_btn.setStyleSheet(
            "QPushButton { background-color:#37474f; color:white; border-radius:8px; "
            "font-weight:600; } QPushButton:hover { background-color:#455a64; }"
        )
        self.rescan_btn.setToolTip("如果你已经在外部完成了 host 初始化，点这里重新检测")
        self.rescan_btn.clicked.connect(self.rebuild_body)
        btn_row.addWidget(self.rescan_btn)
        self.body_box.addLayout(btn_row)

        hint = CaptionLabel(
            "已存在 host 引导包，但完整运行时（Python venv、working/、cache）尚未初始化。\n\n"
            "推荐点上方「▶ 装完整版（推荐）」让聚合启动器直接下完整安装包并解好，\n"
            "之后「启动应用」即可直开助手主窗口，彻底跳过 PyAppify host 小窗。\n"
            "（若整包下载失败，再用「启动 host 初始化（兜底）」让 host 自己拉一次。）"
        )
        hint.setWordWrap(True)
        self.body_box.addWidget(hint)

    # ===== 只读数据 =====
    def manual_refresh(self):
        """手动重新拉取版本列表与说明（只读，不写任何 app 目录）。"""
        self.data = load_app_json(self.app["app_json"])
        self.profile = get_current_profile(self.data)
        self.populate_versions()  # 重新填缓存版本 + 后台拉取完整 github 版本
        self.load_changelog()

    def _adjust_changelog_height(self):
        """按 document 实际高度调整 changelog_text 的 minHeight，让卡片随 commit 列表自动撑开。

        QTextEdit 默认 sizeHint 基于 viewport，不会随 document 增长——必须手动把
        minHeight 设成「document 高度 + 边框 + 内边距」。监听 contentsChanged 后，
        setPlainText/setHtml 一变文档就触发，连带父卡片布局也跟着撑高。
        """
        if not hasattr(self, "changelog_text"):
            return
        doc_h = int(self.changelog_text.document().size().height())
        # frameWidth()*2（上下边框）+ 文档上下内边距 + 4px 微调余量
        extra = self.changelog_text.frameWidth() * 2 + 6
        self.changelog_text.setMinimumHeight(max(120, doc_h + extra))

    def refresh_data(self):
        # lite 模式：无 app_json 可读，只维护「安装态 + 运行态」
        if self.app.get("lite") or self.app.get("generic"):
            exe = self.app.get("exe", "") or ""
            now_installed = bool(exe) and os.path.isfile(exe)
            if now_installed != self._installed:
                self.rebuild_body()
                return
            if not self._installed:
                return
            self.refresh_badge()
            return

        data = load_app_json(self.app["app_json"])
        now_installed = bool(data)
        if now_installed != self._installed:
            # 用户装好/卸载后刷新整张卡片动态区
            self.rebuild_body()
            return
        if not self._installed:
            return
        self.data = data
        self.profile = get_current_profile(self.data)
        # 仅在空白时才覆盖小灰字，避免抢走"已发起启动"过渡提示
        if not self.status_label.text():
            self.status_label.setText(self.get_status_text())
        self.refresh_badge()
        self.update_progress_ui()
        new_ver = self.data.get("current_version", "") or "未知"
        if self.ver_tag.text() != new_ver:
            self.ver_tag.setText(new_ver)
            self.populate_versions()
            self.load_changelog()
            self.refresh_update_button()

    def snapshot(self):
        """返回本卡片的只读状态快照，给总览页（OverviewCard）用。

        总览页不自己起线程拉版本、也不重复跑 tasklist 检测进程，一律读这里，
        保证总览页与游戏详情页状态永远一致，且不额外增加网络请求/进程扫描开销。
        """
        if getattr(self, "_lite", False):
            # lite 卡：_on_lite_check_done 已把结论存进 _lite_has_update
            has_update = bool(getattr(self, "_lite_has_update", False))
        else:
            # ok-script 卡：badge 文案承载「可更新」语义（update_btn.isVisible()
            # 在 QStackedWidget 隐藏页上恒 False，不能用于跨页判断）
            has_update = self.badge.text().startswith("可更新")
        return {
            "installed": bool(getattr(self, "_installed", False)),
            "host_ready": bool(getattr(self, "_host_ready", False)),
            "version": self.ver_tag.text() or "未知",
            "running": bool(self.run_tag.isVisible()),
            "badge": self.badge.text(),
            "status": self.status_label.text(),
            "has_update": has_update,
            "game_found": getattr(self, "game_found_path", ""),
        }

    def _is_process_running(self):
        """判定本 app 对应的原启动器是否真实在跑（兜底 app.json.running 不可靠）。

        监测目标就是那个 exe 程序本体（如 ok-nte.exe）。判定优先级：
          1）先看进程表里是否有该 exe 的镜像名（tasklist /FI IMAGENAME）——最直接、最准；
          2）PyAppify 打包的启动器常以内嵌 pythonw.exe 方式运行（exe 主体藏在 pythonw
             里，进程表里见不到 ok-nte.exe 镜像名，只见 pythonw.exe），且 PyAppify
             会把 CommandLine/ExecutablePath 在 wmic 视角下清空（token 降权），无法靠
             命令行匹配 working 目录。**唯一可靠线索是窗口标题**（tasklist /V CSV 第 9
             列），异环标题固定含 "ok-nte"、鸣潮含 "ok-ww" 等。tasklist 走纯 cmd、
             GBK 编码与 encoding="gbk" 完美匹配，不会有 PowerShell 那种 UTF-16/UTF-8
             编码混乱的坑（曾因 encoding="gbk" 解 PowerShell stdout 抛 UnicodeDecodeError
             导致整条路径静默 return False 的根因）。

        所有子进程走 CREATE_NO_WINDOW，不弹黑窗。
        """
        try:
            key = _pyapp_title_key(self.app)  # PyAppify 内部名，如 ok-ef / ok-nte
            if not key:
                return False

            import subprocess as _sp
            import csv as _csv
            import io as _io
            flags = getattr(_sp, "CREATE_NO_WINDOW", 0)

            # ① 优先查 exe 镜像名（某些版本/状态下进程表里会有 ok-nte.exe）
            out = _sp.run(
                ["tasklist", "/FI", f"IMAGENAME eq {key}.exe", "/NH"],
                capture_output=True, text=True,
                encoding="gbk", errors="replace", creationflags=flags,
            )
            if f"{key}.exe" in out.stdout.lower():
                return True

            # ② 回退：pythonw 形态运行时，按窗口标题定位（cmd GBK、稳）
            #    限定 /FI pythonw.exe 避免扫全表（200 进程会阻塞 2~5 秒）
            out = _sp.run(
                ["tasklist", "/FI", "IMAGENAME eq pythonw.exe",
                 "/V", "/FO", "CSV", "/NH"],
                capture_output=True, text=True,
                encoding="gbk", errors="replace", creationflags=flags,
            )
            for row in _csv.reader(_io.StringIO(out.stdout)):
                # CSV: image,pid,session,ses#,mem,status,user,cpu,window title
                if len(row) >= 9 and key in row[8].lower():
                    return True
            return False
        except Exception:
            return False

    def refresh_badge(self):
        """根据更新/安装状态刷新徽章（仅承载「未安装 / 已安装 / 可更新」语义）。

        运行态由三个独立控件分工，互不重复：
          - 徽章：只显示「已安装 / 可更新 vX」（不写"运行中"）
          - run_tag（徽章右侧独立标签）：仅运行中时显示「● 运行中」绿字
          - 启动按钮：运行中时改写「强制关闭」红底（点它二次确认后杀进程）
        运行判定走 _is_process_running 兜底（app.json.running 不可靠）。
        """
        d = self.data
        # 严格以真实进程为准：app.json.running 字段是原启动器启动时写、关闭时没清，
        # 异环进程死透后 app.json 还留着 true，会让聚合启动器持续误判"运行中"。
        # 兜底机制是「tasklist 找不到时多等一次轮询」而非直接相信过期字段。
        running = self._is_process_running()
        # 按钮随运行态切换（启动应用 / 强制关闭）
        self._refresh_start_btn(running=running)
        # run_tag：仅运行中可见
        if hasattr(self, "run_tag"):
            self.run_tag.setVisible(bool(running))
        if running:
            self.badge.setText("已安装")
            self.badge.setStyleSheet(
                "background-color:rgba(45,125,50,0.25); color:#8dffb0; "
                "border-radius:9px; padding:3px 12px; font-size:12px; font-weight:600;"
            )
            return
        # lite 卡：没有 app.json 的版本列表，最新版本来自 GitHub release tag
        if getattr(self, "_lite", False):
            tag = (getattr(self, "_lite_remote", ("",)) or [""])[0]
            if getattr(self, "_lite_has_update", False) and tag:
                self.badge.setText("可更新 %s" % tag)
                self.badge.setStyleSheet(
                    "background-color:rgba(230,81,0,0.28); color:#ffb74d; "
                    "border-radius:9px; padding:3px 12px; font-size:12px; font-weight:600;"
                )
            else:
                self.badge.setText("已安装")
                self.badge.setStyleSheet(
                    "background-color:rgba(45,125,50,0.25); color:#8dffb0; "
                    "border-radius:9px; padding:3px 12px; font-size:12px; font-weight:600;"
                )
            return
        versions = d.get("available_versions", []) or []
        current = d.get("current_version", "")
        # 找「最新比 current 新的」版本（不是 available_versions[0]，
        # 那个是 app.json 写入顺序的任意一项，可能就是 current 本身或更老——
        # 比如 current=v3.6.6、available_versions[0]=v3.6.5，徽章就会误报「可更新 v3.6.5」
        # 把降级当成升级推给用户）。
        # _all_versions 是 _on_versions_fetched 按 ver_key 倒序排好的完整列表，
        # 迭代它遇到的第一个 > current 就是真正的最新可更新版本；
        # _all_versions 还没就绪时再用 available_versions 兜底（顺序无所谓，
        # 只要 > current 就算）。
        newer = None
        all_v = getattr(self, "_all_versions", None) or []
        if current:
            for v in all_v:
                vn = _normalize_tag(v)
                if vn and compare_version(vn, current) > 0:
                    newer = vn
                    break
            if newer is None:
                for v in versions:
                    vn = _normalize_tag(v)
                    if vn and compare_version(vn, current) > 0:
                        newer = vn
                        break
        if newer:
            self.badge.setText(f"可更新 {newer}")
            self.badge.setStyleSheet(
                "background-color:rgba(255,152,0,0.25); color:#ffb74d; "
                "border-radius:9px; padding:3px 12px; font-size:12px; font-weight:600;"
            )
            return
        self.badge.setText("已安装")
        self.badge.setStyleSheet(
            "background-color:rgba(45,125,50,0.25); color:#8dffb0; "
            "border-radius:9px; padding:3px 12px; font-size:12px; font-weight:600;"
        )

    def _refresh_start_btn(self, running: bool):
        """根据运行态切换「启动/关闭」按钮：未运行→「▶ 启动应用」（绿、启动）；
        运行中→「强制关闭」（红、终止进程）。槽随状态动态切换，避免误触发。

        与徽章同源（都基于 _is_process_running）。运行中时按钮可点，点一下直接
        taskkill 掉窗口标题含本 app key 的 pythonw 进程（见 _kill_app_by_title），
        比灰着不能点更实用；关掉后下次轮询自动回落到「▶ 启动应用」。
        """
        if not hasattr(self, "start_btn"):
            return
        # 先断开旧槽，避免状态切换后记重触发
        try:
            self.start_btn.clicked.disconnect()
        except Exception:
            pass
        if running:
            self.start_btn.setText("强制关闭")
            self.start_btn.setEnabled(True)
            self.start_btn.setStyleSheet(
                "QPushButton { background-color:#c62828; color:white; border-radius:8px; "
                "font-weight:600; } QPushButton:hover { background-color:#8e0000; }"
            )
            self.start_btn.clicked.connect(self._on_force_stop)
        else:
            self.start_btn.setText("▶  启动应用")
            self.start_btn.setEnabled(True)
            self.start_btn.setStyleSheet(
                "QPushButton { background-color:#2e7d32; color:white; border-radius:8px; "
                "font-weight:600; } QPushButton:hover { background-color:#1b5e20; }"
            )
            self.start_btn.clicked.connect(self.launch_app)

    def _on_force_stop(self):
        """运行中时「强制关闭」按钮回调：二次确认后终止进程并刷新。"""
        name = self.app.get("display", os.path.basename(
            self.app.get("exe", "")).lower().removesuffix(".exe"))
        ans = QMessageBox.question(
            self.window(), "强制关闭确认",
            f"确定要强制关闭「{name}」吗？\n\n"
            "该操作会直接终止进程，未保存的数据可能丢失，且无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,  # 默认聚焦“否”，防误触
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        if self.app.get("lite") or self.app.get("generic"):
            # Electron 等普通 exe：按镜像名整棵进程树终止。
            # _kill_app_by_title 只匹配 pythonw.exe（PyAppify 形态），对 whimbox_app.exe 无效。
            exe_name = os.path.basename(self.app.get("exe", "")) or ""
            r = subprocess.run(
                ["taskkill", "/IM", exe_name, "/F", "/T"],
                capture_output=True, text=True,
                encoding="gbk", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            ok = r.returncode == 0
            msg = ("已终止 %s" % exe_name) if ok else (
                "终止失败：%s" % ((r.stderr or r.stdout or "").strip() or "未知错误"))
        else:
            key = _pyapp_title_key(self.app)  # PyAppify 内部名，如 ok-ef / ok-nte
            ok, msg = _kill_app_by_title(key)
        QMessageBox.information(self.window(), "强制关闭", msg)
        # 立即刷新状态（不依赖下次 5 秒轮询）
        self.refresh_data()

    def refresh_update_button(self):
        """根据下拉框选中的版本（或回退到最新比 current 新的）刷新按钮文案/颜色。

        行为：
          - 下拉选中 > current → "更新到 {X}" 橙色
          - 下拉选中 < current → "降级到 {X}" 蓝色
          - 下拉选中 == current（且后台有更新）→ "更新到 {最新newer}" 橙色
            —— 这样下拉在当前版本时也能立刻看到"有新版本可装"提示
          - 下拉选中 == current（且无更新）→ "已是最新" 灰色
          - 下拉无有效选择 + 后台有更新 → "更新到 {最新newer}" 橙色
          - 下拉无有效选择 + 已是最新 → "已是最新" 灰色
        """
        if not hasattr(self, "update_btn"):
            return
        cur = _normalize_tag(self.data.get("current_version", "")) if self.data else ""

        # 1) 预算"最新比 current 新的"——这是兜底目标
        latest_newer = None
        all_v = getattr(self, "_all_versions", None) or []
        if cur and all_v:
            for v in all_v:
                vn = _normalize_tag(v)
                if vn and compare_version(vn, cur) > 0:
                    latest_newer = vn
                    break

        target = None
        label_prefix = "更新到"

        # 2) 看下拉选中的（仅当 != current 时覆盖 latest_newer；选 current 时不覆盖，
        #    这样按钮会回落到 latest_newer，给出"有新版本可装"的提示）
        if hasattr(self, "ver_combo") and hasattr(self, "_version_map"):
            sel_text = self.ver_combo.currentText()
            sel_raw = self._version_map.get(sel_text)
            if sel_raw:
                sel_norm = _normalize_tag(sel_raw)
                if sel_norm and cur:
                    cmp = compare_version(sel_norm, cur)
                    if cmp > 0:
                        target = sel_norm
                        label_prefix = "更新到"
                    elif cmp < 0:
                        target = sel_norm
                        label_prefix = "降级到"
                    # cmp == 0: 不覆盖，target 保持 None → 走 latest_newer 兜底

        # 3) 兜底 latest_newer
        if not target and latest_newer:
            target = latest_newer
            label_prefix = "更新到"

        # 4) 再兜底到 app.json 缓存（_all_versions 还没拉到的过渡期）
        if not target and self.data:
            avail = self.data.get("available_versions", []) or []
            for v in avail:
                vn = _normalize_tag(v)
                if cur and vn and compare_version(vn, cur) > 0:
                    target = vn
                    label_prefix = "更新到"
                    break

        # 缓存 target，供 open_update_dialog 预选用
        self._current_target = target
        self._current_target_label = (
            f"{label_prefix} {target}" if target else None
        )

        if target:
            # 升降级按钮（升级橙色，降级蓝色以示"回退需谨慎"）
            self.update_btn.setText(f"{label_prefix} {target}")
            self.update_btn.setEnabled(True)
            if label_prefix == "降级到":
                self.update_btn.setStyleSheet(
                    "QPushButton { background-color:rgba(33,150,243,0.15); "
                    "color:#64b5f6; border:1px solid #2196f3; border-radius:8px; "
                    "font-weight:600; } "
                    "QPushButton:hover { background-color:rgba(33,150,243,0.28); }"
                )
            else:
                self.update_btn.setStyleSheet(
                    "QPushButton { background-color:rgba(255,152,0,0.15); "
                    "color:#ffb74d; border:1px solid #ff9800; border-radius:8px; "
                    "font-weight:600; } "
                    "QPushButton:hover { background-color:rgba(255,152,0,0.28); }"
                )
            tip = f"当前 {cur}，{label_prefix} {target}"
            # 特别说明：下拉在当前版本但按钮指向更新的情况
            if hasattr(self, "ver_combo") and hasattr(self, "_version_map"):
                sel_text = self.ver_combo.currentText()
                sel_raw = self._version_map.get(sel_text)
                if sel_raw and cur and _normalize_tag(sel_raw) == cur:
                    tip += "（下拉在当前版本，按钮指向最新可用更新）"
            tip += "（下载写入本启动器目录，下载后可一键应用到 working/）"
            self.update_btn.setToolTip(tip)
        else:
            self.update_btn.setText("已是最新")
            self.update_btn.setEnabled(True)  # 仍可点开看版本/说明
            self.update_btn.setStyleSheet(
                "QPushButton { background-color:rgba(255,255,255,0.05); "
                "color:#9a9a9a; border:1px solid #555; border-radius:8px; "
                "font-weight:500; } "
                "QPushButton:hover { background-color:rgba(255,255,255,0.10); "
                "color:#cccccc; }"
            )
            self.update_btn.setToolTip("当前已是最新版本")

    def get_status_text(self):
        """小灰字 status_label 的文案：仅承担"启动过渡"提示，运行态完全交给徽章。

        之前版本小灰字会显示"运行中/未运行"，跟徽章 1:1 复读（信息冗余）。
        现在空字符串：徽章负责总结态（运行中/已安装/未安装/可更新），
        小灰字仅在刚点启动瞬间显示"已发起启动（等待窗口出现）"，
        5 秒后由 launch_app 的 QTimer.singleShot 清空，回到空白。
        """
        return ""

    def _human_update_state(self, state):
        """把原启动器写的 update_state 翻成中文阶段名。"""
        s = (state or "").lower()
        if any(k in s for k in ("check", "detect", "检测")):
            return "检测更新"
        if any(k in s for k in ("download", "下载")):
            return "下载中"
        if any(k in s for k in ("extract", "unzip", "解压", "decompress")):
            return "解压中"
        if any(k in s for k in ("install", "安装")):
            return "安装中"
        if any(k in s for k in ("finish", "done", "完成")):
            return "即将完成"
        return state or "进行中"

    def update_progress_ui(self):
        """根据 app.json 的 update_state 显示更新进度（只读，不写任何文件）。"""
        d = self.data or {}
        state = (d.get("update_state") or "").strip()
        err = d.get("update_error")

        # 空闲：隐藏
        if not state or state.lower() == "idle":
            self.update_bar.setVisible(False)
            self.update_label.setVisible(False)
            return

        # 出错：红字提示，隐藏进度条
        if "error" in state.lower() or "fail" in state.lower() or err:
            self.update_bar.setVisible(False)
            self.update_label.setVisible(True)
            self.update_label.setStyleSheet("color:#ff6b6b; font-size:12px;")
            msg = str(err) if err else state
            self.update_label.setText(f"更新失败：{msg}")
            return

        # 进行中：显示滚动进度条 + 阶段文字（原启动器未提供精确百分比）
        target = d.get("update_target_version") or ""
        label = f"更新中：{self._human_update_state(state)}"
        if target:
            label += f" → {target}"
        self.update_bar.setVisible(True)
        self.update_label.setVisible(True)
        self.update_label.setStyleSheet("color:#ffb74d; font-size:12px;")
        self.update_label.setText(label)

    def on_version_changed(self):
        """下拉框选中版本变化：刷新版本说明 + 刷新更新/降级按钮。"""
        self.load_changelog()
        self.refresh_update_button()

    def _ensure_current_in_versions(self, versions):
        """确保 current 在 versions 列表里（app.json 可能漏写当前版本，导致下拉里看不到）。

        不强制置顶：按版本号（newest first）插入到正确位置，让 current 出现在它本该在的位置。
        用 ver_key 做存在性比较，避免 refs/tags/vX.Y.Z^{} 这种带 ref 前缀的形态被漏判。
        """
        cur = _normalize_tag(self.data.get("current_version", "")) if self.data else ""
        if not cur:
            return versions
        cur_key = ver_key(cur)
        # 已存在（按 ver_key 比较，含 v 前缀/ refs/tags/ 前缀 / ^{} 后缀的形态都能匹配）就不动
        if any(ver_key(_normalize_tag(v)) == cur_key for v in versions):
            return versions
        cur_n = _normalize_tag(cur)
        # current 不在列表里 → 按 ver_key 排序插入到正确位置（newest first）
        result = list(versions)
        inserted = False
        for i, v in enumerate(versions):
            if ver_key(_normalize_tag(v)) < cur_key:
                result.insert(i, cur_n)
                inserted = True
                break
        if not inserted:
            # current 比所有列出的版本都旧（或无可比）→ 追加到末尾
            result.append(cur_n)
        return result

    def populate_versions(self):
        self.ver_combo.blockSignals(True)
        self.ver_combo.clear()
        self._version_map.clear()
        current = _normalize_tag(self.data.get("current_version", ""))
        versions = self._ensure_current_in_versions(
            self.data.get("available_versions", []) or []
        )
        seen = set()
        for v in versions:
            v = _normalize_tag(v)
            if v in seen:
                continue
            seen.add(v)
            display = format_version_display(v, current)
            self._version_map[display] = v
            self.ver_combo.addItem(display)
        # 打开启动器时默认跳到最新版本，让用户一眼看到有没有更新
        if versions:
            self.ver_combo.setCurrentIndex(0)
        self.ver_combo.blockSignals(False)

        # 后台从各游戏本地 git 仓库读取「版本 + 更新说明」（与原启动器同源，
        # 数据完全一致；不再 spawn 原启动器 exe，避免弹出原启动器 GUI）。只读。
        exe = self.app.get("exe", "")
        if exe and os.path.isfile(exe):
            if self._version_fetcher and self._version_fetcher.isRunning():
                self._version_fetcher.requestInterruption()
                self._version_fetcher.wait(1000)
            worker = GitVersionFetcher(exe, parent=self)
            worker.fetched.connect(self._on_versions_fetched)
            worker.failed.connect(self._on_version_fetch_failed)
            worker.start()
            self._version_fetcher = worker
            self._version_fetch_started = True
            # 异步请求刚发出去时，先在 changelog 上提示一下"正在拉取"，避免用户看到缓存说明
            if hasattr(self, "changelog_text") and self.changelog_text.toPlainText().startswith("该版本"):
                self.changelog_text.setPlainText("正在从原启动器拉取版本说明…")
        else:
            # 无 exe（如未安装）时保留缓存列表，changelog 走兜底说明
            pass

    def _on_versions_fetched(self, items):
        """原启动器版本列表（含 update_note）拉取完成：刷新下拉框与说明缓存。"""
        if not items or not hasattr(self, "ver_combo"):
            return
        # items: 原启动器返回的 list of {version, previous_version, update_note}
        notes_list = [it for it in items
                      if isinstance(it, dict) and it.get("version")]
        if not notes_list:
            return
        # 必须按 ver_key 排序再交给 calculate_update_notes：它用 [min_idx:max_idx+1]
        # 索引切片来取 current → target 之间的所有版本，若列表未按版本号排序而是按
        # GitHub release 创建时间/任意顺序排（如 ok-ww 实测是 v3.6.5(0)/v3.6.4(1)/v3.5.32(2)/...
        # /v3.6.7-beta.2(11)/v3.6.6-beta.1(12)），中间会夹进十几二十个跟当前跨度无关的版本，
        # 渲染「v3.6.5 → v3.6.6-beta.1」的更新说明时会堆出 30+ 行乱码 commit。
        notes_list = sorted(
            notes_list,
            key=lambda it: ver_key(_normalize_tag(it.get("version", ""))),
            reverse=True,
        )
        self._version_notes_list = notes_list
        version_strings = [_normalize_tag(it["version"]) for it in notes_list]
        current = _normalize_tag(self.data.get("current_version", "")) if self.data else ""
        old_text = self.ver_combo.currentText()
        version_strings = self._ensure_current_in_versions(version_strings)
        # 倒序保留作为兜底（上面已对 notes_list 排过同序，下拉显示顺序与说明聚合索引一致）
        version_strings = sorted(version_strings, key=ver_key, reverse=True)

        self.ver_combo.blockSignals(True)
        self.ver_combo.clear()
        self._version_map.clear()
        seen = set()
        for v in version_strings:
            v = _normalize_tag(v)
            if v in seen:
                continue
            seen.add(v)
            display = format_version_display(v, current)
            self._version_map[display] = v
            self.ver_combo.addItem(display)

        # 尽量保留用户已选；若已选项不存在则默认跳到最新版
        idx = self.ver_combo.findText(old_text)
        self.ver_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.ver_combo.blockSignals(False)
        self._all_versions = version_strings  # 缓存完整列表，供更新对话框/按钮使用
        self.load_changelog()
        self.refresh_update_button()

    def _on_version_fetch_failed(self, error_msg):
        """PyAppify exe 拉版本列表失败：把真实错误显示出来（之前是静默吞掉），便于排查。

        仍然保留 app.json 缓存的版本列表 + 缓存的 update_note 作为兜底，不让界面塌掉。
        """
        # 只在 changelog 还没被用户看到真实数据时，才覆盖提示
        current_text = self.changelog_text.toPlainText() if hasattr(self, "changelog_text") else ""
        if current_text.startswith("正在从原启动器拉取版本说明"):
            self.changelog_text.setPlainText(
                "⚠ 原启动器拉取失败，已回退到 app.json 缓存说明：\n"
                f"  错误：{error_msg}\n\n"
            )
        # 把错误记到启动器日志（terminal / log file），方便事后排查
        try:
            print(f"[GitVersionFetcher] 失败: {error_msg}")
        except Exception:
            pass

    def _show_cached_note(self):
        """在线/原启动器拿不到说明时，回退 app.json 缓存的 update_note。"""
        notes = self.data.get("update_note", []) if self.data else []
        if notes:
            self.changelog_text.setPlainText(
                "在线说明获取失败，已回退到最新版缓存说明：\n\n" +
                "\n".join(f"• {n}" for n in notes)
            )
            return
        self.changelog_text.setPlainText("该版本暂不支持在线显示更新说明。")

    def load_changelog(self):
        """显示 current → 目标版本 的更新说明，数据与原启动器同源（PyAppify 版本列表）。"""
        version = self._version_map.get(self.ver_combo.currentText())
        current = _normalize_tag(self.data.get("current_version", "")) if self.data else ""

        if not version:
            self.changelog_text.clear()
            self.changelog_text.setPlaceholderText("选择目标版本后显示更新内容...")
            return

        notes_list = getattr(self, "_version_notes_list", None)
        if notes_list:
            notes = calculate_update_notes(notes_list, current, version)
            if notes:
                self.changelog_text.setPlainText("\n".join(f"• {n}" for n in notes))
                return
            # 拉到了版本列表但拼不出 notes → 大概率是字段名/嵌套结构和我们的假设不一致。
            # 把 PyAppify 真实返回的前 2 条 sample 出来给用户看，方便排查（不要静默兜底）。
            import json as _dj
            sample = _dj.dumps(notes_list[:2], ensure_ascii=False, indent=1)[:1200]
            self.changelog_text.setPlainText(
                "⚠ 原启动器返回了版本列表但未能解析 update_note。\n"
                "调试信息（PyAppify 真实返回的前 2 条原始结构），"
                "请把这段截图给开发者：\n\n" + sample
            )
            return

        # 兜底：版本列表未就绪或网络不通时，回退到 app.json 缓存的 update_note
        self._show_cached_note()

    # ===== 动作：启动（直接跑游戏助手本体，这是启动器的本职） =====
    def launch_app(self):
        app = self.app
        # lite 模式：没有 working/pythonw，直接启动 exe 本体
        if app.get("lite") or app.get("generic"):
            exe = app.get("exe", "") or ""
            if not exe or not os.path.isfile(exe):
                QMessageBox.critical(
                    self.window(), "启动失败",
                    f"找不到程序：\n{exe or '（未配置 exe 路径）'}",
                )
                return
            ok = run_exe(self.window(), exe, cwd=os.path.dirname(exe) or None,
                         need_admin=False, show_errors=True)
            if ok:
                self.status_label.setText("已发起启动（等待窗口出现）")
                QTimer.singleShot(5000, lambda: self.status_label.setText(""))
            return

        main_script = (self.profile or {}).get("main_script", "main.py")
        admin = bool((self.profile or {}).get("admin", False))
        main_path = os.path.join(app["working"], main_script)
        pythonw = app["pythonw"]

        if not os.path.isfile(main_path):
            QMessageBox.critical(
                self.window(), "启动失败",
                f"找不到助手主程序：\n{main_path}\n\n请重新打开原版启动器修复安装（聚合启动器仅负责启动）。",
            )
            return
        if not os.path.isfile(pythonw):
            QMessageBox.critical(
                self.window(), "启动失败",
                f"找不到 Python：\n{pythonw}\n\n请重新打开原版启动器修复安装（聚合启动器仅负责启动）。",
            )
            return

        # CWD=working：保证相对 import 与日志落点正确
        ok = run_exe(
            self.window(), pythonw,
            args=[main_path], cwd=app["working"],
            need_admin=admin, show_errors=True,
        )
        if ok:
            self.status_label.setText("已发起启动（等待窗口出现）")
            # 5 秒后清空，避免与徽章长期 1:1 复读"运行中"造成信息冗余
            QTimer.singleShot(5000, lambda: self.status_label.setText(""))

    # ===== 动作：安装（从 GitHub Releases 下 win32.zip 就地解压，免管理员、不写注册表） =====
    def _ilog(self, msg):
        """UI 侧安装日志，与 InstallWorker._log 写到同一个 logs/install-<key>.log。"""
        try:
            _d = os.path.join(LAUNCHER_DIR, "logs")
            os.makedirs(_d, exist_ok=True)
            _p = os.path.join(_d, f"install-{self.app.get('key','?')}.log")
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(_p, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [UI] {msg}\n")
        except Exception:
            pass

    def install_app(self):
        if getattr(self, "_installed", False):
            return
        # 防重复触发：已有安装任务在跑则直接返回。
        # 没有这个守卫,连点两次「安装」会启动两个 InstallWorker 并发下同一个文件,
        # 表现就是用户截图里的「重复下载、关不掉」(旧 bug 修了 _probe 之后剩下的)。
        existing = getattr(self, "_install_worker", None)
        if existing is not None and existing.isRunning():
            return
        key = self.app.get("key", "")
        if key not in InstallWorker.REPOS:
            QMessageBox.information(
                self.window(), "安装",
                f"「{self.app.get('display','?')}」暂未配置一键安装（key={key}）。\n"
                "请到 ok-script.com 手动下载，或重新打开原版启动器安装。",
            )
            return
        install_root = self.app.get("install_root", "") or ""
        if not install_root:
            QMessageBox.warning(
                self.window(), "安装",
                "找不到 install_root，请检查 config.json 的 install_root 字段。"
            )
            return
        # install_dir 取「config 里 exe 字段所在目录」= PyAppify install_path
        # （不同游戏深度不同：ok-nte 是 install_root/ok-nte/ok-nte/ 双层，ok-ww/end-field 单层）
        install_dir = os.path.dirname(self.app.get("exe", "") or "") or ""
        if not install_dir:
            QMessageBox.warning(self.window(), "安装",
                f"无法从 config 推导安装目录（exe={self.app.get('exe','')}）。")
            return
        # 读 MirrorChyan CDK 与万载云反代域名，决定下载源提示
        try:
            _cfg = json.load(open(os.path.join(LAUNCHER_DIR, "config.json"), encoding="utf-8"))
            cdk = (_cfg.get("mirrorchyan_cdk", "") or "").strip()
            wz_proxy = (_cfg.get("wanzaiyun_proxy", "") or "").strip()
        except Exception:
            cdk = ""
            wz_proxy = ""
        src_hint = (
            "· 来源：MirrorChyan 国内快源（已配 CDK）> 万载云反代 > cnb/GitHub"
            if cdk
            else "· 来源：万载云反代（免 key 国内直连）> cnb（仅鸣潮）/GitHub 直链"
        )
        src_extra = "" if cdk else "\n  右上「⚙ 设置」可填 MirrorChyan CDK 进一步加速"
        resp = QMessageBox.question(
            self.window(), "一键安装",
            f"将从官方 release 下载并安装「{self.app['display']}」到：\n"
            f"  {install_dir}\n\n"
            f"{src_hint}{src_extra}\n"
            "· 优先下载完整安装包（解压即可直开本体，跳过 PyAppify host 小窗）\n"
            "· 若官方仅提供 host 包，则解压后需再点一次「启动 host 初始化」\n\n"
            "确认下载安装？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return

        self._ilog(f"用户确认安装：key={key}, install_dir={install_dir}, cdk={'有' if cdk else '无'}")
        # ===== 进入安装态：禁用所有触发按钮，激活内嵌进度区 =====
        # 同时禁用 install_btn + rescan_btn + 半装卡片的两个按钮,防连点
        for _b_name in ("install_btn", "rescan_btn"):
            _b = getattr(self, _b_name, None)
            if _b is not None:
                _b.setEnabled(False)
        # 半装状态下还有 full_btn/host_btn（局部变量），重建时已变引用,这里不强求
        self.install_progress.setValue(0)
        self.install_progress.setVisible(True)
        self.install_status.setText(f"正在准备「{self.app['display']}」一键安装…")
        self.install_status.setVisible(True)
        self.install_cancel_btn.setVisible(True)

        self._install_worker = InstallWorker(key, install_root, install_dir, cdk=cdk, proxy=wz_proxy, app=self.app, parent=self)
        self._ilog("InstallWorker 已创建并即将 start()")

        def _on_progress(pct, text):
            if pct >= 0:
                self.install_progress.setValue(pct)
            if text:
                self.install_status.setText(text)
            QApplication.processEvents()

        def _on_done(install_dir_done, tag):
            self.install_progress.setValue(100)
            self.install_status.setText(f"解压完成：{tag or ''}")
            QApplication.processEvents()
            self._hide_install_progress_ui()
            # 判断是整包直装还是 host 引导包：working/main.py 是否存在
            app_json_dir = os.path.dirname(self.app.get("app_json", "") or "")
            working_main = os.path.join(app_json_dir, "working", "main.py") if app_json_dir else ""
            if os.path.isfile(working_main):
                QMessageBox.information(
                    self.window(), "安装完成",
                    f"「{self.app['display']}」完整版已装好：\n{install_dir_done}\n\n"
                    "✅ 完整运行环境已就位。直接点卡片上的「▶ 启动应用」\n"
                    "即可打开助手主窗口（已跳过 PyAppify host 小窗）。",
                )
            else:
                QMessageBox.information(
                    self.window(), "解压完成",
                    f"「{self.app['display']}」host 引导包已解压：\n{install_dir_done}\n\n"
                    "这是 PyAppify host 引导包，完整运行时（Python venv、working/、cache）\n"
                    "需要 host 第一次启动时自动拉取（约几百 MB，按网络耗时数分钟）。\n\n"
                    "请点卡片上的「▶ 启动 host 初始化」按钮，让它跑一次自动下完所有组件。\n"
                    "初始化完成后点「🔄 刷新」即可识别为已安装。",
                )
            self._install_worker = None
            self._ilog(f"安装成功：{install_dir_done}, tag={tag}")
            self.rebuild_body()

        def _on_failed(msg):
            self._hide_install_progress_ui()
            self._install_worker = None
            self._ilog(f"安装失败：{msg}")
            # 按当前状态给提示：首次装 vs 已装兜底 区别开，不再说"都还没装怎么点原版"
            already = (getattr(self, "install_btn", None) and self.install_btn.text() != "安装") or getattr(self, "_host_ready", False)
            extra = (
                "可重新打开原版启动器完成更新（聚合启动器仅负责启动 / 整包安装）。"
                if already
                else "请检查网络后重试，或到 ok-script.com 手动下载安装包。"
            )
            QMessageBox.critical(
                self.window(), "安装失败",
                f"下载/解压失败：\n\n{msg}\n\n{extra}",
            )
            self.rebuild_body()

        self._install_worker.progress.connect(_on_progress)
        self._install_worker.done.connect(_on_done)
        self._install_worker.failed.connect(_on_failed)
        self._install_worker.start()

    def _on_install_cancel_clicked(self):
        """取消按钮被点：通知 worker 停、清 worker 引用、隐藏进度 UI。
        关键修复：旧版 _on_cancel 没把 self._install_worker = None,导致下次
        点 install_btn 时守卫看到旧 worker 还活着就 return,用户感觉按钮坏了。
        同时增加 wait(800) 强等线程退出,守卫不会被"isRunning()==True 但马上要退"的状态骗到。
        """
        # 两条下载路线用了两个不同的引用名：ok-script 的老 InstallWorker 存在
        # _install_worker，新加的 zip/官方安装包 worker 存在 _installer_worker。
        # 只认一个的话，新路线点取消会**毫无反应**（按钮在，但没人接）。
        w = getattr(self, "_install_worker", None) or \
            getattr(self, "_installer_worker", None) or \
            getattr(self, "_gen_update_worker", None)
        if w is None:
            self._hide_install_progress_ui()
            return
        try:
            w.cancel()
        except Exception:
            pass
        try:
            # 等 worker 在 cancel 标志传到下载循环后自然退出(最多 800ms),
            # 不强 terminate,避免半截 zip 文件句柄泄漏
            if w.isRunning():
                w.wait(800)
        except Exception:
            pass
        try:
            w.progress.disconnect()
            w.done.disconnect()
            w.failed.disconnect()
        except Exception:
            pass
        self._install_worker = None
        self._installer_worker = None
        self._gen_update_worker = None
        self._hide_install_progress_ui()
        self.rebuild_body()

    def _hide_install_progress_ui(self):
        """隐藏安装进度三件套 + 恢复原按钮可用态（无论 done/failed/cancel 都走它）。"""
        try:
            self._lite_stop_spin()
        except Exception:
            pass
        try:
            self.install_progress.setVisible(False)
            self.install_progress.setValue(0)
            self.install_status.setVisible(False)
            self.install_status.setText("")
            self.install_cancel_btn.setVisible(False)
            self.install_pause_btn.setVisible(False)
            self.install_pause_btn.setText("⏸ 暂停")
        except Exception:
            pass
        for _b_name in ("install_btn", "rescan_btn"):
            _b = getattr(self, _b_name, None)
            if _b is not None:
                _b.setEnabled(True)

    def _show_install_progress_ui(self, text=""):
        """显示安装进度四件套：进度条 / 状态 / 暂停 / 取消。

        新加的 zip 与官方安装包两条下载路线都走这个，跟 ok-script 那条共用同一套控件，
        免得各写一套、状态不一致。
        """
        try:
            self.install_progress.setVisible(True)
            self.install_progress.setValue(0)
            self.install_status.setVisible(True)
            self.install_status.setText(text or "准备中…")
            self.install_pause_btn.setVisible(True)
            self.install_pause_btn.setText("⏸ 暂停")
            self.install_cancel_btn.setVisible(True)
        except Exception:
            pass

    def _on_install_pause_clicked(self):
        """暂停 / 继续切换。只有支持暂停的 worker 才响应。"""
        w = getattr(self, "_installer_worker", None)
        if w is None or not hasattr(w, "pause"):
            return
        try:
            if getattr(w, "_paused", False):
                w.resume()
                self.install_pause_btn.setText("⏸ 暂停")
            else:
                w.pause()
                self.install_pause_btn.setText("▶ 继续")
        except Exception:
            pass

    def _on_installer_percent(self, pct):
        if hasattr(self, "install_progress"):
            try:
                if pct is None or pct < 0:
                    self.install_progress.setRange(0, 0)   # 未知总长 → 转圈
                else:
                    self.install_progress.setRange(0, 100)
                    self.install_progress.setValue(max(0, min(100, int(pct))))
            except Exception:
                pass

    # ===== 动作：打开原版管理窗口（唯一会改配置的入口，由原启动器自己处理） =====
    def open_manager(self):
        # 优先用实际找到的 host exe（host 名可能跟 config 不一致，如 ok-end-field 解出来叫 ok-ef.exe）
        target = getattr(self, "_host_actual", "") or self.app.get("exe", "")
        run_exe(self.window(), target, [], need_admin=True)

    # ===== 动作：窗口内更新（下载到本启动器目录，真实进度；应用交回原启动器） =====
    def open_update_dialog(self):
        # 先刷新按钮状态，确保 _current_target 是最新的
        self.refresh_update_button()
        avail = self.data.get("available_versions", []) or []
        all_versions = getattr(self, "_all_versions", None) or avail
        versions = self._ensure_current_in_versions(
            all_versions if all_versions else avail
        )
        cur = _normalize_tag(self.data.get("current_version", ""))

        if not versions:
            QMessageBox.information(
                self.window(), "更新",
                f"「{self.app['display']}」暂无可用版本信息，请稍后再试。"
            )
            return

        # 用户在主窗口下拉里选中的版本
        selected_raw = None
        if hasattr(self, "ver_combo") and hasattr(self, "_version_map"):
            selected_raw = self._version_map.get(self.ver_combo.currentText())

        # preselected 优先级：按钮的目标 > 用户下拉选中 > 当前
        # 这样下拉在 current 时点击按钮，对话框也会打开到 latest_newer（而非 current）
        preselected = (
            getattr(self, "_current_target", None)
            or selected_raw
            or cur
            or None
        )

        git_url = (self.profile or {}).get("git_url", "")
        dlg = UpdateDialog(
            self, self.app, cur, versions, git_url, preselected=preselected
        )
        dlg.exec()

    # ===== 动作：卸载（移入回收站，可撤销；不动其他 app 目录） =====
    def uninstall_app(self):
        app_dir = os.path.dirname(self.app["exe"])
        if not os.path.isdir(app_dir):
            QMessageBox.information(
                self.window(), "卸载",
                f"未找到「{self.app['display']}」安装目录：\n{app_dir}"
            )
            return

        # 本启动器如果位于该 app 目录内，无法卸载自身
        launcher_dir = os.path.normcase(os.path.abspath(os.path.dirname(__file__)))
        app_dir_norm = os.path.normcase(os.path.abspath(app_dir))
        if launcher_dir == app_dir_norm or launcher_dir.startswith(app_dir_norm + os.sep):
            QMessageBox.warning(
                self.window(), "无法卸载",
                f"本启动器位于「{self.app['display']}」的安装目录内，无法在此窗口内卸载自身。\n\n"
                f"如需卸载，请关闭本启动器后手动删除目录：\n{app_dir}"
            )
            return

        # 正在运行则先让用户关闭。
        # **必须用实时进程检测 (_is_process_running)，不能信 self.data["running"]**：
        # app.json.running 是原启动器启动时写、关闭时没清的陈旧字段（注释见
        # _is_process_running），进程死透后还常驻 true，会让卸载按钮永远点不动。
        # refresh_badge 已接实时检测兜底，uninstall_app 当时漏接了。
        if self._is_process_running():
            QMessageBox.warning(
                self.window(), "无法卸载",
                f"「{self.app['display']}」正在运行，请先关闭后再卸载。"
            )
            return

        # === 收集所有与本游戏相关的"该清"和"该留"路径（带体积）===
        # 之前只把 app_dir 扔回收站，repos/<key>/ 镜像 (~60MB)、install 日志、
        # versions 缓存全留在 D:\OKApps\launcher\ 下，充其量算"半卸载"。
        key = self.app.get("key", "") or ""
        install_root = self.app.get("install_root", "") or ""

        # 必清（不管选哪档都会移入回收站）
        recycle_items = []    # [(path, label, size_bytes)]
        # 可选清：下载缓存，默认保留（重装时自动复用省流量），
        # 选「彻底清除（含下载缓存）」时才并入 recycle_items 一起带走。
        optional_items = []

        # 1) 安装目录（必清）
        recycle_items.append((app_dir, "安装目录", _sum_size(app_dir)))

        # 2) 启动器侧 git 镜像 repos/<key>/
        if key:
            repos_dir = os.path.join(LAUNCHER_DIR, "repos", key)
            if os.path.isdir(repos_dir):
                recycle_items.append((repos_dir, "启动器版本镜像 (git)", _sum_size(repos_dir)))

        # 3) 启动器侧日志 / 版本缓存（小文件，单独列出来用户更清楚）
        if key:
            logs_dir = os.path.join(LAUNCHER_DIR, "logs")
            for fn in (f"install-{key}.log", f"versions-{key}.json",
                       f"versions-{key}.json.bak"):
                fp = os.path.join(logs_dir, fn)
                if os.path.isfile(fp):
                    recycle_items.append((fp, "启动器日志/缓存", os.path.getsize(fp)))

        # 4) 下载缓存 _dl_<key>/ —— 可选清除
        if key and install_root:
            dl_dir = os.path.join(install_root, f"_dl_{key}")
            if os.path.isdir(dl_dir):
                optional_items.append((dl_dir, "下载缓存（已下好的安装包）", _sum_size(dl_dir)))

        # 5) 桌面/开始菜单里指向本安装目录的快捷方式 —— 卸载后全是死链，一并清
        # （一条龙这类自己会建桌面快捷方式的程序，不扫的话卸完留一堆打不开的图标）
        related_lnk = _scan_related_shortcuts(app_dir)
        for p in related_lnk:
            try:
                sz = os.path.getsize(p)
            except OSError:
                sz = 0
            recycle_items.append((p, "相关快捷方式（桌面/开始菜单）", sz))

        total_size = sum(sz for _p, _l, sz in recycle_items)

        # === 构造确认对话框：体积透明 + 两档清理方式 ===
        # 之前所有档位都走回收站，对 GB 级卸载是伪需求：东西只是挪进
        # $RECYCLE.BIN，D 盘一点空间没回来。现在给「直接删除」真释放空间；
        # 默认按钮仍是取消，回收站档保留作为后悔药。
        lines = [f"将清理「{self.app['display']}」以下内容（共 {_human_size(total_size)}）：", ""]
        for p, label, sz in recycle_items:
            lines.append(f"  · {label}（{_human_size(sz)}）")
            lines.append(f"      {p}")
        if optional_items:
            lines.append("")
            lines.append("以下是下载缓存：移入回收站档会保留（重装时自动复用）；")
            lines.append("直接删除档会连它一起带走。")
            for p, label, sz in optional_items:
                lines.append(f"  · {label}（{_human_size(sz)}）")
                lines.append(f"      {p}")

        box = QMessageBox(self.window())
        box.setWindowTitle("确认卸载")
        box.setText("\n".join(lines))
        box.setIcon(QMessageBox.Warning)
        btn_soft = box.addButton("移入回收站（可还原）", QMessageBox.AcceptRole)
        btn_hard = box.addButton("直接删除（立即释放空间，不可恢复）",
                                 QMessageBox.DestructiveRole)
        btn_cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(btn_cancel)
        box.exec()

        clicked = box.clickedButton()
        if clicked is None or clicked is btn_cancel:
            return
        hard = (clicked is btn_hard)

        # 直接删除档：连下载缓存一起带走（都要真释放空间了，留缓存没意义）
        if hard:
            recycle_items = recycle_items + optional_items
            optional_items = []   # 已清掉，汇总里不再显示"保留"

        # === 执行清理（逐项独立判断，失败的列出来让用户处理）===
        ok_list = []   # [(path, label)]
        fail_list = [] # 失败的 [(path, label, msg)]
        for p, label, _sz in recycle_items:
            if hard:
                ok, msg = _hard_delete(p)
            else:
                ok, msg = send_to_trash(p)
            if ok:
                ok_list.append((p, label))
            else:
                fail_list.append((p, label, msg))

        if not fail_list:
            if hard:
                summary = (f"已直接删除「{self.app['display']}」以下内容"
                           f"（共 {_human_size(total_size)}，空间已释放，未进回收站）：\n\n")
            else:
                summary = f"已把「{self.app['display']}」以下内容移入回收站：\n\n"
            for p, label in ok_list:
                summary += f"  · {label}\n        {p}\n"
            if optional_items:
                summary += "\n保留（未清除，重装时自动复用）：\n"
                for p, label, _sz in optional_items:
                    summary += f"  · {label}\n        {p}\n"
            summary += ("\n如需找回，可还原（回收站）。"
                        if not hard else "\n此操作不可恢复。")
            QMessageBox.information(self.window(),
                                    "卸载完成", summary)
        else:
            summary = (f"部分完成：{len(ok_list)}/{len(recycle_items)} 项已清理，"
                       f"{len(fail_list)} 项失败。\n\n")
            if ok_list:
                summary += "已清理：\n"
                for p, label in ok_list:
                    summary += f"  · {label}\n        {p}\n"
            summary += "\n失败（文件可能被占用）：\n"
            for p, label, msg in fail_list:
                summary += f"  · {label}: {msg}\n        {p}\n"
            summary += "\n请关闭相关程序后，对失败项可再点右上角 ⚙ 菜单里的「卸载」重试。"
            QMessageBox.warning(self.window(), "部分完成", summary)

        self.rebuild_body()


class UpdateDialog(QDialog):
    """窗口内「更新到所选版本」对话框：点开始后自动下载并应用到原启动器 working/。

    流程：点「开始更新」→ 一次确认 → 后台下载镜像到 launcher/repos/<key>（作缓存，
    加速下次增量 fetch）→ 自动终止运行进程 → 同步代码到 app['working']（覆盖代码、
    保留缓存/日志/配置/数据库等运行数据，不备份、不占额外空间）→ 写回 app.json 当前版本。
    失败时可点「打开原版管理窗口」交回原启动器处理。
    写的是官方 app 的本地安装目录，属于官方仓库范畴，可写（用户已授权）。
    """

    def __init__(self, parent, app, current, versions, git_url, preselected=None):
        super().__init__(parent)
        self.app = app
        self.git_url = git_url
        self.versions = versions  # 从新到旧
        self.current = current
        self._worker = None

        self.setWindowTitle(f"更新 {app['display']}")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        # 目标版本选择（与主卡片 ComboBox 用同样的格式化：v3.5.28 正式版（当前））
        row = QHBoxLayout()
        row.addWidget(CaptionLabel("目标版本"))
        self.combo = ComboBox()
        self.combo.setMinimumWidth(240)
        cur_n = _normalize_tag(self.current)
        for i, ver in enumerate(versions):
            label = format_version_display(ver, self.current)
            if i == 0:
                # 最新项：把"（升级）"换成"（最新）"；若它就是当前则合写"（当前·最新）"
                if "（当前）" in label:
                    label = label.replace("（当前）", "（当前·最新）")
                else:
                    label = label.replace("（升级）", "（最新）")
            self.combo.addItem(label)
        # 预选用户在主窗口下拉里选的版本（若有）；否则默认最新
        sel_idx = 0
        if preselected:
            target_n = _normalize_tag(preselected)
            for i, ver in enumerate(versions):
                if _normalize_tag(ver) == target_n:
                    sel_idx = i
                    break
        self.combo.setCurrentIndex(sel_idx)
        row.addWidget(self.combo, stretch=1)
        v.addLayout(row)

        # 真实进度条
        self.bar = QProgressBar()
        self.bar.setFixedHeight(16)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        v.addWidget(self.bar)

        self.status = CaptionLabel(
            "点击「开始更新」直接下载并更新到原启动器源程序目录 working/：\n"
            "覆盖代码文件，保留缓存 / 日志 / 配置 / 数据库等运行数据；不备份、不占额外空间。"
        )
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        # 按钮行：第一行 = 下载/关闭；第二行 = 下载完成后的两种应用方式
        btn_row1 = QHBoxLayout()
        self.start_btn = PushButton("开始更新")
        self.start_btn.setFixedHeight(38)
        self.start_btn.clicked.connect(self.start_update)
        btn_row1.addWidget(self.start_btn)

        self.close_btn = PushButton("关闭")
        self.close_btn.setFixedHeight(38)
        self.close_btn.clicked.connect(self.reject)
        btn_row1.addWidget(self.close_btn)
        v.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.apply_btn = PushButton("打开原版管理窗口")
        self.apply_btn.setFixedHeight(38)
        self.apply_btn.setEnabled(False)
        self.apply_btn.setToolTip(
            "交回原启动器（仅在下载/应用失败时使用，正常情况下已自动更新到 working/）。"
        )
        self.apply_btn.clicked.connect(self.open_manager)
        btn_row2.addWidget(self.apply_btn)
        v.addLayout(btn_row2)

    def start_update(self):
        target = _normalize_tag(self.versions[self.combo.currentIndex()])
        working = self.app.get("working", "")
        # 单次确认（防误点；点开始即自动下载 + 终止进程 + 覆盖 working/ 代码 + 保留运行数据）
        resp = QMessageBox.question(
            self,
            "确认更新到原启动器",
            f"将下载 {target} 并直接更新到原启动器源程序目录：\n{working}\n\n"
            "· 覆盖代码文件，保留缓存 / 日志 / 配置 / 数据库等运行数据\n"
            "· 应用若正在运行会先被终止\n"
            "· 直接覆盖、不产生备份（不占额外空间）\n\n"
            "确认继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        self.start_btn.setEnabled(False)
        self.combo.setEnabled(False)
        self.status.setText(f"正在下载 {target}…")
        self.bar.setValue(0)
        self._worker = MirrorUpdater(self.app["key"], self.git_url, target, parent=self)
        self._worker.progress.connect(self.on_progress)
        self._worker.done.connect(self.on_done)
        self._worker.failed.connect(self.on_failed)
        self._worker.start()

    def on_progress(self, pct, text):
        if pct >= 0:
            self.bar.setValue(pct)
            self.status.setText(
                (text[:80] if text else "") or f"下载中… {pct}%"
            )
        else:
            self.status.setText(text or "下载中…")

    def on_done(self, local_dir):
        target = _normalize_tag(self.versions[self.combo.currentIndex()])
        self.bar.setValue(100)
        self.status.setText(
            f"下载完成，正在更新到原启动器 working/（{target}）…"
        )
        # 下载完成自动应用：杀进程 → 同步代码 → 写 app.json（用户无需再点按钮）
        self._apply_worker = ApplyWorker(self.app, target, local_dir, parent=self)
        self._apply_worker.progress.connect(self.status.setText)
        self._apply_worker.done.connect(self.on_apply_done)
        self._apply_worker.start()

    def on_failed(self, msg):
        self.bar.setValue(0)
        self.status.setText(
            f"下载失败：{msg}\n\n可改点「打开原版管理窗口」由原启动器直接更新。"
        )
        self.start_btn.setEnabled(True)
        self.combo.setEnabled(True)

    # 注：原「应用到 working 目录」按钮 + apply_direct 方法已删除，
    # 下载完成后由 on_done 自动调用 ApplyWorker 完成 kill + 同步 + 写 current_version。

    def on_apply_done(self, ok, msg):
        if ok:
            self.bar.setValue(100)
            self.status.setText(
                f"{msg}\n\n运行数据已保留。可关闭本窗口，"
                "再从主窗口点「启动应用」运行新版本。"
            )
            self.apply_btn.setEnabled(True)  # 已自动应用，可选去原版窗口看一眼
        else:
            self.status.setText(
                f"应用失败：{msg}\n\n可改点「打开原版管理窗口」由原启动器处理。"
            )
            self.apply_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.combo.setEnabled(True)

    def open_manager(self):
        run_exe(self, self.app["exe"], [], need_admin=True)
        self.accept()


# ===== 左侧边栏导航（自绘深色，不跟随主题） =====
# 主窗口原本是「手写 56px 深灰顶栏 + 单列竖排卡片」，没有任何导航机制。现改成
# 「左侧固定侧栏 + 右侧堆叠内容区」。侧栏刻意用自己的深色样式，而不用 FluentWindow
# 自带导航栏——后者跟随系统主题色，与本项目深色调冲突。
#
# ⚠️ 线程安全铁律：QStackedWidget 切页只是隐藏/显示，不会销毁 widget，所以正在跑的
# InstallWorker / GitVersionFetcher 不会被误杀。因此**所有页面必须在 Launcher.__init__
# 里一次性预创建并常驻**，绝不能做成「切到时才创建、切走就销毁」。


class NavButton(QWidget):
    """侧栏里的一行导航项：3px 选中指示条 + 20px 图标 + 文字。"""

    clicked = Signal(str)

    def __init__(self, key, text, icon=None, icon_path=None):
        super().__init__()
        self.key = key
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 12, 0)
        lay.setSpacing(10)

        self._bar = QWidget()
        self._bar.setFixedWidth(3)
        lay.addWidget(self._bar)

        if icon_path and os.path.exists(icon_path):
            ic = QLabel()
            ic.setPixmap(QPixmap(icon_path).scaled(
                20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            ic.setFixedSize(20, 20)
            ic.setStyleSheet("background:transparent;")
            lay.addWidget(ic)
        else:
            iw = IconWidget(icon or FluentIcon.HOME)
            iw.setFixedSize(20, 20)
            lay.addWidget(iw)

        self._label = QLabel(text)
        lay.addWidget(self._label)
        lay.addStretch(1)
        self.set_selected(False)

    def mouseReleaseEvent(self, e):
        self.clicked.emit(self.key)
        super().mouseReleaseEvent(e)

    def set_selected(self, on):
        if on:
            self.setStyleSheet(
                "NavButton { background-color:rgba(255,255,255,0.09); border-radius:6px; }")
            self._bar.setStyleSheet("background:#4a9eff; border-radius:1px;")
            self._label.setStyleSheet(
                "color:#ffffff; font-size:14px; font-weight:600; background:transparent;")
        else:
            self.setStyleSheet(
                "NavButton { background:transparent; border-radius:6px; }"
                "NavButton:hover { background-color:rgba(255,255,255,0.05); }")
            self._bar.setStyleSheet("background:transparent; border-radius:1px;")
            self._label.setStyleSheet(
                "color:#c9ccd4; font-size:14px; background:transparent;")


class SideBar(QWidget):
    """固定 220px 宽的深色侧栏：顶部品牌区 + 中部导航 + 底部设置。"""

    sig_changed = Signal(str)

    def __init__(self, apps):
        super().__init__()
        self.setFixedWidth(220)
        self.setStyleSheet("background-color:#232329;")
        self._buttons = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 0, 8, 12)
        root.setSpacing(4)

        # 顶部品牌区（原 56px 手写顶栏的替代品）
        brand = QWidget()
        brand.setFixedHeight(64)
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(12, 0, 8, 0)
        bl.setSpacing(10)
        logo = QLabel()
        logo_path = os.path.join(ASSETS_DIR, "launcher-icon.png")
        if os.path.exists(logo_path):
            logo.setPixmap(QPixmap(logo_path).scaled(
                28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setFixedSize(28, 28)
        logo.setStyleSheet("background:transparent;")
        bl.addWidget(logo)
        name = QLabel("游戏助手启动器")
        name.setStyleSheet(
            "color:#ffffff; font-size:15px; font-weight:700; background:transparent;")
        bl.addWidget(name)
        bl.addStretch(1)
        root.addWidget(brand)

        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color:rgba(255,255,255,0.07);")
        root.addWidget(line)
        root.addSpacing(8)

        self._add(root, "overview", "总览", FluentIcon.HOME, None)
        for app in apps:
            self._add(root, app.get("key", ""), app.get("display", ""),
                      None, app.get("icon", ""))
        root.addStretch(1)
        self._add(root, "settings", "设置", FluentIcon.SETTING, None)

    def _add(self, layout, key, text, icon, icon_rel):
        path = ""
        if icon_rel:
            path = (icon_rel if os.path.isabs(icon_rel)
                    else os.path.join(LAUNCHER_DIR, icon_rel))
        btn = NavButton(key, text, icon, path)
        btn.clicked.connect(self._on_click)
        self._buttons[key] = btn
        layout.addWidget(btn)

    def _on_click(self, key):
        self.select(key)

    def select(self, key):
        if key not in self._buttons:
            return
        # 幂等守卫：switch_to() 会回调 select() 同步高亮，若不拦住就会形成
        # 「select → emit sig_changed → switch_to → select → …」的无限递归。
        if getattr(self, "_current", None) == key:
            return
        self._current = key
        for k, b in self._buttons.items():
            b.set_selected(k == key)
        self.sig_changed.emit(key)


class OverviewCard(CardWidget):
    """总览页的轻量状态卡：只读展示 + 一个快捷按钮。

    不自己起线程拉版本、也不重复扫进程——一律从对应 AppCard.snapshot() 读，
    保证总览页和详情页状态永远一致且不增加额外开销。按钮直接调 AppCard 的方法，
    业务逻辑保持单份，不会出现两套实现打架。
    """

    sig_open_detail = Signal(str)

    def __init__(self, app, card):
        super().__init__()
        self.app = app
        self.card = card
        self.key = app.get("key", "")
        self.setMinimumWidth(240)
        self.setCursor(Qt.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        ic = QLabel()
        p = self._icon_path()
        if p and os.path.exists(p):
            ic.setPixmap(QPixmap(p).scaled(
                40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        ic.setFixedSize(40, 40)
        ic.setStyleSheet("background:transparent;")
        head.addWidget(ic)

        box = QVBoxLayout()
        box.setSpacing(2)
        nm = StrongBodyLabel(app.get("display", self.key))
        nm.setStyleSheet("font-size:15px; font-weight:700;")
        box.addWidget(nm)
        self.state_label = CaptionLabel("")
        box.addWidget(self.state_label)
        head.addLayout(box)
        head.addStretch(1)
        root.addLayout(head)

        self.ver_label = CaptionLabel("版本 未知")
        root.addWidget(self.ver_label)

        self.action_btn = PushButton("启动")
        self.action_btn.setFixedHeight(30)
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.clicked.connect(self._on_action)
        root.addWidget(self.action_btn)

        self.refresh()

    def _icon_path(self):
        rel = self.app.get("icon", "")
        if not rel:
            return ""
        return rel if os.path.isabs(rel) else os.path.join(LAUNCHER_DIR, rel)

    def mouseReleaseEvent(self, e):
        self.sig_open_detail.emit(self.key)
        super().mouseReleaseEvent(e)

    def refresh(self):
        s = self.card.snapshot()
        self.ver_label.setText("版本 %s" % s["version"])
        if s["running"]:
            state, color = "● 运行中", "#8dffb0"
        elif s["installed"]:
            if s["has_update"]:
                state, color = "有新版本可用", "#ffb74d"
            else:
                state, color = "已安装", "#8dffb0"
        elif s["game_found"]:
            state, color = "检测到游戏，未装助手", "#9ec5ff"
        else:
            state, color = "未安装", "#9aa0a6"
        self.state_label.setText(state)
        self.state_label.setStyleSheet("color:%s; font-size:12px;" % color)

        if s["running"]:
            self.action_btn.setText("强制关闭")
        elif not s["installed"]:
            self.action_btn.setText("安装")
        elif s["has_update"]:
            self.action_btn.setText("更新")
        else:
            self.action_btn.setText("启动")

    def _on_action(self):
        s = self.card.snapshot()
        try:
            if s["running"]:
                self.card._on_force_stop()
            elif not s["installed"]:
                self.card.install_app()
            elif s["has_update"]:
                if getattr(self.card, "_lite", False):
                    self.card._on_lite_update()
                else:
                    self.card.open_update_dialog()
            else:
                self.card.launch_app()
        except Exception as e:
            QMessageBox.warning(self, "操作失败", str(e))
        QTimer.singleShot(800, self.refresh)


class OverviewPage(QWidget):
    """总览页：三张轻量状态卡的网格 + 顶部扫描按钮。"""

    sig_open_detail = Signal(str)

    def __init__(self, apps, cards, on_scan=None):
        super().__init__()
        self.overview_cards = []

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)

        top = QHBoxLayout()
        hint = CaptionLabel(
            "总览：点卡片进入详情页，或直接点卡内按钮快速操作。状态每 5 秒自动刷新。")
        hint.setWordWrap(True)
        top.addWidget(hint, stretch=1)
        self.scan_btn = PushButton("🔍 扫描游戏")
        self.scan_btn.setFixedHeight(32)
        self.scan_btn.setCursor(Qt.PointingHandCursor)
        if on_scan is not None:
            self.scan_btn.clicked.connect(on_scan)
        else:
            self.scan_btn.setEnabled(False)
        top.addWidget(self.scan_btn)
        root.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(16)
        for i, app in enumerate(apps):
            card = cards.get(app.get("key", ""))
            if card is None:
                continue
            oc = OverviewCard(app, card)
            oc.sig_open_detail.connect(self.sig_open_detail)
            self.overview_cards.append(oc)
            grid.addWidget(oc, i // 3, i % 3)
        root.addLayout(grid)
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)

    def refresh(self):
        for oc in self.overview_cards:
            oc.refresh()


class SettingsPage(QWidget):
    """设置页：MirrorChyan CDK + 万载云反代域名的常驻表单。

    取代原来「连弹两个 QInputDialog」的 open_settings，读写的是同一个 config.json。
    """

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(12)
        root.setAlignment(Qt.AlignTop)

        title = StrongBodyLabel("设置")
        title.setStyleSheet("font-size:20px; font-weight:700;")
        root.addWidget(title)

        cfg = self._read_cfg()

        root.addSpacing(4)
        root.addWidget(StrongBodyLabel("MirrorChyan CDK"))
        tip1 = CaptionLabel(
            "填写后，一键安装/更新会优先走国内加速源。到 mirrorchyan.com 登录，"
            "在「我的 CDK」处获取。留空 = 不启用，走 cnb.cool / GitHub 回退。")
        tip1.setWordWrap(True)
        root.addWidget(tip1)
        self.cdk_edit = LineEdit()
        self.cdk_edit.setPlaceholderText("留空表示不启用 MirrorChyan")
        self.cdk_edit.setText((cfg.get("mirrorchyan_cdk") or "").strip())
        self.cdk_edit.setFixedHeight(34)
        root.addWidget(self.cdk_edit)

        root.addSpacing(10)
        root.addWidget(StrongBodyLabel("万载云反代域名"))
        tip2 = CaptionLabel(
            "免登录免 key 的 GitHub 反代，覆盖全部游戏。主域名失效时可改成其它可用节点，"
            "留空 = 用内置默认域名（https://github.top-host.top/）。")
        tip2.setWordWrap(True)
        root.addWidget(tip2)
        self.wz_edit = LineEdit()
        self.wz_edit.setPlaceholderText("默认 https://github.top-host.top/")
        self.wz_edit.setText((cfg.get("wanzaiyun_proxy") or "").strip())
        self.wz_edit.setFixedHeight(34)
        root.addWidget(self.wz_edit)

        root.addSpacing(8)
        self.save_btn = PushButton("保存")
        self.save_btn.setFixedSize(120, 34)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save)
        root.addWidget(self.save_btn)
        root.addStretch(1)

        # ===== 启动器自身更新 =====
        root.addSpacing(10)
        root.addWidget(StrongBodyLabel("检查更新"))
        self.self_ver_label = CaptionLabel("当前版本 v%s" % APP_VERSION)
        self.self_ver_label.setWordWrap(True)
        root.addWidget(self.self_ver_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.self_check_btn = PushButton("检查更新")
        self.self_check_btn.setFixedSize(110, 34)
        self.self_check_btn.setCursor(Qt.PointingHandCursor)
        self.self_check_btn.clicked.connect(self._on_self_check)
        btn_row.addWidget(self.self_check_btn)
        # 预发布（测试版）默认不提示，勾上才把 beta/预发布算进来
        self.self_pre_chk = QCheckBox("包含测试版")
        self.self_pre_chk.setCursor(Qt.PointingHandCursor)
        self.self_pre_chk.setToolTip(
            "默认只提示正式版。勾上后，预发布（测试版）也会被视为可更新版本。")
        btn_row.addWidget(self.self_pre_chk)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.self_dl_btn = PushButton("下载新版")
        self.self_dl_btn.setFixedSize(110, 34)
        self.self_dl_btn.setCursor(Qt.PointingHandCursor)
        self.self_dl_btn.setEnabled(False)
        self.self_dl_btn.clicked.connect(self._on_self_download)
        root.addWidget(self.self_dl_btn, 0, Qt.AlignLeft)

        self.self_dl_bar = IndeterminateProgressBar()
        self.self_dl_bar.setFixedHeight(4)
        self.self_dl_bar.setVisible(False)
        root.addWidget(self.self_dl_bar)

        # 版本号固定钉在页脚：报 bug 时能说清自己在跑哪个版本（不占标题栏）
        ver = CaptionLabel("版本 v%s" % APP_VERSION)
        ver.setStyleSheet("color:#888780; font-size:11px;")
        ver.setAlignment(Qt.AlignLeft)
        root.addWidget(ver)

        # ===== 匿名错误上报 =====
        root.addSpacing(10)
        root.addWidget(StrongBodyLabel("匿名错误上报"))
        tip_t = CaptionLabel(
            "开启后，程序崩溃时会把「版本号 + 错误类型 + 调用栈」发给作者，用于修 bug。"
            "路径、用户名、CDK、邮箱在发送前一律替换成占位符。默认关闭。")
        tip_t.setWordWrap(True)
        root.addWidget(tip_t)

        tcfg = self._read_cfg().get("telemetry") or {}
        self.tele_chk = QCheckBox("允许匿名上报错误（帮助改进）")
        self.tele_chk.setCursor(Qt.PointingHandCursor)
        self.tele_chk.setChecked(bool(tcfg.get("enabled")))
        self.tele_chk.stateChanged.connect(self._on_tele_toggle)
        root.addWidget(self.tele_chk)

        self.tele_ping_chk = QCheckBox("同时发送启动计数（统计有多少人在用）")
        self.tele_ping_chk.setCursor(Qt.PointingHandCursor)
        self.tele_ping_chk.setChecked(bool(tcfg.get("ping")))
        self.tele_ping_chk.setEnabled(bool(tcfg.get("enabled")))
        self.tele_ping_chk.stateChanged.connect(self._on_tele_toggle)
        root.addWidget(self.tele_ping_chk)

        self.tele_tip = CaptionLabel("")
        self.tele_tip.setWordWrap(True)
        self.tele_tip.setStyleSheet("color:#888780; font-size:11px;")
        root.addWidget(self.tele_tip)
        self._refresh_tele_tip()

        # 线程句柄：页面常驻，worker 必须挂在 self 上防被 GC
        self._self_worker = None
        self._self_dl_worker = None
        self._self_info = None

    def _refresh_tele_tip(self):
        """提示当前是「真的会发」还是「没配端点所以实际不发」，避免误导。"""
        ep = str((self._read_cfg().get("telemetry") or {}).get("endpoint") or "").strip()
        if ep and self.tele_chk.isChecked():
            self.tele_tip.setText("已启用，上报地址：%s" % ep)
        elif self.tele_chk.isChecked():
            self.tele_tip.setText("已勾选，但 config.json 的 telemetry.endpoint 为空，"
                                  "实际不会发送。")
        else:
            self.tele_tip.setText("未启用。出错只会写到本地 logs/error.log，不联网。")

    def _on_tele_toggle(self, *_a):
        """把两个开关写回 config.json（不动其它字段）。"""
        cfg = self._read_cfg()
        t = cfg.get("telemetry")
        if not isinstance(t, dict):
            t = {}
        t["enabled"] = self.tele_chk.isChecked()
        t["ping"] = self.tele_ping_chk.isChecked()
        if "endpoint" not in t:
            t["endpoint"] = ""
        cfg["telemetry"] = t
        try:
            with open(self._cfg_path(), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", "写 config.json 失败：%s" % e)
            return
        self.tele_ping_chk.setEnabled(self.tele_chk.isChecked())
        self._refresh_tele_tip()

    # ---------- 启动器自身更新 ----------

    SELF_REPO = "Gyl1219/game-launcher-hub"

    def _on_self_check(self, force=False):
        """点「检查更新」或启动后自动查一次。worker 已在跑就忽略，防重复点。"""
        if getattr(self, "_self_worker", None) is not None and \
                self._self_worker.isRunning():
            return
        self.self_check_btn.setEnabled(False)
        self.self_check_btn.setText("检查中…")
        self.self_ver_label.setText("正在查询 GitHub Releases…")

        worker = SelfUpdateWorker(self.SELF_REPO,
                                  include_pre=self.self_pre_chk.isChecked(),
                                  parent=self)
        worker.done.connect(self._on_self_check_done)
        worker.failed.connect(self._on_self_check_failed)
        self._self_worker = worker
        worker.start()

    def _on_self_check_done(self, info):
        self._self_worker = None
        self.self_check_btn.setEnabled(True)
        self.self_check_btn.setText("检查更新")
        self._self_info = info

        cur = info.get("current") or APP_VERSION
        latest = info.get("latest") or ""
        if not latest:
            self.self_ver_label.setText("当前版本 v%s（未找到可用 Release）" % cur)
            self.self_dl_btn.setEnabled(False)
            return

        suffix = "（测试版）" if info.get("prerelease") else ""
        if not info.get("has_new"):
            text = "当前版本 v%s 已是最新%s" % (cur, suffix)
            if info.get("from_cache"):
                text += "（30 分钟内缓存结果）"
            self.self_ver_label.setText(text)
            self.self_dl_btn.setEnabled(False)
            return

        # 有新版：把更新说明原文给用户看，别只丢一个版本号
        body = (info.get("body") or "").strip()
        if len(body) > 600:
            body = body[:600] + "\n…（完整说明见 Release 页面）"
        text = ("发现新版本 %s%s（当前 v%s）" % (latest, suffix, cur))
        if info.get("from_cache"):
            text += "（30 分钟内缓存结果）"
        if body:
            text += "\n\n" + body
        self.self_ver_label.setText(text)
        # 没拿到 exe 资产就别给下载按钮（点下去必然失败）
        self.self_dl_btn.setEnabled(bool(info.get("url")))

    def _on_self_check_failed(self, msg):
        self._self_worker = None
        self.self_check_btn.setEnabled(True)
        self.self_check_btn.setText("检查更新")
        self.self_ver_label.setText("检查失败：%s" % msg)
        self.self_dl_btn.setEnabled(False)

    def _on_self_download(self):
        """下载新版 exe 到 .cache/selfupdate/（不自动替换，替换要用户自己决定）。"""
        info = getattr(self, "_self_info", None) or {}
        url = info.get("url") or ""
        tag = (info.get("latest") or "new").lstrip("v")
        if not url:
            return
        if getattr(self, "_self_dl_worker", None) is not None and \
                self._self_dl_worker.isRunning():
            return

        save_dir = os.path.join(LAUNCHER_CACHE_DIR, "selfupdate")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, "game-launcher-hub-v%s-win64.exe" % tag)

        self.self_dl_btn.setEnabled(False)
        self.self_dl_btn.setText("下载中…")
        self.self_dl_bar.setVisible(True)
        self.self_dl_bar.setRange(0, 0)  # 走马灯：LiteDownloadWorker 只给 done/total

        # key 用固定值 "game-launcher-hub"：启动器自己在 Mirror酱 的 rid 由用户配置
        worker = LiteDownloadWorker(url, save_path, parent=self,
                                    key="game-launcher-hub")
        worker.progress.connect(self._on_self_dl_progress)
        worker.finished_ok.connect(lambda p: self._on_self_dl_done(p, tag))
        worker.failed.connect(self._on_self_dl_failed)
        self._self_dl_worker = worker
        worker.start()

    def _on_self_dl_progress(self, done, total):
        if total > 0:
            self.self_dl_bar.setRange(0, 100)
            self.self_dl_bar.setValue(int(done * 100 / total))

    def _on_self_dl_done(self, path, tag):
        self._self_dl_worker = None
        self.self_dl_bar.setVisible(False)
        self.self_dl_btn.setEnabled(True)
        self.self_dl_btn.setText("下载新版")
        mb = 1.0
        try:
            mb = os.path.getsize(path) / (1024 * 1024)
        except Exception:
            pass
        box = QMessageBox(self)
        box.setWindowTitle("下载完成")
        box.setIcon(QMessageBox.Information)
        box.setText("已下载 v%s（%.1f MB）：\n%s" % (tag, mb, path))
        box.setInformativeText(
            "当前启动器仍在运行，替换前请先关闭它。\n"
            "关闭后用上面这个新 exe 覆盖/替换即可完成升级。")
        open_btn = box.addButton("打开所在文件夹", QMessageBox.ActionRole)
        box.addButton("好", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            try:
                os.startfile(os.path.dirname(path))
            except Exception:
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(os.path.dirname(path)))

    def _on_self_dl_failed(self, msg):
        self._self_dl_worker = None
        self.self_dl_bar.setVisible(False)
        self.self_dl_btn.setEnabled(True)
        self.self_dl_btn.setText("下载新版")
        QMessageBox.warning(self, "下载失败", msg)

    def _cfg_path(self):
        return os.path.join(LAUNCHER_DIR, "config.json")

    def _read_cfg(self):
        try:
            with open(self._cfg_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _on_save(self):
        cfg = self._read_cfg()
        cdk = (self.cdk_edit.text() or "").strip()
        wz = (self.wz_edit.text() or "").strip()
        if wz and not wz.endswith("/"):
            wz += "/"
        cfg["mirrorchyan_cdk"] = cdk
        cfg["wanzaiyun_proxy"] = wz
        try:
            with open(self._cfg_path(), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", "写 config.json 失败：%s" % e)
            return
        try:
            InfoBar.success("已保存", "设置已写入 config.json", duration=2500,
                            parent=self, position=InfoBarPosition.TOP_RIGHT)
        except Exception:
            QMessageBox.information(self, "已保存", "设置已写入 config.json")


def _make_scroll_page(child, max_width=900):
    """把内容包成标准的「滚动区 + 水平居中 + 最大宽」页面。

    沿用原来主窗口的布局套路（ScrollArea + 居中 wrapper + 最大宽容器），
    只是把宽度从 760/1040 放宽到 900，利用侧栏布局后更宽的内容区。
    """
    content = QWidget()
    cl = QVBoxLayout(content)
    cl.setContentsMargins(28, 22, 28, 22)
    cl.setSpacing(16)
    cl.addWidget(child)
    cl.addStretch(1)
    content.setMaximumWidth(max_width)

    wrapper = QWidget()
    wl = QHBoxLayout(wrapper)
    wl.setContentsMargins(0, 0, 0, 0)
    wl.addStretch(1)
    wl.addWidget(content, stretch=1)
    wl.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(wrapper)

    page = QWidget()
    pl = QVBoxLayout(page)
    pl.setContentsMargins(0, 0, 0, 0)
    pl.addWidget(scroll)
    return page


class Launcher(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("游戏助手启动器")
        self.setMinimumSize(1080, 680)
        self.resize(1240, 800)
        # 窗口图标用「游戏助手启动器」通用图标，而不是某个具体游戏图标
        self.setWindowIcon(QIcon(os.path.join(ASSETS_DIR, "launcher-icon.png")))

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===== 左侧固定侧栏 =====
        self.sidebar = SideBar(APPS)
        root.addWidget(self.sidebar)

        # ===== 右侧堆叠内容区 =====
        # 所有页面一次性预创建并常驻：QStackedWidget 切页只是隐藏/显示、不销毁 widget，
        # 因此正在跑的安装/更新线程不会被误杀 —— 这是本次改动的线程安全底线。
        self.stack = QStackedWidget()
        self._page_index = {}

        # 1) 先建好三张 AppCard（总览页要引用它们读状态，必须早于总览页创建）
        self.cards = {}  # key -> AppCard（游戏本体扫描结果回调要用）
        game_pages = []
        for app in APPS:
            key = app.get("key", "")
            card = AppCard(app)
            self.cards[key] = card
            game_pages.append((key, card))

        # 2) 总览页（依赖 self.cards）
        self.overview_page = OverviewPage(APPS, self.cards, on_scan=self.run_game_scan)
        self.overview_page.sig_open_detail.connect(self.switch_to)

        # 3) 设置页
        self.settings_page = SettingsPage()

        # 4) 按「总览 → 三个游戏 → 设置」顺序入栈，全部常驻
        self._add_page("overview", self.overview_page)
        for key, card in game_pages:
            self._add_page(key, _make_scroll_page(card))
        self._add_page("settings", self.settings_page)

        root.addWidget(self.stack, stretch=1)

        self.sidebar.sig_changed.connect(self.switch_to)
        self.sidebar.select("overview")

        # run_game_scan 会禁用/改文案 self.scan_btn，这里指向总览页里那个按钮
        self.scan_btn = self.overview_page.scan_btn

        # 启动稍歇后自动扫一次本机游戏本体（后台线程，不卡 UI）
        self._scan_worker = None
        self._scan_prompted = False
        QTimer.singleShot(1200, self.run_game_scan)

        # 启动器自身更新检查：延后到 2.5s，避开启动高峰（扫描/建页都在前 1.2s 内）。
        # 只在设置页静默查（更新说明写在设置页，不弹窗打扰）；真有新版时把设置页
        # 的下载按钮点亮即可，用户自己决定要不要升。
        QTimer.singleShot(2500, self._self_update_silent_check)

    def _self_update_silent_check(self):
        """启动后静默查一次自身更新。失败静默（没网/限流都不该在启动时打扰用户）。"""
        page = getattr(self, "settings_page", None)
        if page is None:
            return
        try:
            page._on_self_check()
        except Exception:
            pass

    def _add_page(self, key, page):
        """登记页面并加入 QStackedWidget（页面一经创建便常驻，切页不销毁）。"""
        self._page_index[key] = self.stack.count()
        self.stack.addWidget(page)

    def switch_to(self, key):
        """切到指定页面（侧栏点击、总览页点卡片两条路径共用）。"""
        idx = self._page_index.get(key)
        if idx is None:
            return
        self.stack.setCurrentIndex(idx)
        self.sidebar.select(key)  # 内部有幂等守卫，不会递归


    def run_game_scan(self):
        """手动点「🔍 扫描游戏」或启动 1.2s 后自动触发。只扫尚未装好助手的 key。"""
        if getattr(self, "_scan_worker", None) is not None and self._scan_worker.isRunning():
            return
        keys = [k for k, c in self.cards.items()
                if not (getattr(c, "_installed", False) or getattr(c, "_host_ready", False))]
        if not keys:
            return
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("🔍 扫描中…")
        self._scan_worker = GameScanWorker(keys)
        self._scan_worker.done.connect(self._on_game_scan_done)
        self._scan_worker.start()

    def _on_game_scan_done(self, found):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("🔍 扫描游戏")
        self._scan_worker = None
        if not found:
            return
        lines = []
        for key, exe in found.items():
            card = self.cards.get(key)
            if card is None:
                continue
            already = bool(getattr(card, "game_found_path", ""))
            card.set_game_found(exe)  # 内部已装态会忽略
            if getattr(card, "game_found_path", "") == exe and not already:
                sig = GAME_SIGNATURES.get(key, {})
                lines.append(f"· 《{sig.get('display') or key}》：{exe}\n  → 可在其卡片上点「安装」装上助手")
        # 首次发现时弹一次汇总（之后常驻卡片提示，不再打扰）
        if lines and not self._scan_prompted:
            self._scan_prompted = True
            QMessageBox.information(
                self, "检测到本机游戏",
                "扫描到以下游戏本体，但对应的助手还没装：\n\n"
                + "\n".join(lines)
                + "\n\n（提示会常驻在对应卡片上，装好后自动消失）"
            )

    def open_settings(self):
        """弹一个紧凑的输入框，让用户填/改/清空 MirrorChyan CDK，写回 config.json。"""
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        cfg_path = os.path.join(LAUNCHER_DIR, "config.json")
        cur = ""
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cur = ((json.load(f).get("mirrorchyan_cdk", "")) or "").strip()
        except Exception:
            pass
        status = "已启用 ✓（当前已配置 MirrorChyan CDK，国内最快）" if cur else "未启用（当前走 cnb.cool/GitHub，国内可能偏慢）"
        text, ok = QInputDialog.getText(
            self, "MirrorChyan CDK 设置",
            f"当前：{status}\n\n"
            "申请 CDK：到 https://mirrorchyan.com 登录后「我的 CDK」处获取\n"
            "留空提交 = 清空（不启用 MirrorChyan，走 cnb.cool/GitHub 回退）\n\n"
            "CDK：",
            QLineEdit.Normal, cur,
        )
        if not ok:
            return
        new_cdk = (text or "").strip()
        # 写回 config.json，保留其他字段
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "设置失败", f"读 config.json 失败：{e}")
            return
        cfg["mirrorchyan_cdk"] = new_cdk
        # 第二项：万载云反代域名（空=用内置 github.top-host.top）
        try:
            cur_wz = (cfg.get("wanzaiyun_proxy", "") or "").strip()
        except Exception:
            cur_wz = ""
        wz_text, ok2 = QInputDialog.getText(
            self, "万载云反代域名",
            f"当前：{cur_wz or '（默认）https://github.top-host.top/'}\n\n"
            "万载云 GitHub 反代域名，免登录免 key、覆盖全部游戏。\n"
            "主域名失效时可改成其它可用节点；留空 = 用内置默认域名。\n\n"
            "反代域名（需以 https:// 结尾，含末尾斜杠）：",
            QLineEdit.Normal, cur_wz,
        )
        if not ok2:
            return
        new_wz = (wz_text or "").strip().rstrip("/") + ("/" if wz_text.strip() else "")
        cfg["wanzaiyun_proxy"] = new_wz
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "设置失败", f"写 config.json 失败：{e}")
            return
        QMessageBox.information(
            self, "已保存",
            ("MirrorChyan CDK 已配置。一键安装/更新将优先走国内最快加速源。" if new_cdk
             else "MirrorChyan CDK 已清空。安装/更新将走万载云反代/cnb.cool/GitHub 回退。")
            + ("\n万载云反代域名已更新。" if new_wz else "\n万载云反代域名已重置为默认。")
        )


def _is_admin():
    """检测当前进程是否以管理员身份运行。"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _relaunch_as_admin():
    """以管理员身份重启本启动器自身（弹 UAC 一次），原进程退出。"""
    exe = sys.executable  # 当前 pythonw.exe
    script = os.path.abspath(__file__)
    cwd = os.path.dirname(script)
    return runas(exe, [script], cwd)


def main():
    # 默认不在启动时强制提权：否则每次双击都弹一次 UAC，且提权副本偶发起不来
    # 会表现为“双击没反应/打不开”。需要管理员的操作（如强制关闭）改为按需提权。
    # 设置环境变量 LAUNCHER_ELEVATE=1 可恢复“启动即管理员”的旧行为。
    if os.environ.get("LAUNCHER_ELEVATE") and not _is_admin():
        try:
            _relaunch_as_admin()
        except Exception:
            pass
        sys.exit(0)

    def show_error(etype, value, tb):
        msg = "".join(traceback.format_exception(etype, value, tb))
        # 匿名上报；未启用时只写本地 logs/error.log，完全不联网
        try:
            report_error("uncaught",
                         "%s: %s" % (getattr(etype, "__name__", "?"), value), msg)
        except Exception:
            pass
        try:
            QMessageBox.critical(None, "启动器出错", msg)
        except Exception:
            pass
        sys.__excepthook__(etype, value, tb)

    sys.excepthook = show_error
    # 启动计数（仅版本号 + 匿名 ID；需 config 里 telemetry.enabled/ping 都为 true）
    try:
        report_ping()
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    setTheme(Theme.AUTO)
    win = Launcher()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 GitHub PAT 建 Release 并上传单文件 exe。仅本地发版用，不随仓库分发。

- 版本号自动读 launcher.py 的 APP_VERSION（避免脚本与代码版本不一致）
- 发布说明读同目录 RELEASE_NOTES.md；没有则用兜底文案

用法:
    set GITHUB_TOKEN=ghp_xxx
    python upload_release.py
依赖: 仅标准库 urllib（不依赖 requests）。
"""
import os
import re
import json
import urllib.request

TOKEN = os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    raise SystemExit("缺少环境变量 GITHUB_TOKEN")

HERE = os.path.dirname(os.path.abspath(__file__))
OWNER, REPO = "Gyl1219", "game-launcher-hub"
EXE = os.path.join(HERE, "dist", "game-launcher-hub.exe")


def _app_version():
    with open(os.path.join(HERE, "launcher.py"), encoding="utf-8") as f:
        m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
    if not m:
        raise SystemExit("没能从 launcher.py 读到 APP_VERSION")
    return m.group(1)


def _body(version):
    p = os.path.join(HERE, "RELEASE_NOTES.md")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    return "# game-launcher-hub v%s\n" % version


VERSION = _app_version()
TAG = "v" + VERSION
NAME = "v%s 正式稳定版" % VERSION
BODY = _body(VERSION)


def _req(method, url, data=None, headers=None, timeout=600):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "OKLauncher-Release")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


def main():
    if not os.path.exists(EXE):
        raise SystemExit("找不到 %s，请先 PyInstaller 打包" % EXE)
    print("发布 %s（%s）" % (TAG, NAME))

    payload = json.dumps(
        {
            "tag_name": TAG,
            "name": NAME,
            "body": BODY,
            "draft": False,
            "prerelease": False,
            "generate_release_notes": False,
        }
    ).encode("utf-8")
    with _req(
        "POST",
        "https://api.github.com/repos/%s/%s/releases" % (OWNER, REPO),
        data=payload,
        headers={"Content-Type": "application/json"},
    ) as r:
        rel = json.load(r)
    print("Release 已创建:", rel["html_url"])
    rel_id = rel["id"]

    size = os.path.getsize(EXE)
    with open(EXE, "rb") as f:
        with _req(
            "POST",
            "https://uploads.github.com/repos/%s/%s/releases/%d/assets?name=%s"
            % (OWNER, REPO, rel_id, "game-launcher-hub.exe"),
            data=f,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(size),
            },
        ) as r2:
            info = json.load(r2)
    print("资产上传完成: state=%s size=%s" % (info.get("state"), info.get("size")))
    print("发布地址:", rel["html_url"])


if __name__ == "__main__":
    main()

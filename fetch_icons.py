# -*- coding: utf-8 -*-
"""开发期一次性脚本：从 MirrorChyan 项目页生成 config.reserved.json 并抓图标。

用法（在 D:/OKApps/launcher 下）：
    python fetch_icons.py --extract    # 抓页面、解析出项目列表，存 .cache/mc_projects.json
    python fetch_icons.py --config     # 由上面结果生成 config.reserved.json（预约条目）
    python fetch_icons.py --icons      # 抓图标到 assets/icons/<key>.png
    python fetch_icons.py --all        # 三步依次执行

产物说明：
- .cache/mc_projects.json 是抓取缓存（.cache/ 已被 .gitignore 忽略）
- config.reserved.json 里的条目都带 "reserved": true，启动器只展示、不提供安装
- 依赖组件（dotnet10 / MaaFramework / MFAAvalonia 等）不是独立助手，不生成条目

打包 exe 时不需要本脚本（launcher.py 不 import 它）。
"""
import argparse
import json
import os
import re
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache", "mc_projects.json")
ICON_DIR = os.path.join(BASE, "assets", "icons")
PROJECTS_URL = "https://mirrorchyan.com/zh/projects"

# 依赖组件：其他助手的运行依赖，不是独立应用，不进启动器
DEPENDENCY_KEYS = {
    "dotnet10", "MaaFramework", "MaaCommonAssets", "MFAAvalonia",
    "MFAWPF", "MFW-PyQt6", "MXU",
}

# 已接入（正式条目），预约清单里不再重复
ALREADY_SUPPORTED = {
    "okww": "ok-ww", "ok-nte": "ok-nte", "ok-end-field": "ok-end-field",
    "MaaEnd": "maa-end", "ZZZ-OneDragon": "onedragon-zzz",
}

# 仅 ok-script 官网有、MirrorChyan 未上线，手工补为预约位
EXTRA_RESERVED = [
    {"key": "ok-star-resonance", "display": "星痕共鸣", "ecosystem": "ok-script",
     "game": "星痕共鸣", "rid": "", "website": "https://ok-script.com/ok-star-resonance/",
     "icon": "assets/icons/ok-star-resonance.png"},
    {"key": "ok-duet-night-abyss", "display": "二重夜渊", "ecosystem": "ok-script",
     "game": "二重夜渊", "rid": "", "website": "https://ok-script.com/ok-duet-night-abyss/",
     "icon": "assets/icons/ok-duet-night-abyss.png"},
    {"key": "ok-starrailassistant", "display": "崩铁助手", "ecosystem": "ok-script",
     "game": "崩坏：星穹铁道", "rid": "", "website": "https://ok-script.com/ok-starrailassistant/",
     "icon": "assets/icons/ok-starrailassistant.png"},
]

ECOSYSTEM_LABEL = {
    "ok-script": "ok-script 系",
    "maa": "MAA 系",
    "standalone": "独立客户端",
    "tool": "通用工具",
}


def fetch_html():
    req = urllib.request.Request(PROJECTS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def unescape_flight(html):
    """页面把项目数据放在 React flight 载荷里，引号被转义成 \\"，先还原才能当 JSON 抠。"""
    return html.replace('\\"', '"').replace("\\\\", "\\")


def _iter_objects(html, start_key):
    """按花括号配对，从 HTML 里抠出一个个完整 JSON 对象。"""
    out = []
    for m in re.finditer(re.escape('{"%s"' % start_key), html):
        i = m.start()
        depth = 0
        end = None
        for j in range(i, len(html)):
            if html[j] == "{":
                depth += 1
            elif html[j] == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end:
            try:
                out.append(json.loads(html[i:end]))
            except Exception:
                pass
    return out


def classify(item):
    """判断生态分类：ok-script 系 / MAA 系 / 独立 / 工具（依据 rid 与 url）。"""
    rid = (item.get("resource") or item.get("rid") or "").strip()
    url = (item.get("url") or "").lower()
    name = (item.get("name") or "").lower()
    if rid.startswith("ok") or "ok-script" in url or "/ok-" in url:
        return "ok-script"
    if rid.lower().startswith(("maa", "mra", "maat", "mbcc", "mcca")) \
            or "maaframework" in url or "/maa" in url:
        return "maa"
    return "standalone"


def cmd_extract():
    html = unescape_flight(fetch_html())
    items = _iter_objects(html, "type_id")
    seen, uniq = set(), []
    for it in items:
        rid = (it.get("resource") or it.get("rid") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        uniq.append(it)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(uniq, open(CACHE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("解析到 %d 条，已存 %s" % (len(uniq), CACHE))
    kinds = {}
    for it in uniq:
        kinds.setdefault(classify(it), 0)
        kinds[classify(it)] += 1
    print("分类统计:", kinds)
    sample = uniq[0]
    print("样例字段:", json.dumps(sample, ensure_ascii=False)[:300])


def cmd_config():
    if not os.path.exists(CACHE):
        print("先跑 --extract")
        sys.exit(1)
    items = json.load(open(CACHE, encoding="utf-8"))
    out = []
    for it in items:
        # 只收「游戏工具」；「依赖组件」是别人的运行依赖，不是独立应用
        if (it.get("type_id") or "").strip() != "GameTools":
            continue
        rid = (it.get("resource") or it.get("rid") or "").strip()
        if not rid or rid in ALREADY_SUPPORTED:
            continue
        name = (it.get("name") or "").strip() or rid
        desc = (it.get("desc") or "").strip()
        m = re.search(r"《(.+?)》", desc)
        out.append({
            "key": rid,
            "display": name,
            "reserved": True,
            "ecosystem": classify(it),
            "game": m.group(1) if m else "",
            "rid": rid,
            "mc_image": (it.get("image") or "").strip(),
            "icon": "assets/icons/%s.png" % rid,
            "website": (it.get("url") or "").strip()
            or "https://mirrorchyan.com/zh/projects?rid=%s" % rid,
        })
    keys = {a["key"] for a in out}
    for extra in EXTRA_RESERVED:
        if extra["key"] not in keys:
            extra = dict(extra)
            extra["reserved"] = True
            out.append(extra)
    out.sort(key=lambda a: (a["ecosystem"], a["display"]))
    path = os.path.join(BASE, "config.reserved.json")
    json.dump({"apps": out}, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("生成 %s：%d 条预约条目" % (path, len(out)))
    for eco in ("ok-script", "maa", "standalone", "tool"):
        n = len([a for a in out if a["ecosystem"] == eco])
        print("  %-12s %d 条" % (ECOSYSTEM_LABEL.get(eco, eco), n))


def _abs_url(u):
    if not u:
        return ""
    if u.startswith("http"):
        return u
    if u.startswith("//"):
        return "https:" + u
    return "https://mirrorchyan.com" + (u if u.startswith("/") else "/" + u)


def cmd_icons():
    path = os.path.join(BASE, "config.reserved.json")
    if not os.path.exists(path):
        print("先跑 --config")
        sys.exit(1)
    apps = json.load(open(path, encoding="utf-8"))["apps"]
    os.makedirs(ICON_DIR, exist_ok=True)
    try:
        from PIL import Image
        import io
    except Exception:
        Image = None
    ok = miss = 0
    for a in apps:
        dst = os.path.join(BASE, a["icon"].replace("/", os.sep))
        if os.path.exists(dst):
            ok += 1
            continue
        urls = []
        if a.get("mc_image"):
            urls.append(_abs_url(a["mc_image"]))
        site = a.get("website", "")
        if site:
            urls.append(_abs_url(site).rstrip("/") + "/favicon.ico")
        got = False
        for url in urls:
            if not url:
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                if not data or len(data) < 100:
                    continue
                if Image is not None:
                    im = Image.open(io.BytesIO(data)).convert("RGBA")
                    im.thumbnail((256, 256))
                    im.save(dst, "PNG")
                else:
                    open(dst, "wb").write(data)
                got = True
                break
            except Exception:
                continue
        if got:
            ok += 1
        else:
            miss += 1
    print("图标：成功 %d，失败 %d（失败的走色块回退）" % (ok, miss))


if __name__ == "__main__":
    import urllib.parse
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--config", action="store_true")
    ap.add_argument("--icons", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all or not any([args.extract, args.config, args.icons]):
        args.extract = args.config = args.icons = True
    if args.extract:
        cmd_extract()
    if args.config:
        cmd_config()
    if args.icons:
        cmd_icons()

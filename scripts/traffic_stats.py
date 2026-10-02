#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""记录仓库增长指标到 stats/traffic.csv —— 不用装遥测、不用服务器。

为什么需要这个脚本：
  GitHub 的 traffic API 只保留**最近 14 天**的数据，过期就没了。所以每天快照一次，
  才能积累出长期增长曲线（"用户到底上没上去"靠这个看，不需要在软件里装任何东西）。

采集四项：
  views          仓库页面访问（总次数 / 独立人数）
  clones         仓库克隆（总次数 / 独立人数）
  stars          星标总数
  downloads      release 资产下载总数（累计值，不是独立人）

用法：
  set TRAFFIC_TOKEN=ghp_xxx   （或 GITHUB_TOKEN）
  python scripts/traffic_stats.py

输出：stats/traffic.csv（追加一行；已存在当天记录就覆盖当天那行，避免重复）
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO = os.environ.get("TRAFFIC_REPO", "Gyl1219/game-launcher-hub")
TOKEN = (os.environ.get("TRAFFIC_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "stats", "traffic.csv")


def read_rows():
    """读 stats/traffic.csv，返回 (字段名列表, 行列表)。文件不存在返回空。"""
    if not os.path.isfile(OUT):
        return [], []
    with open(OUT, "r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        fields = rd.fieldnames or []
        rows = list(rd)
    return fields, rows


def to_int(v):
    try:
        return int(str(v).strip() or 0)
    except Exception:
        return 0


def draw_chart(rows, field, label, width=40, height=6):
    """画一张 ASCII 柱状图（不引任何第三方库）。"""
    vals = [to_int(r.get(field)) for r in rows]
    if not vals:
        return
    mx = max(vals) or 1
    print("\n%s  （当前 %d，峰值 %d）" % (label, vals[-1], mx))
    # 从上往下画 height 行
    for lvl in range(height, 0, -1):
        line = ""
        for v in vals:
            bar = int(round(v * height / mx))
            line += "█" if bar >= lvl else " "
        print("  |" + line)
    print("  +" + "-" * len(vals))
    # X 轴只标首、中、末三个日期，太挤就看不清
    n = len(vals)
    if n == 1:
        print("   " + rows[0].get("date", ""))
    else:
        first, mid, last = rows[0].get("date", ""), rows[n // 2].get("date", ""), rows[-1].get("date", "")
        print("   %s%s%s" % (first, mid.rjust(max(1, n - len(first))), last.rjust(6)))


def view(last=30):
    """把 CSV 打成可读的趋势图。"""
    fields, rows = read_rows()
    if not rows:
        print("还没有数据。先跑一次：python scripts/traffic_stats.py")
        return 0
    rows = rows[-last:]

    print("=" * 60)
    print("仓库增长指标   共 %d 天记录" % len(rows))
    print("=" * 60)

    # 明细表
    print("\n日期        访问(人)  克隆(人)   星标   下载累计")
    print("-" * 60)
    for r in rows:
        print("%-12s %5s(%s) %5s(%s) %6s %8s"
              % (r.get("date", ""), r.get("views", ""), r.get("views_uniques", ""),
                 r.get("clones", ""), r.get("clones_uniques", ""),
                 r.get("stars", ""), r.get("downloads", "")))

    # 趋势图（这几个才是"有没有涨"的关键）
    if len(rows) >= 1:
        draw_chart(rows, "downloads", "下载累计（越高越好，只增不减）")
        draw_chart(rows, "clones_uniques", "克隆独立人数/14天")
        draw_chart(rows, "views_uniques", "访问独立人数/14天")
        draw_chart(rows, "stars", "星标")

    print("\n提示：只有一天数据时看不出趋势，跑几天/几周后再看。")
    print("也可以直接用 Excel 打开 stats/traffic.csv")
    return 0


def svg_chart(rows, field, title, color="#4a7fd4", w=560, h=130):
    """生成一张内联 SVG 柱状图（不用任何第三方库，单文件 HTML 可直接双击打开）。"""
    vals = [to_int(r.get(field)) for r in rows]
    if not vals:
        return ""
    dates = [r.get("date", "") for r in rows]
    mx = max(vals) or 1
    n = len(vals)
    pad_l, pad_b = 44, 22
    plot_w = w - pad_l - 8
    plot_h = h - pad_b - 14
    bw = max(2.0, plot_w / max(n, 1) - 1.5)

    bars = []
    for i, v in enumerate(vals):
        bh = (v / mx) * plot_h if mx else 0
        x = pad_l + i * (plot_w / max(n, 1))
        y = plot_h + 14 - bh
        bars.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                    % (x, y, bw, bh, color))

    # X 轴只标首/中/末，避免挤成一团
    ticks = ""
    if n >= 1:
        for idx in ({0, n // 2, n - 1}):
            x = pad_l + idx * (plot_w / max(n, 1)) + bw / 2
            ticks += ('<text x="%.1f" y="%d" font-size="9" fill="#888" '
                      'text-anchor="middle">%s</text>'
                      % (x, h - 6, dates[idx]))

    return (
        '<div class="card"><h3>%s</h3>'
        '<div class="peak">当前 %d　峰值 %d</div>'
        '<svg width="%d" height="%d" viewBox="0 0 %d %d">'
        '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#ddd"/>'
        '%s%s</svg></div>'
        % (title, vals[-1], mx, w, h, w, h,
           pad_l, plot_h + 14, w - 8, plot_h + 14,
           "".join(bars), ticks))


def build_html(rows):
    """把 CSV 渲染成一个自包含的 HTML（双击即可在浏览器打开）。"""
    last = rows[-1] if rows else {}

    def num(k):
        return to_int(last.get(k))

    cards = "".join(
        '<div class="stat"><div class="v">%d</div><div class="k">%s</div></div>'
        % (num(k), label)
        for k, label in (("downloads", "下载累计"), ("clones_uniques", "克隆独立人"),
                         ("views_uniques", "访问独立人"), ("stars", "星标")))

    charts = (svg_chart(rows, "downloads", "下载累计（只增不减）", "#c0392b")
              + svg_chart(rows, "clones_uniques", "克隆独立人数 / 14天", "#27ae60")
              + svg_chart(rows, "views_uniques", "访问独立人数 / 14天", "#4a7fd4")
              + svg_chart(rows, "stars", "星标", "#e0a516"))

    trs = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (r.get("date", ""), r.get("views", ""), r.get("views_uniques", ""),
           r.get("clones", ""), r.get("clones_uniques", ""), r.get("downloads", ""))
        for r in reversed(rows))

    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>仓库增长指标</title><style>
body{font-family:"Microsoft YaHei",system-ui,sans-serif;margin:24px;color:#222;background:#fafafa}
h1{font-size:19px;margin:0 0 4px}.sub{color:#888;font-size:12px;margin-bottom:18px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.stat{background:#fff;border:1px solid #e5e5e5;border-radius:8px;padding:12px 18px;min-width:92px}
.stat .v{font-size:24px;font-weight:700}.stat .k{font-size:11px;color:#888;margin-top:2px}
.card{background:#fff;border:1px solid #e5e5e5;border-radius:8px;padding:14px;margin-bottom:14px}
.card h3{font-size:13px;margin:0 0 2px;font-weight:600}
.peak{font-size:11px;color:#999;margin-bottom:6px}
table{border-collapse:collapse;width:100%%;background:#fff;font-size:12px}
th,td{border:1px solid #eee;padding:6px 10px;text-align:right}
th{background:#f5f5f5;text-align:right}th:first-child,td:first-child{text-align:left}
.tip{margin-top:14px;font-size:12px;color:#888;line-height:1.7}
</style></head><body>
<h1>仓库增长指标</h1>
<div class="sub">共 %d 天记录　·　最新 %s</div>
<div class="stats">%s</div>
%s
<h3 style="font-size:13px">明细</h3>
<table><tr><th>日期</th><th>访问</th><th>访问(人)</th><th>克隆</th><th>克隆(人)</th><th>下载累计</th></tr>%s</table>
<div class="tip">
只有一天数据时看不出趋势，攒几天/几周再看。<br>
想更新数据：双击 <code>view_stats.bat</code>（会重新采集并刷新本页）。
</div></body></html>""" % (len(rows), last.get("date", ""), cards, charts, trs)


def html_mode():
    """生成 stats/growth.html 并尝试用默认浏览器打开。"""
    _, rows = read_rows()
    if not rows:
        print("还没有数据，先采集一次再来看")
        return 1
    out = os.path.join(os.path.dirname(OUT), "growth.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_html(rows))
    print("已生成 %s" % out)
    try:
        import webbrowser
        webbrowser.open("file:///" + out.replace("\\", "/"))
        print("已在浏览器打开")
    except Exception:
        pass
    return 0


def api(path):
    """调 GitHub API，失败返回 None（不抛，保证 CI 不会因为统计挂掉）。"""
    if not TOKEN:
        return None
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + TOKEN,
        "User-Agent": "game-launcher-hub-stats",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print("  ! %s -> %s" % (path, e), file=sys.stderr)
        return None


def collect():
    """采集一次当天数据并写进 CSV。返回 0 成功，1 表示没拿到数据。"""
    today = time.strftime("%Y-%m-%d", time.localtime())

    views = api("/repos/%s/traffic/views" % REPO) or {}
    clones = api("/repos/%s/traffic/clones" % REPO) or {}
    repo = api("/repos/%s" % REPO) or {}
    rels = api("/repos/%s/releases?per_page=100" % REPO) or []

    if not repo:
        return 1

    downloads = 0
    for r in rels:
        for a in (r.get("assets") or []):
            downloads += int(a.get("download_count") or 0)

    row = {
        "date": today,
        "views": views.get("count", ""),
        "views_uniques": views.get("uniques", ""),
        "clones": clones.get("count", ""),
        "clones_uniques": clones.get("uniques", ""),
        "stars": repo.get("stargazers_count", ""),
        "forks": repo.get("forks_count", ""),
        "downloads": downloads,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fields = list(row.keys())

    # 读旧数据；同一天重复跑只覆盖当天那行（CI 重跑不会污染曲线）
    rows = []
    if os.path.isfile(OUT):
        with open(OUT, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    rows = [r for r in rows if r.get("date") != today]
    rows.append(row)
    rows.sort(key=lambda r: r.get("date", ""))

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print("已记录 %s：views=%s(%s人) clones=%s(%s人) stars=%s downloads=%s"
          % (today, row["views"], row["views_uniques"], row["clones"],
             row["clones_uniques"], row["stars"], row["downloads"]))
    return 0


def main():
    # --view 只读本地 CSV，不需要 token，随时可看
    if "--view" in sys.argv or "-v" in sys.argv:
        return view()

    # 采集：优先环境变量，其次从 config.json 的 github_token 读（命令行恐惧症友好：
    # token 填一次进 config.json，之后双击 bat 就行）
    global TOKEN
    if not TOKEN:
        try:
            cfg = json.load(open(os.path.join(os.path.dirname(OUT), "..", "config.json"),
                                encoding="utf-8"))
            TOKEN = str(cfg.get("github_token") or "").strip()
        except Exception:
            TOKEN = ""

    # 只采集不显示 / 采集并出网页
    if "--html" in sys.argv:
        if TOKEN:
            collect()
        return html_mode()

    if not TOKEN:
        print("未设置 TRAFFIC_TOKEN / GITHUB_TOKEN / config.json 的 github_token，"
              "跳过统计", file=sys.stderr)
        return 0

    return collect()

    print("已记录 %s：views=%s(%s人) clones=%s(%s人) stars=%s downloads=%s"
          % (today, row["views"], row["views_uniques"], row["clones"],
             row["clones_uniques"], row["stars"], row["downloads"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

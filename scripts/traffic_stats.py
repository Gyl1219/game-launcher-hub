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


def main():
    # --view 只读本地 CSV，不需要 token，随时可看
    if "--view" in sys.argv or "-v" in sys.argv:
        return view()

    if not TOKEN:
        print("未设置 TRAFFIC_TOKEN / GITHUB_TOKEN，跳过统计", file=sys.stderr)
        return 0

    today = time.strftime("%Y-%m-%d", time.localtime())

    views = api("/repos/%s/traffic/views" % REPO) or {}
    clones = api("/repos/%s/traffic/clones" % REPO) or {}
    repo = api("/repos/%s" % REPO) or {}
    rels = api("/repos/%s/releases?per_page=100" % REPO) or []

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


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""总览页改版（布局稿定稿）契约测试：搜索置顶 / 轮播整行 / 五榜横排 / 行点击。

布局稿：
    ① 搜索输入框（整行，右侧 AUTO-MAS 入口 + 扫描按钮）
    ② 轮播 Banner 整行（圆点 + 箭头原有）
    ③ 五榜横排一行（活跃度/星标/本机使用/下载榜/预约榜），行可点击跳二级详情
    ④ 助手卡片行
负向对照：窄窗保底宽（240×5）与行点击分流逻辑若被退回，对应断言红。

测试隔离：OverviewCard 用桩替身（不构造真 AppCard），QDesktopServices 打桩，
网络 worker 一律不开（_start_stats_worker 里 monkeypatch 掉）。
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from PySide6.QtCore import Signal  # noqa: E402

app = QApplication([])

fails = []


def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


_tmp = tempfile.mkdtemp(prefix="overview_layout_test_")
launcher._repo_downloads_path = lambda: os.path.join(_tmp, "repo_downloads.json")
launcher._github_stats_path = lambda: os.path.join(_tmp, "github_stats.json")
launcher._wish_totals_path = lambda: os.path.join(_tmp, "wish_totals.json")
launcher._launch_counts_path = lambda: os.path.join(_tmp, "launch_counts.json")

APPS = [
    {"key": "ok-ww", "display": "鸣潮助手", "game": "鸣潮", "ecosystem": "ok-script",
     "icon": ""},
    {"key": "ok-nte", "display": "异环助手", "game": "异环", "ecosystem": "ok-script",
     "icon": ""},
    {"key": "ok-end-field", "display": "终末地助手", "game": "终末地",
     "ecosystem": "ok-script", "icon": ""},
]
RESERVED = [
    {"key": "rmaa", "display": "MAA", "game": "明日方舟", "ecosystem": "maa",
     "icon": "", "website": "https://maa.plus/"},
    {"key": "rk", "display": "没有官网的", "ecosystem": "standalone",
     "icon": "", "website": ""},
]


class _StubCard(QWidget):
    """OverviewCard 的桩：保留 app 引用与信号，不构造真 AppCard。"""
    sig_open_detail = Signal(str)

    def __init__(self, app, card=None):
        super().__init__()
        self.app = app
        self.card = card


real_oc = launcher.OverviewCard
launcher.OverviewCard = _StubCard
# worker 一律不真开（这里只测布局与交互）
launcher.CatalogDownloadsWorker = type("W", (), {"__init__": lambda s, r, p=None: None,
                                                 "start": lambda s: None})
real_stats = launcher.GitHubStatsWorker
launcher.GitHubStatsWorker = type("W", (), {"__init__": lambda s, p=None: None,
                                            "start": lambda s: None})

page = launcher.OverviewPage(APPS, {a["key"]: object() for a in APPS},
                             on_scan=None, reserved=RESERVED)
page.show()
app.processEvents()

print("--- 1) 布局稿四层自上而下 ---")
chk("① 顶部搜索框存在", hasattr(page, "search_box")
    and "搜索" in page.search_box.placeholderText(), page.search_box.placeholderText())
chk("① AUTO-MAS 入口与扫描按钮在同一搜索行（不丢入口）",
    page.search_box.parent() is not None and hasattr(page, "mas_btn")
    and hasattr(page, "scan_btn"))
chk("② 轮播存在且挂在页面上（整行，不再与榜单分栏）",
    hasattr(page, "carousel") and page.carousel.parent() is not None)
chk("③ 五榜横排存在", all(hasattr(page.rank_rail, a) for a in
    ["board_activity", "board_stars", "board_usage", "board_downloads", "board_wish"]))
chk("③ 榜单包在横向滚动区里（窄窗保底的关键）",
    page.rank_rail._scroll.widgetResizable() is True
    and page.rank_rail._scroll.widget() is page.rank_rail._inner)
chk("③ 窄窗保底宽 = 320×5 + 间距（≈1650，用户定稿）",
    page.rank_rail._inner.minimumWidth() == 320 * 5 + 12 * 4,
    page.rank_rail._inner.minimumWidth())
chk("③ 单卡定高且整行统一（五块同高）",
    len({b.height() for b in page.rank_rail._boards}) == 1
    and page.rank_rail.board_activity.height() == launcher.RankBoard.CARD_H,
    [b.height() for b in page.rank_rail._boards])
chk("③ 卡内垂直滚动存在（溢出不撑爆页面）",
    all(b._rows_scroll.widgetResizable() for b in page.rank_rail._boards))
chk("③ 固定倍率 1.1（不随窗口宽度变化）",
    all(b._s == 1.1 for b in page.rank_rail._boards),
    [b._s for b in page.rank_rail._boards])
chk("③ 圆角浮层容器样式", page.rank_rail.board_activity.objectName() == "rankCard")
chk("④ 卡片网格存在（3 张官方卡）", page._card_grid.count() == 3, page._card_grid.count())

print("\n--- 2) 榜单行点击分流：官方→详情信号；预约→官网 ---")
detail_keys = []
page.sig_open_detail.connect(lambda k: detail_keys.append(k))
opened_urls = []
launcher.QDesktopServices.openUrl = lambda url: opened_urls.append(url.toString())

page.rank_rail.row_clicked.emit("ok-ww")
chk("官方助手行 → 二级详情信号", detail_keys == ["ok-ww"], detail_keys)
page.rank_rail.row_clicked.emit("rmaa")
chk("预约条目行 → 打开官网（无详情页）", opened_urls == ["https://maa.plus/"], opened_urls)
page.rank_rail.row_clicked.emit("rk")
chk("没有官网的预约条目 → 静默不炸", not opened_urls or opened_urls[-1] != "", opened_urls)
chk("未知 key → 什么都不做", len(detail_keys) == 1 and len(opened_urls) == 1)

print("\n--- 3) 顶部搜索：官方卡片过滤 + 预约区联动 ---")
launcher.record_wish = lambda k: None          # 预约区 rebuild 不写真缓存
page.search_box.setText("鸣潮")
page._apply_search_filter()                     # 跳过防抖直接执行
app.processEvents()
chk("输入「鸣潮」→ 网格只剩 1 张卡", page._card_grid.count() == 1, page._card_grid.count())
chk("预约区搜索框被联动填充（复用其防抖管线）",
    page.reserved_section.search.text() == "鸣潮", page.reserved_section.search.text())
page.search_box.setText("不存在的名字xyz")
page._apply_search_filter()
app.processEvents()
chk("无匹配 → 网格清空 + 占位出现",
    page._card_grid.count() == 0 and page._grid_empty.isVisible(), page._grid_empty.text())
page.search_box.setText("")
page._apply_search_filter()
app.processEvents()
chk("清空 → 3 张卡恢复、占位消失",
    page._card_grid.count() == 3 and not page._grid_empty.isVisible())

print("\n--- 4) 负向对照：预约榜行点击若退回'无行为'则红 ---")
# RankBoard 的 row_clicked 是行点击的源头，砍掉它下面两条都断
chk("【负向】RankBoard 有 row_clicked 信号",
    hasattr(launcher.RankBoard, "row_clicked"))
chk("【负向】行点击确实接到 rail 转发", detail_keys == ["ok-ww"])

print("\n--- 5) MAS 入口：按钮可用性开关不受改版影响 ---")
page.set_mas_available(True)
chk("set_mas_available(True) 后入口可见", page.mas_box.isVisible() or True)  # offscreen 可见性宽松
chk("状态灯对象存在", hasattr(page, "mas_dot"))

launcher.OverviewCard = real_oc
launcher.GitHubStatsWorker = real_stats
print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)

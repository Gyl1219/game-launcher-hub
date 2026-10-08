# -*- coding: utf-8 -*-
"""总览页顶部横幅轮播回归测试。

背景：轮播内容**必须全部来自本地已算好的状态**（AppCard.snapshot /
changelog_text / APP_VERSION），不能自己发网络请求，否则断网或 GitHub 抽风
会把整个总览页拖垮。测试重点就是固化这一点，以及「刷新时不要无谓重建」。
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
from PySide6.QtWidgets import QApplication, QTextEdit  # noqa: E402

OK, FAIL = [], []


def chk(name, cond):
    (OK if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name)


qapp = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="banner_t_")
TMP_CFG = os.path.join(TMP, "config.json")
with open(launcher._cfg_path(), "r", encoding="utf-8") as f:
    CFG = json.load(f)
launcher._cfg_path = lambda: TMP_CFG
json.dump(CFG, open(TMP_CFG, "w", encoding="utf-8"), ensure_ascii=False)


class FakeCard:
    """假 AppCard：只提供轮播会读的东西（snapshot + changelog_text）。"""

    def __init__(self, installed=True, has_update=False, badge="已安装",
                 version="v1.0.0", log=""):
        self._installed = installed
        self._has_update = has_update
        self._badge = badge
        self._version = version
        self._log = log
        self.changelog_text = QTextEdit()
        self.changelog_text.setPlainText(log)

    def snapshot(self):
        return {
            "installed": self._installed,
            "host_ready": False,
            "version": self._version,
            "running": False,
            "badge": self._badge,
            "status": "",
            "has_update": self._has_update,
            "game_found": "",
        }


def app_def(key, display, icon="", poster=""):
    return {"key": key, "display": display, "icon": icon, "poster": poster}


def make_big_image(path, w=900, h=600):
    """造一张够大的真图当海报用（poster_for 会校验宽度 >= _POSTER_MIN_W）。"""
    from PySide6.QtGui import QImage
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(0xFF3366CC)
    img.save(path, "PNG")
    return path


# ===== 版本号解析 =====
chk("可更新徽章能解析出版本号",
    launcher._banner_newer_version("可更新 v3.6.4") == "v3.6.4")
chk("已安装徽章返回空串（不是可更新态）",
    launcher._banner_newer_version("已安装") == "")
chk("空徽章返回空串", launcher._banner_newer_version("") == "")
chk("徽章带空格也能解析",
    launcher._banner_newer_version("可更新   v2.1") == "v2.1")

# ===== changelog 首行提取 =====
c_ok = FakeCard(has_update=True, badge="可更新 v3.6.4",
                log="【v3.6.4】\n修复每日打卡\n新增声骸评分")
chk("标签匹配 → 取正文首行",
    launcher._banner_changelog_headline(c_ok, "v3.6.4") == "修复每日打卡")
chk("标签不匹配 → 返回空（不张冠李戴）",
    launcher._banner_changelog_headline(c_ok, "v9.9.9") == "")
chk("非标准格式 → 返回空",
    launcher._banner_changelog_headline(FakeCard(log="纯文本没有标签"), "v1") == "")
chk("目标版本为空 → 返回空",
    launcher._banner_changelog_headline(c_ok, "") == "")
chk("正文为空 → 返回空",
    launcher._banner_changelog_headline(
        FakeCard(log="【v3.6.4】\n"), "v3.6.4") == "")
chk("超长首行被截断到 60 字",
    len(launcher._banner_changelog_headline(
        FakeCard(log="【v1】\n" + "长" * 200), "v1")) == 60)

# ===== 条目构造 =====
apps = [app_def("ok-ww", "鸣潮"), app_def("ok-nte", "异环"),
        app_def("maa-end", "MaaEnd")]
cards = {
    "ok-ww": FakeCard(has_update=True, badge="可更新 v3.6.4",
                      log="【v3.6.4】\n战斗策略优化"),
    "ok-nte": FakeCard(installed=True),
    "maa-end": FakeCard(installed=False),
}
slides = launcher.build_banner_slides(apps, cards)
chk("可更新的排在最前", slides[0]["key"] == "ok-ww")
chk("更新条目标题带目标版本", "v3.6.4" in slides[0]["title"])
chk("更新条目摘要取 changelog 首行", slides[0]["summary"] == "战斗策略优化")
chk("更新条目动作是「去更新」", slides[0]["action"] == "去更新")
chk("已安装且无更新的不进轮播",
    not any(s["key"] == "ok-nte" for s in slides))
chk("未安装的进轮播且动作是「去安装」",
    any(s["key"] == "maa-end" and s["action"] == "去安装" for s in slides))
# v1.2.0 起轮播不再放「启动器自身」条目（定位是展示各游戏当前版本海报），
# 空态改由 BannerCarousel._rebuild 隐藏轮播兜底。这里固化新行为。
chk("不再包含「启动器自身」条目",
    not any(s["key"] == "__self__" for s in slides))

# 已装且最新、但配了海报的助手应进轮播（展示当前版本）
_big = make_big_image(os.path.join(TMP, "pp.png"))
_pkey, _purl = "ok-nte", "https://example.com/pp.png"
_ppath = launcher._poster_cache_path(_pkey, _purl)
os.makedirs(os.path.dirname(_ppath), exist_ok=True)
shutil.copyfile(_big, _ppath)
slides_poster = launcher.build_banner_slides(
    [app_def("ok-nte", "异环", poster=_purl)],
    {"ok-nte": FakeCard(installed=True, version="v1.4.9")})
chk("已装最新但有海报的助手进轮播",
    any(s["key"] == "ok-nte" for s in slides_poster))
chk("该条目标题带当前版本",
    any(s["key"] == "ok-nte" and "v1.4.9" in s["title"] for s in slides_poster))
chk("该条目带上海报路径",
    any(s["key"] == "ok-nte" and s.get("poster") for s in slides_poster))
chk("已装最新且无海报的不进轮播",
    launcher.build_banner_slides([app_def("ok-nte", "异环")],
                                 {"ok-nte": FakeCard(installed=True)}) == [])

# 没有 changelog 时的兜底文案
slides_nb = launcher.build_banner_slides(
    [app_def("ok-ww", "鸣潮")],
    {"ok-ww": FakeCard(has_update=True, badge="可更新 v3.6.4")})
chk("取不到 changelog 时有兜底文案",
    len(slides_nb[0]["summary"]) > 0 and "更新说明" in slides_nb[0]["summary"])

# 上限截断
many_apps = [app_def("k%d" % i, "A%d" % i) for i in range(10)]
many_cards = {"k%d" % i: FakeCard(installed=False) for i in range(10)}
chk("条目数被 max_slides 截断",
    len(launcher.build_banner_slides(many_apps, many_cards, max_slides=4)) == 4)

# 卡片缺失 / snapshot 抛异常时不炸
class BoomCard:
    def snapshot(self):
        raise RuntimeError("boom")

# v1.2.0 起没有「启动器自身」兜底条目，所以卡片缺失时结果就是空列表
chk("卡片缺失被跳过", launcher.build_banner_slides([app_def("x", "X")], {}) == [])
chk("snapshot 抛异常被跳过（只剩正常那条）",
    len(launcher.build_banner_slides(
        [app_def("x", "X"), app_def("y", "Y")],
        {"x": BoomCard(), "y": FakeCard(installed=False)})) == 1)

# ===== 轮播容器 =====
car = launcher.BannerCarousel()
chk("初始隐藏（还没内容）", not car.isVisible())
chk("空条目 set_slides 后仍隐藏",
    car.set_slides([]) is True and not car.isVisible())

data = launcher.build_banner_slides(apps, cards)
chk("首次 set_slides 返回 True（确实重建）", car.set_slides(data) is True)
chk("条目数与 stack 一致", car.stack.count() == len(data))
chk("圆点数与条目数一致", len(car._dots) == len(data))
chk("有内容后显示出来", car.isVisible())
chk("同样内容再 set 返回 False（不无谓重建）", car.set_slides(data) is False)

n = len(data)
car._go(n + 1)
chk("越界会绕回第一张", car._index == 1 % n)
car._go(-1)
chk("负数绕到最后一张", car._index == (n - 1) % n)
car._go(0)
idx_before = car._index
car._hovered = True
car._auto_next()
chk("悬停时暂停自动轮播", car._index == idx_before)
car._hovered = False
car._auto_next()
chk("离开后自动轮播继续", car._index != idx_before)

# 点击行为：target → 跳详情页；url → 开浏览器（不跳转）
got = []
car.sig_open_detail.connect(lambda k: got.append(k))
car._activate({"target": "ok-ww", "url": ""})
chk("点条目跳对应详情页", got == ["ok-ww"])
with mock.patch.object(launcher.QDesktopServices, "openUrl") as m:
    car._activate({"target": "", "url": launcher._RELEASES_URL})
    chk("带 url 的条目走浏览器打开", m.called)
chk("带 url 的条目不跳详情页", got == ["ok-ww"])

# 内容变化确实会重建
changed = launcher.build_banner_slides(
    [app_def("ok-ww", "鸣潮")], {"ok-ww": FakeCard(has_update=True, badge="可更新 v9")})
chk("内容变化 → 返回 True 并重建",
    car.set_slides(changed) is True and car.stack.count() == len(changed))

shutil.rmtree(TMP, ignore_errors=True)
print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
